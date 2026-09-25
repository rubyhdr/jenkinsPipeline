from datetime import timedelta
from decimal import Decimal

import pytest

from app.models import Reservation, utcnow
from app.services import ConflictError, NotFoundError, PermissionDeniedError, circulation

pytestmark = pytest.mark.unit


def test_borrow_creates_loan_with_due_date(member, make_book, policy):
    book = make_book(copies=2)
    now = utcnow()
    loan = circulation.borrow(member, book, policy, now=now)
    assert loan.due_at == now + timedelta(days=14)
    assert book.available_copies == 1


def test_cannot_borrow_same_book_twice(member, make_book, policy):
    book = make_book(copies=2)
    circulation.borrow(member, book, policy)
    with pytest.raises(ConflictError, match="already have"):
        circulation.borrow(member, book, policy)


def test_loan_limit_enforced(member, make_book, policy):
    for i in range(policy.max_active_loans):
        circulation.borrow(member, make_book(title=f"B{i}"), policy)
    with pytest.raises(ConflictError, match="maximum"):
        circulation.borrow(member, make_book(title="One too many"), policy)


def test_overdue_loan_blocks_new_borrowing(member, make_book, policy):
    past = utcnow() - timedelta(days=30)
    circulation.borrow(member, make_book(), policy, now=past)
    with pytest.raises(ConflictError, match="overdue"):
        circulation.borrow(member, make_book(title="Other"), policy)


def test_cannot_borrow_when_no_copies(member, make_user, make_book, policy):
    book = make_book(copies=1)
    circulation.borrow(make_user(), book, policy)
    with pytest.raises(ConflictError, match="Reserve"):
        circulation.borrow(member, book, policy)


def test_return_calculates_late_fee(member, make_book, policy):
    start = utcnow() - timedelta(days=17)
    loan = circulation.borrow(member, make_book(), policy, now=start)
    circulation.return_loan(loan, member, policy, now=loan.due_at + timedelta(days=3))
    assert loan.fee == Decimal("1.50")
    assert not loan.is_active


def test_return_twice_is_rejected(member, make_book, policy):
    loan = circulation.borrow(member, make_book(), policy)
    circulation.return_loan(loan, member, policy)
    with pytest.raises(ConflictError):
        circulation.return_loan(loan, member, policy)


def test_member_cannot_return_someone_elses_loan(member, make_user, make_book, policy):
    loan = circulation.borrow(make_user(), make_book(), policy)
    with pytest.raises(PermissionDeniedError):
        circulation.return_loan(loan, member, policy)


def test_librarian_can_check_in_any_loan(member, librarian, make_book, policy):
    loan = circulation.borrow(member, make_book(), policy)
    circulation.return_loan(loan, librarian, policy)
    assert loan.returned_at is not None


def test_renew_extends_due_date_once(member, make_book, policy):
    loan = circulation.borrow(member, make_book(), policy)
    original_due = loan.due_at
    circulation.renew(loan, member, policy)
    assert loan.due_at == original_due + timedelta(days=14)
    with pytest.raises(ConflictError, match="maximum"):
        circulation.renew(loan, member, policy)


def test_renew_blocked_when_someone_is_waiting(member, make_user, make_book, policy):
    book = make_book(copies=1)
    loan = circulation.borrow(member, book, policy)
    circulation.reserve(make_user(), book)
    with pytest.raises(ConflictError, match="waiting"):
        circulation.renew(loan, member, policy)


def test_renew_returned_loan_rejected(member, make_book, policy):
    loan = circulation.borrow(member, make_book(), policy)
    circulation.return_loan(loan, member, policy)
    with pytest.raises(ConflictError):
        circulation.renew(loan, member, policy)


def test_reserve_only_when_unavailable(member, make_book):
    with pytest.raises(ConflictError, match="borrow this book now"):
        circulation.reserve(member, make_book(copies=1))


def test_reservation_queue_and_hold_on_return(member, make_user, make_book, policy):
    book = make_book(copies=1)
    holder = make_user()
    loan = circulation.borrow(holder, book, policy)

    first = circulation.reserve(member, book)
    second_user = make_user()
    second = circulation.reserve(second_user, book)
    assert first.queue_position() == 1
    assert second.queue_position() == 2

    with pytest.raises(ConflictError, match="already reserved"):
        circulation.reserve(member, book)

    circulation.return_loan(loan, holder, policy)
    assert first.status == Reservation.READY
    assert book.available_copies == 0  # held for the first member

    with pytest.raises(ConflictError):
        circulation.borrow(second_user, book, policy)

    new_loan = circulation.borrow(member, book, policy)
    assert new_loan.is_active
    assert first.status == Reservation.FULFILLED


def test_cancelling_ready_reservation_passes_hold_on(member, make_user, make_book, policy):
    book = make_book(copies=1)
    holder = make_user()
    loan = circulation.borrow(holder, book, policy)
    first = circulation.reserve(member, book)
    second = circulation.reserve(make_user(), book)
    circulation.return_loan(loan, holder, policy)

    circulation.cancel_reservation(first, member)
    assert first.status == Reservation.CANCELLED
    assert second.status == Reservation.READY

    with pytest.raises(ConflictError):
        circulation.cancel_reservation(first, member)


def test_cannot_reserve_book_you_have(member, make_user, make_book, policy):
    book = make_book(copies=1)
    circulation.borrow(member, book, policy)
    with pytest.raises(ConflictError, match="on loan"):
        circulation.reserve(member, book)


def test_lookups_raise_not_found(app):
    for getter in (circulation.get_book, circulation.get_loan, circulation.get_reservation):
        with pytest.raises(NotFoundError):
            getter(999)


def test_dashboard_stats(member, make_book, policy):
    book = make_book(copies=2)
    circulation.borrow(member, book, policy, now=utcnow() - timedelta(days=20))
    stats = circulation.dashboard_stats()
    assert stats["active_loans"] == 1
    assert stats["overdue_loans"] == 1
    assert stats["members"] == 1
    assert stats["popular"][0][0].id == book.id
    assert [loan.book_id for loan in circulation.overdue_loans()] == [book.id]
