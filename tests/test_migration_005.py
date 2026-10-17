"""Tests for task 1.6: migration 005 (4 new cross-border destinations).

Checks: UP adds the 4 rows with Ari's Mongolian labels, OSRM km + source, the
categories mn_china / mn_russia, and leaves the 7 old rows unchanged;
scripts/migrate.py applies it after 004; DOWN removes them again (also when a
service record points to one) and UP works again.

Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED.
Each test runs in a throwaway schema inside a transaction that is rolled back.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator

import psycopg
import pytest

from scripts import migrate as M
from tests.test_migrate import SQL_DIR
from tests.test_schema import database_url

UP = SQL_DIR / "migrations" / "005_destinations_cross_border.up.sql"
DOWN = SQL_DIR / "migrations" / "005_destinations_cross_border.down.sql"

NEW = {  # name: (name_mn, route_category, one_way_km)
    "Ganqimaodu (CN side of Gashuunsukhait border)": ("Ганцмод", "mn_china", 247),
    "Ceke (CN side of Shiveekhuren border)": ("Сэхээ", "mn_china", 928),
    "Ulan-Ude (via Altanbulag–Kyakhta)": ("Улаан-Үд", "mn_russia", 578),
    "Kosh-Agach (via Tsagaannuur–Tashanta)": ("Кош-Агач", "mn_russia", 1786),
}


@pytest.fixture
def pg_004() -> Iterator[psycopg.Connection]:
    """Throwaway schema: schema.sql + sample data + migrations 001–004 (the state before 005)."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m005_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(conn)
    for v in ("001", "002", "003", "004"):
        M.apply_one(conn, migrations[v])
    yield conn
    conn.rollback()
    conn.close()


def rows(conn: psycopg.Connection) -> dict[str, tuple]:
    """{name: (name_mn, route_category, one_way_km, source)} of every destination."""
    sql = "SELECT name, name_mn, route_category, one_way_km, source FROM destinations ORDER BY id"
    return {r[0]: r[1:] for r in conn.execute(sql).fetchall()}


def test_migrate_applies_005_after_004(pg_004: psycopg.Connection) -> None:
    applied = M.migrate(pg_004, M.find_migrations())
    assert [m.version for m in applied][:1] == ["005"]
    assert "005" in [r[0] for r in pg_004.execute("SELECT version FROM schema_migrations")]


def test_up_adds_four_rows_and_keeps_old_ones(pg_004: psycopg.Connection) -> None:
    before = rows(pg_004)
    pg_004.execute(UP.read_text(encoding="utf-8"))
    after = rows(pg_004)
    assert {k: v for k, v in after.items() if k in before} == before
    added = {k: v for k, v in after.items() if k not in before}
    assert {k: v[:3] for k, v in added.items()} == NEW
    assert all(v[3].startswith("https://router.project-osrm.org/route/v1/driving/") for v in added.values())


def test_up_twice_is_refused(pg_004: psycopg.Connection) -> None:
    """name and name_mn are UNIQUE: a second run fails instead of adding copies."""
    pg_004.execute(UP.read_text(encoding="utf-8"))
    with pytest.raises(psycopg.errors.UniqueViolation):
        pg_004.execute(UP.read_text(encoding="utf-8"))


def test_down_removes_rows_even_when_a_service_uses_one(pg_004: psycopg.Connection) -> None:
    before = rows(pg_004)
    pg_004.execute(UP.read_text(encoding="utf-8"))
    service_id = pg_004.execute("SELECT id FROM service_records ORDER BY id LIMIT 1").fetchone()[0]
    pg_004.execute("UPDATE service_records SET destination_id = "
                   "(SELECT id FROM destinations WHERE name_mn = 'Сэхээ'), destination_raw = NULL WHERE id = %s",
                   (service_id,))
    pg_004.execute(DOWN.read_text(encoding="utf-8"))
    assert rows(pg_004) == before
    raw = pg_004.execute("SELECT destination_id, destination_raw FROM service_records WHERE id = %s",
                         (service_id,)).fetchone()
    assert raw == (None, "Сэхээ")  # the record keeps where it was heading
    pg_004.execute(UP.read_text(encoding="utf-8"))
    assert len(rows(pg_004)) == len(before) + 4
