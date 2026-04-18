from flask import Blueprint, render_template, current_app
from flask_login import login_required, current_user
from models import get_all_conversations_for_user

main = Blueprint("main", __name__)


@main.route("/")
def index():
    """Renders the main chat interface."""
    return render_template("index.html")


@main.route("/profile")
@login_required
def profile():
    """Renders the user profile page."""
    conversations = get_all_conversations_for_user(current_app.instance_path, current_user.id)
    return render_template(
        "profile.html", user=current_user, conversations=conversations
    )
