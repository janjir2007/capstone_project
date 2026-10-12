"""Tests for task 4.4: reminders, segments with at_risk, migration 003, fleet numbers, HEIC.

Fake data only: sample_data.sql (100% synthetic) + trucks created here, the
fake Ridge folder from tests/test_serving.py. Postgres tests skip without a
running database (``docker compose up -d db``).
"""

from __future__ import annotations

import io
import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path

import psycopg
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Connection, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import prediction as P
from src.api.clock import get_today
from src.api.config import PLACEHOLDER_PHONE, Contact, reminder_contact
from src.api.db import get_session
from src.api.main import create_app
from src.api.reminders import format_liters, message_mn
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
# Message + contact
# ==========================================================================

def test_message_has_plate_last_change_oil_and_contact() -> None:
    text = message_mn("1234 УБА", date(2026, 8, 10), "15W-40", Decimal("32.0"), overdue=False, contact=CONTACT)
    assert text == ("Сайн байна уу! 1234 УБА дугаартай машины тос солих хугацаа ойртлоо. "
                    "Сүүлд сольсон: 2026.08.10 (15W-40, 32 л). Geo-Expert: 99000001")


def test_overdue_message_says_time_has_come() -> None:
    text = message_mn("HT-12", date(2026, 1, 5), "15W-40", 40.5, overdue=True, contact=CONTACT)
    assert "хугацаа болсон байна." in text and "2026.01.05" in text and "40.5 л" in text


@pytest.mark.parametrize(("liters", "shown"), [(Decimal("32.0"), "32"), (Decimal("32.5"), "32.5"), (38, "38"),
                                               (Decimal("100.0"), "100")])
def test_format_liters(liters: Decimal | int, shown: str) -> None:
    assert format_liters(liters) == shown


def test_contact_from_env_and_placeholder_flag() -> None:
    assert reminder_contact({}) == Contact("Geo-Expert", PLACEHOLDER_PHONE, is_placeholder=True)
    assert reminder_contact({"GEO_EXPERT_PHONE": " 88112233 ", "GEO_EXPERT_NAME": "Гео Эксперт"}) == \
        Contact("Гео Эксперт", "88112233", is_placeholder=False)


# ==========================================================================
# Buffers, batch prediction, segments
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


@pytest.mark.parametrize(("count", "predicted", "segment"), [
    (1, date(2026, 10, 5), "new"),         # 10-05 + 7 = 10-12, not < 10-12
    (1, date(2026, 10, 4), "at_risk"),     # 10-04 + 7 = 10-11 < 10-12
    (2, None, "returning"),
    (3, date(2026, 12, 1), "loyal"),
    (9, date(2026, 1, 1), "at_risk"),      # at_risk wins over loyal
])
def test_segment_rule_d007(count: int, predicted: date | None, segment: str) -> None:
    assert P.segment_of(count, predicted, TODAY) == segment


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
# Endpoints on Postgres (sample data + fake model)
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


def new_service(client: TestClient, plate: str, day: str, destination: str, km: int = 100_000,
                phone: str | None = "99110009") -> dict:
    dest_id = next(d["id"] for d in client.get("/destinations").json() if d["name"] == destination)
    r = client.post("/services", json={"identifier": plate, "company_name": "Test 4.4", "service_date": day,
                                       "odometer_km": km, "oil_grade": "10W-40", "liters": 36.5,
                                       "destination_id": dest_id, "driver_phone": phone})
    assert r.status_code == 201, r.text
    return r.json()


def due(client: TestClient, **params: str) -> dict:
    r = client.get("/reminders/due", params=params)
    assert r.status_code == 200, r.text
    return r.json()


def test_due_list_has_the_right_trucks(client: TestClient) -> None:
    # Sample trucks (no destination -> b0 = 58 days, buffer 12): newest service + 58 − 12 <= 2026-10-12 ?
    #   v1 08-10 -> send 09-25 yes · v2 09-10 -> 10-26 no · v3 09-20 -> 11-05 no
    #   v4 05-10 -> 06-25 yes · v5 08-25 -> 10-10 yes · v6 09-01 -> 10-17 no
    # New trucks, first visit -> b1 (buffer 1):
    #   Beijing 09-01: 17,500 / 501.9 = 34.9 -> 35 d -> 10-06, send 10-05 yes
    #   Kyakhta 10-01: 17,500 / 216.7 = 80.7 -> 81 d -> 12-21, send 12-20 no
    a = new_service(client, "0000 ТЕС", "2026-09-01", "Beijing")["vehicle_id"]
    new_service(client, "0001 ТЕС", "2026-10-01", "Kyakhta (RU side of border)")
    result = due(client)
    assert result["as_of"] == TODAY.isoformat() and result["contact_is_placeholder"] is False
    assert {r["vehicle_id"] for r in result["reminders"]} == {1, 4, 5, a}
    sends = [r["send_on"] for r in result["reminders"]]
    assert sends == sorted(sends)  # oldest reminder day first
    item = next(r for r in result["reminders"] if r["vehicle_id"] == a)
    assert (item["method"], item["buffer_days"], item["predicted_date"], item["send_on"]) == \
        ("b1", 1, "2026-10-06", "2026-10-05")
    assert (item["identifier"], item["phone"], item["last_change_date"], item["oil_grade"], item["liters"]) == \
        ("0000 ТЕС", "99110009", "2026-09-01", "10W-40", 36.5)
    assert (item["status"], item["days_left"]) == ("overdue", -6)
    assert item["message_mn"] == ("Сайн байна уу! 0000 ТЕС дугаартай машины тос солих хугацаа болсон байна. "
                                  "Сүүлд сольсон: 2026.09.01 (10W-40, 36.5 л). Geo-Expert: 99000001")


def test_due_list_as_of_uses_only_services_until_then(client: TestClient) -> None:
    # as_of 2026-06-30: v1's newest service by then = 05-20 -> 07-17, send 07-05 -> not due yet;
    # v4 (05-10 -> send 06-25) is due. Later services do not exist yet on that day.
    ids = {r["vehicle_id"] for r in due(client, as_of="2026-06-30")["reminders"]}
    assert 4 in ids and 1 not in ids


def test_mark_sent_is_idempotent_and_removes_from_due(client: TestClient) -> None:
    item = next(r for r in due(client)["reminders"] if r["vehicle_id"] == 1)
    first = client.post(f"/reminders/{item['service_id']}/sent")
    assert first.status_code == 201
    body = first.json()
    assert (body["service_id"], body["vehicle_id"], body["already_sent"]) == (item["service_id"], 1, False)
    assert body["message_text"] == item["message_mn"] and body["send_on"] == item["send_on"]
    again = client.post(f"/reminders/{item['service_id']}/sent")
    assert again.status_code == 200 and again.json() == body | {"already_sent": True}
    assert 1 not in {r["vehicle_id"] for r in due(client)["reminders"]}


def test_new_service_starts_a_new_cycle_and_old_id_is_409(client: TestClient) -> None:
    a = new_service(client, "0002 ТЕС", "2026-08-01", "Beijing")
    old_service = next(r["service_id"] for r in due(client)["reminders"] if r["vehicle_id"] == a["vehicle_id"])
    assert client.post(f"/reminders/{old_service}/sent").status_code == 201
    b = new_service(client, "0002 ТЕС", "2026-08-20", "Beijing", km=110_000)  # came back: ridge now
    r = client.post(f"/reminders/{old_service}/sent")
    assert r.status_code == 200  # already stored: still idempotent
    other = new_service(client, "0003 ТЕС", "2026-08-01", "Beijing")
    first_service = other["service"]["id"]
    new_service(client, "0003 ТЕС", "2026-09-01", "Beijing", km=115_000)
    stale = client.post(f"/reminders/{first_service}/sent")
    assert stale.status_code == 409 and stale.json()["detail"]["code"] == "not_latest_service"
    assert b["service"]["id"] != old_service


def test_mark_unknown_service_is_404(client: TestClient) -> None:
    assert client.post("/reminders/999999/sent").status_code == 404


def test_segments_count_at_risk_from_predictions(client: TestClient) -> None:
    # Sample trucks are all b0 (58 days). On 2027-01-01 every one is past predicted + 7 -> at_risk.
    later = client.get("/stats/segments", params={"as_of": "2027-01-01"}).json()
    assert later["counts"]["at_risk"] == later["total"] == 6
    # Today: v4 (05-10 -> 07-07, +7 = 07-14 < 10-12) is at risk; v1 (-> 10-07, +7 = 10-14) is not yet.
    now = client.get("/stats/segments").json()
    assert now["counts"]["at_risk"] == 1
    card = client.get("/vehicles/4").json()
    assert card["segment"] == "at_risk" and card["prediction"]["predicted_date"] == "2026-07-07"


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


def test_reminders_503_without_model(pg: Connection, tmp_path: Path) -> None:  # noqa: F811
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=tmp_path)
    with TestClient(app) as client:
        assert client.get("/reminders/due").status_code == 503
        assert client.post("/reminders/1/sent").status_code == 503


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
