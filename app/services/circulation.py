"""Borrowing, returning, renewing and reserving books."""
from sqlalchemy import func

from ..extensions import db
from ..models import Book, Loan, Reservation, User, utcnow
from . import ConflictError, NotFoundError, PermissionDeniedError
from . import rules


def _check_actor(actor: User, owner_id: int):
    if actor.id != owner_id and not actor.is_librarian:
        raise PermissionDeniedError("You can only manage your own loans and reservations.")


def get_book(book_id: int) -> Book:
    book = db.session.get(Book, book_id)
    if book is None:
        raise NotFoundError("Book not found.")
    return book


def get_loan(loan_id: int) -> Loan:
    loan = db.session.get(Loan, loan_id)
    if loan is None:
        raise NotFoundError("Loan not found.")
    return loan


def get_reservation(reservation_id: int) -> Reservation:
    reservation = db.session.get(Reservation, reservation_id)
    if reservation is None:
        raise NotFoundError("Reservation not found.")
    return reservation


def active_loans(user: User):
    return user.loans.filter(Loan.returned_at.is_(None)).order_by(Loan.due_at).all()


def promote_waiting(book: Book):
    """Hold free copies for the members at the front of the reservation queue."""
    promoted = []
    while book.available_copies > 0:
        nxt = (
            book.reservations.filter(Reservation.status == Reservation.WAITING)
            .order_by(Reservation.id)
            .first()
        )
        if nxt is None:
            break
        nxt.status = Reservation.READY
        db.session.flush()
        promoted.append(nxt)
    return promoted


def borrow(user: User, book: Book, policy: rules.LoanPolicy, now=None) -> Loan:
    now = now or utcnow()
    current = active_loans(user)

    if any(loan.book_id == book.id for loan in current):
        raise ConflictError("You already have this book on loan.")

    allowed, reason = rules.can_borrow(
        len(current), any(loan.is_overdue(now) for loan in current), policy
    )
    if not allowed:
        raise ConflictError(reason)

    own_reservation = book.reservations.filter(
        Reservation.user_id == user.id,
        Reservation.status.in_([Reservation.WAITING, Reservation.READY]),
    ).first()

    if own_reservation is not None and own_reservation.status == Reservation.READY:
        own_reservation.status = Reservation.FULFILLED  # the held copy becomes the loan
    elif book.available_copies <= 0:
        raise ConflictError("No copies are available right now. Reserve it instead.")
    elif own_reservation is not None:
        own_reservation.status = Reservation.FULFILLED

    loan = Loan(user=user, book=book, borrowed_at=now, due_at=rules.due_date(now, policy))
    db.session.add(loan)
    db.session.commit()
    return loan


def return_loan(loan: Loan, actor: User, policy: rules.LoanPolicy, now=None) -> Loan:
    now = now or utcnow()
    _check_actor(actor, loan.user_id)
    if not loan.is_active:
        raise ConflictError("This loan has already been returned.")

    loan.returned_at = now
    loan.fee = rules.late_fee(loan.due_at, now, policy)
    db.session.flush()
    promote_waiting(loan.book)
    db.session.commit()
    return loan


def renew(loan: Loan, actor: User, policy: rules.LoanPolicy, now=None) -> Loan:
    now = now or utcnow()
    _check_actor(actor, loan.user_id)
    if not loan.is_active:
        raise ConflictError("Returned loans cannot be renewed.")

    allowed, reason = rules.can_renew(
        loan.renewals, loan.is_overdue(now), loan.book.waiting_count > 0, policy
    )
    if not allowed:
        raise ConflictError(reason)

    loan.due_at = rules.due_date(max(loan.due_at, now), policy)
    loan.renewals += 1
    db.session.commit()
    return loan


def reserve(user: User, book: Book) -> Reservation:
    if book.available_copies > 0:
        raise ConflictError("Copies are available, so you can borrow this book now.")
    if any(loan.book_id == book.id for loan in active_loans(user)):
        raise ConflictError("You already have this book on loan.")
    existing = book.reservations.filter(
        Reservation.user_id == user.id,
        Reservation.status.in_([Reservation.WAITING, Reservation.READY]),
    ).first()
    if existing is not None:
        raise ConflictError("You have already reserved this book.")

    reservation = Reservation(user=user, book=book)
    db.session.add(reservation)
    db.session.commit()
    return reservation


def cancel_reservation(reservation: Reservation, actor: User) -> Reservation:
    _check_actor(actor, reservation.user_id)
    if not reservation.is_open:
        raise ConflictError("This reservation is no longer open.")
    was_ready = reservation.status == Reservation.READY
    reservation.status = Reservation.CANCELLED
    db.session.flush()
    if was_ready:
        promote_waiting(reservation.book)
    db.session.commit()
    return reservation


def overdue_loans(now=None):
    now = now or utcnow()
    return (
        Loan.query.filter(Loan.returned_at.is_(None), Loan.due_at < now)
        .order_by(Loan.due_at)
        .all()
    )


def dashboard_stats(now=None):
    now = now or utcnow()
    active = Loan.query.filter(Loan.returned_at.is_(None))
    popular = (
        db.session.query(Book, func.count(Loan.id).label("loan_count"))
        .join(Loan, Loan.book_id == Book.id)
        .group_by(Book.id)
        .order_by(func.count(Loan.id).desc(), Book.title)
        .limit(5)
        .all()
    )
    return {
        "books": Book.query.count(),
        "copies": db.session.query(func.coalesce(func.sum(Book.copies_total), 0)).scalar(),
        "members": User.query.filter_by(role=User.ROLE_MEMBER).count(),
        "active_loans": active.count(),
        "overdue_loans": active.filter(Loan.due_at < now).count(),
        "waiting_reservations": Reservation.query.filter_by(status=Reservation.WAITING).count(),
        "fees_collected": float(
            db.session.query(func.coalesce(func.sum(Loan.fee), 0)).scalar() or 0
        ),
        "popular": popular,
        "recent_loans": Loan.query.order_by(Loan.borrowed_at.desc()).limit(8).all(),
    }
