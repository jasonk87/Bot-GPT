from flask import Blueprint, render_template, request, jsonify, current_app
from flask_login import login_required, current_user
from models import Conversation
from werkzeug.utils import secure_filename
import os
from utils import get_workspace_path

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


@main.route('/upload', methods=['POST'])
@login_required
def upload_file():
    if 'file' not in request.files:
        return jsonify({'error': 'No file part'}), 400

    file = request.files['file']
    conversation_id = request.form.get('conversation_id')

    if file.filename == '':
        return jsonify({'error': 'No selected file'}), 400

    if file and conversation_id:
        filename = secure_filename(file.filename)
        workspace_path = get_workspace_path(conversation_id, current_user.id)
        if not workspace_path:
            return jsonify({'error': 'Could not determine workspace.'}), 400

        file.save(os.path.join(workspace_path, filename))
        return jsonify({'message': 'File uploaded successfully', 'filename': filename}), 200

    return jsonify({'error': 'Invalid request'}), 400
