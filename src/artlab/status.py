"""Payment status of an Artlab receipt (bill) and of our service record (task 9.6b-2).

Rules (PM-approved 9.6b plan + review):
- a payment whose `type` is a credit type (ARTLAB_CREDIT_PAY_TYPES, default LOAN «Зээл») makes the
  bill Төлөөгүй; the amount due is the CREDIT part only (PM 6(a): mixed cash + LOAN bills exist)
- otherwise, any payment = Төлсөн
- no payment at all = Тодорхойгүй (we cannot tell)
- Төлсөн (дараа) = a later bank transfer paid the credit part: set by src/artlab/transfers.py
  (stub until Artlab sends an acc-txn sample)

A service rolls up its linked bills (many bills -> one service, PM §4). No linked bill = Тодорхойгүй.
"""

from __future__ import annotations

import os
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Any

PAID = "paid"
UNPAID = "unpaid"
PAID_LATER = "paid_later"
UNKNOWN = "unknown"
STATUSES = (PAID, UNPAID, PAID_LATER, UNKNOWN)  # same 4 values as the CHECK in migration 008

LABELS_MN = {
    PAID: "Төлсөн",
    UNPAID: "Төлөөгүй",
    PAID_LATER: "Төлсөн (дараа)",
    UNKNOWN: "Тодорхойгүй",
}

DEFAULT_CREDIT_PAY_TYPES = ("LOAN",)  # «Зээл», seen on the test DB (docs/artlab_api_notes.md §8c)


def credit_pay_types(env: Mapping[str, str] | None = None) -> frozenset[str]:
    """ARTLAB_CREDIT_PAY_TYPES from the environment (comma list), default LOAN."""
    raw = (env if env is not None else os.environ).get("ARTLAB_CREDIT_PAY_TYPES", "")
    types = {t.strip().upper() for t in raw.split(",") if t.strip()}
    return frozenset(types or DEFAULT_CREDIT_PAY_TYPES)


@dataclass(frozen=True)
class PaymentSplit:
    """A bill's payments split into paid-now and on-credit amounts."""

    paid_now: float  # sum of non-credit payment amounts (change NOT subtracted: needs verification)
    credit_amount: float  # sum of credit-type payment amounts = what is still owed
    n_payments: int


def split_payments(payments: Sequence[Mapping[str, Any]] | None,
                   credit_types: frozenset[str]) -> PaymentSplit:
    """Sum the payments of one bill by kind. Unknown / missing amounts count as 0."""
    paid_now = credit = 0.0
    rows = list(payments or [])
    for pay in rows:
        amount = _money(pay.get("amount"))
        if str(pay.get("type", "")).upper() in credit_types:
            credit += amount
        else:
            paid_now += amount
    return PaymentSplit(paid_now=paid_now, credit_amount=credit, n_payments=len(rows))


def bill_status(split: PaymentSplit) -> str:
    """Төлөөгүй if any credit part, Төлсөн if paid some other way, else Тодорхойгүй."""
    if split.credit_amount > 0:
        return UNPAID
    if split.n_payments > 0:
        return PAID
    return UNKNOWN


def service_status(bill_statuses: Iterable[str]) -> str:
    """One status for a service from all bills linked to it.

    no bill -> Тодорхойгүй; any unpaid -> Төлөөгүй; any unknown -> Тодорхойгүй;
    any paid later -> Төлсөн (дараа); else Төлсөн.
    """
    statuses = set(bill_statuses)
    if not statuses:
        return UNKNOWN
    for status in (UNPAID, UNKNOWN, PAID_LATER):
        if status in statuses:
            return status
    return PAID


def _money(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0
