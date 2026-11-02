"""Link an Artlab receipt (bill) to one of our service records (task 9.6b-2).

Rule (PM-accepted 9.6a + 9.6b review):
1. plate: services whose truck plate is in the receipt, service_date within ±1 day of billDate
2. else phone: services whose driver_phone is in the receipt, same window
3. else no link («Тодорхойгүй»); never guessed

Result per bill:
- confidence "both"  : exactly one service matches plate AND phone
- confidence "plate" : the plate gives exactly one service (phone absent, ambiguous, or the same)
- confidence "phone" : no plate match, the phone gives exactly one service
- note "conflict"    : plate -> one service, phone -> exactly one OTHER service (a person checks)
- note "multiple"    : several services fit and plate+phone together do not single one out
- note "none"        : nothing fits

Several bills may link to the same service (oil + filters on separate receipts, PM §4).
The plate is primary, so an ambiguous phone does not block a unique plate match.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import date, timedelta

WINDOW_DAYS = 1  # PM-approved: service_date within billDate ± 1 day

BOTH, PLATE, PHONE = "both", "plate", "phone"
CONFLICT, MULTIPLE, NONE = "conflict", "multiple", "none"


@dataclass(frozen=True)
class ServiceCandidate:
    """The few columns of one service record that matching reads."""

    service_id: int
    service_date: date
    plate_normalized: str | None  # NULL for fleet-number trucks
    driver_phone: str | None


@dataclass(frozen=True)
class Match:
    """service_id + confidence when linked; otherwise note says why not (never both)."""

    service_id: int | None
    confidence: str | None
    note: str | None


def in_window(bill_date: date, service_date: date, days: int = WINDOW_DAYS) -> bool:
    """True if the service is at most `days` days before or after the receipt."""
    return abs((service_date - bill_date).days) <= days


def window(bill_date: date, days: int = WINDOW_DAYS) -> tuple[date, date]:
    """(first, last) service_date to load from the database for one receipt date."""
    return bill_date - timedelta(days=days), bill_date + timedelta(days=days)


def match_bill(
    bill_date: date,
    plates: Iterable[str],
    phones: Iterable[str],
    candidates: Iterable[ServiceCandidate],
) -> Match:
    """Apply the rule above to one receipt. `candidates` may hold more than the window."""
    plate_set, phone_set = set(plates), set(phones)
    near = [c for c in candidates if in_window(bill_date, c.service_date)]
    by_plate = {c.service_id for c in near if c.plate_normalized and c.plate_normalized in plate_set}
    by_phone = {c.service_id for c in near if c.driver_phone and c.driver_phone in phone_set}

    both = by_plate & by_phone
    if len(both) == 1:
        return Match(next(iter(both)), BOTH, None)
    if len(by_plate) == 1:
        (sid,) = by_plate
        if len(by_phone) == 1:  # exactly one OTHER service by phone (same one was caught above)
            return Match(None, None, CONFLICT)
        return Match(sid, PLATE, None)
    if len(by_plate) > 1:
        return Match(None, None, MULTIPLE)
    if len(by_phone) == 1:
        return Match(next(iter(by_phone)), PHONE, None)
    if len(by_phone) > 1:
        return Match(None, None, MULTIPLE)
    return Match(None, None, NONE)
