from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash
from extensions import db

# --- Core User & Conversation Models ---

class User(UserMixin, db.Model):
    """User model for the application."""
    id = db.Column(db.Integer, primary_key=True)
    username = db.Column(db.String(150), unique=True, nullable=False)
    password_hash = db.Column(db.String(150), nullable=False)

    # User-specific settings
    selected_model = db.Column(db.String(150), nullable=True)
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

# --- V2.0: Fully Implemented Multi-Layered Memory Models ---

class GlobalKnowledge(db.Model):
    """Stores shared, non-personal knowledge for the RAG system (cached web searches, etc.)."""
    id = db.Column(db.Integer, primary_key=True)
    query_text = db.Column(db.String(500), unique=True, nullable=False)
    response_content = db.Column(db.Text, nullable=False)

class UserMemory(db.Model):
    """Stores private, key-value facts about a specific user."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    fact_key = db.Column(db.String(150), nullable=False)
    fact_value = db.Column(db.String(500), nullable=False)
    context = db.Column(db.String(250), nullable=True) # e.g., "for Kentucky", "during 2025"
    user = db.relationship('User', foreign_keys=[user_id])

class UserRelationship(db.Model):
    """Defines relationships between users for natural language understanding."""
    id = db.Column(db.Integer, primary_key=True)
    user_one_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    user_two_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    relationship_description = db.Column(db.String(150), nullable=False) # e.g., "is the wife of"

    user_one = db.relationship('User', foreign_keys=[user_one_id])
    user_two = db.relationship('User', foreign_keys=[user_two_id])

class UserPreferences(db.Model):
    """Stores behavioral preferences for a user to tailor the agent's style."""
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    preference_key = db.Column(db.String(150), nullable=False)
    preference_value = db.Column(db.String(500), nullable=False)
    user = db.relationship('User', foreign_keys=[user_id])