import os
from flask import Flask
from extensions import db, login_manager
from models import User
from routes import main as main_blueprint

def create_app():
    """Create and configure an instance of the Flask application."""
    app = Flask(__name__, instance_relative_config=True, template_folder='templates')
    
    # --- Configuration ---
    app.config['SECRET_KEY'] = 'a_very_secret_key_that_should_be_changed'
    # Use instance folder for the database.
    app.config['SQLALCHEMY_DATABASE_URI'] = f"sqlite:///{os.path.join(app.instance_path, 'users.db')}"
    app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False
    app.config['MAX_CONTENT_LENGTH'] = 16 * 1024 * 1024
    app.config['OLLAMA_HOST'] = os.environ.get("OLLAMA_HOST", "http://192.168.86.30:11434")
    app.config['USER_DATA_DIR'] = os.path.join(os.path.dirname(os.path.abspath(__file__)), "user_data")

    # Ensure the instance folder exists
    try:
        os.makedirs(app.instance_path)
    except OSError:
        pass

    # --- Initialize Extensions ---
    db.init_app(app)
    login_manager.init_app(app)
    login_manager.login_view = 'main.login'

    @login_manager.user_loader
    def load_user(user_id):
        # Updated to use the modern Session.get() method to avoid legacy warnings
        return db.session.get(User, int(user_id))

    # --- Register Blueprints ---
    app.register_blueprint(main_blueprint)

    # --- Create Database Tables ---
    with app.app_context():
        db.create_all()

    return app

if __name__ == '__main__':
    app = create_app()
    app.run(host='0.0.0.0', port=5000, debug=True)
