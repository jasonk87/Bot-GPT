import os
from flask import Flask, jsonify
from flask_login import LoginManager
from config import config
from extensions import socketio

# Import blueprints after initializing socketio to avoid circular imports
# (Actually, standard practice is to import blueprints inside create_app or after socketio definition)

def create_app(config_name=None):
    """Create and configure an instance of the Flask application."""
    if config_name is None:
        config_name = os.getenv("FLASK_CONFIG", "default")

    app = Flask(__name__, instance_relative_config=True, template_folder="templates")

    # --- Configuration ---
    app.config.from_object(config[config_name])

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path, exist_ok=True)
    except OSError:
        if not os.path.isdir(app.instance_path):
            raise

    from shared_paths import migrate_legacy_users_file

    migrate_legacy_users_file(app)

    # --- Initialize Extensions ---
    socketio.init_app(
        app, 
        cors_allowed_origins="*",
        ping_timeout=120,    # Allow longer pauses for localized LLM thinking/reasoning
        ping_interval=25
    )

    login_manager = LoginManager()
    login_manager.init_app(app)
    login_manager.login_view = "auth.login"

    @login_manager.user_loader
    def load_user(user_id):
        from models import get_user_by_id
        from shared_paths import get_users_path

        return get_user_by_id(get_users_path(), int(user_id))

    # --- Register Blueprints ---
    from routes import main as main_blueprint
    from auth import auth as auth_blueprint
    from chat import chat as chat_blueprint
    from workspace import workspace as workspace_blueprint

    app.register_blueprint(main_blueprint)
    app.register_blueprint(auth_blueprint)
    app.register_blueprint(chat_blueprint)
    app.register_blueprint(workspace_blueprint)

    # --- Health Check Endpoint ---
    @app.route('/health')
    def health_check():
        return jsonify({"status": "ok"}), 200

    return app

if __name__ == "__main__":
    app = create_app()
    socketio.run(
        app,
        host="0.0.0.0",
        port=5000,
        debug=True,
        allow_unsafe_werkzeug=True,
        use_reloader=True,
        reloader_type='stat', # More stable than watchdog in this environment
    )

