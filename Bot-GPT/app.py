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
        os.makedirs(app.instance_path)
    except OSError:
        pass

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
    socketio.run(app, host='0.0.0.0', port=5000, debug=True)
