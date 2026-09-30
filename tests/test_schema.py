"""Schema tests (Task 1.1): schema.sql loads, sample rows load, example queries
return the expected results, and the key constraints reject bad data.

Needs a running PostgreSQL (``docker compose up -d db``). If none is reachable
the whole module is SKIPPED, so CI stays green until CI gets its own Postgres
service (task 6.2).

Isolation: everything runs inside a throwaway schema in ONE transaction that
is rolled back at the end, so the dev database is never changed.
"""

import os
import re
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path
from typing import Any

import psycopg
import pytest
from psycopg.rows import dict_row

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "src" / "data"


def database_url() -> str:
    """Build the connection URL from DATABASE_URL or POSTGRES_* env variables.

    Defaults match the dev defaults in docker-compose.yml. A SQLAlchemy-style
    URL (postgresql+psycopg://) is converted to the plain form psycopg expects.
    """
    url = os.environ.get("DATABASE_URL")
    if url:
        return url.replace("postgresql+psycopg://", "postgresql://", 1)
    user = os.environ.get("POSTGRES_USER", "oil")
    password = os.environ.get("POSTGRES_PASSWORD", "oil_dev_password")
    host = os.environ.get("POSTGRES_HOST", "localhost")
    port = os.environ.get("POSTGRES_PORT", "5432")
    name = os.environ.get("POSTGRES_DB", "oil_change")
    return f"postgresql://{user}:{password}@{host}:{port}/{name}"


def load_named_queries(path: Path) -> dict[str, str]:
    """Split a SQL file into {name: sql} using '-- name: <name>' marker lines."""
    parts = re.split(r"^-- name:\s*(\w+)\s*$", path.read_text(encoding="utf-8"), flags=re.MULTILINE)
    # parts = [header, name1, sql1, name2, sql2, ...]
    return {name: sql.strip() for name, sql in zip(parts[1::2], parts[2::2])}


@pytest.fixture(scope="module")
def conn() -> Iterator[psycopg.Connection]:
    """Connection with schema + sample data loaded into a temporary schema."""
    try:
        connection = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable (run `docker compose up -d db`): {exc}")

    schema = f"test_{uuid.uuid4().hex[:8]}"
    with connection.cursor() as cur:
        cur.execute(f"CREATE SCHEMA {schema}")
        cur.execute(f"SET search_path TO {schema}")
        cur.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
        cur.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    yield connection
    connection.rollback()  # removes the temporary schema and everything in it
    connection.close()


def fetch_all(conn: psycopg.Connection, sql: str, params: tuple[Any, ...] = ()) -> list[dict[str, Any]]:
    """Run a query and return rows as dicts."""
    with conn.cursor(row_factory=dict_row) as cur:
        cur.execute(sql, params)
        return cur.fetchall()


def assert_rejected(conn: psycopg.Connection, error: type[Exception], sql: str) -> None:
    """Assert that a statement fails with the given error.

    conn.transaction() inside an open transaction is a SAVEPOINT: the failed
    statement is undone without losing the loaded sample data.
    """
    with pytest.raises(error):
        with conn.transaction():
            conn.execute(sql)


QUERIES = load_named_queries(SQL_DIR / "example_queries.sql")


# --------------------------------------------------------------------------
# Example queries on the sample rows
# --------------------------------------------------------------------------

def test_example_file_has_all_queries() -> None:
    """The brief's three queries (plus segment counts) are present."""
    assert set(QUERIES) >= {
        "lookup_by_plate", "lookup_by_phone", "service_count_per_vehicle", "segment_per_vehicle",
    }


def test_lookup_by_plate(conn: psycopg.Connection) -> None:
    """Plate 1234УБА -> vehicle 1, its last service pre-fills the form."""
    rows = fetch_all(conn, QUERIES["lookup_by_plate"])
    assert len(rows) == 1
    row = rows[0]
    assert row["vehicle_id"] == 1
    assert row["service_count"] == 3
    assert row["last_service_date"] == date(2026, 8, 10)
    assert row["last_oil_grade"] == "15W-40"
    assert row["last_driver_phone"] == "99110002"  # driver changed, D-004


def test_lookup_by_phone(conn: psycopg.Connection) -> None:
    """Phone 99110002 drove vehicles 1 and 6 -> both found, newest first."""
    rows = fetch_all(conn, QUERIES["lookup_by_phone"])
    assert [r["vehicle_id"] for r in rows] == [6, 1]


def test_service_count_per_vehicle(conn: psycopg.Connection) -> None:
    rows = fetch_all(conn, QUERIES["service_count_per_vehicle"])
    assert {r["vehicle_id"]: r["service_count"] for r in rows} == {1: 3, 2: 2, 3: 1, 4: 1, 5: 2, 6: 2}


def test_segment_per_vehicle(conn: psycopg.Connection) -> None:
    rows = fetch_all(conn, QUERIES["segment_per_vehicle"])
    assert {r["vehicle_id"]: r["segment"] for r in rows} == {
        1: "loyal",
        2: "returning",
        3: "new",
        4: "at_risk",    # predicted 2026-07-15, never came back
        5: "returning",  # mine truck, engine hours only
        6: "returning",  # prediction passed, but it DID come back on 2026-09-01
    }


def test_segment_counts(conn: psycopg.Connection) -> None:
    rows = fetch_all(conn, QUERIES["segment_counts"])
    assert {r["segment"]: r["vehicles"] for r in rows} == {
        "at_risk": 1, "loyal": 1, "new": 1, "returning": 3,
    }


@pytest.mark.parametrize(
    ("as_of", "vehicle_id", "expected"),
    [
        (date(2026, 7, 22), 4, "new"),      # 07-15 + 7 = 07-22: grace not over yet
        (date(2026, 7, 23), 4, "at_risk"),  # first day after the grace period
        (date(2026, 8, 28), 6, "at_risk"),  # overdue before it came back...
        (date(2026, 9, 1), 6, "returning"),  # ...and not at risk once it did
        (date(2026, 7, 20), 1, "returning"),  # only 2 services existed by then
    ],
)
def test_segments_depend_on_as_of(conn: psycopg.Connection, as_of: date, vehicle_id: int, expected: str) -> None:
    """Segments are computed for any date, only from data that existed then."""
    rows = fetch_all(conn, "SELECT segment FROM vehicle_segments(%s) WHERE vehicle_id = %s", (as_of, vehicle_id))
    assert rows == [{"segment": expected}]


def test_vehicle_without_service_by_as_of_is_excluded(conn: psycopg.Connection) -> None:
    """Vehicle 3's first service is 2026-09-20, so it has no segment on 2026-09-01."""
    rows = fetch_all(conn, "SELECT vehicle_id FROM vehicle_segments(%s)", (date(2026, 9, 1),))
    assert 3 not in {r["vehicle_id"] for r in rows}


# --------------------------------------------------------------------------
# Constraints reject bad data
# --------------------------------------------------------------------------

NEW_SERVICE = (
    "INSERT INTO service_records (vehicle_id, service_date, odometer_km, engine_hours, "
    "oil_grade, liters, route, driver_phone) VALUES "
)


def test_new_rows_get_ids_after_sample_ids(conn: psycopg.Connection) -> None:
    """setval() in sample_data.sql moved the id counter: a normal insert works."""
    with conn.transaction(force_rollback=True):
        rows = fetch_all(conn, "INSERT INTO companies (name) VALUES ('Шинэ ХХК') RETURNING id")
        assert rows[0]["id"] == 5


@pytest.mark.parametrize("phone", ["9911000", "+97699110001", "9911 0001", "99-110001"])
def test_bad_phone_rejected(conn: psycopg.Connection, phone: str) -> None:
    assert_rejected(conn, psycopg.errors.CheckViolation,
                    NEW_SERVICE + f"(1, '2026-09-30', 1, NULL, '15W-40', 30, 'ub_city', '{phone}')")


def test_service_needs_km_or_engine_hours(conn: psycopg.Connection) -> None:
    assert_rejected(conn, psycopg.errors.CheckViolation,
                    NEW_SERVICE + "(1, '2026-09-30', NULL, NULL, '15W-40', 30, 'ub_city', '99110001')")


def test_unknown_route_rejected(conn: psycopg.Connection) -> None:
    assert_rejected(conn, psycopg.errors.CheckViolation,
                    NEW_SERVICE + "(1, '2026-09-30', 1, NULL, '15W-40', 30, 'darkhan', '99110001')")


def test_plate_vehicle_needs_normalized_plate(conn: psycopg.Connection) -> None:
    assert_rejected(conn, psycopg.errors.CheckViolation,
                    "INSERT INTO vehicles (company_id, identifier_type, identifier) VALUES (1, 'plate', '1111 УБА')")


def test_duplicate_plate_rejected(conn: psycopg.Connection) -> None:
    assert_rejected(conn, psycopg.errors.UniqueViolation,
                    "INSERT INTO vehicles (company_id, identifier_type, identifier, plate_normalized) "
                    "VALUES (2, 'plate', '1234УБА', '1234УБА')")


def test_fleet_no_unique_only_within_company(conn: psycopg.Connection) -> None:
    """'HT-12' already exists in company 4: rejected there, allowed in company 1."""
    assert_rejected(conn, psycopg.errors.UniqueViolation,
                    "INSERT INTO vehicles (company_id, identifier_type, identifier) VALUES (4, 'fleet_no', 'HT-12')")
    with conn.transaction(force_rollback=True):
        conn.execute("INSERT INTO vehicles (company_id, identifier_type, identifier) VALUES (1, 'fleet_no', 'HT-12')")


def test_prediction_service_must_be_same_vehicle(conn: psycopg.Connection) -> None:
    """Service 7 belongs to vehicle 4, so a prediction for vehicle 1 cannot use it."""
    assert_rejected(conn, psycopg.errors.ForeignKeyViolation,
                    "INSERT INTO predictions (vehicle_id, based_on_service_id, predicted_days, predicted_date, "
                    "model_version) VALUES (1, 7, 60, '2026-12-01', 'x')")


def test_sent_reminder_needs_sent_at(conn: psycopg.Connection) -> None:
    assert_rejected(conn, psycopg.errors.CheckViolation,
                    "INSERT INTO reminders (vehicle_id, prediction_id, phone, message_text, status) "
                    "VALUES (1, 1, '99110002', 'test', 'sent')")
