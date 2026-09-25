"""Database models for the Shelf library system."""
from datetime import datetime, timezone

from flask_login import UserMixin
from sqlalchemy import func
from werkzeug.security import check_password_hash, generate_password_hash

from .extensions import db


def utcnow():
    """Naive UTC timestamp (stored consistently in SQLite and Postgres)."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


class User(UserMixin, db.Model):
    __tablename__ = "users"

    ROLE_MEMBER = "member"
    ROLE_LIBRARIAN = "librarian"

    id = db.Column(db.Integer, primary_key=True)
    name = db.Column(db.String(120), nullable=False)
    email = db.Column(db.String(255), unique=True, nullable=False, index=True)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False, default=ROLE_MEMBER)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    loans = db.relationship("Loan", back_populates="user", lazy="dynamic")
    reservations = db.relationship("Reservation", back_populates="user", lazy="dynamic")

    def set_password(self, password):
        self.password_hash = generate_password_hash(password)

    def check_password(self, password):
        return check_password_hash(self.password_hash, password)

    @property
    def is_librarian(self):
        return self.role == self.ROLE_LIBRARIAN

    def to_dict(self):
        return {"id": self.id, "name": self.name, "email": self.email, "role": self.role}


class Book(db.Model):
    __tablename__ = "books"

    id = db.Column(db.Integer, primary_key=True)
    isbn = db.Column(db.String(20), unique=True, nullable=False, index=True)
    title = db.Column(db.String(255), nullable=False, index=True)
    author = db.Column(db.String(255), nullable=False, index=True)
    genre = db.Column(db.String(80), nullable=False, default="General")
    year = db.Column(db.Integer)
    description = db.Column(db.Text, default="")
    copies_total = db.Column(db.Integer, nullable=False, default=1)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    loans = db.relationship("Loan", back_populates="book", lazy="dynamic")
    reservations = db.relationship("Reservation", back_populates="book", lazy="dynamic")

    @property
    def active_loan_count(self):
        return self.loans.filter(Loan.returned_at.is_(None)).count()

    @property
    def held_count(self):
        """Copies set aside for a member whose reservation is ready for pickup."""
        return self.reservations.filter(Reservation.status == Reservation.READY).count()

    @property
    def available_copies(self):
        return max(self.copies_total - self.active_loan_count - self.held_count, 0)

    @property
    def waiting_count(self):
        return self.reservations.filter(Reservation.status == Reservation.WAITING).count()

    def to_dict(self):
        return {
            "id": self.id,
            "isbn": self.isbn,
            "title": self.title,
            "author": self.author,
            "genre": self.genre,
            "year": self.year,
            "description": self.description,
            "copies_total": self.copies_total,
            "available_copies": self.available_copies,
            "waiting_reservations": self.waiting_count,
        }


class Loan(db.Model):
    __tablename__ = "loans"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False, index=True)
    borrowed_at = db.Column(db.DateTime, nullable=False, default=utcnow)
    due_at = db.Column(db.DateTime, nullable=False)
    returned_at = db.Column(db.DateTime)
    renewals = db.Column(db.Integer, nullable=False, default=0)
    fee = db.Column(db.Numeric(8, 2), nullable=False, default=0)

    user = db.relationship("User", back_populates="loans")
    book = db.relationship("Book", back_populates="loans")

    @property
    def is_active(self):
        return self.returned_at is None

    def is_overdue(self, now=None):
        return self.is_active and (now or utcnow()) > self.due_at

    def to_dict(self):
        return {
            "id": self.id,
            "book": {"id": self.book.id, "title": self.book.title, "author": self.book.author},
            "user_id": self.user_id,
            "borrowed_at": self.borrowed_at.isoformat(),
            "due_at": self.due_at.isoformat(),
            "returned_at": self.returned_at.isoformat() if self.returned_at else None,
            "renewals": self.renewals,
            "fee": float(self.fee or 0),
            "overdue": self.is_overdue(),
        }


class Reservation(db.Model):
    __tablename__ = "reservations"

    WAITING = "waiting"
    READY = "ready"
    FULFILLED = "fulfilled"
    CANCELLED = "cancelled"

    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey("users.id"), nullable=False, index=True)
    book_id = db.Column(db.Integer, db.ForeignKey("books.id"), nullable=False, index=True)
    status = db.Column(db.String(20), nullable=False, default=WAITING, index=True)
    created_at = db.Column(db.DateTime, nullable=False, default=utcnow)

    user = db.relationship("User", back_populates="reservations")
    book = db.relationship("Book", back_populates="reservations")

    @property
    def is_open(self):
        return self.status in (self.WAITING, self.READY)

    def queue_position(self):
        if self.status != self.WAITING:
            return None
        ahead = (
            Reservation.query.filter(
                Reservation.book_id == self.book_id,
                Reservation.status == Reservation.WAITING,
                Reservation.id < self.id,
            ).count()
        )
        return ahead + 1

    def to_dict(self):
        return {
            "id": self.id,
            "book": {"id": self.book.id, "title": self.book.title},
            "status": self.status,
            "created_at": self.created_at.isoformat(),
            "queue_position": self.queue_position(),
        }


def genre_counts():
    return (
        db.session.query(Book.genre, func.count(Book.id))
        .group_by(Book.genre)
        .order_by(Book.genre)
        .all()
    )
