"""Tests for task 6.1: scripts/migrate.py (D-041, D-069) and migration 004 (name_mn for the last two
destinations).

Checks: files are found in version order; a fresh database gets 001–004 and a second run is a no-op;
EVERY missing version is applied, also one below the highest (D-069); a failing migration rolls back
only itself and is not recorded; a database migrated by hand is refused until --mark-applied;
migration 004 labels the two destinations and stops if one is missing.

Postgres tests skip without a running database (``docker compose up -d db``; CI has a Postgres
service). Each runs in a throwaway schema inside a transaction that is rolled back at the end, so
``conn.transaction()`` in migrate.py becomes a SAVEPOINT here (same all-or-nothing behaviour).
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from pathlib import Path

import psycopg
import pytest

from scripts import migrate as M
from tests.test_schema import database_url

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "src" / "data"
UP_004 = SQL_DIR / "migrations" / "004_destinations_name_mn_rest.up.sql"
DOWN_004 = SQL_DIR / "migrations" / "004_destinations_name_mn_rest.down.sql"


# ==========================================================================
# No database
# ==========================================================================

def test_finds_all_migrations_in_order() -> None:
    versions = [m.version for m in M.find_migrations()]
    assert versions[:4] == ["001", "002", "003", "004"]
    assert versions == sorted(versions)
    assert M.find_migrations()[3].name == "destinations_name_mn_rest"


def test_every_up_has_a_down() -> None:
    for m in M.find_migrations():
        assert m.path.with_name(m.path.name.replace(".up.sql", ".down.sql")).exists(), m.path.name


def write(folder: Path, name: str, sql: str = "SELECT 1;") -> None:
    (folder / name).write_text(sql, encoding="utf-8")


def test_duplicate_version_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "001_a.up.sql")
    write(tmp_path, "001_b.up.sql")
    with pytest.raises(M.MigrationError, match="used twice"):
        M.find_migrations(tmp_path)


def test_badly_named_file_is_refused(tmp_path: Path) -> None:
    write(tmp_path, "1_a.up.sql")
    with pytest.raises(M.MigrationError, match="NNN_name"):
        M.find_migrations(tmp_path)


def test_sorted_by_version_not_by_file_system(tmp_path: Path) -> None:
    for name in ("010_c.up.sql", "002_b.up.sql", "001_a.up.sql", "002_b.down.sql"):
        write(tmp_path, name)
    assert [m.version for m in M.find_migrations(tmp_path)] == ["001", "002", "010"]


# ==========================================================================
# Postgres
# ==========================================================================

@pytest.fixture
def pg() -> Iterator[psycopg.Connection]:
    """Throwaway schema with schema.sql only (= a fresh Docker volume before migrate.py)."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_migrate_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    yield conn
    conn.rollback()
    conn.close()


def recorded(conn: psycopg.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT version FROM schema_migrations ORDER BY version")]


def labels(conn: psycopg.Connection) -> dict[str, str | None]:
    return dict(conn.execute("SELECT name, name_mn FROM destinations ORDER BY id").fetchall())


def test_fresh_database_gets_everything_then_second_run_is_noop(pg: psycopg.Connection) -> None:
    applied = M.migrate(pg, M.find_migrations())
    assert [m.version for m in applied] == [m.version for m in M.find_migrations()]
    assert recorded(pg) == [m.version for m in M.find_migrations()]
    assert all(labels(pg).values())  # 002 + 004: every destination has a Mongolian label
    assert M.table_exists(pg, "reminders_sent")  # 003
    snapshot = pg.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall()
    assert M.migrate(pg, M.find_migrations()) == []
    assert pg.execute("SELECT version, applied_at FROM schema_migrations ORDER BY version").fetchall() == snapshot


def test_dry_run_changes_nothing(pg: psycopg.Connection) -> None:
    would = M.migrate(pg, M.find_migrations(), dry_run=True)
    assert [m.version for m in would][:4] == ["001", "002", "003", "004"]
    assert not M.table_exists(pg, "schema_migrations") and not M.table_exists(pg, "destinations")


def test_applies_a_gap_below_the_highest_version(pg: psycopg.Connection) -> None:
    """D-069: 001 + 003 applied, 002 not -> 002 (and 004) still run."""
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(pg)
    M.apply_one(pg, migrations["001"])
    M.apply_one(pg, migrations["003"])
    applied = M.migrate(pg, list(migrations.values()))
    assert [m.version for m in applied][:2] == ["002", "004"]
    assert labels(pg)["Beijing"] == "Бээжин"


def test_failing_migration_rolls_back_only_itself(pg: psycopg.Connection, tmp_path: Path) -> None:
    write(tmp_path, "001_ok.up.sql", "CREATE TABLE m_ok (id INT);")
    write(tmp_path, "002_bad.up.sql", "CREATE TABLE m_bad (id INT); SELECT 1/0;")
    write(tmp_path, "003_later.up.sql", "CREATE TABLE m_later (id INT);")
    with pytest.raises(psycopg.errors.DivisionByZero):
        M.migrate(pg, M.find_migrations(tmp_path))
    assert recorded(pg) == ["001"]
    assert M.table_exists(pg, "m_ok")
    assert not M.table_exists(pg, "m_bad") and not M.table_exists(pg, "m_later")


def test_database_migrated_by_hand_is_refused_until_marked(pg: psycopg.Connection) -> None:
    """Like the dev volume: docker-entrypoint ran 001–003 without schema_migrations."""
    migrations = {m.version: m for m in M.find_migrations()}
    for v in ("001", "002", "003"):
        pg.execute(migrations[v].path.read_text(encoding="utf-8"))
    with pytest.raises(M.MigrationError, match="--mark-applied"):
        M.migrate(pg, list(migrations.values()))
    M.mark_applied(pg, list(migrations.values()), ["001", "002", "003"])
    assert [m.version for m in M.migrate(pg, list(migrations.values()))][:1] == ["004"]
    assert labels(pg)["Other / several / unknown"] == "Бусад"


def test_mark_applied_rejects_unknown_version(pg: psycopg.Connection) -> None:
    with pytest.raises(M.MigrationError, match="999"):
        M.mark_applied(pg, M.find_migrations(), ["999"])


# ---------------- migration 004 itself ----------------

@pytest.fixture
def pg_003(pg: psycopg.Connection) -> psycopg.Connection:
    """schema.sql + 001–003 (the state before 004)."""
    for name in ("001_destinations", "002_destinations_name_mn", "003_reminders_sent"):
        pg.execute((SQL_DIR / "migrations" / f"{name}.up.sql").read_text(encoding="utf-8"))
    return pg


def test_004_labels_ub_city_and_other(pg_003: psycopg.Connection) -> None:
    before = labels(pg_003)
    pg_003.execute(UP_004.read_text(encoding="utf-8"))
    after = labels(pg_003)
    assert after["Ulaanbaatar city (local work)"] == "Улаанбаатар хот"
    assert after["Other / several / unknown"] == "Бусад"
    assert {k: v for k, v in after.items() if before[k]} == {k: v for k, v in before.items() if v}  # others unchanged


def test_004_down_and_up_again(pg_003: psycopg.Connection) -> None:
    before = labels(pg_003)
    pg_003.execute(UP_004.read_text(encoding="utf-8"))
    pg_003.execute(DOWN_004.read_text(encoding="utf-8"))
    assert labels(pg_003) == before
    pg_003.execute(UP_004.read_text(encoding="utf-8"))
    assert all(labels(pg_003).values())


def test_004_stops_if_a_destination_is_missing(pg_003: psycopg.Connection) -> None:
    pg_003.execute("UPDATE destinations SET name = 'Other (renamed)' WHERE name = 'Other / several / unknown'")
    with pytest.raises(psycopg.errors.RaiseException, match="expected 2 destinations"):
        pg_003.execute(UP_004.read_text(encoding="utf-8"))
