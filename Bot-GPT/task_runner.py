import os
import subprocess
import threading
import time
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
from typing import Dict, List, Optional, Tuple

from heartbeat import write_heartbeat
from memory_store import upsert_fact
from notification_router import build_notification, route_notification
from task_scheduler import (
    enqueue_notification,
    get_task,
    list_all_tasks,
    mark_task_result,
    save_task,
)


class BackgroundTaskRunner:
    def __init__(
        self,
        app,
        socketio,
        *,
        poll_interval_seconds: int = 5,
        max_concurrent_tasks: int = 2,
    ):
        self.app = app
        self.socketio = socketio
        self.poll_interval_seconds = poll_interval_seconds
        self.max_concurrent_tasks = max_concurrent_tasks
        self._thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._lock = threading.Lock()
        self._futures = set()

    def start(self):
        if self._thread and self._thread.is_alive():
            return
        self._stop_event.clear()
        self._thread = threading.Thread(target=self._run_loop, name="background-task-runner", daemon=True)
        self._thread.start()

    def stop(self):
        self._stop_event.set()
        if self._thread:
            self._thread.join(timeout=3)

    def _run_loop(self):
        with self.app.app_context():
            write_heartbeat(self.app.instance_path, is_running=True)
            with ThreadPoolExecutor(max_workers=self.max_concurrent_tasks) as executor:
                while not self._stop_event.is_set():
                    try:
                        due = self._collect_due_tasks()
                        queue_depth = len(due)
                        self._cleanup_futures()

                        slots = max(0, self.max_concurrent_tasks - len(self._futures))
                        for task in due[:slots]:
                            future = executor.submit(self._execute_task_safe, task)
                            self._futures.add(future)

                        write_heartbeat(
                            self.app.instance_path,
                            is_running=True,
                            active_workers=len(self._futures),
                            queue_depth=queue_depth,
                            last_error=None,
                        )
                    except Exception as exc:
                        write_heartbeat(
                            self.app.instance_path,
                            is_running=True,
                            last_error=str(exc),
                            active_workers=len(self._futures),
                        )

                    self._stop_event.wait(self.poll_interval_seconds)

            write_heartbeat(self.app.instance_path, is_running=False, active_workers=0, queue_depth=0)

    def _cleanup_futures(self):
        if not self._futures:
            return
        done, pending = wait(self._futures, timeout=0, return_when=FIRST_COMPLETED)
        self._futures = pending
        for fut in done:
            try:
                fut.result()
            except Exception:
                # exceptions are recorded in _execute_task_safe
                pass

    def _collect_due_tasks(self) -> List[Dict[str, object]]:
        now = time.time()
        due: List[Dict[str, object]] = []
        for task in list_all_tasks(self.app.instance_path):
            if task.get("status") != "active":
                continue
            next_run = task.get("next_run")
            if next_run is None or float(next_run) <= now:
                due.append(task)
        due.sort(key=lambda task: float(task.get("next_run") or 0.0))
        return due

    def _execute_task_safe(self, task: Dict[str, object]):
        with self._lock:
            user_id = int(task["user_id"])
            task_id = str(task["task_id"])
            try:
                result, should_notify = self._execute_task(task)
                persisted = mark_task_result(self.app.instance_path, user_id, task_id, result)
                write_heartbeat(self.app.instance_path, last_task_activity=time.time())
                self._persist_task_memory(task, result)

                if should_notify:
                    notification = build_notification(
                        user_id=user_id,
                        task_id=task_id,
                        title=task.get("name") or "Task update",
                        message=str(result.get("message") or "Task condition met."),
                        severity=str(result.get("severity") or "info"),
                    )
                    enqueue_notification(self.app.instance_path, user_id, notification)
                    route = route_notification(
                        self.app.instance_path,
                        self.socketio,
                        notification,
                        telegram_bridge=self.app.extensions.get("telegram_bridge"),
                    )
                    notification["route"] = route
                    if route == "active_ui":
                        self.socketio.emit("proactive_task_update", {"task": persisted, "notification": notification}, room=f"user_{user_id}")
            except Exception as exc:
                task["status"] = "failed"
                task["last_result"] = {"status": "error", "message": str(exc), "notified": True}
                task["last_run"] = time.time()
                task["updated_at"] = time.time()
                save_task(self.app.instance_path, user_id, task)
                write_heartbeat(self.app.instance_path, last_task_activity=time.time(), last_error=str(exc))

    def _execute_task(self, task: Dict[str, object]) -> Tuple[Dict[str, object], bool]:
        task_type = task.get("task_type")
        if task_type == "reminder":
            message = (task.get("payload") or {}).get("message") or task.get("description") or task.get("name")
            return {"status": "ok", "message": message, "notified": True, "severity": "info"}, True

        if task_type in {"monitor", "periodic_check", "custom"}:
            return self._run_monitor_task(task)

        if task_type == "repo_check":
            return self._run_repo_check_task(task)
        if task_type == "workflow":
            return self._run_workflow_task(task)

        return {"status": "error", "message": f"Unsupported task type: {task_type}", "notified": True}, True

    def _run_monitor_task(self, task: Dict[str, object]) -> Tuple[Dict[str, object], bool]:
        payload = task.get("payload") or {}
        last_result = task.get("last_result") or {}
        current_value = payload.get("value")
        prior_value = (last_result.get("details") or {}).get("observed_value")

        changed = prior_value is None or current_value != prior_value
        notify_on_change = bool((task.get("conditions") or {}).get("notify_on_change", True))
        message = "Change detected." if changed else "No changes detected."

        result = {
            "status": "ok",
            "message": message,
            "details": {
                "observed_value": current_value,
                "changed": changed,
            },
            "notified": bool(changed and notify_on_change),
            "severity": "warning" if changed else "info",
        }
        return result, bool(changed and notify_on_change)

    def _run_repo_check_task(self, task: Dict[str, object]) -> Tuple[Dict[str, object], bool]:
        payload = task.get("payload") or {}
        repo_path = payload.get("repo_path")
        if not repo_path:
            raise ValueError("repo_check task requires payload.repo_path")

        abs_repo = repo_path if os.path.isabs(repo_path) else os.path.join(self.app.instance_path, str(task["user_id"]), "workspace", str(repo_path))
        if not os.path.isdir(abs_repo):
            raise ValueError(f"Repository path not found: {abs_repo}")

        head = self._run_git_command(abs_repo, ["rev-parse", "HEAD"])
        status_output = self._run_git_command(abs_repo, ["status", "--porcelain"])
        has_dirty = bool(status_output.strip())

        previous_head = (((task.get("last_result") or {}).get("details") or {}).get("head_commit"))
        changed = previous_head is not None and previous_head != head

        conditions = task.get("conditions") or {}
        notify_on_dirty = bool(conditions.get("notify_on_dirty", True))
        notify_on_new_commit = bool(conditions.get("notify_on_new_commit", True))

        should_notify = (changed and notify_on_new_commit) or (has_dirty and notify_on_dirty)
        if changed:
            message = f"Repo updated to {head[:10]} (previous {str(previous_head)[:10]})."
        elif has_dirty:
            message = "Repository has uncommitted changes."
        else:
            message = "Repo check complete: no changes detected."

        result = {
            "status": "ok",
            "message": message,
            "details": {
                "head_commit": head,
                "dirty": has_dirty,
                "new_commit_detected": changed,
            },
            "notified": should_notify,
            "severity": "warning" if (changed or has_dirty) else "info",
        }
        return result, should_notify

    def _run_workflow_task(self, task: Dict[str, object]) -> Tuple[Dict[str, object], bool]:
        from tools.runtime import run_workflow as runtime_run_workflow

        payload = task.get("payload") or {}
        workflow_id = payload.get("workflow_id")
        if not workflow_id:
            raise ValueError("workflow task requires payload.workflow_id")
        if not bool(payload.get("approved", False)):
            return {
                "status": "error",
                "message": "Workflow task blocked: explicit task approval is required for OS/browser workflow actions.",
                "details": {"error_type": "os_tool_safety_block"},
                "notified": True,
                "severity": "warning",
            }, True

        result = runtime_run_workflow(
            workflow_id=workflow_id,
            user_id=int(task["user_id"]),
            execution_context={
                "mode": "agent",
                "os_control_enabled": True,
                "explicit_user_intent": True,
                "source": "background_task",
            },
        )
        success = result.get("status") == "success"
        return {
            "status": "ok" if success else "error",
            "message": "Workflow executed successfully." if success else "Workflow execution failed.",
            "details": result,
            "notified": not success,
            "severity": "warning" if not success else "info",
        }, not success

    @staticmethod
    def _run_git_command(repo_path: str, args: List[str]) -> str:
        process = subprocess.run(
            ["git", "-C", repo_path] + args,
            capture_output=True,
            text=True,
            check=False,
            timeout=20,
        )
        if process.returncode != 0:
            raise RuntimeError(process.stderr.strip() or f"git command failed: {' '.join(args)}")
        return process.stdout.strip()

    def _persist_task_memory(self, task: Dict[str, object], result: Dict[str, object]) -> None:
        key = f"proactive_task::{task.get('task_id')}"
        value = f"{task.get('name')}: {result.get('message')}"
        upsert_fact(
            int(task["user_id"]),
            scope="user",
            key=key,
            value=value,
            source_conversation_id=None,
            source_message_index=None,
            confidence=0.8,
        )


def execute_task_instruction(app, user_id: int, instruction: str) -> Dict[str, object]:
    """Execute a safe remote instruction from Telegram.

    Supported v1:
    - existing task id
    - `status` lightweight check
    """
    normalized = (instruction or "").strip()
    runner = BackgroundTaskRunner(app, socketio=app.extensions.get("socketio") if hasattr(app, "extensions") else None)

    task = get_task(app.instance_path, int(user_id), normalized)
    if task:
        result, should_notify = runner._execute_task(task)
        mark_task_result(app.instance_path, int(user_id), task["task_id"], result)
        runner._persist_task_memory(task, result)
        if should_notify:
            notification = build_notification(
                user_id=int(user_id),
                task_id=task["task_id"],
                title=task.get("name") or "Task update",
                message=str(result.get("message") or "Task condition met."),
                severity=str(result.get("severity") or "info"),
            )
            enqueue_notification(app.instance_path, int(user_id), notification)
            route_notification(
                app.instance_path,
                runner.socketio,
                notification,
                telegram_bridge=app.extensions.get("telegram_bridge"),
            )
        return {"status": "ok", "message": f"Executed task {task['name']}: {result.get('message')}"}

    if normalized.lower() in {"status", "health"}:
        return {"status": "ok", "message": "Remote instruction executed: system status check completed."}

    if normalized.lower().startswith("workflow:"):
        query = normalized.split(":", 1)[1].strip()
        if not query:
            return {"status": "rejected", "message": "Provide a workflow id or name after workflow:."}
        from workflow_learning import get_workflow, select_best_workflow
        from tools.runtime import run_workflow as runtime_run_workflow

        workflow = get_workflow(app.instance_path, int(user_id), query) or select_best_workflow(app.instance_path, int(user_id), query)
        if not workflow:
            return {"status": "rejected", "message": "No matching workflow found."}
        result = runtime_run_workflow(
            workflow_id=workflow["workflow_id"],
            user_id=int(user_id),
            execution_context={
                "mode": "agent",
                "os_control_enabled": True,
                "explicit_user_intent": True,
                "source": "telegram_remote",
            },
        )
        if result.get("status") == "pending_approval":
            return {
                "status": "pending_approval",
                "message": "Workflow execution is pending approval. Approve the OS action from the web app approvals panel.",
            }
        return {
            "status": result.get("status"),
            "message": f"Workflow '{workflow.get('name')}' execution status: {result.get('status')}",
        }

    return {
        "status": "rejected",
        "message": "Instruction rejected. Use /run <task_id> or /run status.",
    }
