import itertools

import pytest

from app import create_app
from app.extensions import db as _db
from app.models import Book, User
from app.seed import isbn13
from app.services.rules import LoanPolicy

_isbn_counter = itertools.count(100000000)


@pytest.fixture
def app():
    app = create_app("testing")
    with app.app_context():
        _db.create_all()
        yield app
        _db.session.remove()
        _db.drop_all()
        _db.engine.dispose()


@pytest.fixture
def client(app):
    return app.test_client()


@pytest.fixture
def policy():
    return LoanPolicy(loan_period_days=14, max_active_loans=3, max_renewals=1,
                      fee_per_day=0.5, fee_cap=5.0)


@pytest.fixture
def make_user(app):
    counter = itertools.count(1)

    def _make(role=User.ROLE_MEMBER, password="Password123", email=None, name=None):
        n = next(counter)
        user = User(name=name or f"User {n}", email=email or f"user{n}@example.com", role=role)
        user.set_password(password)
        _db.session.add(user)
        _db.session.commit()
        return user

    return _make


@pytest.fixture
def make_book(app):
    def _make(title="Test Book", author="A. Author", genre="Fiction", copies=1, **extra):
        book = Book(isbn=isbn13(f"978{next(_isbn_counter)}"), title=title, author=author,
                    genre=genre, copies_total=copies, **extra)
        _db.session.add(book)
        _db.session.commit()
        return book

    return _make


@pytest.fixture
def member(make_user):
    return make_user(email="member@example.com")


@pytest.fixture
def librarian(make_user):
    return make_user(role=User.ROLE_LIBRARIAN, email="librarian@example.com", name="Lib Rarian")


@pytest.fixture
def login(client):
    def _login(email, password="Password123"):
        return client.post("/login", data={"email": email, "password": password},
                           follow_redirects=True)

    return _login


@pytest.fixture
def api_token(client):
    def _token(email, password="Password123"):
        res = client.post("/api/auth/token", json={"email": email, "password": password})
        assert res.status_code == 200, res.get_json()
        return {"Authorization": f"Bearer {res.get_json()['token']}"}

    return _token
