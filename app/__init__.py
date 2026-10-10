"""Application factory."""

from flask import Flask, request, Response
from flask_cors import CORS

from app.config import Config
from app.models.db_models import db


def create_app(config_class=Config):
    app = Flask(
        __name__,
        static_folder="../static",
        template_folder="../templates",
    )
    app.config.from_object(config_class)

    db.init_app(app)
    CORS(app)

    @app.before_request
    def require_auth():
        auth = request.authorization
        if not auth or not (auth.username == 'SATCORP1' and auth.password == 'SAT-ATT-SYS-UAE'):
            return Response(
                'Could not verify your access level for that URL.\n'
                'You have to login with proper credentials', 401,
                {'WWW-Authenticate': 'Basic realm="Login Required"'}
            )

    import os
    with app.app_context():
        os.makedirs(os.path.dirname(app.config["DB_PATH"]), exist_ok=True)
        os.makedirs(app.config["DATASET_DIR"], exist_ok=True)
        os.makedirs(app.config["UNKNOWN_LOG_DIR"], exist_ok=True)
        os.makedirs(app.config["RECOGNIZED_LOG_DIR"], exist_ok=True)
        db.create_all()

    from app.api.routes import api_bp
    from app.api.views import views_bp

    app.register_blueprint(api_bp, url_prefix="/api")
    app.register_blueprint(views_bp)

    return app
