"""Tests for task 9.6b-2: migration 008 (artlab_bills, artlab_transfers, sync_runs).

Checks: UP creates the 3 tables with no free-text / name columns (privacy); every CHECK / UNIQUE /
FK from the PM-approved plan holds; many bills may link one service; deleting a service unlinks
its bills; scripts/migrate.py applies 008 after 007; DOWN drops all 3 and UP works again.

Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED.
Each test runs in a throwaway schema inside a transaction that is rolled back.
All rows are synthetic.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from scripts import migrate as M
from src.artlab.status import STATUSES
from tests.test_migrate import SQL_DIR
from tests.test_schema import database_url

UP = SQL_DIR / "migrations" / "008_artlab.up.sql"
DOWN = SQL_DIR / "migrations" / "008_artlab.down.sql"
TABLES = {"artlab_bills", "artlab_transfers", "sync_runs"}

BILL = ("INSERT INTO artlab_bills (artlab_id, bill_date, bill_type, bill_status, credit_amount, "
        "plates, phones, service_id, match_confidence, match_note, payment_status, paid_by_txn) "
        "VALUES (%s, '2026-10-15', 'SALE_VAT', 'COMPLETE', 0, %s, %s, %s, %s, %s, %s, %s)")
TXN = ("INSERT INTO artlab_transfers (txn_key, txn_date, account_code, amount, phones) "
       "VALUES (%s, '2026-10-20', %s, 80000, %s)")


@pytest.fixture
def pg_007() -> Iterator[psycopg.Connection]:
    """Throwaway schema: schema.sql + sample data + migrations 001–007 (the state before 008)."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m008_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(conn)
    for v in ("001", "002", "003", "004", "005", "006", "007"):
        M.apply_one(conn, migrations[v])
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def pg(pg_007: psycopg.Connection) -> psycopg.Connection:
    """State after 008."""
    pg_007.execute(UP.read_text(encoding="utf-8"))
    return pg_007


def tables(conn: psycopg.Connection) -> set[str]:
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    return {r[0] for r in conn.execute(sql).fetchall()}


def columns(conn: psycopg.Connection, table: str) -> set[str]:
    sql = ("SELECT column_name FROM information_schema.columns "
           "WHERE table_schema = current_schema() AND table_name = %s")
    return {r[0] for r in conn.execute(sql, (table,)).fetchall()}


def a_service(conn: psycopg.Connection) -> int:
    """A fresh synthetic service on sample vehicle 1 (nothing else points to it)."""
    sql = ("INSERT INTO service_records (vehicle_id, service_date, odometer_km, oil_grade, liters) "
           "VALUES (1, '2026-10-15', 100000, '15W-40', 30) RETURNING id")
    return conn.execute(sql).fetchone()[0]


def bill(conn, artlab_id, *, plates=(), phones=(), service_id=None, confidence=None, note="none",
         status="paid", txn=None) -> None:
    conn.execute(BILL, (artlab_id, list(plates), list(phones), service_id, confidence, note, status, txn))


def test_runner_applies_008_after_007(pg_007: psycopg.Connection) -> None:
    pending = [m.version for m in M.find_migrations()
               if m.version not in {r[0] for r in pg_007.execute("SELECT version FROM schema_migrations")}]
    assert pending[0] == "008"  # 009+ follow (task 9.6b-3)
    M.apply_one(pg_007, {m.version: m for m in M.find_migrations()}["008"])
    assert TABLES <= tables(pg_007)


def test_no_free_text_or_personal_columns(pg: psycopg.Connection) -> None:
    forbidden = {"description", "descr", "num", "name", "driver_name", "customer", "text", "dtls"}
    for table in TABLES:
        assert not columns(pg, table) & forbidden, table


def test_payment_status_check_matches_python_statuses(pg: psycopg.Connection) -> None:
    for i, status in enumerate(s for s in STATUSES if s != "paid_later"):
        bill(pg, 100 + i, status=status)
    pg.execute(TXN, ("t1", "127000000001", []))
    bill(pg, 200, status="paid_later", txn="t1")


def test_many_bills_link_one_service(pg: psycopg.Connection) -> None:
    sid = a_service(pg)
    bill(pg, 1, plates=["1234УБА"], service_id=sid, confidence="plate", note=None)
    bill(pg, 2, phones=["99112233"], service_id=sid, confidence="phone", note=None, status="unpaid")
    n = pg.execute("SELECT count(*) FROM artlab_bills WHERE service_id = %s", (sid,)).fetchone()[0]
    assert n == 2


def test_constraints(pg: psycopg.Connection) -> None:
    sid = a_service(pg)
    pg.execute(TXN, ("t1", "127000000001", ["99112233"]))
    bill(pg, 1, status="paid_later", txn="t1")
    cases = [
        (dict(artlab_id=2, status="late"), psycopg.errors.CheckViolation),                # unknown status
        (dict(artlab_id=2, status="paid_later"), psycopg.errors.CheckViolation),          # no transfer named
        (dict(artlab_id=2, status="paid", txn="t1"), psycopg.errors.CheckViolation),      # txn without paid_later
        (dict(artlab_id=2, status="paid_later", txn="t1"), psycopg.errors.UniqueViolation),  # txn pays 1 bill
        (dict(artlab_id=2, status="paid_later", txn="nope"), psycopg.errors.ForeignKeyViolation),
        (dict(artlab_id=2, phones=["9911"]), psycopg.errors.CheckViolation),              # not 8 digits
        (dict(artlab_id=2, phones=["99112233", "x"]), psycopg.errors.CheckViolation),
        (dict(artlab_id=2, service_id=sid, confidence=None, note=None), psycopg.errors.CheckViolation),
        (dict(artlab_id=2, service_id=sid, confidence="plate", note="none"), psycopg.errors.CheckViolation),
        (dict(artlab_id=2, confidence="guess"), psycopg.errors.CheckViolation),
        (dict(artlab_id=2, note="maybe"), psycopg.errors.CheckViolation),
        (dict(artlab_id=2, service_id=999999, confidence="both", note=None), psycopg.errors.ForeignKeyViolation),
        (dict(artlab_id=1), psycopg.errors.UniqueViolation),                               # same Artlab id
    ]
    for kwargs, error in cases:
        pg.execute("SAVEPOINT s")
        with pytest.raises(error):
            bill(pg, **kwargs)
        pg.execute("ROLLBACK TO SAVEPOINT s")
    for sql, args, error in [
        ("INSERT INTO artlab_bills (artlab_id, bill_date, bill_type, bill_status, payment_status) "
         "VALUES (9, '2026-10-15', 'PURCHASE', 'COMPLETE', 'paid')", None, psycopg.errors.CheckViolation),
        ("INSERT INTO artlab_bills (artlab_id, bill_date, bill_type, bill_status, payment_status, credit_amount) "
         "VALUES (9, '2026-10-15', 'SALE', 'COMPLETE', 'unpaid', -1)", None, psycopg.errors.CheckViolation),
        (TXN, ("t2", "12-7", []), psycopg.errors.CheckViolation),                          # account digits only
        ("INSERT INTO sync_runs (kind) VALUES ('hourly')", None, psycopg.errors.CheckViolation),
        ("INSERT INTO sync_runs (kind, finished_at) VALUES ('bills', now())", None, psycopg.errors.CheckViolation),
    ]:
        pg.execute("SAVEPOINT s")
        with pytest.raises(error):
            pg.execute(sql, args)
        pg.execute("ROLLBACK TO SAVEPOINT s")


def test_deleting_a_service_unlinks_its_bills(pg: psycopg.Connection) -> None:
    sid = a_service(pg)
    bill(pg, 1, plates=["1234УБА"], service_id=sid, confidence="both", note=None)
    pg.execute("DELETE FROM service_records WHERE id = %s", (sid,))
    assert pg.execute("SELECT service_id FROM artlab_bills WHERE artlab_id = 1").fetchone() == (None,)


def test_sync_run_row(pg: psycopg.Connection) -> None:
    rid = pg.execute("INSERT INTO sync_runs (kind) VALUES ('bills') RETURNING id").fetchone()[0]
    pg.execute("UPDATE sync_runs SET finished_at = now(), ok = true, bills_seen = 12 WHERE id = %s", (rid,))
    assert pg.execute("SELECT ok, bills_seen, transfers_seen FROM sync_runs").fetchone() == (True, 12, 0)


def test_artlab_ids_above_2_pow_53_fit(pg: psycopg.Connection) -> None:
    big = 104333577398533121  # id size seen on the test DB (paymethods, notes §8c)
    bill(pg, big)
    assert pg.execute("SELECT artlab_id FROM artlab_bills").fetchone() == (big,)


def test_down_then_up_again(pg: psycopg.Connection) -> None:
    sid = a_service(pg)
    bill(pg, 1, service_id=sid, confidence="plate", note=None)
    pg.execute(DOWN.read_text(encoding="utf-8"))
    assert not TABLES & tables(pg)
    assert pg.execute("SELECT count(*) FROM service_records WHERE id = %s", (sid,)).fetchone() == (1,)
    pg.execute(UP.read_text(encoding="utf-8"))
    assert TABLES <= tables(pg)
