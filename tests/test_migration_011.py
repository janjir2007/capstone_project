"""Migration 011 (task 9.15a-2): Messenger tables, ref backfill, plate_mismatch + messenger channel.

Throwaway schema with schema.sql + the 100% synthetic sample data + migrations 001–010, then 011.
Needs a running PostgreSQL (``docker compose up -d db``); otherwise SKIPPED.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator

import psycopg
import pytest

from scripts import migrate as M
from tests.test_migrate import SQL_DIR
from tests.test_migration_010 import columns, fails, tables
from tests.test_schema import database_url

UP = (SQL_DIR / "migrations" / "011_messenger.up.sql").read_text(encoding="utf-8")
DOWN = (SQL_DIR / "migrations" / "011_messenger.down.sql").read_text(encoding="utf-8")
NEW_TABLES = {"messenger_refs", "messenger_links", "messenger_pending", "messenger_seen", "messenger_otn"}
READING = ("INSERT INTO odometer_readings (vehicle_id, service_id, unit, value, reading_date, source, status, "
           "flag_reason) VALUES (1, 3, 'km', %s, '2026-09-01', %s, %s, %s)")
REMINDER = ("INSERT INTO reminders_sent (vehicle_id, service_id, stage, message_text, send_on, channel) "
            "VALUES (1, 3, 'single', 'text', '2026-09-26', %s)")
PSID = "1234567890123456"  # made up


@pytest.fixture
def pg_010() -> Iterator[psycopg.Connection]:
    """State before 011: schema + sample data + 001–010."""
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m011_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    conn.execute((SQL_DIR / "schema.sql").read_text(encoding="utf-8"))
    conn.execute((SQL_DIR / "sample_data.sql").read_text(encoding="utf-8"))
    migrations = {m.version: m for m in M.find_migrations()}
    M.ensure_table(conn)
    for v in ("001", "002", "003", "004", "005", "006", "007", "008", "009", "010"):
        M.apply_one(conn, migrations[v])
    yield conn
    conn.rollback()
    conn.close()


@pytest.fixture
def pg(pg_010: psycopg.Connection) -> psycopg.Connection:
    pg_010.execute(UP)
    return pg_010


def test_runner_applies_011_after_010(pg_010: psycopg.Connection) -> None:
    done = {r[0] for r in pg_010.execute("SELECT version FROM schema_migrations")}
    pending = [m.version for m in M.find_migrations() if m.version not in done]
    assert pending[0] == "011"
    M.apply_one(pg_010, {m.version: m for m in M.find_migrations()}["011"])
    assert NEW_TABLES <= tables(pg_010)


def test_one_random_ref_per_km_service(pg: psycopg.Connection) -> None:
    refs = pg.execute("SELECT r.ref, r.service_id, r.vehicle_id = s.vehicle_id FROM messenger_refs r "
                      "JOIN service_records s ON s.id = r.service_id").fetchall()
    km_services = pg.execute("SELECT id FROM service_records WHERE odometer_km IS NOT NULL").fetchall()
    assert sorted(sid for _, sid, _ in refs) == sorted(i for (i,) in km_services)   # mine trucks: none
    assert all(same for *_, same in refs)
    codes = [ref for ref, *_ in refs]
    assert all(re.fullmatch(r"[A-Z2-9]{8}", c) for c in codes)
    assert len(set(codes)) == len(codes) == 9                                       # all different


def test_up_down_up(pg_010: psycopg.Connection) -> None:
    """Down removes only what the old CHECKs refuse; every other reading and reminder stays."""
    pg_010.execute(UP)
    pg_010.execute(READING, (260_000, "messenger", "ok", None))
    pg_010.execute(READING, (261_000, "messenger", "flagged", "plate_mismatch"))
    pg_010.execute(REMINDER, ("messenger",))
    readings = pg_010.execute("SELECT count(*) FROM odometer_readings").fetchone()[0]
    pg_010.execute(DOWN)
    assert not NEW_TABLES & tables(pg_010)
    assert pg_010.execute("SELECT count(*) FROM odometer_readings").fetchone()[0] == readings - 1
    assert pg_010.execute("SELECT count(*) FROM odometer_readings WHERE source = 'messenger'").fetchone()[0] == 1
    assert pg_010.execute("SELECT count(*) FROM reminders_sent WHERE channel = 'messenger'").fetchone()[0] == 0
    fails(pg_010, READING, (262_000, "manual", "flagged", "plate_mismatch"))           # old CHECKs back
    fails(pg_010, REMINDER, ("messenger",))
    pg_010.execute(UP)
    assert NEW_TABLES <= tables(pg_010)


def test_new_check_values(pg: psycopg.Connection) -> None:
    pg.execute(READING, (260_000, "messenger", "flagged", "plate_mismatch"))
    pg.execute(REMINDER, ("messenger",))
    fails(pg, READING, (260_000, "messenger", "flagged", "typo"))
    fails(pg, REMINDER, ("viber",))


def test_pending_holds_parsed_values_only(pg: psycopg.Connection) -> None:
    """PM 9.15a-2: plate + km (+ day, expiry), no message text."""
    assert columns(pg, "messenger_pending") == {"psid", "plate", "value", "reading_date", "expires_at", "created_at"}
    insert = ("INSERT INTO messenger_pending (psid, plate, value, reading_date, expires_at) "
              "VALUES (%s, %s, %s, '2026-10-11', now())")
    pg.execute(insert, (PSID, "9988НАА", 871_234))
    fails(pg, insert, (PSID, "1234УБА", 1))                                           # one per PSID
    fails(pg, insert, ("2", "Сайн уу", 1))                                            # not a plate
    fails(pg, insert, ("abc", "9988НАА", 1))                                          # PSID = digits
    fails(pg, insert, ("3", "9988НАА", 0))


def test_links_and_otn_constraints(pg: psycopg.Connection) -> None:
    link = "INSERT INTO messenger_links (psid, vehicle_id, linked_via, service_id) VALUES (%s, %s, %s, %s)"
    pg.execute(link, (PSID, 1, "ref", 3))
    pg.execute(link, (PSID, 2, "plate", None))                                        # one driver, two trucks
    pg.execute(link, ("99", 1, "plate", None))                                         # one truck, two drivers
    fails(pg, link, (PSID, 1, "plate", None))                                          # same pair twice
    fails(pg, link, ("98", 1, "ref", None))                                            # ref needs its service
    fails(pg, link, ("97", 1, "plate", 3))
    fails(pg, link, ("96", 1, "sms", None))
    otn = "INSERT INTO messenger_otn (psid, vehicle_id, token, expires_at) VALUES (%s, 1, %s, now())"
    pg.execute(otn, (PSID, "tok-1"))
    fails(pg, otn, (PSID, "tok-1"))                                                    # one token = one row
    fails(pg, otn, (PSID, " "))
    ref = "INSERT INTO messenger_refs (ref, service_id, vehicle_id) VALUES (%s, %s, %s)"
    fails(pg, ref, ("ABCD1234", 9, 5))                                                 # 1 is not in A-Z 2-9
    fails(pg, ref, ("ABCDEFGH", 3, 2))                                                 # service of another truck
