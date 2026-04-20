import json
import os
from pathlib import Path

from app import create_app
from config import TestConfig


def test_legacy_users_file_migrates(tmp_path):
    legacy_dir = tmp_path / "legacy_users"
    legacy_dir.mkdir(parents=True)
    legacy_users = legacy_dir / "users.json"
    legacy_users.write_text(json.dumps({"1": {"id": 1, "username": "legacy", "password_hash": "x"}}))

    original_dir = TestConfig.USER_DATA_DIR
    TestConfig.USER_DATA_DIR = str(legacy_dir)
    app = None
    try:
        app = create_app("testing")
        migrated = Path(app.instance_path) / "users.json"
        assert migrated.exists()
        payload = json.loads(migrated.read_text())
        assert payload["1"]["username"] == "legacy"
    finally:
        TestConfig.USER_DATA_DIR = original_dir
        if app and os.path.exists(app.instance_path):
            import shutil
            shutil.rmtree(app.instance_path)
