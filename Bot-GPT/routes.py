from flask import Blueprint, render_template
from flask_login import login_required, current_user
from models import Conversation

main = Blueprint('main', __name__)


@main.route('/')
def index():
    """Renders the main chat interface."""
    return render_template('index.html')


@main.route('/profile')
@login_required
def profile():
    """Renders the user profile page."""
    conversations = Conversation.query.filter_by(owner_id=current_user.id).all()
    return render_template('profile.html', user=current_user, conversations=conversations)
