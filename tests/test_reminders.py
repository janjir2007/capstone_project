"""Tests for tasks 4.4 + 9.5b + 9.5c: one reminder per service (75 days), stop phones, segments
(150-day at_risk), the REMINDER_DAYS / AT_RISK_DAYS settings, migrations 003 + 006 + 007, fleet
numbers, HEIC.

Fake data only: sample_data.sql (100% synthetic) + trucks created here, the
fake Ridge folder from tests/test_serving.py. Postgres tests skip without a
running database (``docker compose up -d db``).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import date, timedelta
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import prediction as P
from src.api.clock import get_today
from src.api.config import PLACEHOLDER_PHONE, ConfigError, Contact, ReminderRules, reminder_contact, reminder_rules
from src.api.db import get_session
from src.api.main import create_app
from src.api.reminders import is_due, km_check_message, message_mn, reminder_day, segment_of, sms_parts
from src.api.routers.reminders import get_contact
from src.cv import plate_reader as R
from tests.test_api_data import pg  # noqa: F401  (Postgres: schema + 001 + 003 + sample data)
from tests.test_schema import database_url
from tests.test_serving import StubRecognizer, model_dir, predictor, visit  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "src" / "data"
TODAY = date(2026, 10, 12)
CONTACT = Contact(name="Geo-Expert", phone="99000001", is_placeholder=False)
RULES = ReminderRules(reminder_days=75, at_risk_days=150)


@pytest.fixture(autouse=True)
def default_rules(monkeypatch: pytest.MonkeyPatch) -> None:
    """Every test starts from the defaults (75 / 150 / 5 / 34, 12000 km), whatever the developer's shell has."""
    for name in ("REMINDER_DAYS", "AT_RISK_DAYS", "REMINDER_LEAD_DAYS", "KM_CHECK_DAYS", "OIL_INTERVAL_KM"):
        monkeypatch.delenv(name, raising=False)


# ==========================================================================
# Message + contact (9.5c: one short text)
# ==========================================================================

def test_message_exact_text_and_sms_parts() -> None:
    """9.14a: Cyrillic = UCS-2 (70 per SMS, 67 per part): the live text is 3 parts (135 characters),
    not "<= 160" as tested before. Shorter wordings are proposed to Ari; the text stays until he picks."""
    text = message_mn("1234 УБА", date(2026, 8, 10), "15W-40", CONTACT)
    assert text == ("Сайн байна уу! 1234 УБА машины тосыг 2026.08.10-нд солиулсан (15W-40). "
                    "Дахин солих хугацаа болж байна. Wolf Oil - Гео-Эксперт: 99000001")
    assert (len(text), sms_parts(text)) == (135, 3)


@pytest.mark.parametrize(("text", "parts"), [
    ("", 0), ("a" * 160, 1), ("a" * 161, 2), ("a" * 306, 2), ("a" * 307, 3),   # GSM-7: 160 / 153
    ("[]" * 40, 1), ("[]" * 40 + "a", 2),                                    # extension chars count 2
    ("Б" * 70, 1), ("Б" * 71, 2), ("Б" * 134, 2), ("Б" * 135, 3),            # UCS-2: 70 / 67
    ("a" * 69 + "Б", 1), ("a" * 70 + "Б", 2),                                # one Cyrillic letter -> UCS-2
    ("😀" * 35, 1), ("😀" * 36, 2),                                          # emoji = 2 UTF-16 units
])
def test_sms_parts(text: str, parts: int) -> None:
    assert sms_parts(text) == parts


# Worst case the app can produce today: plates are 8 characters ("1234 УБА"), fleet numbers so far
# <= 6 ("HT-12"): 10 leaves room; CONTACT_PHONE as "+976" + 8 digits; the longest oil grade name seen.
WORST_ID, WORST_PHONE, WORST_OIL = "HT-1234-AB", "+97699112233", "Shell Rimula R4 X 15W-40"


def test_km_check_text_exact_and_at_most_2_sms() -> None:
    text = km_check_message("1234 УБА", date(2026, 8, 10), CONTACT)
    assert text == ("Сайн байна уу! 1234 УБА машины тосыг 2026.08.10-нд солиулсан. Одоогийн км-ээ хариу "
                    "бичнэ үү. Wolf Oil - Гео-Эксперт: 99000001")
    assert (len(text), sms_parts(text)) == (125, 2)
    worst = km_check_message(WORST_ID, date(2026, 12, 31), Contact("Geo-Expert", WORST_PHONE, False))
    assert sms_parts(worst) == 2, len(worst)
    assert len(message_mn("1234 УБА", date(2026, 8, 10), "Shell Rimula R4 X 15W-40", CONTACT)) <= 160


def test_contact_phone_wins_then_old_setting_then_placeholder() -> None:
    assert reminder_contact({}) == Contact("Geo-Expert", PLACEHOLDER_PHONE, is_placeholder=True)
    assert reminder_contact({"GEO_EXPERT_PHONE": " 88112233 ", "GEO_EXPERT_NAME": "Гео Эксперт"}) == \
        Contact("Гео Эксперт", "88112233", is_placeholder=False)
    assert reminder_contact({"CONTACT_PHONE": "99887766", "GEO_EXPERT_PHONE": "88112233"}).phone == "99887766"
    assert reminder_contact({"CONTACT_PHONE": "  ", "GEO_EXPERT_PHONE": "88112233"}).phone == "88112233"


# ==========================================================================
# Settings: REMINDER_DAYS / AT_RISK_DAYS
# ==========================================================================

def test_rules_default_and_values() -> None:
    assert reminder_rules({}) == RULES == ReminderRules(75, 150, lead_days=5, km_check_days=34)
    assert reminder_rules({"REMINDER_DAYS": " 60 ", "AT_RISK_DAYS": "120"}) == ReminderRules(60, 120)
    assert reminder_rules({"REMINDER_DAYS": "", "AT_RISK_DAYS": "200"}) == ReminderRules(75, 200)
    assert reminder_rules({"REMINDER_LEAD_DAYS": "7", "KM_CHECK_DAYS": "30"}) == ReminderRules(75, 150, 7, 30)


@pytest.mark.parametrize(("env", "name"), [
    ({"REMINDER_DAYS": "0"}, "REMINDER_DAYS"), ({"REMINDER_DAYS": "75.5"}, "REMINDER_DAYS"),
    ({"AT_RISK_DAYS": "-1"}, "AT_RISK_DAYS"), ({"AT_RISK_DAYS": "abc"}, "AT_RISK_DAYS"),
    ({"REMINDER_DAYS": "150"}, "greater than"),                       # 150 <= 150
    ({"REMINDER_DAYS": "80", "AT_RISK_DAYS": "70"}, "greater than"),
    ({"REMINDER_LEAD_DAYS": "0"}, "REMINDER_LEAD_DAYS"), ({"KM_CHECK_DAYS": "x"}, "KM_CHECK_DAYS"),
    ({"REMINDER_LEAD_DAYS": "150"}, "REMINDER_LEAD_DAYS .* less than AT_RISK_DAYS"),     # 9.14a
    ({"KM_CHECK_DAYS": "75"}, "KM_CHECK_DAYS .* less than REMINDER_DAYS"),              # check after the reminder
])
def test_rules_reject_bad_values(env: dict[str, str], name: str) -> None:
    with pytest.raises(ConfigError, match=name):
        reminder_rules(env)


def test_api_does_not_start_when_at_risk_is_not_after_the_reminder(monkeypatch: pytest.MonkeyPatch,
                                                                   tmp_path: Path) -> None:
    monkeypatch.setenv("REMINDER_DAYS", "150")
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=tmp_path)
    with pytest.raises(ConfigError, match="AT_RISK_DAYS"):
        with TestClient(app):
            pass


# ==========================================================================
# Due + segment rules (pure)
# ==========================================================================

LAST = date(2026, 8, 1)


@pytest.mark.parametrize(("days", "due"), [(0, False), (74, False), (75, True), (149, True), (400, True)])
def test_due_from_day_75(days: int, due: bool) -> None:
    assert is_due(LAST, LAST + timedelta(days=days), False, RULES) is due
    assert is_due(LAST, LAST + timedelta(days=days), True, RULES) is False   # sent once -> never again


def test_reminder_day_follows_the_setting() -> None:
    assert reminder_day(LAST, RULES) == date(2026, 10, 15)
    assert reminder_day(LAST, ReminderRules(30, 60)) == date(2026, 8, 31)


@pytest.mark.parametrize(("count", "days", "segment"), [
    (1, 10, "new"), (2, 149, "returning"), (3, 149, "loyal"), (7, 90, "loyal"),
    (1, 150, "at_risk"), (9, 200, "at_risk"),   # 150+ days without a new service: at_risk wins
])
def test_segment_rule_150_days(count: int, days: int, segment: str) -> None:
    assert segment_of(count, LAST, LAST + timedelta(days=days), RULES) == segment


def test_segment_rule_follows_the_setting() -> None:
    assert segment_of(3, LAST, LAST + timedelta(days=100), ReminderRules(60, 90)) == "at_risk"


# ==========================================================================
# Prediction (ML code kept; reminders no longer use it)
# ==========================================================================

def test_buffers_come_from_the_model_folder(predictor: P.Predictor) -> None:  # noqa: F811
    assert predictor.buffers == {"ridge": 7, "b0": 12, "b1": 1}  # fake files: model buffer_days 7, params 12 / 1
    p = predictor.predict(1, [visit(1, "2026-08-10", None, dest=None, route="mixed")], TODAY)  # b0
    assert predictor.send_on(p) == date(2026, 9, 25)  # 2026-10-07 − 12


def test_batch_equals_one_by_one(predictor: P.Predictor) -> None:  # noqa: F811
    histories = {
        1: [visit(1, "2026-06-01", 300_000), visit(2, "2026-07-20", 318_000)],                 # ridge
        2: [visit(3, "2026-09-01", 100_000, dest="Kyakhta (RU side of border)")],             # b1
        3: [visit(4, "2026-05-10", 5_000, dest=None, route="mixed")],                         # b0
        4: [visit(5, "2026-01-01", 1), visit(6, "2026-03-03", 20_001), visit(7, "2026-05-01", 39_000)],  # ridge
    }
    batch = predictor.predict_many(histories, TODAY)
    assert {v: p.method for v, p in batch.items()} == {1: "ridge", 2: "b1", 3: "b0", 4: "ridge"}
    assert batch == {vid: predictor.predict(vid, visits, TODAY) for vid, visits in histories.items()}


# ==========================================================================
# Migration 003 (throwaway schema, rolled back)
# ==========================================================================

@pytest.fixture
def raw_pg() -> Iterator[psycopg.Connection]:
    try:
        conn = psycopg.connect(database_url(), connect_timeout=3)
    except psycopg.OperationalError:
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    schema = f"test_m003_{uuid.uuid4().hex[:8]}"
    conn.execute(f"CREATE SCHEMA {schema}")
    conn.execute(f"SET search_path TO {schema}")
    for name in ("schema.sql", "migrations/001_destinations.up.sql", "sample_data.sql"):
        conn.execute((SQL_DIR / name).read_text(encoding="utf-8"))
    yield conn
    conn.rollback()
    conn.close()


def _tables(conn: psycopg.Connection) -> set[str]:
    return {r[0] for r in conn.execute("SELECT table_name FROM information_schema.tables "
                                       "WHERE table_schema = current_schema()").fetchall()}


def test_migration_003_up_down_up(raw_pg: psycopg.Connection) -> None:
    up = (SQL_DIR / "migrations/003_reminders_sent.up.sql").read_text(encoding="utf-8")
    down = (SQL_DIR / "migrations/003_reminders_sent.down.sql").read_text(encoding="utf-8")
    before = _tables(raw_pg)
    raw_pg.execute(up)
    assert _tables(raw_pg) == before | {"reminders_sent"}
    raw_pg.execute(down)
    assert _tables(raw_pg) == before
    raw_pg.execute(up)
    assert "reminders_sent" in _tables(raw_pg)


def test_migration_003_constraints(raw_pg: psycopg.Connection) -> None:
    raw_pg.execute((SQL_DIR / "migrations/003_reminders_sent.up.sql").read_text(encoding="utf-8"))
    insert = ("INSERT INTO reminders_sent (vehicle_id, service_id, phone, message_text, method, model_version, "
              "predicted_date, send_on) VALUES (%s, %s, %s, 'x', 'b0', 'ridge-test', '2026-10-07', '2026-09-25')")
    raw_pg.execute(insert, (1, 3, "99110001"))  # service 3 = vehicle 1's newest sample service
    for args, error in [((1, 3, None), psycopg.errors.UniqueViolation),        # one per service
                        ((2, 1, None), psycopg.errors.ForeignKeyViolation),    # service 1 belongs to vehicle 1
                        ((1, 2, "123"), psycopg.errors.CheckViolation)]:       # phone not 8 digits
        raw_pg.execute("SAVEPOINT s")
        with pytest.raises(error):
            raw_pg.execute(insert, args)
        raw_pg.execute("ROLLBACK TO SAVEPOINT s")


# ==========================================================================
# Migration 006 (throwaway schema, rolled back)
# ==========================================================================

M006_UP = (SQL_DIR / "migrations/006_reminder_stages.up.sql").read_text(encoding="utf-8")
M006_DOWN = (SQL_DIR / "migrations/006_reminder_stages.down.sql").read_text(encoding="utf-8")
OLD_ROW = ("INSERT INTO reminders_sent (vehicle_id, service_id, phone, message_text, method, model_version, "
           "predicted_date, send_on) VALUES (1, 3, '99110002', 'old', 'b0', 'ridge-test', '2026-10-07', '2026-09-25')")
STAGE_ROW = ("INSERT INTO reminders_sent (vehicle_id, service_id, stage, phone, message_text, send_on) "
             "VALUES (%s, %s, %s, %s, 'x', '2026-10-09')")


def test_migration_006_up_down_up_keeps_old_rows(raw_pg: psycopg.Connection) -> None:
    raw_pg.execute((SQL_DIR / "migrations/003_reminders_sent.up.sql").read_text(encoding="utf-8"))
    raw_pg.execute(OLD_ROW)                                   # a row from before 9.5b
    raw_pg.execute(M006_UP)
    assert "reminder_stops" in _tables(raw_pg)
    assert raw_pg.execute("SELECT stage, method FROM reminders_sent").fetchall() == [(None, "b0")]
    raw_pg.execute(STAGE_ROW, (1, 3, "2m", "99110002"))
    raw_pg.execute(M006_DOWN)                                 # month rows go, the old row stays
    assert "reminder_stops" not in _tables(raw_pg)
    assert raw_pg.execute("SELECT method FROM reminders_sent").fetchall() == [("b0",)]
    raw_pg.execute(M006_UP)
    assert "reminder_stops" in _tables(raw_pg)


def test_migration_006_constraints(raw_pg: psycopg.Connection) -> None:
    raw_pg.execute((SQL_DIR / "migrations/003_reminders_sent.up.sql").read_text(encoding="utf-8"))
    raw_pg.execute(M006_UP)
    raw_pg.execute(STAGE_ROW, (1, 3, "1m", "99110002"))
    raw_pg.execute(STAGE_ROW, (1, 3, "2m", "99110002"))      # another stage of the same service: fine
    raw_pg.execute("INSERT INTO reminder_stops (phone) VALUES ('99110002')")
    for sql, args, error in [
        (STAGE_ROW, (1, 3, "1m", None), psycopg.errors.UniqueViolation),          # each stage once
        (STAGE_ROW, (1, 3, "4m", None), psycopg.errors.CheckViolation),           # unknown stage
        (STAGE_ROW, (1, 3, None, None), psycopg.errors.CheckViolation),           # neither stage nor method
        ("INSERT INTO reminder_stops (phone) VALUES (%s)", ("99110002",), psycopg.errors.UniqueViolation),
        ("INSERT INTO reminder_stops (phone) VALUES (%s)", ("123",), psycopg.errors.CheckViolation),
    ]:
        raw_pg.execute("SAVEPOINT s")
        with pytest.raises(error):
            raw_pg.execute(sql, args)
        raw_pg.execute("ROLLBACK TO SAVEPOINT s")


# ==========================================================================
# Migration 007 (throwaway schema, rolled back)
# ==========================================================================

M007_UP = (SQL_DIR / "migrations/007_single_reminder.up.sql").read_text(encoding="utf-8")
M007_DOWN = (SQL_DIR / "migrations/007_single_reminder.down.sql").read_text(encoding="utf-8")


def _up_to_006(conn: psycopg.Connection) -> None:
    conn.execute((SQL_DIR / "migrations/003_reminders_sent.up.sql").read_text(encoding="utf-8"))
    conn.execute(M006_UP)


def test_migration_006_named_its_stage_check_as_007_expects(raw_pg: psycopg.Connection) -> None:
    _up_to_006(raw_pg)
    names = {r[0] for r in raw_pg.execute("SELECT conname FROM pg_constraint WHERE conrelid = 'reminders_sent'::regclass")}
    assert "reminders_sent_stage_check" in names


def test_migration_007_keeps_old_rows_and_down_turns_single_into_3m(raw_pg: psycopg.Connection) -> None:
    _up_to_006(raw_pg)
    raw_pg.execute(OLD_ROW)                                   # before 9.5b (prediction)
    raw_pg.execute(STAGE_ROW, (1, 3, "2m", "99110002"))       # 9.5b
    raw_pg.execute(M007_UP)
    rows = "SELECT service_id, stage, method, channel FROM reminders_sent ORDER BY id"
    assert raw_pg.execute(rows).fetchall() == [(3, None, "b0", "manual"), (3, "2m", None, "manual")]
    raw_pg.execute(STAGE_ROW, (2, 4, "single", None))         # 9.5c row (service 4 = vehicle 2's newest)
    raw_pg.execute(M007_DOWN)                                 # nothing deleted: single -> 3m
    assert raw_pg.execute("SELECT service_id, stage FROM reminders_sent ORDER BY id").fetchall() == \
        [(3, None), (3, "2m"), (4, "3m")]
    raw_pg.execute(M007_UP)                                   # and up again
    assert raw_pg.execute("SELECT count(*) FROM reminders_sent").fetchone() == (3,)


def test_migration_007_constraints(raw_pg: psycopg.Connection) -> None:
    _up_to_006(raw_pg)
    raw_pg.execute(M007_UP)
    raw_pg.execute(STAGE_ROW, (1, 3, "single", "99110002"))
    raw_pg.execute(STAGE_ROW, (1, 3, "3m", "99110002"))      # an old stage next to it: the table allows it
    with_channel = ("INSERT INTO reminders_sent (vehicle_id, service_id, stage, message_text, send_on, channel) "
                    "VALUES (1, 2, 'single', 'x', '2026-10-09', %s)")
    raw_pg.execute(with_channel, ("sms",))
    for sql, args, error in [
        (STAGE_ROW, (1, 3, "single", None), psycopg.errors.UniqueViolation),     # one single per service
        (STAGE_ROW, (1, 3, "4m", None), psycopg.errors.CheckViolation),
        (with_channel, ("viber",), psycopg.errors.CheckViolation),                 # unknown channel
        (with_channel, (None,), psycopg.errors.NotNullViolation),
    ]:
        raw_pg.execute("SAVEPOINT s")
        with pytest.raises(error):
            raw_pg.execute(sql, args)
        raw_pg.execute("ROLLBACK TO SAVEPOINT s")


# ==========================================================================
# Endpoints on Postgres (sample data; today = 2026-10-12)
# ==========================================================================

@pytest.fixture
def client(pg: Connection, model_dir: Path) -> Iterator[TestClient]:  # noqa: F811
    savepoint = pg.begin_nested()

    def test_session() -> Iterator[Session]:
        with Session(bind=pg, join_transaction_mode="create_savepoint") as session:
            yield session

    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=model_dir)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_today] = lambda: TODAY
    app.dependency_overrides[get_contact] = lambda: CONTACT
    with TestClient(app) as test_client:
        yield test_client
    savepoint.rollback()


def new_service(client: TestClient, plate: str, day: str, km: int = 100_000, phone: str | None = "99110009") -> dict:
    """POST /services without a destination (9.5a form)."""
    r = client.post("/services", json={"identifier": plate, "company_name": "Test 9.5c", "service_date": day,
                                       "odometer_km": km, "oil_grade": "10W-40", "liters": 36.5,
                                       "driver_phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


def due(client: TestClient, **params: str) -> dict:
    r = client.get("/reminders/due", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def due_ids(client: TestClient, **params: str) -> list[int]:
    return [r["vehicle_id"] for r in due(client, **params)["reminders"]]


def sent(client: TestClient, service_id: int):
    return client.post(f"/reminders/{service_id}/sent")


def test_due_list_pace_or_75_days(client: TestClient) -> None:
    """Sample data on 10-12 (9.14a; stored interval 15000 from the migration 010 backfill):
    v1 05-20 -> 08-10, 23 500 km in 82 days = 286.6 km/day: due 08-10 + 52 = 10-01, reminder 09-26 -> due ·
    v6 06-01 -> 09-01, 271.7 km/day: due 10-26, reminder 10-21 -> not yet ·
    v2 06-15 -> 09-10, 74.7 km/day: due 2027-03-29, capped at 09-10 + 150 - 5 = 2027-02-02 ·
    v3 one service (no pace) -> 75 days: 12-04 · v4 one service 05-10 -> 75 days: 07-24, due and at risk ·
    v5 mine truck (engine hours) -> no reminder."""
    result = due(client)
    assert result["as_of"] == TODAY.isoformat() and result["contact_is_placeholder"] is False
    assert [r["vehicle_id"] for r in result["reminders"]] == [4, 1]   # oldest reminder day first
    v4, v1 = result["reminders"]
    assert (v4["segment"], v4["days_since"], v4["send_on"], v4["basis"]) == ("at_risk", 155, "2026-07-24", "fixed")
    assert (v4["rate_per_day"], v4["pace_source"], v4["next_due_date"]) == (None, None, None)
    assert "stage" not in v4                                   # contract v0.15: one reminder, no stage
    assert (v1["service_id"], v1["send_on"], v1["next_due_date"], v1["basis"]) == \
        (3, "2026-09-26", "2026-10-01", "pace")
    assert (v1["rate_per_day"], v1["pace_source"], v1["days_since"]) == (286.6, "services", 63)
    assert (v1["odometer_km"], v1["target_km"], v1["segment"]) == (255_500, 270_500, "loyal")
    later = due(client, as_of="2026-11-01")["reminders"]
    assert [r["vehicle_id"] for r in later] == [4, 1, 6]
    assert later[2]["send_on"] == "2026-10-21"
    assert 2 not in due_ids(client, as_of="2027-02-01") and 2 in due_ids(client, as_of="2027-02-02")  # the cap
    assert (v1["identifier"], v1["phone"], v1["last_change_date"], v1["oil_grade"]) == \
        ("1234 УБА", "99110002", "2026-08-10", "15W-40")
    assert v1["message_mn"] == message_mn("1234 УБА", date(2026, 8, 10), "15W-40", CONTACT)


def test_reminder_days_is_a_setting(client: TestClient, monkeypatch: pytest.MonkeyPatch) -> None:
    """REMINDER_DAYS moves trucks without a pace (v4), REMINDER_LEAD_DAYS those with one (v1)."""
    monkeypatch.setenv("REMINDER_DAYS", "60")
    monkeypatch.setenv("REMINDER_LEAD_DAYS", "10")
    send_on = {r["vehicle_id"]: r["send_on"] for r in due(client)["reminders"]}
    assert send_on == {4: "2026-07-09", 1: "2026-09-21"}
    monkeypatch.setenv("AT_RISK_DAYS", "160")                   # v4 (155 d) is no longer at risk
    assert client.get("/stats/segments").json()["counts"]["at_risk"] == 0
    assert client.get("/vehicles/4").json()["segment"] != "at_risk"


def test_sent_once_then_gone_until_a_new_service(client: TestClient) -> None:
    old = new_service(client, "0002 ТЕС", "2026-07-01", km=100_000)    # 103 days -> due
    vid, old_id = old["vehicle_id"], old["service"]["id"]
    assert vid in due_ids(client)
    first = sent(client, old_id)
    assert first.status_code == 201
    body = first.json()
    assert (body["stage"], body["channel"], body["already_sent"], body["send_on"]) == \
        ("single", "manual", False, "2026-09-14")
    assert vid not in due_ids(client) and vid not in due_ids(client, as_of="2027-06-01")  # never again
    back = new_service(client, "0002 ТЕС", "2026-09-01", km=118_000)  # came back: new cycle
    # 9.14a: 18 000 km in 62 days = 290.3 km/day -> 12 000 km due 09-01 + 41 = 10-12, reminder 10-07
    item = next(r for r in due(client)["reminders"] if r["vehicle_id"] == vid)
    assert (item["service_id"], item["target_km"], item["segment"]) == (back["service"]["id"], 130_000, "returning")
    assert (item["send_on"], item["next_due_date"], item["basis"]) == ("2026-10-07", "2026-10-12", "pace")
    assert sent(client, old_id).status_code == 200                     # stored before: still idempotent


def test_new_service_makes_an_old_reminder_stale(client: TestClient) -> None:
    old = new_service(client, "0003 ТЕС", "2026-06-01")
    new_service(client, "0003 ТЕС", "2026-10-01")
    r = sent(client, old["service"]["id"])
    assert r.status_code == 409 and r.json()["detail"]["code"] == "not_latest_service"


def test_double_sent_makes_one_row(client: TestClient, pg: Connection) -> None:
    first = sent(client, 7)                                   # v4's newest service (05-10)
    assert first.status_code == 201
    body = first.json()
    assert (body["service_id"], body["vehicle_id"], body["method"]) == (7, 4, None)
    again = sent(client, 7)
    assert again.status_code == 200 and again.json() == body | {"already_sent": True}
    old_ui = client.post("/reminders/7/sent", params={"stage": "3m"})   # a 9.5b UI tab still open: ignored
    assert old_ui.status_code == 200 and old_ui.json()["stage"] == "single"
    assert pg.execute(text("SELECT count(*) FROM reminders_sent WHERE service_id = 7")).scalar_one() == 1
    assert 4 not in due_ids(client)


@pytest.mark.parametrize("old_stage", ["1m", "2m", "3m"])
def test_old_month_row_counts_as_sent(client: TestClient, pg: Connection, old_stage: str) -> None:
    """PM 9.5c Q2: a 9.5b row for the current service = reminded; POST returns that row."""
    pg.execute(text("INSERT INTO reminders_sent (vehicle_id, service_id, stage, phone, message_text, send_on) "
                    "VALUES (4, 7, :stage, NULL, 'old 9.5b text', '2026-08-09')"), {"stage": old_stage})
    assert 4 not in due_ids(client)
    r = sent(client, 7)
    assert r.status_code == 200 and (r.json()["stage"], r.json()["already_sent"]) == (old_stage, True)
    assert pg.execute(text("SELECT count(*) FROM reminders_sent WHERE service_id = 7")).scalar_one() == 1


def test_old_prediction_row_does_not_count(client: TestClient, pg: Connection) -> None:
    """Rows from before 9.5b (stage NULL) did not count in 9.5b either."""
    pg.execute(text("INSERT INTO reminders_sent (vehicle_id, service_id, message_text, method, model_version, "
                    "predicted_date, send_on) VALUES (4, 7, 'x', 'b0', 'ridge-test', '2026-06-20', '2026-06-08')"))
    assert 4 in due_ids(client)


@pytest.mark.parametrize(("service_id", "code"), [
    (5, 422),        # v2: reminder day 2027-02-02 (9.14a pace, capped): not due yet
    (9, 422),        # v5 mine truck (engine hours only): no reminders
    (999_999, 404),
])
def test_mark_sent_refusals(client: TestClient, service_id: int, code: int) -> None:
    assert sent(client, service_id).status_code == code


def test_stop_phone_removes_its_reminders_and_can_be_undone(client: TestClient) -> None:
    phone = new_service(client, "0004 ТЕС", "2026-07-01", phone="99110077")
    vid, sid = phone["vehicle_id"], phone["service"]["id"]
    r = client.post("/reminders/stops", json={"phone": "+976 9911-0077"})
    assert r.status_code == 201 and r.json()["phone"] == "99110077"
    assert client.post("/reminders/stops", json={"phone": "99110077"}).status_code == 200  # idempotent
    assert [s["phone"] for s in client.get("/reminders/stops").json()] == ["99110077"]
    assert vid not in due_ids(client) and 4 in due_ids(client)  # v4 has another phone
    assert sent(client, sid).status_code == 422
    assert client.delete("/reminders/stops/99110077").status_code == 204
    assert vid in due_ids(client) and client.get("/reminders/stops").json() == []
    assert client.delete("/reminders/stops/99110077").status_code == 204                  # already gone
    assert client.post("/reminders/stops", json={"phone": "123"}).status_code == 422


def test_reminders_work_without_model_files(pg: Connection, tmp_path: Path) -> None:  # noqa: F811
    """Reminders need no ML model (since 9.5b; was 503 before)."""
    savepoint = pg.begin_nested()

    def test_session() -> Iterator[Session]:
        with Session(bind=pg, join_transaction_mode="create_savepoint") as session:
            yield session

    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=tmp_path)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_today] = lambda: TODAY
    with TestClient(app) as no_model:
        assert no_model.get("/reminders/due").status_code == 200
        assert no_model.get("/stats/segments").json()["counts"]["at_risk"] == 1
    savepoint.rollback()


def test_segments_at_risk_after_150_days(client: TestClient) -> None:
    later = client.get("/stats/segments", params={"as_of": "2027-03-01"}).json()
    assert later["counts"]["at_risk"] == later["total"] == 6   # every sample truck 150+ days out by then
    now = client.get("/stats/segments").json()
    assert now["counts"]["at_risk"] == 1                       # v4 (05-10, 155 days); v1 is 63 days
    assert client.get("/stats/segments", params={"as_of": "2026-10-06"}).json()["counts"]["at_risk"] == 0
    assert client.get("/vehicles/4").json()["segment"] == "at_risk"


def test_segments_and_cards_agree(client: TestClient) -> None:
    stats = client.get("/stats/segments").json()["counts"]
    cards = [client.get(f"/vehicles/{v}").json()["segment"] for v in range(1, 7)]
    assert {s: cards.count(s) for s in stats if cards.count(s)} == {s: n for s, n in stats.items() if n}


def test_post_service_finds_fleet_truck_without_dash(client: TestClient) -> None:
    r = client.post("/services", json={"identifier_type": "fleet_no", "identifier": "ht 12",
                                       "company_name": "Өмнөд Уурхай ХХК", "service_date": "2026-10-01",
                                       "engine_hours": 9000, "oil_grade": "15W-40", "liters": 60,
                                       "destination_raw": "Оюу толгой", "route": "mine_site"})
    assert r.status_code == 201, r.text
    assert (r.json()["vehicle_id"], r.json()["vehicle_created"]) == (5, False)


# ==========================================================================
# HEIC photos
# ==========================================================================

def heic_bytes(size: tuple[int, int] = (40, 20)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (200, 10, 10)).save(buf, format="HEIF")
    return buf.getvalue()


def test_heic_is_read() -> None:
    rgb = R.load_upright_rgb(heic_bytes())
    assert rgb.shape == (20, 40, 3) and tuple(rgb[5, 5]) == pytest.approx((200, 10, 10), abs=6)


def test_recognize_accepts_heic(tmp_path: Path) -> None:
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=tmp_path)
    with TestClient(app) as client:
        app.state.recognizer = StubRecognizer()
        r = client.post("/plates/recognize", files={"file": ("IMG_0001.HEIC", heic_bytes(), "image/heic")})
        assert r.status_code == 200 and r.json()["plate_normalized"] == "1234УБА"
