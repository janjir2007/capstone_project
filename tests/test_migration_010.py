"""Migration 010 (task 9.14a): stored interval / target km, odometer_readings + its backfill, km_checks.

Throwaway schema with schema.sql + the 100% synthetic sample data + migrations 001–009, then 010.
Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED.
"""

from __future__ import annotations

import uuid
from collections.abc import Iterator
from datetime import date

import psycopg
import pytest

from scripts import migrate as M
from src.api.pace import Reading, flag_of
from tests.test_migrate import SQL_DIR
from tests.test_schema import database_url

UP = (SQL_DIR / "migrations" / "010_km_readings.up.sql").read_text(encoding="utf-8")
DOWN = (SQL_DIR / "migrations" / "010_km_readings.down.sql").read_text(encoding="utf-8")
NEW_TABLES = {"odometer_readings", "km_checks"}
SERVICE = ("INSERT INTO service_records (vehicle_id, service_date, odometer_km, engine_hours, oil_grade, liters) "
           "VALUES (%s, %s, %s, %s, '15W-40', 30) RETURNING id")


@pytest.fixture
def pg_009() -> Iterator[psycopg.Connection]:
    """State before 010: schema + sample data + 001–009."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m010_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(conn)
    for v in ("001", "002", "003", "004", "005", "006", "007", "008", "009"):
        M.apply_one(conn, migrations[v])
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def pg(pg_009: psycopg.Connection) -> psycopg.Connection:
    """State after 010."""
    pg_009.execute(UP)
    return pg_009


def tables(conn: psycopg.Connection) -> set[str]:
    sql = "SELECT table_name FROM information_schema.tables WHERE table_schema = current_schema()"
    return {r[0] for r in conn.execute(sql).fetchall()}


def columns(conn: psycopg.Connection, table: str) -> set[str]:
    sql = ("SELECT column_name FROM information_schema.columns "
           "WHERE table_schema = current_schema() AND table_name = %s")
    return {r[0] for r in conn.execute(sql, (table,)).fetchall()}


def fails(conn: psycopg.Connection, sql: str, args: tuple = ()) -> None:
    """``sql`` must be refused by a constraint (the transaction goes on)."""
    conn.execute("SAVEPOINT s")
    with pytest.raises(psycopg.errors.IntegrityError):
        conn.execute(sql, args)
    conn.execute("ROLLBACK TO SAVEPOINT s")


def test_runner_applies_010_after_009(pg_009: psycopg.Connection) -> None:
    pending = [m.version for m in M.find_migrations()
               if m.version not in {r[0] for r in pg_009.execute("SELECT version FROM schema_migrations")}]
    assert pending[0] == "010"
    M.apply_one(pg_009, {m.version: m for m in M.find_migrations()}["010"])
    assert NEW_TABLES <= tables(pg_009)


def test_up_down_up_keeps_every_service(pg_009: psycopg.Connection) -> None:
    services = pg_009.execute("SELECT * FROM service_records ORDER BY id").fetchall()
    pg_009.execute(UP)
    pg_009.execute(DOWN)
    assert not NEW_TABLES & tables(pg_009)
    assert not {"interval_km", "target_km"} & columns(pg_009, "service_records")
    assert pg_009.execute("SELECT * FROM service_records ORDER BY id").fetchall() == services
    pg_009.execute(UP)
    assert NEW_TABLES <= tables(pg_009) and {"interval_km", "target_km"} <= columns(pg_009, "service_records")


def test_backfill_15000_for_km_services_none_for_mine_trucks(pg: psycopg.Connection) -> None:
    rows = pg.execute("SELECT odometer_km, interval_km, target_km FROM service_records ORDER BY id").fetchall()
    assert all(i == 15000 and t == km + 15000 for km, i, t in rows if km is not None)
    assert [(i, t) for km, i, t in rows if km is None] == [(None, None), (None, None)]   # sample mine truck v5


def test_backfill_one_service_reading_per_service(pg: psycopg.Connection) -> None:
    got = pg.execute("SELECT s.id, r.unit, r.value, r.reading_date = s.service_date, r.source, r.status "
                     "FROM service_records s JOIN odometer_readings r ON r.service_id = s.id ORDER BY s.id").fetchall()
    assert len(got) == pg.execute("SELECT count(*) FROM service_records").fetchone()[0] == 11
    assert {(unit, same_day, source, status) for _, unit, _, same_day, source, status in got} == \
        {("km", True, "service", "ok"), ("hours", True, "service", "ok")}       # sample data: all plausible
    assert [float(v) for sid, unit, v, *_ in got if sid in (8, 9)] == [12500.0, 12980.5]  # engine hours
    rate = pg.execute("SELECT rate_per_day FROM odometer_readings WHERE service_id = 3").fetchone()[0]
    assert float(rate) == 286.6                                           # 23 500 km / 82 days


def test_backfill_flags_match_the_python_rule(pg_009: psycopg.Connection) -> None:
    """Bad pairs added BEFORE 010 get the same status as src/api/pace.flag_of gives them."""
    vid = pg_009.execute("INSERT INTO vehicles (company_id, identifier_type, identifier, plate_normalized) "
                         "VALUES (1, 'plate', '9999 ТЕС', '9999ТЕС') RETURNING id").fetchone()[0]
    km = [(date(2026, 1, 1), 100_000), (date(2026, 2, 1), 99_000),      # lower
          (date(2026, 3, 1), 99_100),                                    # 3.6 km/day: too slow
          (date(2026, 3, 2), 140_000),                                   # 40 900 km in 1 day: too fast
          (date(2026, 3, 2), 140_500),                                   # same day, higher: too fast
          (date(2026, 4, 1), 149_500)]                                   # 300 km/day: ok
    ids = [pg_009.execute(SERVICE, (vid, d, k, None)).fetchone()[0] for d, k in km]
    pg_009.execute(UP)
    got = dict(pg_009.execute("SELECT service_id, flag_reason FROM odometer_readings WHERE vehicle_id = %s",
                              (vid,)).fetchall())
    expected = [None] + [flag_of(Reading(*a), Reading(*b), "km") for a, b in zip(km, km[1:])]
    assert [got[i] for i in ids] == expected == [None, "not_higher", "too_slow", "too_fast", "too_fast", None]
    status = dict(pg_009.execute("SELECT service_id, status FROM odometer_readings WHERE vehicle_id = %s",
                                 (vid,)).fetchall())
    assert [status[i] for i in ids] == ["ok", "flagged", "flagged", "flagged", "flagged", "ok"]


def test_target_km_must_be_odometer_plus_interval(pg: psycopg.Connection) -> None:
    fails(pg, "UPDATE service_records SET target_km = 1 WHERE id = 1")
    fails(pg, "UPDATE service_records SET interval_km = NULL WHERE id = 1")             # both or none
    fails(pg, "UPDATE service_records SET interval_km = 15000, target_km = 15000 WHERE id = 8")  # mine truck
    fails(pg, "UPDATE service_records SET interval_km = 0, target_km = odometer_km WHERE id = 1")
    pg.execute("UPDATE service_records SET interval_km = 12000, target_km = odometer_km + 12000 WHERE id = 1")


READING = ("INSERT INTO odometer_readings (vehicle_id, service_id, unit, value, reading_date, source, status, "
           "flag_reason) VALUES (%s, %s, %s, %s, '2026-09-01', %s, %s, %s)")


def test_readings_constraints(pg: psycopg.Connection) -> None:
    pg.execute(READING, (1, 3, "km", 260_000, "manual", "ok", None))
    pg.execute(READING, (1, 3, "km", 262_000, "manual", "ok", None))                  # many replies per service
    pg.execute(READING, (1, 3, "km", 1, "manual", "flagged", "not_higher"))
    fails(pg, READING, (1, 3, "km", 1, "manual", "flagged", None))                   # flagged needs a reason
    fails(pg, READING, (1, 3, "km", 1, "manual", "ok", "too_fast"))                  # ok has none
    fails(pg, READING, (1, 3, "km", 1, "manual", "flagged", "typo"))
    fails(pg, READING, (1, 3, "miles", 1, "manual", "ok", None))
    fails(pg, READING, (1, 3, "km", 1, "viber", "ok", None))
    fails(pg, READING, (1, 3, "km", -1, "manual", "ok", None))
    fails(pg, READING, (2, 3, "km", 1, "manual", "ok", None))                        # service of another truck
    fails(pg, READING, (1, 3, "km", 255_500, "service", "ok", None))                 # 2nd service reading


CHECK = ("INSERT INTO km_checks (vehicle_id, service_id, phone, message_text, check_on) "
         "VALUES (%s, %s, %s, %s, '2026-10-24')")


def test_km_checks_one_per_service(pg: psycopg.Connection) -> None:
    pg.execute(CHECK, (3, 6, "99110004", "text"))
    assert pg.execute("SELECT channel FROM km_checks").fetchone()[0] == "manual"
    fails(pg, CHECK, (3, 6, "99110004", "again"))
    fails(pg, CHECK, (1, 6, None, "text"))                                            # service of another truck
    fails(pg, CHECK, (1, 3, "123", "text"))                                           # phone = 8 digits
    fails(pg, CHECK, (1, 3, None, "  "))
