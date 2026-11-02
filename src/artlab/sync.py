"""Artlab -> our database sync (task 9.6b-3). Reads Artlab, writes ONLY our own tables.

    python -m src.artlab.sync --kind bills     # every 30 min, 07:00-22:00 UB (PM 9.6b §3)
    python -m src.artlab.sync --kind acc_txn   # every 2 h
    python -m src.artlab.sync --kind nightly   # 02:30 UB: re-check unpaid + unlinked bills
    python -m src.artlab.sync --kind bills --as-of 2026-08-10   # as if today were that day

On the server systemd starts these (deploy/systemd/ocp-artlab-*); NOT installed yet: the real
Artlab connection waits for the accounting OK (D-114). Until then it runs against the Artlab
TEST account into the LOCAL Docker database only.

Every run writes a sync_runs row (counts only; error = exception class name). The log holds
counts, dates and account codes; never a description, plate, phone, token or password.
Exit code 0 = ok, 1 = the run failed (systemd shows the unit as failed).

Settings (.env file, then environment variables, which win):
  ARTLAB_URL, ARTLAB_USER, ARTLAB_PASS    Artlab login (src/artlab/client.load_env)
  POSTGRES_* or DATABASE_URL              our database (same as the API)
  ARTLAB_CREDIT_PAY_TYPES  = LOAN         payment types that mean "on credit"
  ARTLAB_BANK_ACCOUNTS     = (empty)      comma list of account codes for acc-txn
  ARTLAB_SYNC_DAYS         = 3            bills run: today and the days before
  ARTLAB_ACC_TXN_DAYS      = 2            acc_txn run: today and the day before
  ARTLAB_UNPAID_LOOKBACK_DAYS = 90        nightly run: how far back unpaid bills are re-checked
  ARTLAB_ZERO_ROW_WARN_RUNS   = 12        warn when an account had 0 rows this many runs in a row
                                          (12 x 2 h = one day; a wrong code also returns 0 rows)
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import psycopg

from src.api.clock import today_ulaanbaatar
from src.api.config import load_settings
from src.artlab.bills import ArtlabBill, parse_bill
from src.artlab.client import ArtlabClient, ArtlabError, artlab_settings, as_list, load_env
from src.artlab.matching import Match, ServiceCandidate, match_bill
from src.artlab.status import credit_pay_types
from src.artlab.transfers import parse_transfers

log = logging.getLogger("artlab.sync")

KINDS = ("bills", "acc_txn", "nightly")


# ---------------------------------------------------------------- settings


@dataclass(frozen=True)
class SyncConfig:
    """Sync settings; see the module docstring for the environment names."""

    credit_types: frozenset[str]
    bank_accounts: tuple[str, ...]
    sync_days: int = 3
    acc_txn_days: int = 2
    unpaid_lookback_days: int = 90
    zero_row_warn_runs: int = 12


def _positive_int(env: Mapping[str, str], name: str, default: int) -> int:
    raw = env.get(name, "").strip()
    if not raw:
        return default
    if not raw.isdigit() or int(raw) < 1:
        raise ArtlabError(f"{name} must be a whole number >= 1")
    return int(raw)


def sync_config(env: Mapping[str, str] | None = None) -> SyncConfig:
    """Read and check the sync settings. Bad values -> ArtlabError naming the setting."""
    env = os.environ if env is None else env
    accounts = tuple(a.strip() for a in env.get("ARTLAB_BANK_ACCOUNTS", "").split(",") if a.strip())
    if not all(a.isdigit() and len(a) <= 20 for a in accounts):
        raise ArtlabError("ARTLAB_BANK_ACCOUNTS must be account codes (digits), comma-separated")
    return SyncConfig(
        credit_types=credit_pay_types(env),
        bank_accounts=accounts,
        sync_days=_positive_int(env, "ARTLAB_SYNC_DAYS", 3),
        acc_txn_days=_positive_int(env, "ARTLAB_ACC_TXN_DAYS", 2),
        unpaid_lookback_days=_positive_int(env, "ARTLAB_UNPAID_LOOKBACK_DAYS", 90),
        zero_row_warn_runs=_positive_int(env, "ARTLAB_ZERO_ROW_WARN_RUNS", 12),
    )


# ---------------------------------------------------------------- database (our tables only)


def start_run(conn: psycopg.Connection, kind: str, account: str | None = None) -> int:
    """New sync_runs row (committed at once, so a crashed run stays visible as unfinished)."""
    with conn.transaction():
        row = conn.execute(
            "INSERT INTO sync_runs (kind, account_code) VALUES (%s, %s) RETURNING id", (kind, account)
        ).fetchone()
    assert row is not None
    return int(row[0])


def finish_run(conn: psycopg.Connection, run_id: int, ok: bool, bills: int = 0,
               transfers: int = 0, error: BaseException | None = None) -> None:
    """Close a sync_runs row. Only the exception CLASS is stored, never its message."""
    with conn.transaction():
        conn.execute(
            "UPDATE sync_runs SET finished_at = now(), ok = %s, bills_seen = %s, "
            "transfers_seen = %s, error_class = %s WHERE id = %s",
            (ok, bills, transfers, type(error).__name__ if error else None, run_id),
        )


def load_candidates(conn: psycopg.Connection, first: date, last: date) -> list[ServiceCandidate]:
    """Services dated first..last with the truck's plate and the driver's phone."""
    rows = conn.execute(
        "SELECT s.id, s.service_date, v.plate_normalized, s.driver_phone "
        "FROM service_records s JOIN vehicles v ON v.id = s.vehicle_id "
        "WHERE s.service_date BETWEEN %s AND %s",
        (first, last),
    ).fetchall()
    return [ServiceCandidate(r[0], r[1], r[2], r[3]) for r in rows]


# Re-syncing a bill refreshes everything, except that a bill already settled by a later
# transfer («Төлсөн (дараа)») stays settled while Artlab still shows it as on credit.
UPSERT_BILL = """
INSERT INTO artlab_bills (artlab_id, bill_date, bill_type, bill_status, total_gross, paid_now,
    credit_amount, plates, phones, service_id, match_confidence, match_note, payment_status)
VALUES (%s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s, %s)
ON CONFLICT (artlab_id) DO UPDATE SET
    bill_date = EXCLUDED.bill_date, bill_type = EXCLUDED.bill_type,
    bill_status = EXCLUDED.bill_status, total_gross = EXCLUDED.total_gross,
    paid_now = EXCLUDED.paid_now, credit_amount = EXCLUDED.credit_amount,
    plates = EXCLUDED.plates, phones = EXCLUDED.phones, service_id = EXCLUDED.service_id,
    match_confidence = EXCLUDED.match_confidence, match_note = EXCLUDED.match_note,
    payment_status = CASE
        WHEN artlab_bills.payment_status = 'paid_later' AND EXCLUDED.payment_status = 'unpaid'
        THEN 'paid_later' ELSE EXCLUDED.payment_status END,
    paid_by_txn = CASE
        WHEN artlab_bills.payment_status = 'paid_later' AND EXCLUDED.payment_status = 'unpaid'
        THEN artlab_bills.paid_by_txn ELSE NULL END,
    synced_at = now()
"""


def upsert_bills(conn: psycopg.Connection, matched: Sequence[tuple[ArtlabBill, Match]]) -> None:
    """Write all bills of one run in ONE transaction (all or nothing)."""
    with conn.transaction():
        for bill, m in matched:
            conn.execute(UPSERT_BILL, (
                bill.artlab_id, bill.bill_date, bill.bill_type, bill.bill_status, bill.total_gross,
                bill.paid_now, bill.credit_amount, list(bill.plates), list(bill.phones),
                m.service_id, m.confidence, m.note, bill.payment_status,
            ))


def oldest_unpaid(conn: psycopg.Connection) -> date | None:
    row = conn.execute("SELECT min(bill_date) FROM artlab_bills WHERE payment_status = 'unpaid'").fetchone()
    return row[0] if row else None


def zero_row_streak(conn: psycopg.Connection, account: str, runs: int) -> bool:
    """True if the last `runs` finished acc-txn runs for `account` were all ok with 0 rows."""
    rows = conn.execute(
        "SELECT ok, transfers_seen FROM sync_runs WHERE kind IN ('acc_txn', 'nightly') "
        "AND account_code = %s AND finished_at IS NOT NULL ORDER BY started_at DESC, id DESC LIMIT %s",
        (account, runs),
    ).fetchall()
    return len(rows) == runs and all(ok and seen == 0 for ok, seen in rows)


# ---------------------------------------------------------------- steps


def match_all(conn: psycopg.Connection, bills: Sequence[ArtlabBill]) -> list[tuple[ArtlabBill, Match]]:
    """Match every bill against the services around its date (one query for the whole run)."""
    if not bills:
        return []
    first = min(b.bill_date for b in bills) - timedelta(days=1)
    last = max(b.bill_date for b in bills) + timedelta(days=1)
    candidates = load_candidates(conn, first, last)
    return [(b, match_bill(b.bill_date, b.plates, b.phones, candidates)) for b in bills]


def sync_bills(client: ArtlabClient, conn: psycopg.Connection, cfg: SyncConfig,
               first: date, last: date) -> int:
    """Fetch bills first..last, keep completed sales, match, upsert. Returns sales written."""
    rows, truncated = client.fetch_all(
        "/pos/bills", {"withDtl": "1", "from": first.isoformat(), "to": last.isoformat()}
    )
    if truncated:
        log.warning("bills %s..%s: page cap reached, some bills were not read", first, last)
    bills: list[ArtlabBill] = []
    bad = 0
    for raw in rows:
        try:
            bill = parse_bill(raw, cfg.credit_types)
        except ValueError:
            bad += 1
            continue
        if bill is not None:
            bills.append(bill)
    if bad:
        log.warning("bills %s..%s: %d rows without a valid id / date skipped", first, last, bad)
    matched = match_all(conn, bills)
    upsert_bills(conn, matched)
    linked = sum(m.service_id is not None for _, m in matched)
    log.info("bills %s..%s: %d read, %d sales, %d linked, %d unpaid",
             first, last, len(rows), len(bills), linked,
             sum(b.payment_status == "unpaid" for b in bills))
    return len(bills)


def rematch_unlinked(conn: psycopg.Connection, since: date) -> int:
    """Re-try stored bills without a link (a service may have been entered after the receipt)."""
    rows = conn.execute(
        "SELECT artlab_id, bill_date, plates, phones FROM artlab_bills "
        "WHERE service_id IS NULL AND bill_date >= %s", (since,)
    ).fetchall()
    if not rows:
        return 0
    candidates = load_candidates(conn, min(r[1] for r in rows) - timedelta(days=1),
                                 max(r[1] for r in rows) + timedelta(days=1))
    linked = 0
    with conn.transaction():
        for artlab_id, bill_date, plates, phones in rows:
            m = match_bill(bill_date, plates, phones, candidates)
            conn.execute(
                "UPDATE artlab_bills SET service_id = %s, match_confidence = %s, match_note = %s "
                "WHERE artlab_id = %s", (m.service_id, m.confidence, m.note, artlab_id),
            )
            linked += m.service_id is not None
    log.info("re-match since %s: %d unlinked bills, %d now linked", since, len(rows), linked)
    return linked


def sync_acc_txn(client: ArtlabClient, conn: psycopg.Connection, cfg: SyncConfig,
                 first: date, last: date, kind: str = "acc_txn") -> int:
    """One acc-txn report per bank account; one sync_runs row each. Returns total rows seen.

    Transfers are only COUNTED until parse_transfers() is implemented (Artlab sample pending).
    After each account: warn if it returned 0 rows `zero_row_warn_runs` runs in a row.
    """
    if not cfg.bank_accounts:
        log.warning("acc-txn: ARTLAB_BANK_ACCOUNTS is empty, nothing to read")
        return 0
    total = 0
    failed: BaseException | None = None
    for account in cfg.bank_accounts:
        run_id = start_run(conn, kind, account)
        try:
            status, _, data = client.acc_txn([account], first.isoformat(), last.isoformat())
            if status != 200:
                raise ArtlabError(f"acc-txn HTTP {status}")
            n_rows = len(as_list(data))  # shape seen: {"value": [...], "success": true}
            try:
                parse_transfers(data, account)
            except NotImplementedError:
                log.info("acc-txn %s: %d rows counted; transfer parsing waits for an Artlab sample",
                         account, n_rows)
            finish_run(conn, run_id, True, transfers=n_rows)
            total += n_rows
        except Exception as err:  # one bad account must not hide the others
            finish_run(conn, run_id, False, error=err)
            log.error("acc-txn %s: failed (%s)", account, type(err).__name__)
            failed = err
            continue
        if zero_row_streak(conn, account, cfg.zero_row_warn_runs):
            log.warning("acc-txn %s: 0 rows in the last %d runs; check ARTLAB_BANK_ACCOUNTS "
                        "(a wrong account code also returns 0 rows)", account, cfg.zero_row_warn_runs)
    if failed is not None:
        raise failed
    return total


# ---------------------------------------------------------------- runs


def run(kind: str, client: ArtlabClient, conn: psycopg.Connection, cfg: SyncConfig,
        today: date) -> None:
    """One sync run of `kind`. Raises on failure (the sync_runs row then says ok = false)."""
    if kind not in KINDS:
        raise ValueError(f"kind must be one of {KINDS}")
    if kind == "acc_txn":  # per-account rows are written inside
        sync_acc_txn(client, conn, cfg, today - timedelta(days=cfg.acc_txn_days - 1), today)
        return
    run_id = start_run(conn, kind)
    bills = transfers = 0
    try:
        if kind == "bills":
            bills = sync_bills(client, conn, cfg, today - timedelta(days=cfg.sync_days - 1), today)
        else:  # nightly: back to the oldest unpaid bill, at most the lookback, at least sync_days
            floor = today - timedelta(days=cfg.unpaid_lookback_days)
            first = min(oldest_unpaid(conn) or today, today - timedelta(days=cfg.sync_days - 1))
            first = max(first, floor)
            bills = sync_bills(client, conn, cfg, first, today)
            rematch_unlinked(conn, floor)
            transfers = sync_acc_txn(client, conn, cfg, first, today, kind="nightly")
    except Exception as err:
        finish_run(conn, run_id, False, bills, transfers, err)
        raise
    finish_run(conn, run_id, True, bills, transfers)


def connect() -> psycopg.Connection:
    """Autocommit connection to our database (same settings as the API and scripts/migrate)."""
    url = load_settings().database_url.replace("postgresql+psycopg://", "postgresql://", 1)
    return psycopg.connect(url, autocommit=True, connect_timeout=10)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Artlab -> database sync (read-only on Artlab).")
    parser.add_argument("--kind", choices=KINDS, required=True)
    parser.add_argument("--env", default=".env", help=".env file with ARTLAB_* (env variables win)")
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="run as if today were YYYY-MM-DD (local tests / backfill; default: today in UB)")
    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    try:
        creds = load_env(Path(args.env))
        cfg = sync_config(artlab_settings(Path(args.env)))
        client = ArtlabClient(creds["ARTLAB_URL"])
        client.login(creds["ARTLAB_USER"], creds["ARTLAB_PASS"])
        with connect() as conn:
            run(args.kind, client, conn, cfg, args.as_of or today_ulaanbaatar())
    except ArtlabError as err:  # our own messages: safe to print (no secrets, no data)
        log.error("sync %s failed: %s", args.kind, err)
        return 1
    except Exception as err:  # anything else: class only (a DB error may quote row values)
        log.error("sync %s failed: %s", args.kind, type(err).__name__)
        return 1
    log.info("sync %s ok", args.kind)
    return 0


if __name__ == "__main__":
    sys.exit(main())
