"""Tests for tasks 4.4 + 9.5b: month-stage reminders, stop phones, segments (90-day at_risk),
migrations 003 + 006, fleet numbers, HEIC.

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
from src.api.config import PLACEHOLDER_PHONE, Contact, reminder_contact
from src.api.db import get_session
from src.api.main import create_app
from src.api.reminders import due_stage, format_km, message_mn, segment_of, stage_day, stage_reached
from src.api.routers.reminders import get_contact
from src.cv import plate_reader as R
from tests.test_api_data import pg  # noqa: F401  (Postgres: schema + 001 + 003 + sample data)
from tests.test_schema import database_url
from tests.test_serving import StubRecognizer, model_dir, predictor, visit  # noqa: F401  (fixtures)

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "src" / "data"
TODAY = date(2026, 10, 12)
CONTACT = Contact(name="Geo-Expert", phone="99000001", is_placeholder=False)


# ==========================================================================
# Message + contact (9.5b: Ari's month texts)
# ==========================================================================

def test_month_messages_exact_text() -> None:
    args = ("1234 УБА", date(2026, 8, 10), "15W-40", 270_500, CONTACT)
    assert message_mn("1m", *args) == (
        "Сайн байна уу! Гео-Эксперт ХХК-ийн тосыг сонгосонд баярлалаа. 1234 УБА машины тос солиулснаас хойш "
        "1 сар боллоо (2026.08.10, 15W-40). Дараагийн солилт: 270 500 км-т. Гүйлтээ шалгаарай. Сайн яваарай! "
        "99000001")
    assert message_mn("2m", *args) == (
        "Сайн байна уу! 1234 УБА машины тос солиулснаас хойш 2 сар боллоо. Дараагийн солилт: 270 500 км-т. "
        "Гүйлтээ шалгахаа мартуузай. 99000001")
    assert message_mn("3m", *args) == (
        "Сайн байна уу! 1234 УБА машин 270 500 км-т хүрсэн бол тосоо солих цаг боллоо. "
        "Бид таны байгаа газар очиж сольж өгнө. 99000001")


@pytest.mark.parametrize(("km", "shown"), [(270_500, "270 500"), (15_000, "15 000"), (1_234_567, "1 234 567"),
                                           (900, "900")])
def test_format_km(km: int, shown: str) -> None:
    assert format_km(km) == shown


def test_contact_phone_wins_then_old_setting_then_placeholder() -> None:
    assert reminder_contact({}) == Contact("Geo-Expert", PLACEHOLDER_PHONE, is_placeholder=True)
    assert reminder_contact({"GEO_EXPERT_PHONE": " 88112233 ", "GEO_EXPERT_NAME": "Гео Эксперт"}) == \
        Contact("Гео Эксперт", "88112233", is_placeholder=False)
    assert reminder_contact({"CONTACT_PHONE": "99887766", "GEO_EXPERT_PHONE": "88112233"}).phone == "99887766"
    assert reminder_contact({"CONTACT_PHONE": "  ", "GEO_EXPERT_PHONE": "88112233"}).phone == "88112233"


# ==========================================================================
# Stage + segment rules (pure)
# ==========================================================================

LAST = date(2026, 8, 1)


@pytest.mark.parametrize(("days", "stage"), [(0, None), (29, None), (30, "1m"), (59, "1m"), (60, "2m"),
                                             (65, "2m"), (89, "2m"), (90, "3m"), (400, "3m")])
def test_stage_reached(days: int, stage: str | None) -> None:
    assert stage_reached(LAST, LAST + timedelta(days=days)) == stage


def test_day_65_only_2m_and_each_stage_once() -> None:
    day65 = LAST + timedelta(days=65)
    assert due_stage(LAST, day65, set()) == "2m"            # 1m was missed: skipped, never offered
    assert due_stage(LAST, day65, {"1m"}) == "2m"
    assert due_stage(LAST, day65, {"2m"}) is None           # sent once -> not again
    assert due_stage(LAST, LAST + timedelta(days=95), {"1m", "2m"}) == "3m"
    assert due_stage(LAST, LAST + timedelta(days=200), {"3m"}) is None  # nothing after 3m
    assert due_stage(LAST, LAST + timedelta(days=10), set()) is None


def test_stage_day() -> None:
    assert [stage_day(LAST, s) for s in ("1m", "2m", "3m")] == [date(2026, 8, 31), date(2026, 9, 30),
                                                                 date(2026, 10, 30)]


@pytest.mark.parametrize(("count", "days", "segment"), [
    (1, 10, "new"), (2, 89, "returning"), (3, 89, "loyal"), (7, 30, "loyal"),
    (1, 90, "at_risk"), (9, 120, "at_risk"),   # 90+ days without a new service: at_risk wins
])
def test_segment_rule_90_days(count: int, days: int, segment: str) -> None:
    assert segment_of(count, LAST, LAST + timedelta(days=days)) == segment


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
    r = client.post("/services", json={"identifier": plate, "company_name": "Test 9.5b", "service_date": day,
                                       "odometer_km": km, "oil_grade": "10W-40", "liters": 36.5,
                                       "driver_phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


def due(client: TestClient, **params: str) -> dict:
    r = client.get("/reminders/due", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def stages(client: TestClient, **params: str) -> dict[int, str]:
    return {r["vehicle_id"]: r["stage"] for r in due(client, **params)["reminders"]}


def sent(client: TestClient, service_id: int, stage: str):
    return client.post(f"/reminders/{service_id}/sent", params={"stage": stage})


def test_due_list_month_stages(client: TestClient) -> None:
    """Sample data on 10-12: v1 08-10 (63 d) -> 2m (1m skipped) · v2 09-10 (32 d) -> 1m ·
    v3 09-20 (22 d) -> nothing · v4 05-10 (155 d) -> 3m, at risk · v5 mine truck (engine hours) ->
    no reminder · v6 09-01 (41 d) -> 1m."""
    result = due(client)
    assert result["as_of"] == TODAY.isoformat() and result["contact_is_placeholder"] is False
    assert {r["vehicle_id"]: r["stage"] for r in result["reminders"]} == {1: "2m", 2: "1m", 4: "3m", 6: "1m"}
    sends = [r["send_on"] for r in result["reminders"]]
    assert sends == sorted(sends)  # oldest stage day first
    v1 = next(r for r in result["reminders"] if r["vehicle_id"] == 1)
    assert (v1["service_id"], v1["days_since"], v1["send_on"], v1["odometer_km"], v1["target_km"], v1["segment"]) == \
        (3, 63, "2026-10-09", 255_500, 270_500, "loyal")
    assert (v1["identifier"], v1["phone"], v1["last_change_date"], v1["oil_grade"]) == \
        ("1234 УБА", "99110002", "2026-08-10", "15W-40")
    assert v1["message_mn"] == message_mn("2m", "1234 УБА", date(2026, 8, 10), "15W-40", 270_500, CONTACT)
    v4 = next(r for r in result["reminders"] if r["vehicle_id"] == 4)
    assert (v4["stage"], v4["segment"]) == ("3m", "at_risk")


def test_day_65_shows_only_2m(client: TestClient) -> None:
    vid = new_service(client, "0000 ТЕС", "2026-08-08")["vehicle_id"]  # 65 days before 10-12
    assert stages(client)[vid] == "2m"
    assert stages(client, as_of="2026-09-15")[vid] == "1m"            # 38 days: 1m


def test_each_stage_once_then_the_next(client: TestClient) -> None:
    created = new_service(client, "0001 ТЕС", "2026-09-10")             # 32 days -> 1m
    vid, sid = created["vehicle_id"], created["service"]["id"]
    assert sent(client, sid, "1m").status_code == 201
    assert vid not in stages(client)                                   # 1m sent, 2m not yet
    assert stages(client, as_of="2026-11-10")[vid] == "2m"              # day 61
    assert stages(client, as_of="2026-12-10")[vid] == "3m"              # day 91


def test_double_sent_makes_one_row(client: TestClient, pg: Connection) -> None:
    first = sent(client, 3, "2m")
    assert first.status_code == 201
    body = first.json()
    assert (body["service_id"], body["vehicle_id"], body["stage"], body["already_sent"]) == (3, 1, "2m", False)
    assert body["send_on"] == "2026-10-09" and body["method"] is None and body["phone"] == "99110002"
    again = sent(client, 3, "2m")
    assert again.status_code == 200 and again.json() == body | {"already_sent": True}
    rows = pg.execute(text("SELECT count(*) FROM reminders_sent WHERE service_id = 3 AND stage = '2m'")).scalar_one()
    assert rows == 1
    assert 1 not in stages(client)


def test_truck_returns_resets_stages(client: TestClient) -> None:
    old = new_service(client, "0002 ТЕС", "2026-07-01", km=100_000)    # 103 days -> 3m
    vid, old_id = old["vehicle_id"], old["service"]["id"]
    assert stages(client)[vid] == "3m" and sent(client, old_id, "3m").status_code == 201
    assert vid not in stages(client)
    back = new_service(client, "0002 ТЕС", "2026-09-01", km=118_000)  # came back: new service, 41 days
    item = next(r for r in due(client)["reminders"] if r["vehicle_id"] == vid)
    assert (item["stage"], item["service_id"], item["target_km"]) == ("1m", back["service"]["id"], 133_000)
    assert item["segment"] == "returning"                             # no longer at risk
    assert sent(client, old_id, "3m").status_code == 200              # stored before: still idempotent
    stale = sent(client, old_id, "2m")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "not_latest_service"


@pytest.mark.parametrize(("service_id", "stage", "code"), [
    (6, "1m", 422),       # v3, 22 days: 1m has not started
    (3, "3m", 422),       # v1, 63 days: 3m has not started
    (9, "1m", 422),       # v5 mine truck (engine hours only): no reminders
    (999_999, "1m", 404),
])
def test_mark_sent_refusals(client: TestClient, service_id: int, stage: str, code: int) -> None:
    assert sent(client, service_id, stage).status_code == code


def test_mark_sent_needs_a_valid_stage(client: TestClient) -> None:
    assert client.post("/reminders/3/sent").status_code == 422
    assert sent(client, 3, "6m").status_code == 422


def test_stop_phone_removes_its_reminders_and_can_be_undone(client: TestClient) -> None:
    r = client.post("/reminders/stops", json={"phone": "+976 9911-0002"})
    assert r.status_code == 201 and r.json()["phone"] == "99110002"
    assert client.post("/reminders/stops", json={"phone": "99110002"}).status_code == 200  # idempotent
    assert [s["phone"] for s in client.get("/reminders/stops").json()] == ["99110002"]
    assert 1 not in stages(client) and 6 in stages(client)  # v1's latest driver stopped; v6 has another phone
    assert sent(client, 3, "2m").status_code == 422
    assert client.delete("/reminders/stops/99110002").status_code == 204
    assert stages(client)[1] == "2m" and client.get("/reminders/stops").json() == []
    assert client.delete("/reminders/stops/99110002").status_code == 204                  # already gone
    assert client.post("/reminders/stops", json={"phone": "123"}).status_code == 422


def test_reminders_work_without_model_files(pg: Connection, tmp_path: Path) -> None:  # noqa: F811
    """9.5b: month stages need no ML model (was 503 before)."""
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


def test_segments_at_risk_after_90_days(client: TestClient) -> None:
    later = client.get("/stats/segments", params={"as_of": "2027-01-01"}).json()
    assert later["counts"]["at_risk"] == later["total"] == 6   # every sample truck 90+ days out by then
    now = client.get("/stats/segments").json()
    assert now["counts"]["at_risk"] == 1                       # v4 (05-10, 155 days); v1 is 63 days
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
