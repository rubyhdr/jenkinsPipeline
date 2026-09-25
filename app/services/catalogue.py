"""Searching and managing the book catalogue."""
from sqlalchemy import or_

from ..extensions import db
from ..models import Book, Loan
from . import ConflictError, LibraryError
from . import rules
from .circulation import promote_waiting

EDITABLE_FIELDS = ("isbn", "title", "author", "genre", "year", "description", "copies_total")


def search(query: str = "", genre: str = "", available_only: bool = False, limit: int = 100):
    q = Book.query
    query = (query or "").strip()
    if query:
        like = f"%{query}%"
        q = q.filter(
            or_(
                Book.title.ilike(like),
                Book.author.ilike(like),
                Book.isbn.ilike(f"%{rules.normalise_isbn(query)}%"),
                Book.genre.ilike(like),
            )
        )
    if genre:
        q = q.filter(Book.genre == genre)
    books = q.order_by(Book.title).limit(limit).all()
    if available_only:
        books = [b for b in books if b.available_copies > 0]
    return books


def genres():
    return [g for (g,) in db.session.query(Book.genre).distinct().order_by(Book.genre)]


def _to_int(value, message):
    try:
        return int(value)
    except (TypeError, ValueError):
        raise LibraryError(message) from None


def _clean_isbn(value):
    if not rules.is_valid_isbn(value):
        raise LibraryError("ISBN is not valid.")
    return rules.normalise_isbn(value)


def _clean_copies(value):
    copies = _to_int(value, "Copies must be a whole number.")
    if not 0 <= copies <= 100:
        raise LibraryError("Copies must be between 0 and 100.")
    return copies


def _clean_required(field):
    def clean(value):
        if not value:
            raise LibraryError(f"{field.capitalize()} is required.")
        return value
    return clean


CLEANERS = {
    "isbn": _clean_isbn,
    "title": _clean_required("title"),
    "author": _clean_required("author"),
    "copies_total": _clean_copies,
    "year": lambda value: _to_int(value, "Year must be a number."),
}


def _clean(data: dict) -> dict:
    """Trim, validate and convert the editable fields present in `data`."""
    cleaned = {}
    for field in EDITABLE_FIELDS:
        value = data.get(field)
        if isinstance(value, str):
            value = value.strip()
        if value is None or (field == "year" and value == ""):
            continue
        cleaned[field] = CLEANERS.get(field, lambda v: v)(value)
    return cleaned


def create_book(data: dict) -> Book:
    cleaned = _clean(data)
    missing = [f for f in ("isbn", "title", "author") if not cleaned.get(f)]
    if missing:
        raise LibraryError(f"Missing required fields: {', '.join(missing)}.")
    if Book.query.filter_by(isbn=cleaned["isbn"]).first():
        raise ConflictError("A book with this ISBN already exists.")
    book = Book(**cleaned)
    db.session.add(book)
    db.session.commit()
    return book


def update_book(book: Book, data: dict) -> Book:
    cleaned = _clean(data)
    if "isbn" in cleaned and cleaned["isbn"] != book.isbn:
        if Book.query.filter_by(isbn=cleaned["isbn"]).first():
            raise ConflictError("A book with this ISBN already exists.")
    if "copies_total" in cleaned and cleaned["copies_total"] < book.active_loan_count:
        raise ConflictError("Copies cannot be fewer than the number currently on loan.")
    for field, value in cleaned.items():
        setattr(book, field, value)
    db.session.flush()
    promote_waiting(book)
    db.session.commit()
    return book


def delete_book(book: Book):
    if book.loans.filter(Loan.returned_at.is_(None)).count():
        raise ConflictError("Books with active loans cannot be deleted.")
    for reservation in book.reservations:
        db.session.delete(reservation)
    for loan in book.loans:
        db.session.delete(loan)
    db.session.delete(book)
    db.session.commit()
