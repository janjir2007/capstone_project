"""Migration 012 (task 9.15a-3): odometer_readings.reviewed_at for the «Шалгах» list.

Throwaway schema with schema.sql + the 100% synthetic sample data + migrations 001–011, then 012.
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

UP = (SQL_DIR / "migrations" / "012_reading_reviewed.up.sql").read_text(encoding="utf-8")
DOWN = (SQL_DIR / "migrations" / "012_reading_reviewed.down.sql").read_text(encoding="utf-8")
READING = ("INSERT INTO odometer_readings (vehicle_id, service_id, unit, value, reading_date, source, status, "
           "flag_reason) VALUES (1, 3, 'km', 261000, '2026-09-01', 'messenger', 'flagged', 'plate_mismatch')")


@pytest.fixture
def pg_011() -> Iterator[psycopg.Connection]:
    """State before 012: schema + sample data + 001–011."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m012_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(conn)
    for v in ("001", "002", "003", "004", "005", "006", "007", "008", "009", "010", "011"):
        M.apply_one(conn, migrations[v])
    yield conn
    conn.rollback()
    conn.close()


def test_runner_applies_012_after_011(pg_011: psycopg.Connection) -> None:
    done = {r[0] for r in pg_011.execute("SELECT version FROM schema_migrations")}
    assert [m.version for m in M.find_migrations() if m.version not in done][0] == "012"
    M.apply_one(pg_011, {m.version: m for m in M.find_migrations()}["012"])
    assert "reviewed_at" in columns(pg_011, "odometer_readings")


def test_up_down_up_keeps_readings(pg_011: psycopg.Connection) -> None:
    pg_011.execute(READING)
    before = pg_011.execute("SELECT count(*) FROM odometer_readings").fetchone()[0]
    pg_011.execute(UP)
    assert pg_011.execute("SELECT count(*) FROM odometer_readings WHERE reviewed_at IS NULL").fetchone()[0] == before
    pg_011.execute("UPDATE odometer_readings SET reviewed_at = now() WHERE source = 'messenger'")
    pg_011.execute(DOWN)
    assert "reviewed_at" not in columns(pg_011, "odometer_readings")
    assert pg_011.execute("SELECT count(*) FROM odometer_readings").fetchone()[0] == before
    pg_011.execute(UP)
    assert "reviewed_at" in columns(pg_011, "odometer_readings")
