"""Payment status from the Artlab copy in our database (task 9.6b-4). Read only.

The sync (src/artlab/sync.py) fills artlab_bills + sync_runs; this module only reads them.
Plain SQL (sqlalchemy.text) instead of ORM models: the tables use Postgres arrays, and the
tests' SQLite engines build Base.metadata, which must stay portable.

Rules (PM-approved 9.6b plan; one implementation: src/artlab/status.py):
- "connected" = at least one successful bills / nightly sync run exists. Before that every
  payment field is null: the dashboard shows nothing instead of «Тодорхойгүй» everywhere.
- a service's status rolls up all bills linked to it (service_status); no bill = unknown
- amount_due = credit amount of its bills that are still unpaid
- match_confidence = the WEAKEST link among its bills (both > plate > phone)
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import date

from sqlalchemy import text
from sqlalchemy.orm import Session

from src.artlab.status import UNKNOWN, UNPAID, service_status

_CONFIDENCE_ORDER = ("both", "plate", "phone")  # strongest first


@dataclass(frozen=True)
class ServicePayment:
    """Payment fields of one service (all None when payments are not connected)."""

    payment_status: str | None
    amount_due: float | None
    match_confidence: str | None


NOT_CONNECTED = ServicePayment(None, None, None)
NO_BILL = ServicePayment(UNKNOWN, None, None)


def connected(session: Session) -> bool:
    """True once a bills or nightly sync has succeeded at least once."""
    return bool(session.execute(text(
        "SELECT EXISTS (SELECT 1 FROM sync_runs WHERE ok AND kind IN ('bills', 'nightly'))"
    )).scalar())


def service_payments(session: Session, service_ids: Iterable[int] | None = None) -> dict[int, ServicePayment]:
    """{service_id: ServicePayment} for services with at least one linked bill.

    ``service_ids`` None = every linked service (dashboard search, one query).
    Services missing from the result have no bill: use ``payment_of``.
    """
    sql = ("SELECT service_id, payment_status, credit_amount, match_confidence "
           "FROM artlab_bills WHERE service_id IS NOT NULL")
    params: dict[str, object] = {}
    if service_ids is not None:
        ids = list(service_ids)
        if not ids:
            return {}
        sql += " AND service_id = ANY(:ids)"
        params["ids"] = ids
    bills: dict[int, list[tuple[str, float, str | None]]] = defaultdict(list)
    for sid, status, credit, confidence in session.execute(text(sql), params):
        bills[sid].append((status, float(credit), confidence))
    return {sid: _roll_up(rows) for sid, rows in bills.items()}


def _roll_up(rows: Sequence[tuple[str, float, str | None]]) -> ServicePayment:
    status = service_status(s for s, _, _ in rows)
    due = sum(credit for s, credit, _ in rows if s == UNPAID)
    known = [c for _, _, c in rows if c in _CONFIDENCE_ORDER]
    weakest = max(known, key=_CONFIDENCE_ORDER.index) if known else None
    return ServicePayment(status, due if status == UNPAID else None, weakest)


def payment_of(service_id: int, payments: dict[int, ServicePayment], is_connected: bool) -> ServicePayment:
    """The payment fields of one service, with the not-connected / no-bill rules applied."""
    if not is_connected:
        return NOT_CONNECTED
    return payments.get(service_id, NO_BILL)


# ---------------------------------------------------------------- unpaid list


@dataclass(frozen=True)
class UnpaidBill:
    """One unpaid receipt with the truck it is linked to (if any)."""

    artlab_id: int
    bill_date: date
    days_waiting: int
    amount_due: float
    total_gross: float | None
    match_confidence: str | None
    match_note: str | None
    service_id: int | None
    vehicle_id: int | None
    identifier: str | None
    company_name: str | None
    plates: list[str]
    phones: list[str]


def unpaid_bills(session: Session, today: date) -> list[UnpaidBill]:
    """Every unpaid receipt, oldest first (the longest wait on top)."""
    rows = session.execute(text(
        "SELECT b.artlab_id, b.bill_date, b.credit_amount, b.total_gross, b.match_confidence, b.match_note, "
        "       b.service_id, v.id, v.identifier, c.name, b.plates, b.phones "
        "FROM artlab_bills b "
        "LEFT JOIN service_records s ON s.id = b.service_id "
        "LEFT JOIN vehicles v ON v.id = s.vehicle_id "
        "LEFT JOIN companies c ON c.id = v.company_id "
        "WHERE b.payment_status = 'unpaid' ORDER BY b.bill_date, b.artlab_id"
    )).all()
    return [UnpaidBill(
        artlab_id=r[0], bill_date=r[1], days_waiting=(today - r[1]).days, amount_due=float(r[2]),
        total_gross=None if r[3] is None else float(r[3]), match_confidence=r[4], match_note=r[5],
        service_id=r[6], vehicle_id=r[7], identifier=r[8], company_name=r[9],
        plates=list(r[10] or []), phones=list(r[11] or []),
    ) for r in rows]


# ---------------------------------------------------------------- sync status


@dataclass(frozen=True)
class RunInfo:
    """The latest run of one kind (or of one acc-txn account), and the latest successful one."""

    kind: str
    account_code: str | None
    started_at: object  # datetime with offset
    finished_at: object | None
    ok: bool | None
    bills_seen: int
    transfers_seen: int
    error_class: str | None
    last_ok_at: object | None
    zero_row_streak: int | None  # acc-txn accounts only: finished ok runs in a row with 0 rows


# Account rows (acc-txn calls, also those made inside a nightly run) group by account under
# "acc_txn"; the other rows group by kind (bills, nightly).
_GROUP = "CASE WHEN account_code IS NULL THEN kind ELSE 'acc_txn' END"


def sync_status(session: Session, streak_window: int = 50) -> list[RunInfo]:
    """Latest run per kind (bills, nightly) and per acc-txn account. Empty before the first run."""
    latest = session.execute(text(
        f"SELECT DISTINCT ON ({_GROUP}, account_code) {_GROUP}, account_code, started_at, finished_at, ok, "
        "       bills_seen, transfers_seen, error_class "
        f"FROM sync_runs ORDER BY {_GROUP}, account_code, started_at DESC, id DESC"
    )).all()
    last_ok = {(r[0], r[1]): r[2] for r in session.execute(text(
        f"SELECT {_GROUP}, account_code, max(finished_at) FROM sync_runs WHERE ok GROUP BY 1, 2"
    ))}
    return [RunInfo(kind=r[0], account_code=r[1], started_at=r[2], finished_at=r[3], ok=r[4],
                    bills_seen=r[5], transfers_seen=r[6], error_class=r[7],
                    last_ok_at=last_ok.get((r[0], r[1])),
                    zero_row_streak=_zero_streak(session, r[1], streak_window) if r[1] else None)
            for r in latest]


def _zero_streak(session: Session, account: str, window: int) -> int:
    """Finished acc-txn runs (incl. nightly per-account rows) in a row, newest first, ok with 0 rows."""
    rows = session.execute(text(
        "SELECT ok, transfers_seen FROM sync_runs WHERE account_code = :a AND finished_at IS NOT NULL "
        "ORDER BY started_at DESC, id DESC LIMIT :n"
    ), {"a": account, "n": window}).all()
    streak = 0
    for ok, seen in rows:
        if not (ok and seen == 0):
            break
        streak += 1
    return streak
