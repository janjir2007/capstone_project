"""Task 9.16b: the manual payment rule (src/api/payments.py manual_status / manual_payment), the
PAYMENT_DUE_HOURS setting and the price fields of the request bodies. No database needed.

Examples = docs/plans/9.16b_plan.md §2.2 (UB = Ulaanbaatar, UTC+8, no daylight saving).
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from pydantic import ValidationError

from src.api.config import DEFAULT_PAYMENT_DUE_HOURS, ConfigError, payment_due_hours
from src.api.payments import manual_payment, manual_status
from src.api.schemas import PaymentIn, PriceIn, ServiceCreate
from tests.test_api_data import service_body

UB = timezone(timedelta(hours=8))
SAVED = datetime(2026, 11, 12, 10, 0, tzinfo=UB)


def ub(day: int, hour: int, minute: int = 0) -> datetime:
    return datetime(2026, 11, day, hour, minute, tzinfo=UB)


def status(now: datetime, *, created: datetime = SAVED, price: int | None = 80000, paid: datetime | None = None,
           marked: datetime | None = None, tracked: bool = True, hours: int = 24) -> str | None:
    return manual_status(tracked=tracked, price_mnt=price, paid_at=paid, marked_unpaid_at=marked,
                         created_at=created, now=now, due_hours=hours)


# ---------------------------------------------------------------- the rule (plan §2.2)


@pytest.mark.parametrize(("now", "kwargs", "expected"), [
    (ub(12, 18), {}, "pending"),                                             # 1: 8 h after saving
    (ub(13, 9, 59), {}, "pending"),                                          # 2: 23 h 59 m
    (ub(13, 10), {}, "unpaid"),                                              # 3: exactly 24 h -> «Авлага»
    (ub(14, 8), {"price": None}, "unpaid"),                                  # 4: no price, still «Авлага»
    (ub(13, 8), {"created": ub(12, 23, 30)}, "pending"),                     # 5: new UB day, only 8.5 h
    (ub(12, 10, 6), {"marked": ub(12, 10, 5)}, "unpaid"),                    # 6: «Авлага» pressed, no wait
    (ub(21, 9), {"marked": ub(12, 10, 5), "paid": ub(20, 15)}, "paid"),      # 7: Авлага -> Төлсөн
    (ub(12, 12), {"paid": ub(12, 10, 10)}, "paid"),                          # «Төлсөн» before the 24 h
])
def test_rule_examples(now: datetime, kwargs: dict, expected: str) -> None:
    assert status(now, **kwargs) == expected


def test_undo_paid_goes_back_to_the_rule() -> None:
    """8 + 9: «Буцаах» clears paid_at; the 24 h still count from saving."""
    assert status(ub(12, 12), paid=None) == "pending"
    assert status(ub(13, 11), paid=None) == "unpaid"


def test_saved_before_9_16b_has_no_status() -> None:
    """10: payment_tracked false -> None, whatever the clicks or the time."""
    for kwargs in ({}, {"paid": ub(12, 11)}, {"marked": ub(12, 11)}, {"price": 0}):
        assert status(ub(30, 10), tracked=False, **kwargs) is None


def test_timezone_does_not_matter() -> None:
    """11: the same moments in UTC and in UB give the same answer (server + DB run in UTC)."""
    saved_utc = SAVED.astimezone(timezone.utc)                     # 11-12 02:00 UTC
    assert status(saved_utc + timedelta(hours=24), created=SAVED) == "unpaid"
    assert status(ub(13, 10), created=saved_utc) == "unpaid"
    assert status(saved_utc + timedelta(hours=23, minutes=59), created=SAVED) == "pending"


def test_naive_database_time_is_read_as_utc() -> None:
    """SQLite test engines may hand back a naive created_at: read as UTC, not as local time."""
    naive_utc = SAVED.astimezone(timezone.utc).replace(tzinfo=None)
    assert status(ub(13, 9, 59), created=naive_utc) == "pending"
    assert status(ub(13, 10), created=naive_utc) == "unpaid"


def test_price_zero_is_paid_at_once() -> None:
    """PM Q3: price 0 = nothing owed -> «Төлсөн», even after 24 h or with «Авлага» pressed."""
    assert status(ub(12, 10, 1), price=0) == "paid"
    assert status(ub(20, 10), price=0, marked=ub(12, 11)) == "paid"


@pytest.mark.parametrize(("hours", "now", "expected"), [(1, ub(12, 11), "unpaid"), (1, ub(12, 10, 59), "pending"),
                                                         (72, ub(15, 9, 59), "pending"), (72, ub(15, 10), "unpaid")])
def test_due_hours_setting_is_used(hours: int, now: datetime, expected: str) -> None:
    assert status(now, hours=hours) == expected


# ---------------------------------------------------------------- amount + «since»


def record(**fields) -> SimpleNamespace:
    base = dict(payment_tracked=True, price_mnt=80000, paid_at=None, marked_unpaid_at=None, created_at=SAVED)
    return SimpleNamespace(**{**base, **fields})


def test_amount_and_since_only_while_unpaid() -> None:
    pending = manual_payment(record(), ub(12, 12), 24)
    assert (pending.payment_status, pending.amount_due, pending.unpaid_since) == ("pending", None, None)
    unpaid = manual_payment(record(), ub(14, 9), 24)
    assert (unpaid.payment_status, unpaid.amount_due, unpaid.unpaid_since) == ("unpaid", 80000, ub(13, 10))
    assert manual_payment(record(paid_at=ub(14, 9)), ub(14, 10), 24).amount_due is None
    assert manual_payment(record(price_mnt=None), ub(14, 9), 24).amount_due is None  # «Үнэ оруулаагүй»


def test_since_is_the_earlier_of_pressed_and_24_h() -> None:
    assert manual_payment(record(marked_unpaid_at=ub(12, 10, 5)), ub(12, 11), 24).unpaid_since == ub(12, 10, 5)
    # pressed late (day 3): it was «Авлага» since 24 h after saving already
    assert manual_payment(record(marked_unpaid_at=ub(15, 9)), ub(15, 10), 24).unpaid_since == ub(13, 10)


# ---------------------------------------------------------------- PAYMENT_DUE_HOURS


def test_due_hours_default_and_value() -> None:
    assert payment_due_hours({}) == DEFAULT_PAYMENT_DUE_HOURS == 24
    assert payment_due_hours({"PAYMENT_DUE_HOURS": " 48 "}) == 48


@pytest.mark.parametrize("raw", ["0", "-1", "abc", "1.5", "24h"])
def test_due_hours_rejects_bad_values(raw: str) -> None:
    with pytest.raises(ConfigError, match="PAYMENT_DUE_HOURS"):
        payment_due_hours({"PAYMENT_DUE_HOURS": raw})


def test_bad_due_hours_stops_the_api(monkeypatch: pytest.MonkeyPatch) -> None:
    from fastapi.testclient import TestClient
    from sqlalchemy import create_engine
    from sqlalchemy.pool import StaticPool

    from src.api.main import create_app
    monkeypatch.setenv("PAYMENT_DUE_HOURS", "zero")
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool))
    with pytest.raises(ConfigError, match="PAYMENT_DUE_HOURS"):
        with TestClient(app):
            pass


# ---------------------------------------------------------------- request bodies


@pytest.mark.parametrize("price", [None, 0, 85000, 100_000_000])
def test_service_price_accepted(price: int | None) -> None:
    assert ServiceCreate.model_validate(service_body(price_mnt=price)).price_mnt == price


@pytest.mark.parametrize("price", [-1, 1.5, 85000.0, "85000", 100_000_001, True])
def test_service_price_rejected(price) -> None:
    with pytest.raises(ValidationError):
        ServiceCreate.model_validate(service_body(price_mnt=price))


def test_price_body_needs_the_field_and_allows_null() -> None:
    assert PriceIn.model_validate({"price_mnt": None}).price_mnt is None
    for bad in ({}, {"price_mnt": -5}, {"price_mnt": 2.5}, {"price_mnt": 1, "x": 1}):
        with pytest.raises(ValidationError):
            PriceIn.model_validate(bad)


def test_payment_body_actions() -> None:
    assert {PaymentIn.model_validate({"action": a}).action for a in ("paid", "unpaid", "undo_paid")} == \
        {"paid", "unpaid", "undo_paid"}
    for bad in ({"action": "pending"}, {}, {"action": "paid", "by": "Ари"}):
        with pytest.raises(ValidationError):
            PaymentIn.model_validate(bad)
