"""Later bank transfers -> «Төлсөн (дараа)» (task 9.6b-2: STUB).

STATUS: NOT IMPLEMENTED. The row fields of POST /report/acc-txn are unknown: the only test account
we have (127000000001) returns no rows (docs/artlab_api_notes.md §8c). This module is finished
when Artlab sends an account code with transactions (PM: "finished when Artlab sends a sample").
Until then both functions raise NotImplementedError, so nothing can mark a bill as paid later
by accident.

Approved rule to implement (PM 9.6b plan §6 + review):
- source: acc-txn rows of the bank account codes in ARTLAB_BANK_ACCOUNTS (incoming money only)
- from each transfer description: plates + phones via src/artlab/extract.py; the text is dropped
- an UNPAID bill becomes PAID_LATER when an unused transfer has
    txn_date >= bill_date, the same plate or phone, and amount >= the bill's CREDIT amount (6(a))
- oldest unpaid bill first; one transfer pays at most one bill (UNIQUE artlab_bills.paid_by_txn)
- one lump-sum transfer for several trucks is NOT split: those bills stay unpaid in v1 (6(b))
- txn_key = Artlab's row id if the report has one, else a hash of
    account + date + amount + description (so re-runs do not create duplicates)

Open, from the 9.6b-1 probe: a wrong account code also returns 200 with an empty list, so the
sync must flag "0 transfers for N days" in sync_runs instead of trusting an empty result.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date
from typing import Any

from src.artlab.bills import ArtlabBill

_PENDING = "acc-txn row fields unknown until Artlab sends a sample (docs/artlab_api_notes.md §8c)"


@dataclass(frozen=True)
class Transfer:
    """One incoming bank transfer as stored in artlab_transfers (migration 008)."""

    txn_key: str
    txn_date: date
    account_code: str
    amount: float
    plates: tuple[str, ...]
    phones: tuple[str, ...]


def parse_transfers(report: Any, account_code: str) -> list[Transfer]:
    """acc-txn response -> transfers. STUB: raises until the row fields are known."""
    raise NotImplementedError(_PENDING)


def pay_later(unpaid: Sequence[ArtlabBill], transfers: Sequence[Transfer]) -> dict[int, str]:
    """{artlab_id: txn_key} for unpaid bills settled by a later transfer. STUB: raises."""
    raise NotImplementedError(_PENDING)
