from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

class User(UserMixin, db.Model):
    """User model for the application."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)
    
    # User-specific settings
    selected_model = db.Column(db.String(150), nullable=True)
    selected_persona = db.Column(db.String(150), nullable=True, default='default')

    def set_password(self, password):
        """Create a hashed password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check the hashed password."""
        return check_password_hash(self.password_hash, password)
