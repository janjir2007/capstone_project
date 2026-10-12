"""Migration 002 tests (Task 1.1c, D-040): destinations.name_mn.

Checks: UP adds the column with the 5 Mongolian labels from the brief and
leaves everything else as it was; blank and duplicate labels are refused;
UP stops if a destination it expects is missing; DOWN restores the exact
old table; UP works again after DOWN.

Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED.
Every test runs in its own throwaway schema inside a rolled-back transaction.
"""

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from tests.test_migration_001_destinations import (
    SQL_DIR,
    columns,
    constraints,
    fetch_all,
    run_file,
)
from tests.test_schema import database_url

UP_001 = SQL_DIR / "migrations" / "001_destinations.up.sql"
UP = SQL_DIR / "migrations" / "002_destinations_name_mn.up.sql"
DOWN = SQL_DIR / "migrations" / "002_destinations_name_mn.down.sql"

EXPECTED_LABELS = {
    "Ulaanbaatar city (local work)": None,
    "Zamyn-Uud (MN–CN border)": "Замын-Үүд",
    "Erenhot (CN side of border)": "Эрээн",
    "Beijing": "Бээжин",
    "Altanbulag (MN–RU border)": "Алтанбулаг",
    "Kyakhta (RU side of border)": "Хиагт",
    "Other / several / unknown": None,
}


@pytest.fixture
def db_001() -> Iterator[psycopg.Connection]:
    """A fresh schema with schema.sql + migration 001 + sample rows; rolled back after the test."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable (run `docker compose up -d db`): {exc}")
    schema = f"test_m002_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    for path in (SQL_DIR / "schema.sql", UP_001, SQL_DIR / "sample_data.sql"):
        run_file(conn, path)
    yield conn
    conn.rollback()
    conn.close()


def labels(conn: psycopg.Connection) -> dict[str, str | None]:
    """{name: name_mn} of every destination."""
    return {r["name"]: r["name_mn"] for r in fetch_all(conn, "SELECT name, name_mn FROM destinations ORDER BY id")}


def test_up_adds_the_five_labels(db_001: psycopg.Connection) -> None:
    run_file(db_001, UP)
    assert labels(db_001) == EXPECTED_LABELS
    assert ("name_mn", "text", "YES") in columns(db_001, "destinations")


def test_up_changes_nothing_else(db_001: psycopg.Connection) -> None:
    sql = "SELECT to_jsonb(d) - 'name_mn' AS row FROM destinations d ORDER BY id"
    before = fetch_all(db_001, sql)
    run_file(db_001, UP)
    assert fetch_all(db_001, sql) == before


@pytest.mark.parametrize(
    ("label", "error"),
    [("  ", psycopg.errors.CheckViolation), ("Бээжин", psycopg.errors.UniqueViolation)],
)
def test_blank_or_duplicate_label_refused(db_001: psycopg.Connection, label: str, error: type) -> None:
    run_file(db_001, UP)
    with pytest.raises(error):
        db_001.execute("UPDATE destinations SET name_mn = %s WHERE name = 'Ulaanbaatar city (local work)'", (label,))


def test_up_stops_if_a_destination_is_missing(db_001: psycopg.Connection) -> None:
    """The DO block raises -> the runner's single transaction rolls everything back."""
    db_001.execute("UPDATE destinations SET name = 'Beijing (renamed)' WHERE name = 'Beijing'")
    with pytest.raises(psycopg.errors.RaiseException, match="expected 5 destinations"):
        run_file(db_001, UP)


def test_down_restores_old_table_and_up_again(db_001: psycopg.Connection) -> None:
    cols, cons = columns(db_001, "destinations"), constraints(db_001, "destinations")
    run_file(db_001, UP)
    run_file(db_001, DOWN)
    assert columns(db_001, "destinations") == cols
    assert constraints(db_001, "destinations") == cons
    run_file(db_001, UP)
    assert labels(db_001) == EXPECTED_LABELS
