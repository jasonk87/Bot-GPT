import json
import os
import subprocess
import threading
import time
from typing import Dict, List, Optional

STATE_FILE = "admin_update_state.json"
HISTORY_FILE = "admin_update_history.json"
TARGET_OWNER = "jasonk87"
TARGET_REPO = "Bot-GPT"
DEFAULT_FRESHNESS_SECONDS = 180


class UpdateManager:
    def __init__(self):
        self._lock = threading.Lock()

    def _repo_path(self) -> str:
        return os.path.abspath(os.path.dirname(__file__))

    def _state_path(self, instance_path: str) -> str:
        return os.path.join(instance_path, STATE_FILE)

    def _history_path(self, instance_path: str) -> str:
        return os.path.join(instance_path, HISTORY_FILE)

    def _read_json(self, path: str, default):
        if not os.path.exists(path):
            return default
        try:
            with open(path, "r", encoding="utf-8") as handle:
                return json.load(handle)
        except Exception:
            return default

    def _write_json(self, path: str, payload):
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)

    def _run(self, args: List[str], *, timeout: int = 20, repo_path: Optional[str] = None) -> Dict[str, object]:
        process = subprocess.run(
            args,
            cwd=repo_path or self._repo_path(),
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
        return {
            "ok": process.returncode == 0,
            "stdout": process.stdout.strip(),
            "stderr": process.stderr.strip(),
            "returncode": process.returncode,
        }

    def _git(self, command: List[str], *, timeout: int = 20) -> Dict[str, object]:
        return self._run(["git"] + command, timeout=timeout)

    @staticmethod
    def _line(result: Dict[str, object], fallback: str) -> str:
        return str(result.get("stderr") or result.get("stdout") or fallback).strip()

    def _target_candidates(self) -> List[str]:
        base = f"{TARGET_OWNER}/{TARGET_REPO}"
        return [
            f"https://github.com/{base}",
            f"https://github.com/{base}.git",
            f"git@github.com:{base}",
            f"git@github.com:{base}.git",
        ]

    def _validate_target_remote(self):
        remote = self._git(["remote", "get-url", "origin"])
        if not remote.get("ok"):
            raise RuntimeError(remote.get("stderr") or "Unable to read origin remote URL.")
        url = (remote.get("stdout") or "").strip()
        candidates = self._target_candidates()
        if url not in candidates:
            raise RuntimeError(
                f"Updater is locked to {TARGET_OWNER}/{TARGET_REPO}; origin remote is '{url}'."
            )

    def target_repo(self) -> Dict[str, str]:
        return {"owner": TARGET_OWNER, "repo": TARGET_REPO}

    def get_repo_snapshot(self) -> Dict[str, object]:
        branch = self._git(["rev-parse", "--abbrev-ref", "HEAD"])
        commit = self._git(["rev-parse", "HEAD"])
        dirty = self._git(["status", "--porcelain"])
        return {
            "branch": branch.get("stdout") if branch.get("ok") else None,
            "commit": commit.get("stdout") if commit.get("ok") else None,
            "dirty": bool((dirty.get("stdout") or "").strip()) if dirty.get("ok") else True,
        }

    def remote_branches(self) -> List[Dict[str, str]]:
        refs = self._git([
            "for-each-ref",
            "refs/remotes/origin",
            "--sort=-committerdate",
            "--format=%(refname:short)|%(committerdate:iso8601)|%(objectname)|%(subject)",
        ], timeout=25)
        if not refs.get("ok"):
            return []
        rows = []
        for line in (refs.get("stdout") or "").splitlines():
            parts = line.split("|", 3)
            if len(parts) < 4:
                continue
            rows.append({
                "name": parts[0],
                "full_ref": parts[0],
                "updated_at": parts[1],
                "commit": parts[2],
                "subject": parts[3],
            })
        return rows

    def _refresh_state(self, instance_path: str) -> Dict[str, object]:
        self._validate_target_remote()
        fetch = self._git(["fetch", "--prune"], timeout=45)
        if not fetch.get("ok"):
            raise RuntimeError(fetch.get("stderr") or "git fetch --prune failed")
        snapshot = self.get_repo_snapshot()
        branches = self.remote_branches()
        last_checked = time.time()
        payload = {
            "status": "idle",
            "current_step": "checking",
            "snapshot": snapshot,
            "remote_branches": branches,
            "newest_remote": branches[0] if branches else None,
            "last_checked": last_checked,
            "updated_at": last_checked,
            "target_repo": self.target_repo(),
            "last_log_line": self._line(fetch, "Branch refresh complete."),
        }
        self._write_json(self._state_path(instance_path), payload)
        return payload

    def check(self, instance_path: str) -> Dict[str, object]:
        return self.refresh(instance_path)

    def refresh(self, instance_path: str) -> Dict[str, object]:
        self._set_state(instance_path, "checking", target_repo=self.target_repo(), current_step="checking")
        return self._refresh_state(instance_path)

    def get_status(self, instance_path: str) -> Dict[str, object]:
        return self._read_json(
            self._state_path(instance_path),
            {"status": "idle", "current_step": "idle", "target_repo": self.target_repo()},
        )

    def is_state_fresh(self, instance_path: str, max_age_seconds: int = DEFAULT_FRESHNESS_SECONDS) -> bool:
        status = self.get_status(instance_path)
        checked = float(status.get("last_checked") or 0)
        return checked > 0 and (time.time() - checked) <= max_age_seconds

    def get_history(self, instance_path: str) -> List[Dict[str, object]]:
        payload = self._read_json(self._history_path(instance_path), {"events": []})
        return payload.get("events", [])

    def _append_history(self, instance_path: str, item: Dict[str, object]):
        payload = self._read_json(self._history_path(instance_path), {"events": []})
        events = payload.get("events", [])
        events.append(item)
        payload["events"] = events[-50:]
        self._write_json(self._history_path(instance_path), payload)

    def _set_state(self, instance_path: str, status: str, **extra):
        payload = self.get_status(instance_path)
        payload.update(extra)
        payload["status"] = status
        payload["current_step"] = extra.get("current_step") or status
        payload["updated_at"] = time.time()
        self._write_json(self._state_path(instance_path), payload)

    def start_update(self, instance_path: str, *, branch: str, strategy: str = "abort", smoke_command: Optional[str] = None, restart_command: Optional[str] = None) -> Dict[str, object]:
        with self._lock:
            status = self.get_status(instance_path)
            if status.get("status") in {
                "checking",
                "fetching",
                "checking_dirty_tree",
                "stashing",
                "switching_branch",
                "pulling_or_resetting",
                "running_smoke_check",
                "restarting",
            }:
                return {"status": "busy", "message": "Update already in progress."}
            self._validate_target_remote()
            now = time.time()
            self._set_state(
                instance_path,
                "checking",
                current_step="checking",
                started_at=now,
                target_branch=branch,
                error=None,
                rollback_error=None,
                rollback_result=None,
                failed_step=None,
                last_log_line="Starting update flow.",
                smoke_output=None,
                stash_created=False,
            )
            thread = threading.Thread(
                target=self._run_update_flow,
                kwargs={
                    "instance_path": instance_path,
                    "branch": branch,
                    "strategy": strategy,
                    "smoke_command": smoke_command,
                    "restart_command": restart_command,
                },
                daemon=True,
            )
            thread.start()
            return {"status": "started", "target_branch": branch}

    def _run_update_flow(self, *, instance_path: str, branch: str, strategy: str, smoke_command: Optional[str], restart_command: Optional[str]):
        started_at = time.time()
        snapshot = self.get_repo_snapshot()
        history_item = {
            "started_at": started_at,
            "target_branch": branch,
            "strategy": strategy,
            "snapshot": snapshot,
            "status": "started",
            "target_repo": self.target_repo(),
            "failed_step": None,
            "rollback_result": None,
            "stash_created": False,
        }
        current_step = "checking"
        try:
            self._set_state(
                instance_path,
                "checking",
                current_step="checking",
                snapshot=snapshot,
                started_at=started_at,
                target_branch=branch,
                last_log_line="Validating target remote.",
            )
            self._validate_target_remote()

            current_step = "fetching"
            self._set_state(instance_path, "fetching", current_step=current_step, last_log_line="Fetching latest refs.")
            fetch = self._git(["fetch", "--all", "--prune"], timeout=45)
            if not fetch.get("ok"):
                raise RuntimeError(fetch.get("stderr") or "git fetch failed")

            current_step = "checking_dirty_tree"
            self._set_state(instance_path, "checking_dirty_tree", current_step=current_step, last_log_line="Checking working tree cleanliness.")
            stash_created = False
            if snapshot.get("dirty"):
                if strategy == "abort":
                    raise RuntimeError("Working tree is dirty. Choose force or stash to continue.")
                if strategy == "stash":
                    current_step = "stashing"
                    self._set_state(instance_path, "stashing", current_step=current_step, last_log_line="Stashing local changes.")
                    stash = self._git(["stash", "push", "-u", "-m", "admin-update-autostash"], timeout=25)
                    if not stash.get("ok"):
                        raise RuntimeError(stash.get("stderr") or "Failed to stash changes.")
                    stash_created = True
                    history_item["stash_created"] = True
                    self._set_state(instance_path, "stashing", current_step=current_step, stash_created=True, last_log_line=self._line(stash, "Stash created."))

            target = branch.replace("origin/", "")
            current_step = "switching_branch"
            self._set_state(instance_path, "switching_branch", current_step=current_step, last_log_line=f"Switching to {target}.")
            checkout = self._git(["checkout", target], timeout=25)
            if not checkout.get("ok"):
                create = self._git(["checkout", "-b", target, f"origin/{target}"], timeout=25)
                if not create.get("ok"):
                    raise RuntimeError(create.get("stderr") or "Failed to checkout target branch.")
                self._set_state(instance_path, "switching_branch", current_step=current_step, last_log_line=self._line(create, "Created branch from origin."))
            else:
                self._set_state(instance_path, "switching_branch", current_step=current_step, last_log_line=self._line(checkout, "Switched branch."))

            current_step = "pulling_or_resetting"
            self._set_state(instance_path, "pulling_or_resetting", current_step=current_step, last_log_line=f"Resetting {target} to origin/{target}.")
            reset = self._git(["reset", "--hard", f"origin/{target}"], timeout=30)
            if not reset.get("ok"):
                raise RuntimeError(reset.get("stderr") or "Failed to reset target branch.")
            self._set_state(instance_path, "pulling_or_resetting", current_step=current_step, last_log_line=self._line(reset, "Reset complete."))

            current_step = "running_smoke_check"
            self._set_state(instance_path, "running_smoke_check", current_step=current_step, last_log_line="Running smoke checks.")
            cmd_str = smoke_command or "python -m py_compile app.py"
            run_cmd = ["cmd.exe", "/c", cmd_str] if os.name == "nt" else ["bash", "-lc", cmd_str]
            smoke = self._run(
                run_cmd,
                timeout=60,
            )
            smoke_output = (smoke.get("stderr") or smoke.get("stdout") or "").strip()
            self._set_state(instance_path, "running_smoke_check", current_step=current_step, smoke_output=smoke_output, last_log_line=self._line(smoke, "Smoke check complete."))
            if not smoke.get("ok"):
                raise RuntimeError(smoke.get("stderr") or smoke.get("stdout") or "Smoke verification failed.")

            if restart_command:
                current_step = "restarting"
                self._set_state(instance_path, "restarting", current_step=current_step, last_log_line="Running restart command.")
                restart_cmd = ["cmd.exe", "/c", restart_command] if os.name == "nt" else ["bash", "-lc", restart_command]
                restart = self._run(restart_cmd, timeout=40)
                if not restart.get("ok"):
                    raise RuntimeError(restart.get("stderr") or restart.get("stdout") or "Restart command failed.")
                self._set_state(instance_path, "restarting", current_step=current_step, last_log_line=self._line(restart, "Restart command completed."))

            final_snapshot = self.get_repo_snapshot()
            final_status = "success" if restart_command else "restart_required"
            self._set_state(
                instance_path,
                final_status,
                current_step=final_status,
                snapshot=final_snapshot,
                started_at=started_at,
                target_branch=branch,
                stash_created=stash_created,
                last_log_line="Update complete." if restart_command else "Update complete. Manual restart required.",
            )
            history_item.update({
                "status": final_status,
                "finished_at": time.time(),
                "result_snapshot": final_snapshot,
                "smoke_output": smoke_output,
            })
        except Exception as exc:
            rollback_error = None
            rollback_result = None
            self._set_state(
                instance_path,
                "failed",
                current_step="failed",
                error=str(exc),
                failed_step=current_step,
                started_at=started_at,
                target_branch=branch,
                last_log_line=f"Failed at {current_step}: {exc}",
            )
            if snapshot.get("branch") and snapshot.get("commit"):
                checkout_back = self._git(["checkout", snapshot["branch"]], timeout=20)
                reset_back = self._git(["reset", "--hard", snapshot["commit"]], timeout=25)
                if checkout_back.get("ok") and reset_back.get("ok"):
                    rollback_result = "success"
                    self._set_state(
                        instance_path,
                        "rolled_back",
                        current_step="rolled_back",
                        rollback_to=snapshot,
                        rollback_result=rollback_result,
                        started_at=started_at,
                        target_branch=branch,
                        failed_step=current_step,
                        last_log_line="Rollback completed.",
                    )
                else:
                    rollback_error = ((checkout_back.get("stderr") or "") + " " + (reset_back.get("stderr") or "")).strip()
                    rollback_result = "failed"
                    self._set_state(
                        instance_path,
                        "failed",
                        current_step="failed",
                        rollback_error=rollback_error,
                        rollback_result=rollback_result,
                        started_at=started_at,
                        target_branch=branch,
                        failed_step=current_step,
                    )
            history_item.update({
                "status": "rolled_back" if rollback_result == "success" else "failed",
                "error": str(exc),
                "failed_step": current_step,
                "rollback_result": rollback_result,
                "rollback_error": rollback_error,
                "finished_at": time.time(),
            })
        finally:
            self._append_history(instance_path, history_item)


update_manager = UpdateManager()
