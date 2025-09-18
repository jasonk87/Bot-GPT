import os
import sys
import json

import pytest
import chromadb
from chromadb.config import Settings

# This line must come before the app imports.
# It adds the project root to the Python path.
sys.path.insert(
    0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
)

from app import create_app  # noqa: E402
from extensions import db as _db  # noqa: E402
from models import User  # noqa: E402


@pytest.fixture(scope='function')
def app(tmp_path):
    """Create and configure a new app instance for each test."""
    db_path = tmp_path / "test.db"
    chroma_path = tmp_path / "chroma"
    chroma_path.mkdir()

    app = create_app()
    app.config.update({
        "TESTING": True,
        "SQLALCHEMY_DATABASE_URI": f"sqlite:///{db_path}",
        "WTF_CSRF_ENABLED": False,
        "SECRET_KEY": "test-secret-key",
        "CHROMA_SETTINGS": Settings(
            is_persistent=True,
            persist_directory=str(chroma_path),
            allow_reset=True
        ),
    })

    with app.app_context():
        _db.create_all()
        yield app
        _db.drop_all()


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
    """Create a test user."""
    user = User(username='testuser')
    user.set_password('password')
    db.session.add(user)
    db.session.commit()
    return user


@pytest.fixture
def logged_in_client(client, test_user):
    """A test client logged in via the login route."""
    response = client.post(
        '/login',
        data=json.dumps({
            'username': 'testuser',
            'password': 'password'
        }),
        content_type='application/json'
    )
    assert response.status_code == 200
    return client


@pytest.fixture(scope='function')
def cleanup_chroma(app):
    """Clears the ChromaDB database before each test."""
    with app.app_context():
        client = chromadb.Client(app.config['CHROMA_SETTINGS'])
        client.reset()
