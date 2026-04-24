import os
import shutil
import uuid
from flask import Blueprint, request, jsonify, current_app, Response
from flask_login import login_required, current_user
from werkzeug.utils import secure_filename
from extensions import socketio
from models import (
    load_conversation, save_conversation, check_permission,
    _load_users, get_user_by_id, add_to_conversation_index,
    add_user_to_conversation_index, remove_user_from_conversation_index,
    find_conversation_owner as find_owner_from_index
)
from shared_paths import (
    get_users_path,
    get_conversation_path as _get_conversation_path,
    get_conversation_index_path,
    get_user_conversation_index_path,
)
from artifacts import (
    list_artifacts_for_conversation,
    set_last_active_artifact,
    upsert_artifact_metadata,
    rename_artifact_metadata,
    remove_artifact_metadata,
    snapshot_artifact_version,
    list_artifact_versions,
    get_artifact_version,
)
from tools.file_system import get_workspace_path
from repo_index import (
    discover_local_repositories,
    load_repo_index,
    select_repository,
    extract_repo_metadata,
)
from memory_store import list_facts, load_memory, save_memory
from task_scheduler import (
    create_task,
    delete_task,
    get_task,
    list_notifications,
    list_tasks,
    mark_notifications_read,
    update_task_status,
)
from heartbeat import load_heartbeat
from notification_router import mark_user_activity, get_user_activity
from telegram_router import create_pairing_code, get_pairing_status_for_user, unpair_telegram_user
from os_safety import list_pending_approvals, resolve_approval_request
from workflow_learning import (
    list_workflows as wf_list_workflows,
    get_workflow as wf_get_workflow,
    delete_workflow as wf_delete_workflow,
    select_best_workflow as wf_select_best_workflow,
)
from tools import (
    get_file_tree,
    is_safe_path,
    call_chat_stream,
)


workspace = Blueprint("workspace", __name__)
call_ollama_chat_stream = call_chat_stream


def _is_admin_user(user) -> bool:
    admin_ids = set((current_app.config.get("ADMIN_USER_IDS") or []))
    return int(getattr(user, "id", -1)) in {int(v) for v in admin_ids}


@workspace.before_app_request
def track_user_activity():
    if getattr(current_user, "is_authenticated", False):
        mark_user_activity(current_app.instance_path, int(current_user.id), channel="ui")

def find_conversation_owner(conversation_id):
    """Finds the owner of a conversation using the index."""
    index_path = get_conversation_index_path()
    return find_owner_from_index(index_path, conversation_id)


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
            previous_content = None
            if os.path.exists(file_path) and os.path.isfile(file_path):
                with open(file_path, "r", encoding="utf-8") as existing:
                    previous_content = existing.read()
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            with open(file_path, "w", encoding="utf-8") as f:
                f.write(content)
            if previous_content is not None and previous_content != content:
                snapshot_artifact_version(
                    owner_id,
                    conversation_id,
                    path,
                    previous_content,
                    change_summary="Updated from workspace editor",
                )
            upsert_artifact_metadata(
                owner_id,
                conversation_id,
                path,
            )
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
                remove_artifact_metadata(owner_id, conversation_id, path)
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
        convo_index_path = get_conversation_index_path()
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
            "messages": [],
            "artifacts": [],
            "artifact_versions": {},
            "last_active_artifact_id": None,
        }
        convo_path = _get_conversation_path(owner_id, conversation_id)
        save_conversation(convo_path, conversation_data)

        # Add to the new index
        index_path = get_conversation_index_path()
        add_to_conversation_index(index_path, conversation_id, owner_id)
        add_user_to_conversation_index(get_user_conversation_index_path(), owner_id, conversation_id)

    workspace_path = get_workspace_path(conversation_id, owner_id)
    os.makedirs(workspace_path, exist_ok=True)

    filenames = []
    for file in files:
        if file and file.filename:
            filename = secure_filename(file.filename)
            file.save(os.path.join(workspace_path, filename))
            upsert_artifact_metadata(owner_id, conversation_id, filename)
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
    rename_artifact_metadata(owner_id, conversation_id, old_path, new_path)
    socketio.emit("refresh_files", {"conversation_id": conversation_id}, room=str(conversation_id))
    return jsonify({"success": True, "message": f"Renamed '{old_path}' to '{new_path}'."})


@workspace.route("/api/conversation/<conversation_id>/artifacts", methods=["GET", "POST"])
@login_required
def conversation_artifacts(conversation_id):
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404

    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user):
        return jsonify({"error": "Access denied"}), 403

    if request.method == "POST":
        data = request.get_json() or {}
        artifact_id = data.get("artifact_id")
        if artifact_id:
            set_last_active_artifact(owner_id, conversation_id, artifact_id)
        return jsonify({"success": True})

    artifacts = list_artifacts_for_conversation(owner_id, conversation_id)
    return jsonify({
        "artifacts": artifacts,
        "last_active_artifact_id": conversation_data.get("last_active_artifact_id"),
    })


@workspace.route("/api/artifact/<path:artifact_id>/versions", methods=["GET"])
@login_required
def artifact_versions(artifact_id):
    conversation_id = request.args.get("conversation_id")
    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404
    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user):
        return jsonify({"error": "Access denied"}), 403
    versions = list_artifact_versions(owner_id, conversation_id, artifact_id)
    return jsonify({"artifact_id": artifact_id, "versions": versions})


@workspace.route("/api/artifact/<path:artifact_id>/version/<version_id>", methods=["GET"])
@login_required
def artifact_version_detail(artifact_id, version_id):
    conversation_id = request.args.get("conversation_id")
    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404
    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user):
        return jsonify({"error": "Access denied"}), 403
    version = get_artifact_version(owner_id, conversation_id, artifact_id, version_id)
    if not version:
        return jsonify({"error": "Version not found"}), 404
    return jsonify(version)


@workspace.route("/api/artifact/<path:artifact_id>/version/<version_id>/restore", methods=["POST"])
@login_required
def restore_artifact_version(artifact_id, version_id):
    data = request.get_json() or {}
    conversation_id = data.get("conversation_id")
    if not conversation_id:
        return jsonify({"error": "conversation_id is required"}), 400
    owner_id = find_conversation_owner(conversation_id)
    if not owner_id:
        return jsonify({"error": "Conversation not found"}), 404
    convo_path = _get_conversation_path(owner_id, conversation_id)
    conversation_data = load_conversation(convo_path)
    if not conversation_data or not check_permission(conversation_data, current_user, level="owner"):
        return jsonify({"error": "Access denied for this operation"}), 403
    version = get_artifact_version(owner_id, conversation_id, artifact_id, version_id)
    if not version:
        return jsonify({"error": "Version not found"}), 404

    workspace_path = get_workspace_path(conversation_id, owner_id)
    file_path = os.path.join(workspace_path, artifact_id)
    if not is_safe_path(workspace_path, file_path):
        return jsonify({"error": "Invalid path"}), 403

    previous_content = None
    if os.path.exists(file_path):
        with open(file_path, "r", encoding="utf-8") as existing:
            previous_content = existing.read()

    os.makedirs(os.path.dirname(file_path), exist_ok=True)
    with open(file_path, "w", encoding="utf-8") as target:
        target.write(version["content"])

    if previous_content is not None and previous_content != version["content"]:
        snapshot_artifact_version(
            owner_id,
            conversation_id,
            artifact_id,
            previous_content,
            change_summary=f"Restore point before {version_id}",
        )
    upsert_artifact_metadata(owner_id, conversation_id, artifact_id)
    socketio.emit("refresh_files", {"conversation_id": conversation_id}, room=str(conversation_id))
    return jsonify({"success": True, "artifact_id": artifact_id, "restored_version_id": version_id})


@workspace.route("/api/repos/discover", methods=["POST"])
@login_required
def discover_repositories():
    data = request.get_json() or {}
    base_paths = data.get("base_paths")
    if base_paths is not None and not isinstance(base_paths, list):
        return jsonify({"error": "base_paths must be a list"}), 400
    index = discover_local_repositories(current_user.id, base_paths=base_paths)
    return jsonify(index)


@workspace.route("/api/repos", methods=["GET"])
@login_required
def list_repositories():
    return jsonify(load_repo_index(current_user.id))


@workspace.route("/api/repos/select", methods=["POST"])
@login_required
def select_repository_api():
    data = request.get_json() or {}
    repo = data.get("repo")
    if not repo:
        return jsonify({"error": "repo is required"}), 400
    selected = select_repository(current_user.id, repo)
    if not selected:
        return jsonify({"error": "Repository not found"}), 404
    return jsonify({"selected_repo": selected})


@workspace.route("/api/repos/analyze", methods=["POST"])
@login_required
def analyze_repository_api():
    data = request.get_json() or {}
    repo_path = data.get("path")
    if not repo_path or not os.path.isdir(repo_path):
        return jsonify({"error": "A valid repo path is required"}), 400
    return jsonify({"repo": extract_repo_metadata(repo_path)})


@workspace.route("/api/memory", methods=["GET", "DELETE"])
@login_required
def memory_inspection_api():
    if request.method == "GET":
        scope = request.args.get("scope", "user")
        project_key = request.args.get("project_key")
        conversation_id = request.args.get("conversation_id")
        if conversation_id:
            payload = load_memory(current_user.id)
            session_memory = payload.get("sessions", {}).get(conversation_id, {})
            return jsonify({"scope": "session", "conversation_id": conversation_id, "memory": session_memory})
        facts = list_facts(current_user.id, scope=scope, project_key=project_key)
        return jsonify({"scope": scope, "project_key": project_key, "facts": facts})

    data = request.get_json() or {}
    scope = data.get("scope", "user")
    key = data.get("key")
    project_key = data.get("project_key")
    if not key:
        return jsonify({"error": "key is required"}), 400
    memory = load_memory(current_user.id)
    if scope == "project" and project_key:
        facts = memory.get("project_facts", {}).get(project_key, [])
        memory["project_facts"][project_key] = [fact for fact in facts if fact.get("key") != key]
    else:
        memory["user_facts"] = [fact for fact in memory.get("user_facts", []) if fact.get("key") != key]
    save_memory(current_user.id, memory)
    return jsonify({"success": True, "deleted_key": key})


@workspace.route("/api/tasks", methods=["GET", "POST"])
@login_required
def tasks_api():
    if request.method == "GET":
        user_id = current_user.id
        if _is_admin_user(current_user) and request.args.get("user_id"):
            user_id = int(request.args.get("user_id"))
        return jsonify({"tasks": list_tasks(current_app.instance_path, user_id)})

    payload = request.get_json() or {}
    if not payload.get("schedule"):
        return jsonify({"error": "schedule is required"}), 400
    try:
        task = create_task(current_app.instance_path, current_user.id, payload)
    except ValueError as exc:
        return jsonify({"error": str(exc)}), 400
    return jsonify(task), 201


@workspace.route("/api/tasks/<task_id>", methods=["PATCH", "DELETE", "GET"])
@login_required
def task_detail_api(task_id):
    requester_id = current_user.id
    target_user_id = requester_id
    if _is_admin_user(current_user) and request.args.get("user_id"):
        target_user_id = int(request.args.get("user_id"))

    task = get_task(current_app.instance_path, target_user_id, task_id)
    if not task:
        return jsonify({"error": "Task not found"}), 404
    if task.get("user_id") != requester_id and not _is_admin_user(current_user):
        return jsonify({"error": "Access denied"}), 403

    if request.method == "GET":
        return jsonify(task)
    if request.method == "DELETE":
        removed = delete_task(current_app.instance_path, target_user_id, task_id)
        return jsonify({"success": removed, "task_id": task_id})

    status = (request.get_json() or {}).get("status")
    if status not in {"active", "paused", "failed"}:
        return jsonify({"error": "status must be one of: active, paused, failed"}), 400
    updated = update_task_status(current_app.instance_path, target_user_id, task_id, status)
    return jsonify(updated)


@workspace.route("/api/notifications", methods=["GET", "POST"])
@login_required
def notifications_api():
    if request.method == "GET":
        unread_only = request.args.get("unread_only") == "1"
        return jsonify({"notifications": list_notifications(current_app.instance_path, current_user.id, unread_only=unread_only)})

    marked = mark_notifications_read(current_app.instance_path, current_user.id)
    return jsonify({"marked_read": marked})


@workspace.route("/api/system/heartbeat", methods=["GET"])
@login_required
def heartbeat_api():
    state = load_heartbeat(current_app.instance_path)
    state["last_user_activity"] = get_user_activity(current_app.instance_path, current_user.id).get("last_active_at")
    return jsonify(state)


@workspace.route("/api/telegram/pairing-code", methods=["POST"])
@login_required
def telegram_pairing_code_api():
    expiry = int(current_app.config.get("TELEGRAM_PAIRING_EXPIRY", 300))
    payload = create_pairing_code(current_app.instance_path, current_user.id, expiry_seconds=expiry)
    return jsonify(payload), 201


@workspace.route("/api/telegram/status", methods=["GET"])
@login_required
def telegram_status_api():
    return jsonify(get_pairing_status_for_user(current_app.instance_path, current_user.id))


@workspace.route("/api/telegram/pairing", methods=["DELETE"])
@login_required
def telegram_unpair_api():
    telegram_user_id = request.args.get("telegram_user_id")
    removed = unpair_telegram_user(
        current_app.instance_path,
        current_user.id,
        telegram_user_id=int(telegram_user_id) if telegram_user_id else None,
    )
    return jsonify({"removed": removed})


@workspace.route("/api/workflows", methods=["GET"])
@login_required
def workflows_api():
    query = request.args.get("q")
    if query:
        match = wf_select_best_workflow(current_app.instance_path, current_user.id, query)
        return jsonify({"match": match})
    return jsonify({"workflows": wf_list_workflows(current_app.instance_path, current_user.id)})


@workspace.route("/api/workflows/<workflow_id>", methods=["GET", "DELETE"])
@login_required
def workflow_detail_api(workflow_id):
    if request.method == "GET":
        workflow = wf_get_workflow(current_app.instance_path, current_user.id, workflow_id)
        if not workflow:
            return jsonify({"error": "Workflow not found"}), 404
        return jsonify(workflow)

    removed = wf_delete_workflow(current_app.instance_path, current_user.id, workflow_id)
    return jsonify({"removed": removed})


@workspace.route("/api/workflows/<workflow_id>/run", methods=["POST"])
@login_required
def workflow_run_api(workflow_id):
    from tools.runtime import run_workflow as runtime_run_workflow

    payload = request.get_json(silent=True) or {}
    result = runtime_run_workflow(
        workflow_id=workflow_id,
        user_id=current_user.id,
        execution_context={
            "mode": "agent",
            "os_control_enabled": bool(payload.get("os_control_enabled", False)),
            "explicit_user_intent": True,
            "source": "workspace_api",
        },
    )
    return jsonify(result), (200 if result.get("status") == "success" else 400)


@workspace.route("/api/os-approvals/pending", methods=["GET"])
@login_required
def pending_os_approvals_api():
    return jsonify({"approvals": list_pending_approvals(current_app.instance_path, user_id=current_user.id)})


@workspace.route("/api/os-approvals/<request_id>", methods=["POST"])
@login_required
def resolve_os_approval_api(request_id):
    payload = request.get_json() or {}
    decision = str(payload.get("decision") or "").strip().lower()
    if decision not in {"approve", "reject"}:
        return jsonify({"error": "decision must be approve or reject"}), 400

    pending_for_user = {item.get("request_id") for item in list_pending_approvals(current_app.instance_path, user_id=current_user.id)}
    if request_id not in pending_for_user:
        return jsonify({"error": "approval request not found"}), 404

    resolved = resolve_approval_request(
        current_app.instance_path,
        request_id,
        status="approved" if decision == "approve" else "rejected",
        resolved_by=current_user.id,
    )
    if not resolved:
        return jsonify({"error": "approval request not found"}), 404
    return jsonify({"approval": resolved})
