from flask import Blueprint, request, jsonify, render_template
from flask_login import login_user, logout_user, login_required, current_user
from models import User, get_user_by_username, _load_users, _save_users, get_user_by_id

auth = Blueprint("auth", __name__)

@auth.route("/register", methods=["GET", "POST"])
def register():
    """Handles user registration."""
    if request.method == 'GET':
        return render_template('register.html')

    data = request.get_json()
    username = data.get("username")
    password = data.get("password")

    if get_user_by_username(username):
        return jsonify({"message": "Username already exists"}), 409

    users = _load_users()
    new_id = max([int(k) for k in users.keys()]) + 1 if users else 1

    new_user = User(id=new_id, username=username, password_hash=None)
    new_user.set_password(password)

    users[str(new_id)] = new_user.to_dict()
    _save_users(users)

    # We need to fetch the user object again to make sure it's the correct class instance
    registered_user = get_user_by_id(new_id)
    login_user(registered_user, remember=True)

    return jsonify({"message": "Registration successful", "username": registered_user.username}), 201


@auth.route("/login", methods=["GET", "POST"])
def login():
    """Handles user login."""
    if request.method == 'GET':
        return render_template('login.html')

    data = request.get_json()
    user = get_user_by_username(data.get("username"))

    if user and user.check_password(data.get("password")):
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
