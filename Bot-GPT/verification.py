import shlex
import subprocess
from dataclasses import dataclass
from typing import Dict, List, Optional


@dataclass(frozen=True)
class VerificationStep:
    step_type: str  # lint | test | build_typecheck | targeted_execution
    command: str
    scope: str


def choose_verification_steps(changed_paths: List[str], user_request: str = "") -> List[VerificationStep]:
    lowered_request = (user_request or "").lower()
    normalized_paths = [p for p in (changed_paths or []) if isinstance(p, str)]
    steps: List[VerificationStep] = []

    python_files = [p for p in normalized_paths if p.endswith(".py")]
    js_files = [p for p in normalized_paths if p.endswith(".js")]
    ts_files = [p for p in normalized_paths if p.endswith(".ts") or p.endswith(".tsx")]

    if python_files:
        quoted = " ".join(shlex.quote(path) for path in python_files[:25])
        steps.append(VerificationStep("lint", f"python -m py_compile {quoted}", "changed_python_files"))
    if js_files:
        for path in js_files[:10]:
            steps.append(VerificationStep("build_typecheck", f"node --check {shlex.quote(path)}", path))
    if ts_files:
        steps.append(VerificationStep("build_typecheck", "npm run -s typecheck", "typescript_project"))

    asks_for_tests = any(token in lowered_request for token in ["test", "fix", "bug", "failing", "regression"])
    if asks_for_tests or any(path.startswith("tests/") for path in normalized_paths):
        steps.append(VerificationStep("test", "pytest -q", "workspace"))

    # Keep a deterministic order and avoid duplicate commands.
    deduped = []
    seen = set()
    for step in steps:
        key = (step.step_type, step.command)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(step)
    return deduped


def classify_verification_failure(output: str, return_code: Optional[int] = None) -> str:
    text = (output or "").lower()

    if "no module named" in text or "modulenotfounderror" in text or "cannot import name" in text:
        return "import_error"
    if "syntaxerror" in text or "unexpected indent" in text or "invalid syntax" in text:
        return "syntax_error"
    if "ruff" in text or "flake8" in text or "eslint" in text or "lint" in text:
        return "lint_error"
    if "mypy" in text or "pyright" in text or "type error" in text or "ts2304" in text:
        return "type_error"
    if "failed" in text and ("test" in text or "assert" in text or "pytest" in text):
        return "failing_test"
    if "traceback" in text or "exception" in text:
        return "runtime_error"
    if "no such file or directory" in text or "command not found" in text:
        return "command_error"
    if "could not find a version that satisfies" in text or "requires installation" in text:
        return "missing_dependency"
    if return_code is not None and return_code != 0:
        return "unknown_error"
    return "unknown_error"


def run_verification_step(step: VerificationStep, workspace_path: str, timeout_seconds: int = 120) -> Dict[str, object]:
    try:
        process = subprocess.run(
            step.command,
            cwd=workspace_path,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout_seconds,
            check=False,
        )
        output = (process.stdout or "") + ("\n" + process.stderr if process.stderr else "")
        success = process.returncode == 0
        return {
            "step_type": step.step_type,
            "command": step.command,
            "scope": step.scope,
            "success": success,
            "return_code": process.returncode,
            "output": output.strip()[:4000],
            "classification": None if success else classify_verification_failure(output, process.returncode),
        }
    except subprocess.TimeoutExpired as exc:
        timeout_output = ((exc.stdout or "") + "\n" + (exc.stderr or "")).strip()
        return {
            "step_type": step.step_type,
            "command": step.command,
            "scope": step.scope,
            "success": False,
            "return_code": None,
            "output": timeout_output,
            "classification": "command_error",
        }


def should_continue_repair(pending_failure: Optional[Dict[str, object]], attempts: int, max_attempts: int) -> bool:
    if not pending_failure:
        return False
    failure_type = pending_failure.get("classification")
    if failure_type == "missing_dependency":
        return False
    return attempts < max_attempts


def summarize_verification_results(results: List[Dict[str, object]]) -> str:
    if not results:
        return "No verification steps were run."
    lines = ["Verification results:"]
    for result in results:
        status = "PASS" if result.get("success") else "FAIL"
        classification = result.get("classification")
        class_part = f" ({classification})" if classification else ""
        lines.append(f"- {status}: {result.get('step_type')} -> `{result.get('command')}`{class_part}")
    return "\n".join(lines)
