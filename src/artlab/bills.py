"""One Artlab POS bill (GET /pos/bills?withDtl=1 row) -> the fields we store (task 9.6b-2).

Kept: id, date, type, status, totals, payment split, plates + phones found in the description.
Dropped: the description text, `num` (not unique on the test DB), line items, agent names,
terminal (privacy: store only what matching needs, PM 9.6b). Field names: docs/artlab_api_notes.md §5.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.artlab.extract import extract
from src.artlab.status import bill_status, split_payments

SALE_TYPES = frozenset({"SALE_VAT", "SALE"})  # SALE = «Зарлага /Тооцоотой/», where LOAN was seen
COMPLETE = "COMPLETE"


@dataclass(frozen=True)
class ArtlabBill:
    """A sale receipt as stored in artlab_bills (migration 008), before matching."""

    artlab_id: int
    bill_date: date
    bill_type: str
    bill_status: str
    total_gross: float | None  # missing on bills without line items (2 of 55 on the test DB)
    paid_now: float
    credit_amount: float
    plates: tuple[str, ...]
    phones: tuple[str, ...]
    payment_status: str


def is_sale(raw: Mapping[str, Any]) -> bool:
    """Only completed sales are synced; returns, purchases, moves, open/cancelled bills are not."""
    return raw.get("type") in SALE_TYPES and raw.get("status") == COMPLETE


def parse_bill(raw: Mapping[str, Any], credit_types: frozenset[str]) -> ArtlabBill | None:
    """Artlab bill dict -> ArtlabBill, or None if it is not a completed sale.

    Raises ValueError if `id` or `billDate` is missing / malformed (Artlab data error: the sync
    counts it and goes on).
    """
    if not is_sale(raw):
        return None
    try:
        artlab_id = int(raw["id"])
        bill_date = date.fromisoformat(str(raw["billDate"])[:10])
    except (KeyError, TypeError, ValueError) as err:
        raise ValueError(f"bill without valid id / billDate: {type(err).__name__}") from None
    split = split_payments(raw.get("payments"), credit_types)
    found = extract(raw.get("description"))  # the text goes no further than this line
    gross = raw.get("totalGross")
    return ArtlabBill(
        artlab_id=artlab_id,
        bill_date=bill_date,
        bill_type=str(raw["type"]),
        bill_status=str(raw["status"]),
        total_gross=float(gross) if isinstance(gross, (int, float)) else None,
        paid_now=split.paid_now,
        credit_amount=split.credit_amount,
        plates=found.plates,
        phones=found.phones,
        payment_status=bill_status(split),
    )
