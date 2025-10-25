from flask import Blueprint, request, jsonify
from flask_login import login_user, logout_user, login_required, current_user
from extensions import db
from models import User

auth = Blueprint('auth', __name__)


@auth.route('/register', methods=['POST'])
def register():
    """Handles user registration."""
    data = request.get_json()
    username = data.get('username')
    password = data.get('password')
    if User.query.filter_by(username=username).first():
        return jsonify({"message": "Username already exists"}), 409
    new_user = User(username=username)
    new_user.set_password(password)
    db.session.add(new_user)
    db.session.commit()
    login_user(new_user, remember=True)
    return jsonify({
        "message": "Registration successful",
        "username": new_user.username
    }), 201


@auth.route('/login', methods=['POST'])
def login():
    """Handles user login."""
    data = request.get_json()
    user = User.query.filter_by(username=data.get('username')).first()
    if user and user.check_password(data.get('password')):
        login_user(user, remember=True)
        return jsonify({
            "message": "Login successful", "username": user.username
        }), 200
    return jsonify({"message": "Invalid username or password"}), 401


@auth.route('/logout')
@login_required
def logout():
    """Handles user logout."""
    logout_user()
    return jsonify({"message": "Logout successful"}), 200


@auth.route('/check_auth')
def check_auth():
    """Checks if a user is currently authenticated."""
    if current_user.is_authenticated:
        return jsonify({"username": current_user.username}), 200
    return jsonify({"message": "Not authenticated"}), 401
