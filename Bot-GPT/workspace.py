import os
import shutil
import json
import time
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from extensions import db
from models import Conversation, User, ConversationParticipant
from tools import (
    get_workspace_path,
    get_file_tree,
    is_safe_path,
    call_ollama_chat_stream,
)

workspace = Blueprint("workspace", __name__)


@workspace.route("/api/workspace/files/<conversation_id>", methods=["GET"])
@login_required
def get_workspace_files(conversation_id):
    conversation = Conversation.query.get(conversation_id)
    if not conversation or not conversation.is_participant(current_user.id):
        return jsonify([])
    workspace_path = get_workspace_path(conversation_id, conversation.owner_id)
    return jsonify(get_file_tree(workspace_path))


@workspace.route("/api/workspace/file", methods=["GET"])
@login_required
def get_workspace_file_content():
    path = request.args.get("path")
    conversation_id = request.args.get("conversation_id")
    conversation = Conversation.query.get(conversation_id)
    if not conversation or not conversation.is_participant(current_user.id):
        return jsonify({"error": "Access denied"}), 403

    workspace_path = get_workspace_path(conversation_id, conversation.owner_id)
    file_path = os.path.join(workspace_path, path)
    if not is_safe_path(workspace_path, file_path):
        return jsonify({"error": "Access denied"}), 403

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
        return jsonify({"content": content})
    except FileNotFoundError:
        return jsonify({"error": "File not found"}), 404
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@workspace.route("/api/workspace/file", methods=["POST"])
@login_required
def save_workspace_file():
    data = request.get_json()
    path = data.get("path")
    content = data.get("content")
    conversation_id = data.get("conversation_id")
    conversation = Conversation.query.get(conversation_id)

    if not conversation or conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied"}), 403

    workspace_path = get_workspace_path(conversation_id, conversation.owner_id)
    file_path = os.path.join(workspace_path, path)
    if not is_safe_path(workspace_path, file_path):
        return jsonify({"error": "Access denied"}), 403

    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return jsonify({"success": True, "message": f"File '{path}' saved."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@workspace.route("/api/conversations", methods=["GET"])
@login_required
def get_conversations():
    convos = [
        {
            "id": link.conversation.id,
            "title": link.conversation.title,
            "role": link.role,
        }
        for link in current_user.conversations
    ]
    convos.sort(key=lambda x: x["id"], reverse=True)
    return jsonify(convos)


@workspace.route("/api/conversation/<session_id>", methods=["GET"])
@login_required
def get_conversation(session_id):
    conversation = Conversation.query.get(session_id)
    if not conversation or not conversation.is_participant(current_user.id):
        return jsonify({"error": "Access denied"}), 403

    convo_path = os.path.join(
        current_app.config["USER_DATA_DIR"],
        str(conversation.owner_id),
        "conversations",
        f"{session_id}.json",
    )
    if os.path.exists(convo_path):
        with open(convo_path, "r", encoding="utf-8") as f:
            convo_data = json.load(f)
        return jsonify(convo_data)
    return jsonify({"error": "Conversation data not found"}), 404


@workspace.route("/api/conversation/<session_id>/share", methods=["POST"])
@login_required
def share_conversation(session_id):
    """Shares a conversation with another user."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied. Only the owner can share."}), 403

    data = request.get_json()
    user_id_to_share_with = data.get("user_id")
    if not user_id_to_share_with:
        return jsonify({"error": "user_id is required"}), 400

    user_to_share_with = User.query.get(user_id_to_share_with)
    if not user_to_share_with:
        return jsonify({"error": "User to share with not found"}), 404

    is_already_participant = any(
        p.user_id == user_id_to_share_with for p in conversation.participants
    )
    if is_already_participant:
        return jsonify({"message": "User is already a participant"}), 200

    new_participant = ConversationParticipant(
        user_id=user_id_to_share_with, conversation_id=session_id, role="participant"
    )
    db.session.add(new_participant)
    db.session.commit()

    return jsonify({"message": "Conversation shared successfully"}), 201


@workspace.route("/api/conversation/<session_id>", methods=["DELETE"])
@login_required
def delete_conversation(session_id):
    """Deletes a conversation and its associated workspace."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return jsonify({"error": "Conversation not found"}), 404

    if conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied. Only the owner can delete."}), 403

    user_data_dir = os.path.join(
        current_app.config["USER_DATA_DIR"], str(conversation.owner_id)
    )
    convo_path = os.path.join(user_data_dir, "conversations", f"{session_id}.json")
    workspace_path = os.path.join(user_data_dir, "workspaces", session_id)

    try:
        if os.path.exists(convo_path):
            os.remove(convo_path)
        if os.path.exists(workspace_path):
            shutil.rmtree(workspace_path)

        db.session.delete(conversation)
        db.session.commit()

        return jsonify({"success": True})
    except Exception as e:
        db.session.rollback()
        return jsonify({"error": str(e)}), 500


@workspace.route("/api/conversation/<session_id>/summarize", methods=["GET"])
@login_required
def summarize_conversation(session_id):
    """Streams a summary of a conversation."""
    conversation = Conversation.query.get(session_id)
    if not conversation:
        return Response("Conversation not found", status=404)

    is_participant = any(
        p.user_id == current_user.id for p in conversation.participants
    )
    if not is_participant:
        return Response("Access denied", status=403)

    owner_id = conversation.owner_id
    convo_path = os.path.join(
        current_app.config["USER_DATA_DIR"],
        str(owner_id),
        "conversations",
        f"{session_id}.json",
    )

    if not os.path.exists(convo_path):
        return Response("Conversation data not found", status=404)

    with open(convo_path, "r", encoding="utf-8") as f:
        convo_data = json.load(f)

    messages = convo_data.get("messages", [])
    summary_prompt_messages = [
        {"role": msg["role"], "content": msg["content"]}
        for msg in messages
        if msg["role"] in ["user", "assistant"]
    ]
    summary_model = "llama3.2:latest"
    system_prompt = "You are a summarization expert. Based on the following conversation, provide a concise summary in a few paragraphs. Use markdown for formatting."

    def event_stream():
        try:
            stream = call_ollama_chat_stream(
                summary_model, summary_prompt_messages, system_prompt
            )
            for line in stream:
                try:
                    parsed_data = json.loads(line)
                    chunk = parsed_data.get("message", {}).get("content", "")
                    yield chunk
                except json.JSONDecodeError:
                    continue
        except Exception as e:
            print(f"Error during summarization stream: {e}")
            yield "Sorry, an error occurred while generating the summary."

    return Response(event_stream(), mimetype="text/plain")


@workspace.route("/api/users", methods=["GET"])
@login_required
def get_users():
    """Returns a list of all users, excluding the current user."""
    users = User.query.all()
    users_list = [
        {"id": user.id, "username": user.username}
        for user in users
        if user.id != current_user.id
    ]
    return jsonify(users_list)


@workspace.route("/api/workspace/folder", methods=["POST"])
@login_required
def create_folder():
    """Creates a new folder in the workspace."""
    data = request.get_json()
    path = data.get("path")
    conversation_id = data.get("conversation_id")
    conversation = Conversation.query.get(conversation_id)

    if not conversation or conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied"}), 403

    workspace_path = get_workspace_path(conversation_id, conversation.owner_id)
    folder_path = os.path.join(workspace_path, path)
    if not is_safe_path(workspace_path, folder_path):
        return jsonify({"error": "Access denied"}), 403

    try:
        os.makedirs(folder_path, exist_ok=True)
        return jsonify({"success": True, "message": f"Folder '{path}' created."})
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@workspace.route("/api/workspace/rename", methods=["POST"])
@login_required
def rename_file_or_folder():
    """Renames a file or folder in the workspace."""
    data = request.get_json()
    old_path = data.get("old_path")
    new_path = data.get("new_path")
    conversation_id = data.get("conversation_id")
    conversation = Conversation.query.get(conversation_id)

    if not conversation or conversation.owner_id != current_user.id:
        return jsonify({"error": "Access denied"}), 403

    workspace_path = get_workspace_path(conversation_id, conversation.owner_id)
    old_full_path = os.path.join(workspace_path, old_path)
    new_full_path = os.path.join(workspace_path, new_path)
    if not is_safe_path(workspace_path, old_full_path) or not is_safe_path(
        workspace_path, new_full_path
    ):
        return jsonify({"error": "Access denied"}), 403

    try:
        os.rename(old_full_path, new_full_path)
        return jsonify(
            {"success": True, "message": f"Renamed '{old_path}' to '{new_path}'."}
        )
    except Exception as e:
        return jsonify({"error": str(e)}), 500


@workspace.route("/api/upload", methods=["POST"])
@login_required
def upload_file():
    """Handles file uploads to a conversation's workspace."""
    if "files[]" not in request.files:
        return jsonify(error="No file part"), 400

    files = request.files.getlist("files[]")
    prompt = request.form.get("prompt", "")
    conversation_id = request.form.get("conversation_id")

    if not conversation_id:
        conversation_id = str(int(time.time() * 1000))

    if not files or files[0].filename == "":
        return jsonify(error="No selected file"), 400

    filenames = []
    workspace_path = get_workspace_path(conversation_id, current_user.id)
    if not workspace_path:
        return jsonify(error="Could not create workspace"), 500

    for file in files:
        if file:
            filename = secure_filename(file.filename)
            file.save(os.path.join(workspace_path, filename))
            filenames.append(filename)

    file_list_str = "\n- ".join(filenames)
    message_to_ai = (
        "User uploaded the following files to the workspace:\n"
        f"- {file_list_str}\n\n"
        f"User's prompt: {prompt}"
    )

    return jsonify(message=message_to_ai, conversation_id=conversation_id), 200
