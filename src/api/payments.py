"""Payment status: manual (task 9.16b) and the Artlab copy in our database (task 9.6b-4).

Task 9.16b (migration 013, plan docs/plans/9.16b_plan.md): Artlab has no sales endpoint (D-139), so
the oil changer marks payment by hand. ``manual_status`` is THE rule, used by every service the API
shows and by GET /payments/receivables:
- payment_tracked false (saved before 9.16b)                     -> None (no status at all)
- paid_at set, or price_mnt = 0 (nothing owed, PM Q3)            -> paid     «Төлсөн»
- «Авлага» pressed (marked_unpaid_at), or saved PAYMENT_DUE_HOURS
  (24) or more hours ago                                          -> unpaid   «Авлага»
- otherwise                                                       -> pending  «Хүлээгдэж байна»
Computed when read from created_at and the current moment (timezone-aware), so there is no timer.
ServiceOut.payment_status now comes from here; the Artlab functions below are kept (unused by
ServiceOut) for when Artlab can fill paid_at.

Artlab part (task 9.6b-4), read only:

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
from datetime import date, datetime, timedelta, timezone

from sqlalchemy import or_, select, text
from sqlalchemy.orm import Session, selectinload

from src.api.models import ServiceRecord, Vehicle

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


def unpaid_bills(session: Session, today: date, lookback_days: int) -> list[UnpaidBill]:
    """Unpaid receipts of the last ``lookback_days`` days (linked or not), oldest first (the
    longest wait on top). Older bills are left out: the sync no longer re-checks them (9.12-3)."""
    rows = session.execute(text(
        "SELECT b.artlab_id, b.bill_date, b.credit_amount, b.total_gross, b.match_confidence, b.match_note, "
        "       b.service_id, v.id, v.identifier, c.name, b.plates, b.phones "
        "FROM artlab_bills b "
        "LEFT JOIN service_records s ON s.id = b.service_id "
        "LEFT JOIN vehicles v ON v.id = s.vehicle_id "
        "LEFT JOIN companies c ON c.id = v.company_id "
        "WHERE b.payment_status = 'unpaid' AND b.bill_date >= :since ORDER BY b.bill_date, b.artlab_id"
    ), {"since": today - timedelta(days=lookback_days)}).all()
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


# ---------------------------------------------------------------- task 9.16b: manual payment

MANUAL_PAID, MANUAL_UNPAID, MANUAL_PENDING = "paid", "unpaid", "pending"


def _aware(moment: datetime) -> datetime:
    """A timezone-aware moment; a naive one (SQLite in some tests) is read as UTC."""
    return moment if moment.tzinfo is not None else moment.replace(tzinfo=timezone.utc)


def manual_status(*, tracked: bool, price_mnt: int | None, paid_at: datetime | None,
                  marked_unpaid_at: datetime | None, created_at: datetime, now: datetime,
                  due_hours: int) -> str | None:
    """The payment status of one service (rule in the module docstring). Exactly ``due_hours`` = unpaid.

    Both moments are timezone-aware, so the server / database timezone (UTC) vs Ulaanbaatar (+08:00)
    does not change the answer: 24 h are 24 h, whatever the calendar day in UB.
    """
    if not tracked:
        return None
    if paid_at is not None or price_mnt == 0:
        return MANUAL_PAID
    if marked_unpaid_at is not None:
        return MANUAL_UNPAID
    if _aware(now) - _aware(created_at) >= timedelta(hours=due_hours):
        return MANUAL_UNPAID
    return MANUAL_PENDING


@dataclass(frozen=True)
class ManualPayment:
    """Payment fields of one service as the API shows them."""

    payment_status: str | None
    amount_due: int | None       # = price_mnt while unpaid (None without a price)
    unpaid_since: datetime | None  # when it became «Авлага» (only while unpaid)


def manual_payment(record: ServiceRecord, now: datetime, due_hours: int) -> ManualPayment:
    """Status, amount owed and «Авлага since» of one saved service."""
    status = manual_status(tracked=record.payment_tracked, price_mnt=record.price_mnt, paid_at=record.paid_at,
                           marked_unpaid_at=record.marked_unpaid_at, created_at=record.created_at, now=now,
                           due_hours=due_hours)
    if status != MANUAL_UNPAID:
        return ManualPayment(status, None, None)
    # The earlier of «Авлага» pressed and the end of the waiting time (pressing it late does not move it).
    since = _aware(record.created_at) + timedelta(hours=due_hours)
    if record.marked_unpaid_at is not None:
        since = min(since, _aware(record.marked_unpaid_at))
    return ManualPayment(status, record.price_mnt, since)


@dataclass(frozen=True)
class TruckReceivable:
    """One truck on the dashboard «Төлбөр» list: its «Авлага» services."""

    vehicle_id: int
    identifier: str
    company_name: str
    services: int
    amount_mnt: int
    services_no_price: int
    oldest_service_date: date
    oldest_unpaid_since: datetime
    driver_phone: str | None  # newest «Авлага» service with a phone; on screen only, never in Excel
    service_ids: list[int]    # oldest first


@dataclass(frozen=True)
class Receivables:
    """GET /payments/receivables: every «Авлага» service, grouped per truck."""

    total_mnt: int
    count: int
    count_no_price: int
    trucks: list[TruckReceivable]


def receivables(session: Session, now: datetime, due_hours: int) -> Receivables:
    """Every tracked «Авлага» service, per truck: biggest amount first, then the oldest debt.

    One query over the not-paid tracked services (partial index of migration 013); the rule itself is
    applied in Python with ``manual_payment``, so it exists only once.
    """
    records = session.scalars(
        select(ServiceRecord)
        .where(ServiceRecord.payment_tracked, ServiceRecord.paid_at.is_(None),
               or_(ServiceRecord.price_mnt.is_(None), ServiceRecord.price_mnt != 0))
        .options(selectinload(ServiceRecord.vehicle).selectinload(Vehicle.company))
        .order_by(ServiceRecord.created_at, ServiceRecord.id)
    ).all()
    per_truck: dict[int, list[tuple[ServiceRecord, ManualPayment]]] = defaultdict(list)
    for record in records:
        pay = manual_payment(record, now, due_hours)
        if pay.payment_status == MANUAL_UNPAID:
            per_truck[record.vehicle_id].append((record, pay))
    trucks = []
    for vehicle_id, rows in per_truck.items():
        vehicle = rows[0][0].vehicle
        phones = [r.driver_phone for r, _ in reversed(rows) if r.driver_phone]
        trucks.append(TruckReceivable(
            vehicle_id=vehicle_id, identifier=vehicle.identifier, company_name=vehicle.company.name,
            services=len(rows), amount_mnt=sum(r.price_mnt or 0 for r, _ in rows),
            services_no_price=sum(1 for r, _ in rows if r.price_mnt is None),
            oldest_service_date=min(r.service_date for r, _ in rows),
            oldest_unpaid_since=min(p.unpaid_since for _, p in rows if p.unpaid_since is not None),
            driver_phone=phones[0] if phones else None,
            service_ids=[r.id for r, _ in rows],
        ))
    trucks.sort(key=lambda t: (-t.amount_mnt, t.oldest_unpaid_since, t.vehicle_id))
    return Receivables(total_mnt=sum(t.amount_mnt for t in trucks), count=sum(t.services for t in trucks),
                       count_no_price=sum(t.services_no_price for t in trucks), trucks=trucks)
