import pytest
import sys
import os

# Add the project root to the Python path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from extensions import db, socketio
from models import User
from flask_socketio import SocketIOTestClient

# --- Fixtures ---

@pytest.fixture(scope='session')
def app():
    """Create and configure a new app instance for the session."""
    app = create_app('testing')
    with app.app_context():
        db.create_all()
        yield app
        db.drop_all()

@pytest.fixture(scope='function')
def test_user(app):
    """Create and clean up a test user."""
    with app.app_context():
        user = User(username='testuser')
        user.set_password('password')
        db.session.add(user)
        db.session.commit()
        yield user
        db.session.delete(user)
        db.session.commit()

@pytest.fixture
def client(app):
    """A test client for the app."""
    return app.test_client()

@pytest.fixture
def logged_in_client(client, test_user):
    """A logged-in test client that maintains the session."""
    with client as c:
        c.post('/login', json={'username': 'testuser', 'password': 'password'})
        yield c
        c.get('/logout')

@pytest.fixture
def socketio_test_client(app, logged_in_client):
    """A test client for the socketio server that uses a logged-in client."""
    return SocketIOTestClient(app, socketio, flask_test_client=logged_in_client)
