"""Tests for scripts/wipe_demo.py (task 8.2d) on a throwaway PostgreSQL schema.

Schema = schema.sql + migrations 001–005 + schema_migrations + sample_data.sql + one sent reminder,
so every table the real database has is filled. Skips without PostgreSQL (CI has it).
"""

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from scripts import migrate
from scripts import wipe_demo as W
from tests.test_schema import database_url

SQL_DIR = Path(__file__).resolve().parent.parent / "src" / "data"
SQL_FILES = ["schema.sql", "migrations/001_destinations.up.sql", "migrations/002_destinations_name_mn.up.sql",
             "migrations/003_reminders_sent.up.sql", "migrations/004_destinations_name_mn_rest.up.sql",
             "migrations/005_destinations_cross_border.up.sql",
             "migrations/006_reminder_stages.up.sql", "sample_data.sql"]
EMPTIED = ["companies", "predictions", "reminder_stops", "reminders", "reminders_sent", "service_records", "vehicles"]


@pytest.fixture
def conn() -> Iterator[psycopg.Connection]:
    """Autocommit connection whose search_path is a fresh, filled schema (dropped afterwards)."""
    try:
        connection = psycopg.connect(database_url(), autocommit=True, connect_timeout=3)
    except psycopg.OperationalError as exc:
        pytest.skip(f"PostgreSQL not reachable (run `docker compose up -d db`): {exc}")
    schema = f"test_wipe_{uuid.uuid4().hex[:8]}"
    connection.execute(f"CREATE SCHEMA {schema}")
    connection.execute(f"SET search_path TO {schema}")
    for name in SQL_FILES:
        connection.execute((SQL_DIR / name).read_text(encoding="utf-8"))
    migrate.ensure_table(connection)
    connection.execute("INSERT INTO schema_migrations (version, name) VALUES ('001', 'destinations'), ('002', 'destinations_name_mn')")
    connection.execute(
        "INSERT INTO reminders_sent (vehicle_id, service_id, message_text, method, model_version, predicted_date, send_on) "
        "SELECT vehicle_id, id, 'Сайн байна уу', 'ridge', 'ridge-test', service_date + 60, service_date + 50 "
        "FROM service_records ORDER BY id LIMIT 1")
    yield connection
    connection.execute(f"DROP SCHEMA {schema} CASCADE")
    connection.close()


def counts(conn: psycopg.Connection, tables: list[str]) -> dict[str, int]:
    return W.row_counts(conn, tables)


def echo_phrase(prompt: str) -> str:
    """Types exactly the phrase the prompt asks for (WIPE <database>)."""
    return prompt.split("'")[1]


def test_tables_found_from_foreign_keys(conn) -> None:
    """The 5 core tables (9.5b: + reminder_stops, driver phones) + predictions and reminders (they
    reference vehicles); never the kept ones."""
    assert W.tables_to_empty(conn) == EMPTIED


def test_wrong_confirmation_deletes_nothing(conn, capsys) -> None:
    before = counts(conn, EMPTIED)
    assert all(before[t] > 0 for t in ("companies", "vehicles", "service_records", "reminders_sent"))
    assert W.run(conn, "oil_change_x.sql.gz", ask=lambda _: "wipe") == 1
    assert counts(conn, EMPTIED) == before
    assert "nothing deleted" in capsys.readouterr().out


def test_typed_confirmation_empties_and_keeps(conn, capsys) -> None:
    kept = counts(conn, list(W.KEEP_TABLES))
    assert kept["destinations"] > 0 and kept["schema_migrations"] == 2
    assert W.run(conn, "oil_change_x.sql.gz", ask=echo_phrase) == 0
    assert set(counts(conn, EMPTIED).values()) == {0}
    assert counts(conn, list(W.KEEP_TABLES)) == kept
    # RESTART IDENTITY: the first real company gets id 1
    assert conn.execute("INSERT INTO companies (name) VALUES ('Real LLC') RETURNING id").fetchone()[0] == 1
    assert "oil_change_x.sql.gz" in capsys.readouterr().out


def test_kept_table_is_never_emptied(conn) -> None:
    """If destinations ever referenced a wiped table, the script stops before deleting anything."""
    conn.execute("ALTER TABLE destinations ADD COLUMN company_id BIGINT REFERENCES companies (id)")
    before = counts(conn, EMPTIED + list(W.KEEP_TABLES))
    with pytest.raises(W.WipeError, match="destinations"):
        W.run(conn, "oil_change_x.sql.gz", ask=echo_phrase)
    assert counts(conn, EMPTIED + list(W.KEEP_TABLES)) == before


def test_refuses_without_backup_argument() -> None:
    with pytest.raises(SystemExit) as exc:
        W.main([])
    assert exc.value.code == 2  # argparse: --after-backup is required
