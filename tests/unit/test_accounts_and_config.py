import pytest

from app import create_app
from app.config import get_config
from app.models import User
from app.seed import BOOKS, isbn13, seed_database
from app.services import ConflictError, LibraryError, accounts
from app.services.rules import is_valid_isbn

pytestmark = pytest.mark.unit


def test_register_and_authenticate(app):
    user = accounts.register(" Ada Lovelace ", "ADA@Example.com", "analytical1")
    assert user.email == "ada@example.com" and user.name == "Ada Lovelace"
    assert user.role == User.ROLE_MEMBER
    assert accounts.authenticate("ada@example.com", "analytical1") == user
    assert accounts.authenticate("ada@example.com", "wrong-pass1") is None
    assert accounts.authenticate("nobody@example.com", "analytical1") is None


@pytest.mark.parametrize("name, email, password, message", [
    ("", "a@b.co", "password1", "Name"),
    ("Ada", "not-an-email", "password1", "valid email"),
    ("Ada", "a@b.co", "short1", "at least"),
    ("Ada", "a@b.co", "onlyletters", "letters and numbers"),
    ("Ada", "a@b.co", "12345678", "letters and numbers"),
])
def test_register_validation(app, name, email, password, message):
    with pytest.raises(LibraryError, match=message):
        accounts.register(name, email, password)


def test_register_rejects_unknown_role_and_duplicates(app):
    with pytest.raises(LibraryError, match="role"):
        accounts.register("Ada", "a@b.co", "password1", role="admin")
    accounts.register("Ada", "a@b.co", "password1")
    with pytest.raises(ConflictError):
        accounts.register("Ada", "A@B.co", "password1")


def test_get_config_by_name_and_unknown():
    assert get_config("production").APP_ENV == "production"
    with pytest.raises(ValueError):
        get_config("moon")


def test_production_requires_secret_key(monkeypatch):
    monkeypatch.setattr(get_config("production"), "SECRET_KEY", "dev-only-secret-change-me")
    with pytest.raises(RuntimeError, match="SECRET_KEY"):
        create_app("production")


def test_seed_is_idempotent(app):
    assert seed_database() is True
    assert seed_database(only_if_empty=True) is False
    seed_database()
    assert User.query.count() == 3


def test_seed_isbns_are_valid():
    assert all(is_valid_isbn(isbn13(prefix)) for prefix, *_ in BOOKS)


def test_cli_init_db_and_seed(app):
    runner = app.test_cli_runner()
    assert "Database ready" in runner.invoke(args=["init-db"]).output
    assert "Seeded" in runner.invoke(args=["seed", "--if-empty"]).output
    assert "skipped" in runner.invoke(args=["seed", "--if-empty"]).output
