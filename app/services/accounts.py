"""Member registration and authentication."""
from ..extensions import db
from ..models import User
from . import ConflictError, LibraryError

MIN_PASSWORD_LENGTH = 8


def is_valid_email(email: str) -> bool:
    """Structural check without regex backtracking (SonarQube python:S8786): local@domain.tld."""
    if len(email) > 254 or any(ch.isspace() for ch in email) or email.count("@") != 1:
        return False
    local, domain = email.split("@")
    labels = domain.split(".")
    return bool(local) and len(labels) >= 2 and all(labels)


def validate_password(password: str):
    if len(password or "") < MIN_PASSWORD_LENGTH:
        raise LibraryError(f"Password must be at least {MIN_PASSWORD_LENGTH} characters.")
    if password.isdigit() or password.isalpha():
        raise LibraryError("Password must contain both letters and numbers.")


def register(name: str, email: str, password: str, role: str = User.ROLE_MEMBER) -> User:
    name = (name or "").strip()
    email = (email or "").strip().lower()
    if not name:
        raise LibraryError("Name is required.")
    if not is_valid_email(email):
        raise LibraryError("Please enter a valid email address.")
    validate_password(password)
    if role not in (User.ROLE_MEMBER, User.ROLE_LIBRARIAN):
        raise LibraryError("Unknown role.")
    if User.query.filter_by(email=email).first():
        raise ConflictError("An account with this email already exists.")

    user = User(name=name, email=email, role=role)
    user.set_password(password)
    db.session.add(user)
    db.session.commit()
    return user


def authenticate(email: str, password: str):
    user = User.query.filter_by(email=(email or "").strip().lower()).first()
    if user is None or not user.check_password(password or ""):
        return None
    return user
