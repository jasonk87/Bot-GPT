import os
import sys
import pytest
import shutil
from unittest import mock

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from app import create_app
from extensions import socketio as _socketio
from models import User, _save_users

@pytest.fixture(scope='session')
def app():
    """Create and configure a new app instance for the test session."""
    app = create_app('testing')
    # Clean up and create instance folder for the session
    instance_path = app.instance_path
    if os.path.exists(instance_path):
        shutil.rmtree(instance_path)
    os.makedirs(instance_path)

    with app.app_context():
        yield app

    # Clean up after the session
    if os.path.exists(instance_path):
        shutil.rmtree(instance_path)


@pytest.fixture(scope='session')
def client(app):
    """A test client for the app for the entire session."""
    return app.test_client()

@pytest.fixture(scope='function')
def test_user(app):
    """Create a test user in the users.json file for a function."""
    with app.app_context():
        user = User(id=1, username='testuser', password_hash=None)
        user.set_password('password')
        users = {'1': user.to_dict()}
        _save_users(users)
        yield user
        # Clean up by removing the users.json file
        users_path = os.path.join(app.instance_path, 'users.json')
        if os.path.exists(users_path):
            os.remove(users_path)

@pytest.fixture
def logged_in_client(client, test_user):
    """A test client logged in for a single test."""
    login_response = client.post('/login', json={'username': 'testuser', 'password': 'password'})
    assert login_response.status_code == 200
    yield client
    client.get('/logout')

@pytest.fixture
def socketio_test_client(app, logged_in_client):
    """A Socket.IO test client."""
    from flask_socketio import SocketIOTestClient
    return SocketIOTestClient(app, socketio=_socketio, flask_test_client=logged_in_client)

class SimpleMocker:
    """Lightweight stand-in for pytest-mock's MockerFixture."""
    def __init__(self):
        self._patchers = []
    def patch(self, target, *args, **kwargs):
        patcher = mock.patch(target, *args, **kwargs)
        mocked = patcher.start()
        self._patchers.append(patcher)
        return mocked
    def stop(self):
        for patcher in self._patchers:
            patcher.stop()

@pytest.fixture
def mocker():
    """Provide a minimal mocker fixture."""
    mocker_instance = SimpleMocker()
    yield mocker_instance
    mocker_instance.stop()

@pytest.fixture(scope='function')
def two_users(app):
    """Create two users in the users.json file for a function."""
    with app.app_context():
        user1 = User(id=1, username='testuser1', password_hash=None)
        user1.set_password('password')
        user2 = User(id=2, username='testuser2', password_hash=None)
        user2.set_password('password')
        users = {
            '1': user1.to_dict(),
            '2': user2.to_dict()
        }
        _save_users(users)
        yield user1, user2
        # Clean up by removing the users.json file
        users_path = os.path.join(app.instance_path, 'users.json')
        if os.path.exists(users_path):
            os.remove(users_path)
