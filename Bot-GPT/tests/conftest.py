import json
import pytest
from unittest import mock
import os
import sys

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import db as _db, socketio as _socketio
from models import User


@pytest.fixture(scope="function")
def app(tmp_path):
    """Create and configure a new app instance for each test."""
    db_path = tmp_path / "test.db"
    app = create_app()
    app.config.update(
        {
            "TESTING": True,
            "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
            "WTF_CSRF_ENABLED": False,
            "SECRET_KEY": "test-secret-key",
            "APPLICATION_ROOT": "/",
        }
    )

    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()


class _PatchProxy:
    """Proxy that mimics pytest-mock's patch helper."""

    def __init__(self, register):
        self._register = register

    def __call__(self, target, *args, **kwargs):
        patcher = mock.patch(target, *args, **kwargs)
        mocked = patcher.start()
        self._register(patcher)
        return mocked

    def dict(self, target, *args, **kwargs):
        patcher = mock.patch.dict(target, *args, **kwargs)
        patcher.start()
        self._register(patcher)
        return patcher


class SimpleMocker:
    """Lightweight stand-in for pytest-mock's MockerFixture."""

    def __init__(self):
        self._patchers = []
        self.patch = _PatchProxy(self._register)

    def _register(self, patcher):
        self._patchers.append(patcher)

    def mock_open(self, *args, **kwargs):
        return mock.mock_open(*args, **kwargs)

    def spy(self, obj, attribute):
        patcher = mock.patch.object(obj, attribute, wraps=getattr(obj, attribute))
        wrapped = patcher.start()
        self._register(patcher)
        return wrapped

    def stop(self):
        while self._patchers:
            self._patchers.pop().stop()


@pytest.fixture
def mocker():
    """Provide a minimal mocker fixture when pytest-mock isn't available."""
    simple = SimpleMocker()
    try:
        yield simple
    finally:
        simple.stop()


@pytest.fixture
def socketio(app):
    """A fixture to provide the socketio instance for tests."""
    return _socketio


@pytest.fixture
def client(app):
    """A test client for the app."""
    with app.test_client() as client:
        yield client


@pytest.fixture
def db(app):
    """A fixture to provide the database session for tests."""
    with app.app_context():
        yield _db


@pytest.fixture
def test_user(db):
    """Create a test user, ensuring it's not a duplicate."""
    # Using a specific ID like 1 can cause issues if not cleaned up.
    # A better approach is to check if the user exists.
    user = db.session.get(User, 1)
    if not user:
        user = User(id=1, username="testuser")
        user.set_password("password")
        db.session.add(user)
        db.session.commit()
    return user


@pytest.fixture
def logged_in_client(client, test_user):
    """A test client logged in via the login route."""
    response = client.post(
        "/login",
        data=json.dumps({"username": "testuser", "password": "password"}),
        content_type="application/json",
    )
    assert response.status_code == 200
    return client
