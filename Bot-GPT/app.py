import os
import json
from flask import Flask
from extensions import db, login_manager, socketio, csrf
from models import User
from routes import main as main_blueprint


def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(
        __name__,
        instance_relative_config=True,
        template_folder='templates'
    )

    # --- Configuration ---
    try:
        with open('../credentials.json') as f:
            credentials = json.load(f)
        app.config['SECRET_KEY'] = credentials['SECRET_KEY']
    except (FileNotFoundError, KeyError):
        print("WARNING: credentials.json not found or SECRET_KEY not set. Using a temporary secret key.")
        app.config['SECRET_KEY'] = 'a_very_secret_key_that_should_be_changed'
    # Use instance folder for the database.
    db_path = os.path.join(app.instance_path, 'users.db')
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{db_path}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    ollama_host = os.environ.get("OLLAMA_HOST", "http://192.168.86.30:11434")
    app.config['OLLAMA_HOST'] = ollama_host
    user_data_dir = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "user_data"
    )
    app.config['USER_DATA_DIR'] = user_data_dir

    # --- Google Search API Configuration ---
    try:
        # Try to import keys from a local key.py file
        from key import GOOGLE_API_KEY, GOOGLE_CSE_ID
        app.config['GOOGLE_API_KEY'] = GOOGLE_API_KEY
        app.config['GOOGLE_CSE_ID'] = GOOGLE_CSE_ID
        print("INFO: Successfully loaded Google API keys from key.py")
    except ImportError as e:
        if "No module named 'key'" in str(e):
            print("INFO: 'key.py' not found. Falling back to env vars.")
        else:
            print(f"WARNING: Could not import from 'key.py': {e}")

        # Fallback to environment variables
        app.config['GOOGLE_API_KEY'] = os.environ.get("GOOGLE_API_KEY", "")
        app.config['GOOGLE_CSE_ID'] = os.environ.get("GOOGLE_CSE_ID", "")

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
    csrf.init_app(app)
    login_manager.login_view = 'main.login'

    @login_manager.user_loader
    def load_user(user_id):
        # Updated to use the modern Session.get() method
        return db.session.get(User, int(user_id))

    # --- Register Blueprints ---
    app.register_blueprint(main_blueprint)

    # --- Create Database Tables ---
    with app.app_context():
        db.create_all()

    return app


if __name__ == '__main__':
    app = create_app()
    debug_mode = os.environ.get('FLASK_DEBUG', 'false').lower() in ['true', '1', 't']
    socketio.run(app, host='0.0.0.0', port=5000, debug=debug_mode)
