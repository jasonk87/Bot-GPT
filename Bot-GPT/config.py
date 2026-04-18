import os
from datetime import timedelta
from dotenv import load_dotenv

load_dotenv()


class Config:
    """Base configuration."""

    SECRET_KEY = os.environ.get(
        "SECRET_KEY", "a_very_secret_key_that_should_be_changed"
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    MAX_CONTENT_LENGTH = 16 * 1024 * 1024
    OLLAMA_HOST = os.environ.get("OLLAMA_HOST", "http://localhost:11434")
    PERMANENT_SESSION_LIFETIME = timedelta(days=30)
    REMEMBER_COOKIE_DURATION = timedelta(days=30)
    USER_DATA_DIR = os.path.join(
        os.path.dirname(os.path.abspath(__file__)), "user_data"
    )
    GOOGLE_API_KEY = os.environ.get("GOOGLE_API_KEY", "")
    GOOGLE_CSE_ID = os.environ.get("GOOGLE_CSE_ID", "")


class DevelopmentConfig(Config):
    """Development configuration."""

    DEBUG = True
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DEV_DATABASE_URL",
        "sqlite:///"
        + os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "instance", "users.db"
        ),
    )


class ProductionConfig(Config):
    """Production configuration."""

    DEBUG = False
    SQLALCHEMY_DATABASE_URI = os.environ.get(
        "DATABASE_URL",
        "sqlite:///"
        + os.path.join(
            os.path.abspath(os.path.dirname(__file__)), "instance", "users.db"
        ),
    )


class TestConfig(Config):
    """Testing configuration."""

    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestConfig,
    "default": DevelopmentConfig,
}
