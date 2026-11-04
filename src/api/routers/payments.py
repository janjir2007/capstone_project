"""Artlab payments, read only (task 9.6b-4).

GET /payments/unpaid       unpaid receipts of the last ARTLAB_UNPAID_LOOKBACK_DAYS days (default 90),
                           oldest first, with the linked truck (if any)
GET /payments/sync-status  latest Artlab sync run per kind and per bank account

The data comes from the sync's copy (artlab_bills, sync_runs); nothing here calls Artlab or
writes. Like every data route, Caddy never makes these public (only /health and /auth/* are):
the UI reaches them inside the server after its login check (D-061, D-117).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from src.api.clock import get_today
from src.api.config import unpaid_lookback_days
from src.api.db import get_session
from src.api.payments import connected, sync_status, unpaid_bills
from src.api.schemas import SyncRunOut, SyncStatusOut, UnpaidBillOut, UnpaidList

router = APIRouter(prefix="/payments", tags=["payments"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


@router.get("/unpaid", response_model=UnpaidList)
def unpaid(
    session: SessionDep,
    today: TodayDep,
    limit: Annotated[int, Query(ge=1, le=1000, description="Rows returned (total / total_due count all)")] = 200,
) -> UnpaidList:
    """Receipts still owed (Төлөөгүй) from the last ARTLAB_UNPAID_LOOKBACK_DAYS days, longest wait first. Linked receipts carry the truck and its
    company; unlinked ones only the plates / phones found in the receipt (match_note says why)."""
    bills = unpaid_bills(session, today, unpaid_lookback_days())  # 9.12-3: older bills are not listed
    items = [UnpaidBillOut(**{**b.__dict__, "artlab_id": str(b.artlab_id)}) for b in bills[:limit]]
    return UnpaidList(connected=connected(session), total=len(bills),
                      total_due=round(sum(b.amount_due for b in bills), 2), items=items)


@router.get("/sync-status", response_model=SyncStatusOut)
def get_sync_status(session: SessionDep) -> SyncStatusOut:
    """When the Artlab sync last ran, and whether it worked: one row per kind (bills, nightly) and
    per acc-txn bank account. Empty list before the first run."""
    runs = [SyncRunOut(**r.__dict__) for r in sync_status(session)]
    return SyncStatusOut(connected=connected(session), runs=runs)
