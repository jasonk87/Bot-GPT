import os
import json
import logging
from werkzeug.security import generate_password_hash, check_password_hash
from flask_login import UserMixin
try:
    from filelock import FileLock
except ImportError:  # pragma: no cover - fallback for minimal environments
    class FileLock:  # type: ignore[override]
        def __init__(self, _path):
            self._path = _path

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

logging.basicConfig(level=logging.INFO)

class User(UserMixin):
    """A user class for the file-based authentication system."""
    def __init__(self, id, username, password_hash, **kwargs):
        self.id = int(id)
        self.username = username
        self.password_hash = password_hash
        self.display_name = kwargs.get('display_name', '')
        self.selected_model = kwargs.get('selected_model', '')
        self.selected_persona = kwargs.get('selected_persona', 'default')
        self.response_mode_preference = kwargs.get('response_mode_preference', 'auto')
        self.thought_panel_expanded = kwargs.get('thought_panel_expanded', False)

    def to_dict(self):
        return {
            'id': self.id,
            'username': self.username,
            'password_hash': self.password_hash,
            'display_name': self.display_name,
            'selected_model': self.selected_model,
            'selected_persona': self.selected_persona,
            'response_mode_preference': self.response_mode_preference,
            'thought_panel_expanded': self.thought_panel_expanded,
        }

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

def _load_users(path):
    """Loads the users from the given path."""
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

def _save_users(path, users_dict):
    """Saves the users to the given path."""
    lock = FileLock(f"{path}.lock")
    with lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(users_dict, f, indent=4)

def get_user_by_id(path, user_id):
    """Gets a user by their ID from the given path."""
    users = _load_users(path)
    user_data = users.get(str(user_id))
    if user_data:
        return User(**user_data)
    return None

def get_user_by_username(path, username):
    """Gets a user by their username from the given path."""
    normalized_username = username.strip().lower()
    users = _load_users(path)
    for user_data in users.values():
        if user_data['username'].strip().lower() == normalized_username:
            return User(**user_data)
    return None

def load_conversation(path):
    """Loads a single conversation from its JSON file."""
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return None
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return None

def save_conversation(path, conversation_data):
    """Saves a single conversation to its JSON file."""
    lock = FileLock(f"{path}.lock")
    with lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(conversation_data, f, indent=4)

def _load_conversation_index(path):
    """Loads the conversation index."""
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

def _save_conversation_index(path, index_data):
    """Saves the conversation index."""
    lock = FileLock(f"{path}.lock")
    with lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(index_data, f, indent=4)

def add_to_conversation_index(path, conversation_id, owner_id):
    """Adds a conversation to the index."""
    index = _load_conversation_index(path)
    index[str(conversation_id)] = owner_id
    _save_conversation_index(path, index)

def add_user_to_conversation_index(path, user_id, conversation_id):
    """Adds a conversation to a user's list in the index."""
    index = _load_user_conversation_index(path)
    user_id_str = str(user_id)
    if user_id_str not in index:
        index[user_id_str] = []
    if conversation_id not in index[user_id_str]:
        index[user_id_str].append(conversation_id)
    _save_user_conversation_index(path, index)

def remove_user_from_conversation_index(path, user_id, conversation_id):
    """Removes a conversation from a user's list in the index."""
    index = _load_user_conversation_index(path)
    user_id_str = str(user_id)
    if user_id_str in index and conversation_id in index[user_id_str]:
        index[user_id_str].remove(conversation_id)
        if not index[user_id_str]:  # Clean up empty list
            del index[user_id_str]
    _save_user_conversation_index(path, index)

def find_conversation_owner(path, conversation_id):
    """Finds the owner of a conversation from the index."""
    index = _load_conversation_index(path)
    return index.get(str(conversation_id))

def _load_user_conversation_index(path):
    """Loads the user-to-conversation index."""
    lock = FileLock(f"{path}.lock")
    with lock:
        if not os.path.exists(path):
            return {}
        try:
            with open(path, 'r') as f:
                return json.load(f)
        except (json.JSONDecodeError, FileNotFoundError):
            return {}

def _save_user_conversation_index(path, index_data):
    """Saves the user-to-conversation index."""
    lock = FileLock(f"{path}.lock")
    with lock:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, 'w') as f:
            json.dump(index_data, f, indent=4)

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

def get_all_conversations_for_user(instance_path, user_id):
    """
    Finds all conversations a user is a participant in using the user-conversation index.
    """
    user_convo_index_path = os.path.join(instance_path, 'user_conversation_index.json')
    user_convo_index = _load_user_conversation_index(user_convo_index_path)
    conversation_ids = user_convo_index.get(str(user_id), [])

    user_convos = []
    for convo_id in conversation_ids:
        convo_owner_index_path = os.path.join(instance_path, 'conversation_index.json')
        owner_id = find_conversation_owner(convo_owner_index_path, convo_id)
        if owner_id:
            convo_path = os.path.join(instance_path, str(owner_id), 'conversations', f'{convo_id}.json')
            convo_data = load_conversation(convo_path)
            if convo_data:
                role = 'owner' if str(convo_data.get('owner_id')) == str(user_id) else 'participant'
                user_convos.append({
                    'id': convo_data.get('id'),
                    'title': convo_data.get('title'),
                    'role': role
                })
    return user_convos
