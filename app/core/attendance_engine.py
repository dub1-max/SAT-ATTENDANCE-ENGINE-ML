"""
AttendanceEngine
=================
Turns a raw "this employee_id was recognized right now" event into a
correct attendance record, applying the real-world business rules:

  * First recognition of the day  -> CHECK-IN (marked Late if after grace period)
  * Recognized again soon after   -> IGNORED as a duplicate (logged, not re-marked)
  * Recognized again after the
    minimum gap, with an open
    check-in and no check-out yet -> CHECK-OUT
  * Unknown face                  -> never touches attendance; logged separately

This keeps all the "what does a recognition event actually mean" logic in
one testable place, decoupled from the camera loop and the CV engine.
"""

from __future__ import annotations

from datetime import datetime, date, timedelta, time as dtime
from typing import Optional, Tuple

from app.config import Config
from app.models.db_models import db, Attendance, RecognitionLog, Employee


class AttendanceEngine:
    def __init__(self, config: Config = Config):
        self.cfg = config

    # ------------------------------------------------------------------ #
    def process_event(
        self,
        employee_id: Optional[int],
        confidence: float,
        source: str = "camera-1",
        image_path: Optional[str] = None,
        now: Optional[datetime] = None,
        mode: str = "check_in",
    ) -> Tuple[str, dict]:
        """
        Apply business rules to a single recognition event based on mode.

        Returns (event_type, payload) where event_type is one of:
          "unknown", "check_in", "check_out", "duplicate_ignored", "inactive_employee", "checkout_failed_no_checkin"
        """
        now = now or datetime.now()
        today = now.date()

        # ---- Unknown face -------------------------------------------------
        if employee_id is None:
            log = RecognitionLog(timestamp=now, employee_id=None, event_type="unknown",
                                  confidence=confidence, image_path=image_path)
            db.session.add(log)
            db.session.commit()
            return "unknown", {"message": "Face not recognized", "confidence": confidence}

        employee = Employee.query.get(employee_id)
        if employee is None or not employee.is_active:
            log = RecognitionLog(timestamp=now, employee_id=employee_id, event_type="inactive_employee",
                                  confidence=confidence, image_path=image_path)
            db.session.add(log)
            db.session.commit()
            return "inactive_employee", {"message": "Employee not active/registered"}

        record = Attendance.query.filter_by(employee_id=employee_id, date=today).first()

        # ---- Process based on mode ----------------------------------------
        if mode == "check_out":
            if record is None:
                # Cannot check out if hasn't checked in
                db.session.add(RecognitionLog(timestamp=now, employee_id=employee_id,
                                               event_type="duplicate_ignored", confidence=confidence,
                                               image_path=image_path))
                db.session.commit()
                return "checkout_failed_no_checkin", {"message": "Please Check-in first before checking out."}
            
            if record.check_out_time is not None:
                # Already checked out
                db.session.add(RecognitionLog(timestamp=now, employee_id=employee_id,
                                               event_type="duplicate_ignored", confidence=confidence,
                                               image_path=image_path))
                db.session.commit()
                return "duplicate_ignored", {"message": "Already checked out for today"}
            
            # Eligible check-out
            record.check_out_time = now
            record.check_out_confidence = confidence
            db.session.add(RecognitionLog(timestamp=now, employee_id=employee_id, event_type="recognized",
                                           confidence=confidence, image_path=image_path))
            db.session.commit()
            return "check_out", {"attendance": record.to_dict()}
        
        else: # mode == "check_in"
            if record is None:
                status = self._late_status(now, today)
                record = Attendance(
                    employee_id=employee_id,
                    date=today,
                    check_in_time=now,
                    status=status,
                    check_in_confidence=confidence,
                    source=source,
                )
                db.session.add(record)
                db.session.add(RecognitionLog(timestamp=now, employee_id=employee_id, event_type="recognized",
                                               confidence=confidence, image_path=image_path))
                db.session.commit()
                return "check_in", {"attendance": record.to_dict(), "status": status}
            else:
                # Already checked in today
                db.session.add(RecognitionLog(timestamp=now, employee_id=employee_id,
                                               event_type="duplicate_ignored", confidence=confidence,
                                               image_path=image_path))
                db.session.commit()
                return "duplicate_ignored", {
                    "message": f"Already checked in at {record.check_in_time.strftime('%H:%M:%S')}",
                }

    # ------------------------------------------------------------------ #
    def _late_status(self, now: datetime, today: date) -> str:
        hh, mm = map(int, self.cfg.SHIFT_START_TIME.split(":"))
        shift_start = datetime.combine(today, dtime(hour=hh, minute=mm))
        grace_deadline = shift_start + timedelta(minutes=self.cfg.LATE_GRACE_MINUTES)
        return "Late" if now > grace_deadline else "Present"
