import ast
import subprocess
import os
import tempfile

def lint_python_code(content: str) -> list:
    errors = []
    # 1. Check for basic syntax errors
    try:
        ast.parse(content)
    except SyntaxError as e:
        return [{"line": e.lineno, "column": e.offset, "message": f"SyntaxError: {e.msg}"}]

    # 2. Run flake8 for style and deeper static analysis
    fd, temp_path = tempfile.mkstemp(suffix=".py")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)

        # Run flake8. Format output to parse easily.
        result = subprocess.run(
            ["flake8", "--format=%(row)d:%(col)d:%(code)s %(text)s", temp_path],
            capture_output=True,
            text=True,
            check=False
        )

        for line in result.stdout.splitlines():
            parts = line.split(":", 2)
            if len(parts) >= 3:
                try:
                    row = int(parts[0])
                    col = int(parts[1])
                    msg = parts[2].strip()
                    errors.append({"line": row, "column": col, "message": msg})
                except ValueError:
                    pass
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)

    return errors


def lint_js_code(content: str) -> list:
    # Use node --check for basic JS syntax checking
    errors = []
    fd, temp_path = tempfile.mkstemp(suffix=".js")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)

        result = subprocess.run(
            ["node", "--check", temp_path],
            capture_output=True,
            text=True,
            check=False
        )

        if result.returncode != 0:
            stderr_lines = result.stderr.splitlines()
            line_num = 1
            msg = "SyntaxError"
            for i, line in enumerate(stderr_lines):
                if temp_path in line and ":" in line:
                    try:
                        line_num = int(line.split(":")[-1])
                    except ValueError:
                        pass
                if "SyntaxError:" in line or "ReferenceError:" in line:
                    msg = line.strip()

            errors.append({"line": line_num, "column": 1, "message": msg})

    except FileNotFoundError:
        pass # Node not installed
    finally:
        if os.path.exists(temp_path):
            os.remove(temp_path)
    return errors


def lint_code(filename: str, content: str) -> list:
    """Lints code based on file extension and returns a list of error dictionaries."""
    if filename.endswith(".py"):
        return lint_python_code(content)
    elif filename.endswith(".js") or filename.endswith(".ts") or filename.endswith(".jsx") or filename.endswith(".tsx"):
        return lint_js_code(content)
    return []
