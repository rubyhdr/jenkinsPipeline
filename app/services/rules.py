"""Pure library business rules. No Flask or database dependencies, so they are easy to unit test."""
import math
from dataclasses import dataclass
from datetime import datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal


@dataclass(frozen=True)
class LoanPolicy:
    loan_period_days: int = 14
    max_active_loans: int = 5
    max_renewals: int = 1
    fee_per_day: float = 0.50
    fee_cap: float = 20.00

    @classmethod
    def from_config(cls, config):
        return cls(
            loan_period_days=config.get("LOAN_PERIOD_DAYS", cls.loan_period_days),
            max_active_loans=config.get("MAX_ACTIVE_LOANS", cls.max_active_loans),
            max_renewals=config.get("MAX_RENEWALS", cls.max_renewals),
            fee_per_day=config.get("LATE_FEE_PER_DAY", cls.fee_per_day),
            fee_cap=config.get("LATE_FEE_CAP", cls.fee_cap),
        )


def due_date(start: datetime, policy: LoanPolicy) -> datetime:
    return start + timedelta(days=policy.loan_period_days)


def days_overdue(due_at: datetime, at: datetime) -> int:
    """Whole days late, counting any part of a day as a full day."""
    if at <= due_at:
        return 0
    return math.ceil((at - due_at).total_seconds() / 86400)


def late_fee(due_at: datetime, returned_at: datetime, policy: LoanPolicy) -> Decimal:
    days = days_overdue(due_at, returned_at)
    fee = min(Decimal(str(policy.fee_per_day)) * days, Decimal(str(policy.fee_cap)))
    return fee.quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)


def can_borrow(active_loans: int, has_overdue: bool, policy: LoanPolicy):
    """Return (allowed, reason)."""
    if has_overdue:
        return False, "Return your overdue books before borrowing more."
    if active_loans >= policy.max_active_loans:
        return False, f"You already have the maximum of {policy.max_active_loans} books on loan."
    return True, ""


def can_renew(renewals: int, is_overdue: bool, others_waiting: bool, policy: LoanPolicy):
    """Return (allowed, reason)."""
    if is_overdue:
        return False, "Overdue loans cannot be renewed."
    if renewals >= policy.max_renewals:
        return False, "This loan has already been renewed the maximum number of times."
    if others_waiting:
        return False, "Another member is waiting for this book."
    return True, ""


def is_valid_isbn(isbn: str) -> bool:
    """Validate an ISBN-10 or ISBN-13 checksum (hyphens and spaces are ignored)."""
    digits = isbn.replace("-", "").replace(" ", "").upper()
    if len(digits) == 10:
        if not digits[:9].isdigit() or not (digits[9].isdigit() or digits[9] == "X"):
            return False
        total = sum((10 - i) * int(c) for i, c in enumerate(digits[:9]))
        total += 10 if digits[9] == "X" else int(digits[9])
        return total % 11 == 0
    if len(digits) == 13 and digits.isdigit():
        total = sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(digits))
        return total % 10 == 0
    return False


def normalise_isbn(isbn: str) -> str:
    return isbn.replace("-", "").replace(" ", "").upper()
