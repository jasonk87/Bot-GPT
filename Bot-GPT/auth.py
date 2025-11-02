import os
import json
from flask import Blueprint, request, jsonify, current_app
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash
from filelock import FileLock

from models import User, get_user_by_username, _load_users, _save_users

auth = Blueprint("auth", __name__)

def get_users_path():
    """Constructs the path to the users.json file."""
    return os.path.join(current_app.config["USER_DATA_DIR"], 'users.json')

@auth.route("/register", methods=["POST"])
def register():
    """Handles user registration using a file-based system."""
    users_path = get_users_path()
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"message": "Username and password are required"}), 400

    # Check if user already exists
    if get_user_by_username(users_path, username):
        return jsonify({"message": "Username already exists"}), 409

    # Load users, create new user, and save
    users = _load_users(users_path)

    # Determine new user ID
    new_user_id = max([int(k) for k in users.keys()]) + 1 if users else 1

    # Create new user object
    password_hash = generate_password_hash(password)
    new_user = User(id=new_user_id, username=username, password_hash=password_hash)

    # Add to users dictionary and save
    users[str(new_user_id)] = new_user.to_dict()
    _save_users(users_path, users)

    # Log in the new user
    login_user(new_user, remember=True)

    return jsonify({
        "message": "Registration successful",
        "username": new_user.username
    }), 201


@auth.route("/login", methods=["POST"])
def login():
    """Handles user login using a file-based system."""
    users_path = get_users_path()
    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if not username or not password:
        return jsonify({"message": "Username and password are required"}), 400

    user = get_user_by_username(users_path, username)
    if user and user.check_password(password):
        login_user(user, remember=True)
        return jsonify({"message": "Login successful", "username": user.username}), 200

    return jsonify({"message": "Invalid username or password"}), 401


@auth.route("/logout")
@login_required
def logout():
    """Handles user logout."""
    logout_user()
    return jsonify({"message": "Logout successful"}), 200


@auth.route("/check_auth")
def check_auth():
    """Checks if a user is currently authenticated."""
    if current_user.is_authenticated:
        return jsonify({"username": current_user.username}), 200
    return jsonify({"message": "Not authenticated"}), 401
