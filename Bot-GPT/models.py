from datetime import datetime
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db


class User(UserMixin, db.Model):
    """User model for the application."""

    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)

    # User-specific settings
    selected_model = db.Column(db.String(150), nullable=False, default="qwen3:8b")
    selected_persona = db.Column(db.String(150), nullable=True, default="default")

    conversations = db.relationship(
        "ConversationParticipant", back_populates="user", cascade="all, delete-orphan"
    )

    def set_password(self, password):
        """Create a hashed password."""
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        """Check the hashed password."""
        return check_password_hash(self.password_hash, password)


class ConversationParticipant(db.Model):
    __tablename__ = "conversation_participant"
    user_id = db.Column(db.Integer, db.ForeignKey("user.id"), primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversation.id"), primary_key=True
    )
    role = db.Column(
        db.String(20), nullable=False, default="participant"
    )  # e.g., 'owner', 'participant'

    user = db.relationship("User", back_populates="conversations")
    conversation = db.relationship("Conversation", back_populates="participants")


class Conversation(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    title = db.Column(db.String(100), nullable=False, default="New Chat")
    owner_id = db.Column(db.Integer, db.ForeignKey("user.id"), nullable=False)

    owner = db.relationship("User")
    participants = db.relationship(
        "ConversationParticipant",
        back_populates="conversation",
        cascade="all, delete-orphan",
    )
    messages = db.relationship(
        "Message",
        back_populates="conversation",
        cascade="all, delete-orphan",
        order_by="Message.timestamp",
    )

    def check_permission(self, user, level="participant"):
        """
        Check if a user has a certain permission level for this conversation.
        Level can be 'participant' or 'owner'.
        """
        # The owner always has the highest level of permission.
        if self.owner_id == user.id:
            return True

        # If 'owner' level is explicitly required, and the user is not the owner, deny access.
        if level == "owner":
            return False

        # For 'participant' level, check if they are in the participants list.
        is_participant = any(p.user_id == user.id for p in self.participants)
        return is_participant


class Message(db.Model):
    """Message model for storing chat history."""

    id = db.Column(db.Integer, primary_key=True)
    conversation_id = db.Column(
        db.Integer, db.ForeignKey("conversation.id"), nullable=False
    )
    role = db.Column(db.String(50), nullable=False)  # 'user' or 'assistant'
    content = db.Column(db.Text, nullable=False)
    timestamp = db.Column(db.DateTime, nullable=False, default=datetime.utcnow)

    conversation = db.relationship("Conversation", back_populates="messages")
