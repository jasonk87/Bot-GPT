import os
import json
import logging
from flask import current_app
from flask_login import UserMixin
from werkzeug.security import generate_password_hash, check_password_hash

logging.basicConfig(level=logging.INFO)

# --- User Management ---

class User(UserMixin):
    """A user class for the file-based authentication system."""
    def __init__(self, id, username, password_hash, **kwargs):
        self.id = int(id)
        self.username = username
        self.password_hash = password_hash
        self.selected_model = kwargs.get('selected_model', 'qwen3:8b')
        self.selected_persona = kwargs.get('selected_persona', 'default')

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'password_hash': self.password_hash,
            'selected_model': self.selected_model,
            'selected_persona': self.selected_persona
        }

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

def _get_users_path():
    """Gets the path to the users.json file."""
    return os.path.join(current_app.instance_path, 'users.json')

def _load_users():
    """Loads the users from the users.json file."""
    path = _get_users_path()
    if not os.path.exists(path):
        return {}
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return {}

def _save_users(users_dict):
    """Saves the users to the users.json file."""
    path = _get_users_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(users_dict, f, indent=4)

def get_user_by_id(user_id):
    """Gets a user by their ID."""
    users = _load_users()
    user_data = users.get(str(user_id))
    if user_data:
        return User(**user_data)
    return None

def get_user_by_username(username):
    """Gets a user by their username."""
    users = _load_users()
    for user_data in users.values():
        if user_data['username'] == username:
            return User(**user_data)
    return None

# --- Conversation Management ---

def _get_conversation_path(owner_id, conversation_id):
    """Constructs the file path for a given conversation."""
    return os.path.join(current_app.instance_path, str(owner_id), 'conversations', f'{conversation_id}.json')

def load_conversation(owner_id, conversation_id):
    """Loads a single conversation from its JSON file."""
    path = _get_conversation_path(owner_id, conversation_id)
    if not os.path.exists(path):
        return None
    try:
        with open(path, 'r') as f:
            return json.load(f)
    except (json.JSONDecodeError, FileNotFoundError):
        return None

def save_conversation(owner_id, conversation_id, conversation_data):
    """Saves a single conversation to its JSON file."""
    path = _get_conversation_path(owner_id, conversation_id)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, 'w') as f:
        json.dump(conversation_data, f, indent=4)

def get_all_conversations_for_user(user_id):
    """
    Finds all conversations a user is a participant in by scanning all users' conversation files.
    """
    all_users = _load_users()
    user_convos = []
    user_id_str = str(user_id)

    for owner_id in all_users.keys():
        convo_dir = os.path.join(current_app.instance_path, str(owner_id), 'conversations')
        if not os.path.isdir(convo_dir):
            continue

        for filename in os.listdir(convo_dir):
            if filename.endswith('.json'):
                convo_id = filename.split('.')[0]
                convo_data = load_conversation(owner_id, convo_id)
                if convo_data:
                    # Check if the user is the owner or a participant
                    is_participant = any(p['user_id'] == user_id for p in convo_data.get('participants', []))
                    if str(convo_data.get('owner_id')) == user_id_str or is_participant:
                        role = 'owner' if str(convo_data.get('owner_id')) == user_id_str else 'participant'
                        user_convos.append({
                            'id': convo_data.get('id'),
                            'title': convo_data.get('title'),
                            'role': role
                        })
    return user_convos

def check_permission(conversation_data, user, level="participant"):
    """
    Checks permission based on the conversation data dictionary.
    """
    if not conversation_data or not user:
        return False

    owner_id = conversation_data.get('owner_id')
    if owner_id == user.id:
        return True

    if level == 'owner':
        return False

    participants = conversation_data.get('participants', [])
    is_participant = any(p.get('user_id') == user.id for p in participants)
    return is_participant
