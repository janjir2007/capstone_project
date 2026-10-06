"""Migration 001 tests (Task 1.1b): destinations table + destination columns on
service_records.

Checks: UP runs on a clean DB and on a DB with existing records (which stay
unchanged), seed rows match docs/synthetic_rules.md §1, new constraints work,
DOWN restores the exact old schema, and UP works again after DOWN.

Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED,
like tests/test_schema.py (CI gets Postgres in task 6.2).

Isolation: every test runs in its own throwaway schema inside a savepoint that
is rolled back, so the dev database is never changed.
"""

import re
import uuid
from collections.abc import Iterator
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

from tests.test_schema import database_url

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "src" / "data"
UP = SQL_DIR / "migrations" / "001_destinations.up.sql"
DOWN = SQL_DIR / "migrations" / "001_destinations.down.sql"
RULES = ROOT / "docs" / "synthetic_rules.md"


def run_file(conn: psycopg.Connection, path: Path) -> None:
    """Execute one SQL file on the connection."""
    conn.execute(path.read_text(encoding="utf-8"))


def fetch_all(conn: psycopg.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a query and return rows as dicts."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def columns(conn: psycopg.Connection, table: str) -> list[tuple[str, str, str]]:
    """(name, type, nullable) of every column of a table in the current schema."""
    rows = fetch_all(
        conn,
        "SELECT column_name, data_type, is_nullable FROM information_schema.columns "
        "WHERE table_schema = current_schema() AND table_name = %s ORDER BY ordinal_position",
        (table,),
    )
    return [(r["column_name"], r["data_type"], r["is_nullable"]) for r in rows]


def constraints(conn: psycopg.Connection, table: str) -> set[tuple[str, str]]:
    """(name, definition) of every constraint on a table in the current schema."""
    rows = fetch_all(
        conn,
        "SELECT conname, pg_get_constraintdef(oid) AS def FROM pg_constraint "
        "WHERE conrelid = to_regclass(%s)",
        (table,),
    )
    return {(r["conname"], r["def"]) for r in rows}


def table_exists(conn: psycopg.Connection, table: str) -> bool:
    """True if the table exists in the current schema."""
    return fetch_all(conn, "SELECT to_regclass(%s) AS t", (table,))[0]["t"] is not None


def old_service_rows(conn: psycopg.Connection) -> list[dict[str, Any]]:
    """All service records, without the two columns the migration adds."""
    rows = fetch_all(
        conn,
        "SELECT to_jsonb(sr) - 'destination_id' - 'destination_raw' AS row "
        "FROM service_records sr ORDER BY id",
    )
    return [r["row"] for r in rows]


def rules_destinations(path: Path) -> dict[str, int]:
    """{destination name: one-way km} for rows of synthetic_rules.md §1 with a km value.

    A km value is written in bold, e.g. ``| 2 | Zamyn-Uud (MN–CN border) | `mn_china` | **656** |``.
    """
    pattern = re.compile(r"^\|\s*\d+\s*\|\s*([^|]+?)\s*\|\s*`\w+`\s*\|\s*\*\*([\d,]+)\*\*", re.MULTILINE)
    return {name: int(km.replace(",", "")) for name, km in pattern.findall(path.read_text(encoding="utf-8"))}


@pytest.fixture(scope="module")
def conn() -> Iterator[psycopg.Connection]:
    """One connection for the module; rolled back at the end."""
    try:
        connection = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable (run `docker compose up -d db`): {exc}")
    yield connection
    connection.rollback()
    connection.close()


@pytest.fixture
def clean_db(conn: psycopg.Connection) -> Iterator[psycopg.Connection]:
    """A fresh schema with schema.sql only (no rows); undone after the test."""
    with conn.transaction(force_rollback=True):
        schema = f"test_{uuid.uuid4().hex[:8]}"
        conn.execute(f"CREATE SCHEMA {schema}")
        conn.execute(f"SET LOCAL search_path TO {schema}")
        run_file(conn, SQL_DIR / "schema.sql")
        yield conn


@pytest.fixture
def sample_db(clean_db: psycopg.Connection) -> psycopg.Connection:
    """clean_db plus the synthetic sample rows (existing records)."""
    run_file(clean_db, SQL_DIR / "sample_data.sql")
    return clean_db


# --------------------------------------------------------------------------
# UP
# --------------------------------------------------------------------------

def test_up_on_clean_db_creates_table_and_columns(clean_db: psycopg.Connection) -> None:
    run_file(clean_db, UP)
    assert table_exists(clean_db, "destinations")
    new_cols = [c for c in columns(clean_db, "service_records") if c[0].startswith("destination")]
    assert new_cols == [("destination_id", "bigint", "YES"), ("destination_raw", "text", "YES")]


def test_seed_rows(clean_db: psycopg.Connection) -> None:
    """7 rows; every route category present; round-trip days still NULL (TO FILL)."""
    run_file(clean_db, UP)
    rows = fetch_all(clean_db, "SELECT * FROM destinations ORDER BY id")
    assert len(rows) == 7
    assert {r["route_category"] for r in rows} == {"ub_city", "mn_china", "mn_russia", "mixed"}
    assert all(r["round_trip_days_min"] is None and r["round_trip_days_max"] is None for r in rows)
    # A km value always has its source link, and the other way round.
    assert all((r["one_way_km"] is None) == (r["source"] is None) for r in rows)


def test_seed_km_match_synthetic_rules(clean_db: psycopg.Connection) -> None:
    """Every km in synthetic_rules.md §1 is in the DB with the same value (no drift)."""
    expected = rules_destinations(RULES)
    assert len(expected) == 5  # Zamyn-Uud, Erenhot, Beijing, Altanbulag, Kyakhta
    run_file(clean_db, UP)
    rows = fetch_all(clean_db, "SELECT name, one_way_km FROM destinations WHERE one_way_km IS NOT NULL")
    assert {r["name"]: r["one_way_km"] for r in rows} == expected


def test_up_keeps_existing_records_unchanged(sample_db: psycopg.Connection) -> None:
    before_rows = old_service_rows(sample_db)
    before_view = fetch_all(sample_db, "SELECT * FROM v_vehicle_service_summary ORDER BY vehicle_id")
    run_file(sample_db, UP)
    assert old_service_rows(sample_db) == before_rows
    assert fetch_all(sample_db, "SELECT * FROM v_vehicle_service_summary ORDER BY vehicle_id") == before_view
    nulls = fetch_all(sample_db, "SELECT count(*) AS n FROM service_records "
                                 "WHERE destination_id IS NULL AND destination_raw IS NULL")
    assert nulls[0]["n"] == len(before_rows)


# --------------------------------------------------------------------------
# New columns and constraints
# --------------------------------------------------------------------------

NEW_SERVICE = (
    "INSERT INTO service_records (vehicle_id, service_date, odometer_km, oil_grade, liters, "
    "destination_id, destination_raw) VALUES "
)


def test_service_with_known_destination(sample_db: psycopg.Connection) -> None:
    run_file(sample_db, UP)
    dest_id = fetch_all(sample_db, "SELECT id FROM destinations WHERE name = 'Beijing'")[0]["id"]
    sample_db.execute(NEW_SERVICE + "(1, '2026-10-06', 260000, '15W-40', 32, %s, NULL)", (dest_id,))
    rows = fetch_all(sample_db, "SELECT d.route_category, d.one_way_km FROM service_records sr "
                                "JOIN destinations d ON d.id = sr.destination_id")
    assert rows == [{"route_category": "mn_china", "one_way_km": 1330}]


def test_service_with_unknown_place_as_raw_text(sample_db: psycopg.Connection) -> None:
    run_file(sample_db, UP)
    sample_db.execute(NEW_SERVICE + "(1, '2026-10-06', 260000, '15W-40', 32, NULL, 'Сайншанд')")


def assert_rejected(conn: psycopg.Connection, error: type[Exception], sql: str) -> None:
    """Assert that a statement fails; the SAVEPOINT keeps the rest of the test data."""
    with pytest.raises(error):
        with conn.transaction():
            conn.execute(sql)


def test_unknown_destination_id_rejected(sample_db: psycopg.Connection) -> None:
    run_file(sample_db, UP)
    assert_rejected(sample_db, psycopg.errors.ForeignKeyViolation,
                    NEW_SERVICE + "(1, '2026-10-06', 260000, '15W-40', 32, 9999, NULL)")


def test_blank_destination_raw_rejected(sample_db: psycopg.Connection) -> None:
    run_file(sample_db, UP)
    assert_rejected(sample_db, psycopg.errors.CheckViolation,
                    NEW_SERVICE + "(1, '2026-10-06', 260000, '15W-40', 32, NULL, '  ')")


@pytest.mark.parametrize(
    ("values", "error"),
    [
        ("('Darkhan', 'darkhan', 220, NULL, NULL)", psycopg.errors.CheckViolation),   # bad category
        ("('Darkhan', 'mixed', 0, NULL, NULL)", psycopg.errors.CheckViolation),       # km must be > 0
        ("('Darkhan', 'mixed', 220, 5, 3)", psycopg.errors.CheckViolation),           # min > max
        ("('Beijing', 'mn_china', 1330, NULL, NULL)", psycopg.errors.UniqueViolation),  # duplicate name
        ("(' ', 'mixed', NULL, NULL, NULL)", psycopg.errors.CheckViolation),          # blank name
    ],
)
def test_bad_destination_rejected(clean_db: psycopg.Connection, values: str, error: type[Exception]) -> None:
    run_file(clean_db, UP)
    assert_rejected(clean_db, error,
                    "INSERT INTO destinations (name, route_category, one_way_km, "
                    f"round_trip_days_min, round_trip_days_max) VALUES {values}")


def test_round_trip_days_can_be_filled_later(clean_db: psycopg.Connection) -> None:
    """When Ari fills TO FILL values, a plain UPDATE works (min = max allowed)."""
    run_file(clean_db, UP)
    clean_db.execute("UPDATE destinations SET round_trip_days_min = 4, round_trip_days_max = 4 "
                     "WHERE name = 'Zamyn-Uud (MN–CN border)'")


# --------------------------------------------------------------------------
# DOWN
# --------------------------------------------------------------------------

def test_down_restores_old_schema(sample_db: psycopg.Connection) -> None:
    before_cols = columns(sample_db, "service_records")
    before_cons = constraints(sample_db, "service_records")
    before_rows = old_service_rows(sample_db)
    run_file(sample_db, UP)
    sample_db.execute("UPDATE service_records SET destination_raw = 'test' WHERE id = 1")
    run_file(sample_db, DOWN)
    assert not table_exists(sample_db, "destinations")
    assert columns(sample_db, "service_records") == before_cols
    assert constraints(sample_db, "service_records") == before_cons
    assert old_service_rows(sample_db) == before_rows


def test_up_down_up_cycle(clean_db: psycopg.Connection) -> None:
    """The migration can be re-applied after being undone."""
    run_file(clean_db, UP)
    run_file(clean_db, DOWN)
    run_file(clean_db, UP)
    assert fetch_all(clean_db, "SELECT count(*) AS n FROM destinations")[0]["n"] == 7
