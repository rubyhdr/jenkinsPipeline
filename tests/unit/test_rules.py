from datetime import datetime, timedelta
from decimal import Decimal

import pytest

from app.services import rules
from app.services.rules import LoanPolicy

pytestmark = pytest.mark.unit

POLICY = LoanPolicy(loan_period_days=14, max_active_loans=5, max_renewals=1,
                    fee_per_day=0.5, fee_cap=20.0)
DUE = datetime(2026, 3, 1, 12, 0)


def test_due_date_adds_loan_period():
    assert rules.due_date(datetime(2026, 1, 1), POLICY) == datetime(2026, 1, 15)


@pytest.mark.parametrize("returned, expected", [
    (DUE - timedelta(days=1), 0),
    (DUE, 0),
    (DUE + timedelta(minutes=5), 1),
    (DUE + timedelta(days=1), 1),
    (DUE + timedelta(days=3, hours=1), 4),
])
def test_days_overdue(returned, expected):
    assert rules.days_overdue(DUE, returned) == expected


@pytest.mark.parametrize("days_late, fee", [(0, "0.00"), (1, "0.50"), (7, "3.50"), (40, "20.00")])
def test_late_fee_is_per_day_and_capped(days_late, fee):
    assert rules.late_fee(DUE, DUE + timedelta(days=days_late), POLICY) == Decimal(fee)


def test_can_borrow_allows_under_limit():
    assert rules.can_borrow(4, False, POLICY) == (True, "")


def test_can_borrow_blocks_at_limit():
    allowed, reason = rules.can_borrow(5, False, POLICY)
    assert not allowed and "maximum of 5" in reason


def test_can_borrow_blocks_when_overdue():
    allowed, reason = rules.can_borrow(0, True, POLICY)
    assert not allowed and "overdue" in reason


@pytest.mark.parametrize("renewals, overdue, waiting, allowed", [
    (0, False, False, True),
    (1, False, False, False),
    (0, True, False, False),
    (0, False, True, False),
])
def test_can_renew(renewals, overdue, waiting, allowed):
    assert rules.can_renew(renewals, overdue, waiting, POLICY)[0] is allowed


@pytest.mark.parametrize("isbn", ["9780141439518", "978-0-14-143951-8", "0-8044-2957-X", "0306406152"])
def test_valid_isbns(isbn):
    assert rules.is_valid_isbn(isbn)


@pytest.mark.parametrize("isbn", ["9780141439519", "12345", "030640615X", "abcdefghij", "97801414395AA"])
def test_invalid_isbns(isbn):
    assert not rules.is_valid_isbn(isbn)


def test_normalise_isbn():
    assert rules.normalise_isbn("0-8044-2957-x") == "080442957X"


def test_policy_from_config_uses_defaults_for_missing_keys():
    policy = LoanPolicy.from_config({"LOAN_PERIOD_DAYS": 7})
    assert policy.loan_period_days == 7
    assert policy.max_active_loans == LoanPolicy.max_active_loans
