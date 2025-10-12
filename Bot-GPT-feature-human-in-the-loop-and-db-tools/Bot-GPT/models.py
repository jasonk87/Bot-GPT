from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(UserMixin, db.Model):
    """User model for the application."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)

    # User-specific settings
    selected_model = db.Column(
        db.String(150), nullable=False, default='qwen3:8b'
    )
    selected_persona = db.Column(
        db.String(150), nullable=True, default='default'
    )

    conversations = db.relationship(
        'ConversationParticipant',
        back_populates='user',
        cascade="all, delete-orphan"
    )

    def set_password(self, password):
        """Create a hashed password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check the hashed password."""
        return check_password_hash(self.password_hash, password)


class ConversationParticipant(db.Model):
    __tablename__ = 'conversation_participant'
    user_id = db.Column(
        db.Integer, db.ForeignKey('user.id'), primary_key=True
    )
    conversation_id = db.Column(
        db.String, db.ForeignKey('conversation.id'), primary_key=True
    )
    role = db.Column(
        db.String(20), nullable=False, default='participant'
    )  # e.g., 'owner', 'participant'

    user = db.relationship('User', back_populates='conversations')
    conversation = db.relationship(
        'Conversation', back_populates='participants'
    )


class Conversation(db.Model):
    id = db.Column(db.String(150), primary_key=True)
    title = db.Column(db.String(100), nullable=False, default="New Chat")
    owner_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)

    owner = db.relationship('User')
    participants = db.relationship(
        'ConversationParticipant',
        back_populates='conversation',
        cascade="all, delete-orphan"
    )
