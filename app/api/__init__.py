"""JSON REST API secured with JWT bearer tokens."""
from datetime import datetime, timedelta, timezone
from functools import wraps

import jwt
from flask import Blueprint, current_app, g, jsonify, request

from ..extensions import csrf, db
from ..metrics import record
from ..models import Loan, Reservation, User
from ..services import LibraryError, accounts, catalogue, circulation
from ..services.rules import LoanPolicy

bp = Blueprint("api", __name__, url_prefix="/api")
csrf.exempt(bp)


def issue_token(user: User) -> str:
    now = datetime.now(timezone.utc)
    payload = {
        "sub": str(user.id),
        "role": user.role,
        "iat": now,
        "exp": now + timedelta(minutes=current_app.config["JWT_EXPIRY_MINUTES"]),
    }
    return jwt.encode(payload, current_app.config["SECRET_KEY"], algorithm="HS256")


def token_required(fn):
    @wraps(fn)
    def wrapper(*args, **kwargs):
        header = request.headers.get("Authorization", "")
        if not header.startswith("Bearer "):
            return jsonify(error="Missing bearer token."), 401
        try:
            payload = jwt.decode(
                header[7:], current_app.config["SECRET_KEY"], algorithms=["HS256"]
            )
        except jwt.ExpiredSignatureError:
            return jsonify(error="Token has expired."), 401
        except jwt.InvalidTokenError:
            return jsonify(error="Invalid token."), 401
        user = db.session.get(User, int(payload["sub"]))
        if user is None:
            return jsonify(error="Unknown user."), 401
        g.api_user = user
        return fn(*args, **kwargs)

    return wrapper


def librarian_required(fn):
    @wraps(fn)
    @token_required
    def wrapper(*args, **kwargs):
        if not g.api_user.is_librarian:
            return jsonify(error="Librarian access required."), 403
        return fn(*args, **kwargs)

    return wrapper


def _policy():
    return LoanPolicy.from_config(current_app.config)


def _json():
    data = request.get_json(silent=True)
    if not isinstance(data, dict):
        raise LibraryError("Request body must be a JSON object.")
    return data


def _book_from_body():
    try:
        book_id = int(_json().get("book_id"))
    except (TypeError, ValueError):
        raise LibraryError("book_id must be an integer.") from None
    return circulation.get_book(book_id)


@bp.errorhandler(LibraryError)
def handle_library_error(err):
    return jsonify(error=str(err)), err.status_code


@bp.post("/auth/register")
def register():
    data = _json()
    user = accounts.register(data.get("name"), data.get("email"), data.get("password"))
    return jsonify(user=user.to_dict(), token=issue_token(user)), 201


@bp.post("/auth/token")
def token():
    data = _json()
    user = accounts.authenticate(data.get("email"), data.get("password"))
    if user is None:
        record("logins", "failure")
        return jsonify(error="Invalid email or password."), 401
    record("logins", "success")
    return jsonify(token=issue_token(user), user=user.to_dict())


@bp.get("/me")
@token_required
def me():
    return jsonify(user=g.api_user.to_dict())


@bp.get("/books")
def list_books():
    books = catalogue.search(
        request.args.get("q", ""),
        request.args.get("genre", ""),
        request.args.get("available") in ("1", "true"),
    )
    return jsonify(books=[b.to_dict() for b in books], count=len(books))


@bp.get("/books/<int:book_id>")
def get_book(book_id):
    return jsonify(book=circulation.get_book(book_id).to_dict())


@bp.post("/books")
@librarian_required
def create_book():
    book = catalogue.create_book(_json())
    return jsonify(book=book.to_dict()), 201


@bp.put("/books/<int:book_id>")
@librarian_required
def update_book(book_id):
    book = catalogue.update_book(circulation.get_book(book_id), _json())
    return jsonify(book=book.to_dict())


@bp.delete("/books/<int:book_id>")
@librarian_required
def delete_book(book_id):
    catalogue.delete_book(circulation.get_book(book_id))
    return "", 204


@bp.get("/loans")
@token_required
def list_loans():
    query = Loan.query
    if not (g.api_user.is_librarian and request.args.get("all") in ("1", "true")):
        query = query.filter_by(user_id=g.api_user.id)
    if request.args.get("active") in ("1", "true"):
        query = query.filter(Loan.returned_at.is_(None))
    loans = query.order_by(Loan.borrowed_at.desc()).all()
    return jsonify(loans=[loan.to_dict() for loan in loans])


@bp.post("/loans")
@token_required
def borrow():
    loan = circulation.borrow(g.api_user, _book_from_body(), _policy())
    record("loan_events", "borrow")
    return jsonify(loan=loan.to_dict()), 201


@bp.post("/loans/<int:loan_id>/return")
@token_required
def return_loan(loan_id):
    loan = circulation.return_loan(circulation.get_loan(loan_id), g.api_user, _policy())
    record("loan_events", "return")
    return jsonify(loan=loan.to_dict())


@bp.post("/loans/<int:loan_id>/renew")
@token_required
def renew(loan_id):
    loan = circulation.renew(circulation.get_loan(loan_id), g.api_user, _policy())
    record("loan_events", "renew")
    return jsonify(loan=loan.to_dict())


@bp.get("/reservations")
@token_required
def list_reservations():
    reservations = (
        Reservation.query.filter_by(user_id=g.api_user.id).order_by(Reservation.id.desc()).all()
    )
    return jsonify(reservations=[r.to_dict() for r in reservations])


@bp.post("/reservations")
@token_required
def reserve():
    reservation = circulation.reserve(g.api_user, _book_from_body())
    record("loan_events", "reserve")
    return jsonify(reservation=reservation.to_dict()), 201


@bp.delete("/reservations/<int:reservation_id>")
@token_required
def cancel_reservation(reservation_id):
    circulation.cancel_reservation(circulation.get_reservation(reservation_id), g.api_user)
    return "", 204


@bp.get("/stats")
@librarian_required
def stats():
    data = circulation.dashboard_stats()
    data["popular"] = [
        {"book_id": book.id, "title": book.title, "loans": count} for book, count in data["popular"]
    ]
    data["recent_loans"] = [loan.to_dict() for loan in data["recent_loans"]]
    return jsonify(data)
