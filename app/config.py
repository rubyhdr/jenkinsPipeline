"""Environment-specific configuration, selected with the APP_ENV variable."""
import os


def _bool(value, default=False):
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


class BaseConfig:
    APP_NAME = "Shelf"
    APP_ENV = "base"
    APP_VERSION = os.environ.get("APP_VERSION", "dev")
    GIT_COMMIT = os.environ.get("GIT_COMMIT", "local")

    SECRET_KEY = os.environ.get("SECRET_KEY", "dev-only-secret-change-me")
    SQLALCHEMY_DATABASE_URI = os.environ.get("DATABASE_URL", "sqlite:///shelf-dev.db")
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_ENGINE_OPTIONS = {"pool_pre_ping": True}

    SESSION_COOKIE_HTTPONLY = True
    SESSION_COOKIE_SAMESITE = "Lax"
    WTF_CSRF_ENABLED = True

    JWT_EXPIRY_MINUTES = int(os.environ.get("JWT_EXPIRY_MINUTES", "60"))

    # Library business rules
    LOAN_PERIOD_DAYS = int(os.environ.get("LOAN_PERIOD_DAYS", "14"))
    MAX_ACTIVE_LOANS = int(os.environ.get("MAX_ACTIVE_LOANS", "5"))
    MAX_RENEWALS = 1
    LATE_FEE_PER_DAY = float(os.environ.get("LATE_FEE_PER_DAY", "0.50"))
    LATE_FEE_CAP = float(os.environ.get("LATE_FEE_CAP", "20.00"))

    # Demo-only endpoint used by scripts/simulate_incident.sh to trigger 5xx alerts.
    CHAOS_ENABLED = _bool(os.environ.get("CHAOS_ENABLED"))
    METRICS_ENABLED = True


class DevelopmentConfig(BaseConfig):
    APP_ENV = "development"
    DEBUG = True


class TestingConfig(BaseConfig):
    APP_ENV = "testing"
    TESTING = True
    SQLALCHEMY_DATABASE_URI = "sqlite:///:memory:"
    WTF_CSRF_ENABLED = False
    SECRET_KEY = "testing-secret-key-not-for-production"  # nosec B105 - test-only key
    CHAOS_ENABLED = True


class StagingConfig(BaseConfig):
    APP_ENV = "staging"


class ProductionConfig(BaseConfig):
    APP_ENV = "production"
    SESSION_COOKIE_SECURE = _bool(os.environ.get("SESSION_COOKIE_SECURE"))


CONFIGS = {
    "development": DevelopmentConfig,
    "testing": TestingConfig,
    "staging": StagingConfig,
    "production": ProductionConfig,
}


def get_config(name=None):
    name = (name or os.environ.get("APP_ENV") or "development").lower()
    try:
        return CONFIGS[name]
    except KeyError:
        raise ValueError(f"Unknown APP_ENV '{name}'. Expected one of {sorted(CONFIGS)}") from None
