import os
from flask import Flask
from extensions import db, login_manager, socketio
from models import User
from config import config
from routes import main as main_blueprint
from auth import auth as auth_blueprint
from chat import chat as chat_blueprint
from workspace import workspace as workspace_blueprint


def create_app(config_name=None):
    """Create and configure an instance of the Flask application."""
    if config_name is None:
        config_name = os.getenv('FLASK_CONFIG', 'default')

    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder='templates'
    )

    # --- Configuration ---
    app.config.from_object(config[config_name])

    # To enable Google Search, you can either create a 'key.py' file
    # or set the GOOGLE_API_KEY and GOOGLE_CSE_ID environment variables.

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except TypeError:
        # Python versions prior to 3.2 do not support exist_ok; fall back to
        # a manual check so we still guarantee the directory exists.
        if not os.path.isdir(app.instance_path):
            os.makedirs(app.instance_path)

    # If the application is using a SQLite database ensure its directory exists
    database_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if database_uri.startswith('sqlite:///'):
        db_path = database_uri.replace('sqlite:///', '', 1)
        db_directory = os.path.dirname(db_path)
        if db_directory and not os.path.exists(db_directory):
            os.makedirs(db_directory, exist_ok=True)

    # --- Initialize Extensions ---
    db.init_app(app)
    login_manager.init_app(app)
    socketio.init_app(app)
    login_manager.login_view = 'auth.login'

    @login_manager.user_loader
    def load_user(user_id):
        # Updated to use the modern Session.get() method
        return db.session.get(User, int(user_id))

    # --- Register Blueprints ---
    app.register_blueprint(main_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(chat_blueprint)
    app.register_blueprint(workspace_blueprint)

    # --- Create Database Tables ---
    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    app = create_app()
    socketio.run(app, host='0.0.0.0', port=5000, debug=True, allow_unsafe_werkzeug=True, use_reloader=False)
