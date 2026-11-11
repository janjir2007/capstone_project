"""Migration 013 (task 9.16b-2): manual payment columns on service_records.

Throwaway schema with schema.sql + the 100% synthetic sample data + migrations 001–012, then 013.
Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from scripts import migrate as M
from tests.test_migrate import SQL_DIR
from tests.test_migration_010 import columns
from tests.test_schema import database_url

UP = (SQL_DIR / "migrations" / "013_service_payment.up.sql").read_text(encoding="utf-8")
DOWN = (SQL_DIR / "migrations" / "013_service_payment.down.sql").read_text(encoding="utf-8")
NEW_COLUMNS = {"price_mnt", "paid_at", "marked_unpaid_at", "payment_tracked"}
NEW_SERVICE = ("INSERT INTO service_records (vehicle_id, service_date, odometer_km, oil_grade, liters{cols}) "
               "VALUES (1, '2026-11-12', 300000, '15W-40', 30{vals}) RETURNING id")


def insert(conn: psycopg.Connection, **fields: object) -> int:
    cols = "".join(f", {k}" for k in fields)
    vals = "".join(f", %({k})s" for k in fields)
    return conn.execute(NEW_SERVICE.format(cols=cols, vals=vals), fields).fetchone()[0]


@pytest.fixture
def pg_012() -> Iterator[psycopg.Connection]:
    """State before 013: schema + sample data (= services saved before 9.16b) + 001–012."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m013_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(conn)
    for v in ("001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011", "012"):
        M.apply_one(conn, migrations[v])
    yield conn
    conn.rollback()
    conn.close()


def test_runner_applies_013_after_012(pg_012: psycopg.Connection) -> None:
    done = {r[0] for r in pg_012.execute("SELECT version FROM schema_migrations")}
    assert [m.version for m in M.find_migrations() if m.version not in done] == ["013"]
    M.apply_one(pg_012, {m.version: m for m in M.find_migrations()}["013"])
    assert NEW_COLUMNS <= columns(pg_012, "service_records")


def test_existing_rows_untracked_new_rows_tracked(pg_012: psycopg.Connection) -> None:
    """PM Q1: services saved before 013 get payment_tracked = false, every new one true."""
    before = pg_012.execute("SELECT count(*) FROM service_records").fetchone()[0]
    assert before > 0
    pg_012.execute(UP)
    old = pg_012.execute("SELECT count(*) FROM service_records WHERE NOT payment_tracked AND price_mnt IS NULL "
                         "AND paid_at IS NULL AND marked_unpaid_at IS NULL").fetchone()[0]
    assert old == before
    sid = insert(pg_012)
    assert pg_012.execute("SELECT payment_tracked, price_mnt FROM service_records WHERE id = %s",
                          (sid,)).fetchone() == (True, None)


def test_price_check(pg_012: psycopg.Connection) -> None:
    pg_012.execute(UP)
    insert(pg_012, price_mnt=0)
    insert(pg_012, price_mnt=85000)
    with pytest.raises(psycopg.errors.CheckViolation):
        insert(pg_012, price_mnt=-1)


def test_not_paid_index_exists(pg_012: psycopg.Connection) -> None:
    pg_012.execute(UP)
    index = pg_012.execute("SELECT indexdef FROM pg_indexes WHERE indexname = 'service_records_not_paid_idx'"
                           ).fetchone()[0]
    assert "payment_tracked" in index and "paid_at IS NULL" in index


def test_up_down_up_keeps_services(pg_012: psycopg.Connection) -> None:
    pg_012.execute(UP)
    insert(pg_012, price_mnt=60000, paid_at="2026-11-12 10:00+08")
    count = pg_012.execute("SELECT count(*) FROM service_records").fetchone()[0]
    pg_012.execute(DOWN)
    assert not NEW_COLUMNS & columns(pg_012, "service_records")
    assert pg_012.execute("SELECT count(*) FROM service_records").fetchone()[0] == count
    pg_012.execute(UP)  # again: every row (also the one added after the first UP) counts as old
    assert pg_012.execute("SELECT count(*) FROM service_records WHERE payment_tracked").fetchone()[0] == 0
