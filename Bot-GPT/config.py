import os
from datetime import timedelta

try:
    from dotenv import load_dotenv
except Exception:  # optional dependency in some runtime/test environments
    load_dotenv = None

if load_dotenv:
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
    BACKGROUND_TASKS_ENABLED = True
    BACKGROUND_TASK_POLL_SECONDS = 5
    BACKGROUND_TASK_MAX_CONCURRENCY = 2
    PROACTIVE_IDLE_THRESHOLD_SECONDS = 90
    ADMIN_USER_IDS = [1]
    TELEGRAM_ENABLED = os.environ.get("TELEGRAM_ENABLED", "0") == "1"
    TELEGRAM_BOT_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    TELEGRAM_POLL_INTERVAL = float(os.environ.get("TELEGRAM_POLL_INTERVAL", "2.0"))
    TELEGRAM_PAIRING_EXPIRY = int(os.environ.get("TELEGRAM_PAIRING_EXPIRY", "300"))
    TELEGRAM_DEFAULT_ROUTE = os.environ.get("TELEGRAM_DEFAULT_ROUTE", "stored")
    WORKFLOW_LEARNING_ENABLED = os.environ.get("WORKFLOW_LEARNING_ENABLED", "1") == "1"
    WORKFLOW_MIN_STEPS_TO_RECORD = int(os.environ.get("WORKFLOW_MIN_STEPS_TO_RECORD", "2"))
    WORKFLOW_MAX_STEPS = int(os.environ.get("WORKFLOW_MAX_STEPS", "25"))
    WORKFLOW_AUTO_REPLAY = os.environ.get("WORKFLOW_AUTO_REPLAY", "1") == "1"


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
    BACKGROUND_TASKS_ENABLED = False
    TELEGRAM_ENABLED = False
    WORKFLOW_LEARNING_ENABLED = True


config = {
    "development": DevelopmentConfig,
    "production": ProductionConfig,
    "testing": TestConfig,
    "default": DevelopmentConfig,
}
