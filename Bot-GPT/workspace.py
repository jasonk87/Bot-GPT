import os
import shutil
import uuid
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from app import socketio
from models import (
    load_conversation, save_conversation, check_permission,
    _load_users, get_user_by_id, add_to_conversation_index,
    add_user_to_conversation_index, remove_user_from_conversation_index,
    find_conversation_owner as find_owner_from_index
)
from tools.file_system import get_workspace_path
from tools import (
    get_file_tree,
    is_safe_path,
    call_chat_stream,
)


workspace = Blueprint("workspace", __name__)
call_ollama_chat_stream = call_chat_stream

def _get_conversation_path(owner_id, conversation_id):
    """Constructs the file path for a given conversation."""
    return os.path.join(current_app.instance_path, str(owner_id), 'conversations', f'{conversation_id}.json')

def find_conversation_owner(conversation_id):
    """Finds the owner of a conversation using the index."""
    index_path = os.path.join(current_app.instance_path, 'conversation_index.json')
    return find_owner_from_index(index_path, conversation_id)

def get_user_conversation_index_path():
    """Helper to construct the path to the user-conversation index file."""
    return os.path.join(current_app.instance_path, "user_conversation_index.json")


def get_users_path():
    """Constructs the path to the registered users file."""
    return os.path.join(current_app.config["USER_DATA_DIR"], "users.json")

@workspace.route("/api/workspace/files/<conversation_id>", methods=["GET"])
@login_required
def get_workspace_files(conversation_id):
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(path)
    if not conversation_data or not check_permission(conversation_data, current_user):
        return jsonify({"error": "Access denied"}), 403

    workspace_path = get_workspace_path(conversation_id, owner_id)
    if not workspace_path:
        return jsonify({"error": "Workspace not found"}), 404
    return jsonify(get_file_tree(workspace_path, workspace_path))


@workspace.route("/api/workspace/file", methods=["GET", "POST", "DELETE"])
@login_required
def handle_workspace_file():
    if request.method == 'GET':
        path = request.args.get("path")
        conversation_id = request.args.get("conversation_id")
    else:
        data = request.get_json()
        path = data.get("path")
        conversation_id = data.get("conversation_id")

    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data:
        return jsonify({"error": "Conversation not found"}), 404

    workspace_path = get_workspace_path(conversation_id, owner_id)
    file_path = os.path.join(workspace_path, path)

    if not is_safe_path(workspace_path, file_path):
        return jsonify({"error": "Invalid path"}), 403

    if request.method == 'GET':
        if not check_permission(conversation_data, current_user):
            return jsonify({"error": "Access denied"}), 403
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                content = f.read()
            return jsonify({"content": content})
        except FileNotFoundError:
            return jsonify({"error": "File not found"}), 404
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if request.method == 'POST':
        if not check_permission(conversation_data, current_user, level="owner"):
            return jsonify({"error": "Access denied for this operation"}), 403
        content = data.get("content")
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            socketio.emit("refresh_files", {"conversation_id": conversation_id}, room=str(conversation_id))
            return jsonify({"success": True, "message": f"File '{path}' saved."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

    if request.method == 'DELETE':
        if not check_permission(conversation_data, current_user, level="owner"):
            return jsonify({"error": "Access denied for this operation"}), 403
        try:
            if os.path.isfile(file_path):
                os.remove(file_path)
            elif os.path.isdir(file_path):
                shutil.rmtree(file_path)
            else:
                return jsonify({"error": "File or directory not found"}), 404
            socketio.emit("refresh_files", {"conversation_id": conversation_id}, room=str(conversation_id))
            return jsonify({"success": True, "message": f"Deleted '{path}'."})
        except Exception as e:
            return jsonify({"error": str(e)}), 500

@workspace.route("/api/conversations", methods=["GET", "DELETE"])
@login_required
def handle_conversations():
    if request.method == 'GET':
        from models import get_all_conversations_for_user
        convos = get_all_conversations_for_user(current_app.instance_path, current_user.id)
        convos.sort(key=lambda x: x.get('id', 0), reverse=True)
        return jsonify(convos)

    if request.method == 'DELETE':
        conversation_id = request.json.get("conversation_id")
        return delete_conversation_logic(conversation_id)

def delete_conversation_logic(conversation_id):
    """Common logic for deleting a conversation."""
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user, level="owner"):
        return jsonify({"error": "Access denied"}), 403

    try:
        # Remove from user-conversation index for all participants
        user_convo_index_path = get_user_conversation_index_path()
        for participant in conversation_data.get('participants', []):
            remove_user_from_conversation_index(user_convo_index_path, participant['user_id'], conversation_id)

        if os.path.exists(convo_path):
            os.remove(convo_path)
        workspace_path = get_workspace_path(conversation_id, owner_id)
        if os.path.exists(workspace_path):
            shutil.rmtree(workspace_path)

        # Remove from the main conversation index
        convo_index_path = os.path.join(current_app.instance_path, 'conversation_index.json')
        from models import _load_conversation_index, _save_conversation_index
        convo_index = _load_conversation_index(convo_index_path)
        if conversation_id in convo_index:
            del convo_index[conversation_id]
            _save_conversation_index(convo_index_path, convo_index)

        return jsonify({"success": True, "message": "Conversation deleted successfully"})
    except Exception as e:
        return jsonify({"error": str(e)}), 500

@workspace.route("/api/conversation/<conversation_id>", methods=["DELETE"])
@login_required
def delete_single_conversation(conversation_id):
    """Handles deletion of a single conversation from its specific endpoint."""
    return delete_conversation_logic(conversation_id)



@workspace.route("/api/conversation/<conversation_id>/share", methods=["POST"])
@login_required
def share_conversation(conversation_id):
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user, level="owner"):
        return jsonify({"error": "Access denied. Only the owner can share."}), 403

    user_id_to_share_with = request.json.get("user_id")
    if not user_id_to_share_with:
        return jsonify({"error": "user_id is required"}), 400

    user_to_share_with = get_user_by_id(get_users_path(), user_id_to_share_with)
    if not user_to_share_with:
        return jsonify({"error": "User to share with not found"}), 404

    participants = conversation_data.get('participants', [])
    if any(p['user_id'] == user_id_to_share_with for p in participants):
        return jsonify({"message": "User is already a participant"}), 200

    participants.append({'user_id': user_id_to_share_with, 'role': 'participant'})
    conversation_data['participants'] = participants
    save_conversation(convo_path, conversation_data)

    user_convo_index_path = get_user_conversation_index_path()
    add_user_to_conversation_index(user_convo_index_path, user_id_to_share_with, conversation_id)

    return jsonify({"message": "Conversation shared successfully"}), 201


@workspace.route("/api/conversation/<conversation_id>/summarize", methods=["GET"])
@login_required
def summarize_conversation(conversation_id):
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user):
        return jsonify({"error": "Access denied"}), 403

    conversation_text = "\n".join(
        [f"{msg['role'].capitalize()}: {msg['content']}" for msg in conversation_data.get('messages', [])]
    )
    summary_prompt = f"Please provide a concise summary of the following conversation:\n\n{conversation_text}"

    try:
        model = current_user.selected_model
        stream = call_ollama_chat_stream(
            model,
            messages=[{"role": "user", "content": summary_prompt}],
            system_prompt="You are a helpful assistant that summarizes conversations."
        )
        return Response(stream, mimetype='text/plain')
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@workspace.route("/api/users", methods=["GET"])
@login_required
def get_users():
    users = _load_users(get_users_path())
    users_list = [
        {"id": int(uid), "username": uinfo['username']}
        for uid, uinfo in users.items()
        if int(uid) != current_user.id
    ]
    return jsonify(users_list)


@workspace.route("/api/upload", methods=["POST"])
@login_required
def upload_file():
    if "files[]" not in request.files:
        return jsonify(error="No file part"), 400
    files = request.files.getlist("files[]")
    if not files or files[0].filename == '':
        return jsonify(error="No selected file"), 400

    prompt = request.form.get("prompt", "")
    conversation_id = request.form.get("conversation_id")

    if conversation_id:
        owner_id = find_conversation_owner(conversation_id)
        if not owner_id:
             return jsonify(error="Conversation not found"), 404
        convo_path = _get_conversation_path(owner_id, conversation_id)
        conversation_data = load_conversation(convo_path)
        if not check_permission(conversation_data, current_user):
            return jsonify(error="Access denied"), 403
    else:
        conversation_id = str(uuid.uuid4())
        owner_id = current_user.id
        conversation_data = {
            "id": conversation_id,
            "owner_id": owner_id,
            "title": "New Chat",
            "participants": [{'user_id': owner_id, 'role': 'owner'}],
            "messages": []
        }
        convo_path = _get_conversation_path(owner_id, conversation_id)
        save_conversation(convo_path, conversation_data)

        # Add to the new index
        index_path = os.path.join(current_app.instance_path, 'conversation_index.json')
        add_to_conversation_index(index_path, conversation_id, owner_id)
        add_user_to_conversation_index(get_user_conversation_index_path(), owner_id, conversation_id)

    workspace_path = get_workspace_path(conversation_id, owner_id)
    os.makedirs(workspace_path, exist_ok=True)

    filenames = []
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(workspace_path, filename))
            filenames.append(filename)

    file_list_str = "\\n- ".join(filenames)
    message_to_ai = f"User uploaded the following files to the workspace:\\n- {file_list_str}\\n\\nUser's prompt: {prompt}"

    socketio.emit('refresh_files', {'conversation_id': conversation_id}, room=conversation_id)
    return jsonify(message=message_to_ai, conversation_id=conversation_id), 200


@workspace.route("/api/workspace/folder", methods=["POST"])
@login_required
def create_workspace_folder():
    data = request.get_json() or {}
    path = data.get("path", "").strip()
    conversation_id = data.get("conversation_id")

    if not path or not conversation_id:
        return jsonify({"error": "path and conversation_id are required"}), 400

    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user, level="owner"):
        return jsonify({"error": "Access denied for this operation"}), 403

    workspace_path = get_workspace_path(conversation_id, owner_id)
    folder_path = os.path.join(workspace_path, path)
    if not is_safe_path(workspace_path, folder_path):
        return jsonify({"error": "Invalid path"}), 403

    os.makedirs(folder_path, exist_ok=True)
    socketio.emit("refresh_files", {"conversation_id": conversation_id}, room=str(conversation_id))
    return jsonify({"success": True, "message": f"Created '{path}'."})


@workspace.route("/api/workspace/rename", methods=["POST"])
@login_required
def rename_workspace_item():
    data = request.get_json() or {}
    old_path = data.get("old_path", "").strip()
    new_path = data.get("new_path", "").strip()
    conversation_id = data.get("conversation_id")

    if not old_path or not new_path or not conversation_id:
        return jsonify({"error": "old_path, new_path, and conversation_id are required"}), 400

    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user, level="owner"):
        return jsonify({"error": "Access denied for this operation"}), 403

    workspace_path = get_workspace_path(conversation_id, owner_id)
    source_path = os.path.join(workspace_path, old_path)
    destination_path = os.path.join(workspace_path, new_path)
    if not is_safe_path(workspace_path, source_path) or not is_safe_path(workspace_path, destination_path):
        return jsonify({"error": "Invalid path"}), 403
    if not os.path.exists(source_path):
        return jsonify({"error": "File or directory not found"}), 404

    os.makedirs(os.path.dirname(destination_path), exist_ok=True)
    shutil.move(source_path, destination_path)
    socketio.emit("refresh_files", {"conversation_id": conversation_id}, room=str(conversation_id))
    return jsonify({"success": True, "message": f"Renamed '{old_path}' to '{new_path}'."})
