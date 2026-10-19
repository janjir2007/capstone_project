"""Demo seed tests (task 4.5): src/data/seed_demo.py.

Part 1 needs no database: the demo is built from the real generator config
with a FAKE Ridge model (tests/test_serving.py fixture, the pre-2.9 buffers:
ridge 7, b0 12, b1 1) and checked for the "done when" of the brief: every
segment and status, 5–10 due reminders, fake identities only. The plan is also
checked against the SERVED buffers (task 2.9: ridge 16, b0 13, b1 4), and, when
models/ exists, built with the real served model (task 7.2).

Part 2 writes the demo into a throwaway schema of the local Postgres
(schema + migrations 001–005, nothing else) and calls the real endpoints.
SKIPPED if Postgres is not running.
"""

from __future__ import annotations

import re
import uuid
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import pandas as pd
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Connection, create_engine, func, select
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import prediction as P
from src.api.clock import get_today
from src.api.config import Contact, to_sqlalchemy_url
from src.api.db import create_db_engine, database_is_up, get_session
from src.api.main import create_app
from src.api.models import ReminderSent
from src.api.routers.reminders import get_contact
from src.common.plates import is_valid_plate, normalize_plate
from src.data import seed_demo as D
from src.data.generator import DEFAULT_CONFIG, generate_clean, load_config
from tests.test_schema import database_url
from tests.test_serving import model_dir, predictor  # noqa: F401  (fixtures: fake Ridge + real route table)

ROOT = Path(__file__).resolve().parent.parent
SQL_DIR = ROOT / "src" / "data"
SQL_FILES = ["schema.sql", "migrations/001_destinations.up.sql", "migrations/002_destinations_name_mn.up.sql",
             "migrations/003_reminders_sent.up.sql", "migrations/004_destinations_name_mn_rest.up.sql",
             "migrations/005_destinations_cross_border.up.sql"]
TODAY = date(2026, 10, 12)
CONTACT = Contact(name="Geo-Expert", phone="99000001", is_placeholder=False)


@pytest.fixture(scope="module")
def clean() -> pd.DataFrame:
    """Synthetic clean records from the real generator config (seed 42)."""
    return generate_clean(load_config(ROOT / DEFAULT_CONFIG))


@pytest.fixture(scope="module")
def trucks(clean: pd.DataFrame, predictor: P.Predictor) -> list[D.DemoTruck]:  # noqa: F811
    return D.build_demo(clean, predictor, TODAY)


def by_plate(trucks: list[D.DemoTruck], plate: str) -> D.DemoTruck:
    return next(t for t in trucks if t.plate_normalized == plate)


# ==========================================================================
# Part 1 — no database
# ==========================================================================

def test_plan_is_about_40_trucks_with_1_to_5_services() -> None:
    assert len(D.PLAN) == 40
    assert {s.services for s in D.PLAN} == {1, 2, 3, 4, 5}
    fixed = [s.plate for s in D.PLAN if s.plate]
    assert len(fixed) == len(set(fixed)) == 4
    assert all(is_valid_plate(p) for p in fixed)


@pytest.mark.parametrize("today", [TODAY, date(2026, 10, 20), date(2027, 1, 15), date(2027, 7, 1)])
def test_every_segment_status_and_5_to_10_due(clean: pd.DataFrame, predictor: P.Predictor,  # noqa: F811
                                              today: date) -> None:
    """The brief's 'done when', on several seed days (summer, autumn, winter)."""
    trucks = D.build_demo(clean, predictor, today)
    assert D.problems(D.summary(trucks, predictor, today)) == []


SERVED_2_9_BUFFERS = {"ridge": 16, "b0": 13, "b1": 4}  # models/ since task 2.9 (docs/ml_results.md)
FIXTURE_BUFFERS = {"ridge": 7, "b0": 12, "b1": 1}  # tests/test_serving.py fake model


@pytest.mark.parametrize("buffers", [SERVED_2_9_BUFFERS, FIXTURE_BUFFERS])
def test_plan_gives_5_to_10_due_with_these_buffers(buffers: dict[str, int]) -> None:
    """Task 7.2: the 2.9 buffers put 13 trucks on the list with the old plan; the plan must fit both."""
    assert 5 <= D.planned_due(buffers) <= 10


def test_slot_method_follows_prediction_rules() -> None:
    assert D.slot_method(D.Slot(1, 10)) == "b1"
    assert D.slot_method(D.Slot(3, 10)) == "ridge"
    assert D.slot_method(D.Slot(3, 25, newest_destination=D.UB_CITY)) == "b0"
    assert D.slot_method(D.Slot(2, 22, newest_raw=D.RAW_DESTINATION)) == "b0"


@pytest.mark.skipif(not (ROOT / "models" / "next_change_model.joblib").exists(),
                    reason="needs the served model files in models/ (git-ignored)")
def test_real_served_model_builds_a_seedable_demo(clean: pd.DataFrame) -> None:
    """What `python -m src.data.seed_demo` checks before writing, with the REAL model + buffers."""
    real = P.load_predictor(ROOT / "models")
    built = D.build_demo(clean, real, TODAY)
    assert D.problems(D.summary(built, real, TODAY)) == []
    overdue = by_plate(built, D.PLATE_OVERDUE)
    assert overdue.prediction.status == "overdue" and D.is_due(overdue, real, TODAY)


def test_problems_reports_what_is_missing() -> None:
    from collections import Counter
    s = {"segments": Counter(new=3, loyal=1), "statuses": Counter(ok=4), "methods": Counter(), "due": 2}
    assert D.problems(s) == ["segment returning is empty", "segment at_risk is empty",
                             "status due_soon is empty", "status overdue is empty",
                             "due list has 2 trucks, wanted 5–10"]


def test_identities_are_fake_and_in_real_format(trucks: list[D.DemoTruck]) -> None:
    plates = [t.plate_normalized for t in trucks]
    assert len(set(plates)) == len(plates) == 40
    for t in trucks:
        assert is_valid_plate(t.plate_normalized)                    # 4 digits + 3 allowed letters
        assert normalize_plate(t.identifier) == t.plate_normalized   # '1001 УБА' -> '1001УБА'
        assert t.company.startswith("Демо ")
        for s in t.services:
            assert re.fullmatch(r"0000[0-9]{4}", s.driver_phone)     # never a real number
            assert s.driver_name


def test_dates_are_past_ordered_and_odometer_grows(trucks: list[D.DemoTruck]) -> None:
    for slot, t in zip(D.PLAN, trucks):
        assert len(t.services) == slot.services
        days = [s.service_date for s in t.services]
        assert days == sorted(days) and len(set(days)) == len(days)
        assert days[-1] <= TODAY                                     # no service in the future
        km = [s.odometer_km for s in t.services]
        assert km == sorted(km)


def test_trucks_land_near_their_planned_day(trucks: list[D.DemoTruck]) -> None:
    """Exact, except at a season edge (the season feature jumps): then at most a few days off."""
    misses = [abs(t.prediction.days_left - s.days_left) for s, t in zip(D.PLAN, trucks)]
    assert max(misses) <= 3


def test_documented_plates(trucks: list[D.DemoTruck], predictor: P.Predictor) -> None:  # noqa: F811
    loyal, overdue = by_plate(trucks, D.PLATE_LOYAL), by_plate(trucks, D.PLATE_OVERDUE)
    new, at_risk = by_plate(trucks, D.PLATE_NEW), by_plate(trucks, D.PLATE_AT_RISK)
    assert (D.segment(loyal, TODAY), loyal.prediction.status, loyal.prediction.method) == ("loyal", "ok", "ridge")
    assert len(loyal.services) == 5
    assert (overdue.prediction.status, D.is_due(overdue, predictor, TODAY)) == ("overdue", True)
    assert (D.segment(new, TODAY), new.prediction.method) == ("new", "b1")   # first visit -> B1
    assert D.segment(at_risk, TODAY) == "at_risk"
    assert at_risk.reminder_sent and not D.is_due(at_risk, predictor, TODAY)


def test_b0_fallback_trucks(trucks: list[D.DemoTruck]) -> None:
    """One truck going to UB city (route not modelled) and one typed by hand -> B0."""
    ub = next(t for s, t in zip(D.PLAN, trucks) if s.newest_destination)
    raw = next(t for s, t in zip(D.PLAN, trucks) if s.newest_raw)
    assert (ub.services[-1].route, ub.prediction.method) == ("ub_city", "b0")
    assert (raw.services[-1].destination, raw.services[-1].destination_raw) == (None, D.RAW_DESTINATION)
    assert raw.prediction.method == "b0"


def test_shared_driver_phone(trucks: list[D.DemoTruck]) -> None:
    """D-004: the overdue truck's driver drove the loyal truck's 2 oldest services."""
    phone = by_plate(trucks, D.PLATE_OVERDUE).services[-1].driver_phone
    loyal = by_plate(trucks, D.PLATE_LOYAL)
    assert [s.driver_phone == phone for s in loyal.services] == [True, True, False, False, False]


def test_same_trucks_every_run(clean: pd.DataFrame, predictor: P.Predictor,  # noqa: F811
                               trucks: list[D.DemoTruck]) -> None:
    assert D.build_demo(clean, predictor, TODAY) == trucks


def test_fit_dates_never_puts_a_service_in_the_future(trucks: list[D.DemoTruck],
                                                      predictor: P.Predictor) -> None:  # noqa: F811
    """A target further away than the model's prediction cannot be reached: newest service = today."""
    services, prediction = D.fit_dates(trucks[0].services, 300, predictor, TODAY)
    assert services[-1].service_date == TODAY
    assert prediction.days_left < 300


# ==========================================================================
# Part 2 — the demo in Postgres, through the API
# ==========================================================================

@pytest.fixture(scope="module")
def empty_pg() -> Iterator[Connection]:
    """Throwaway schema with schema.sql + migrations 001–005 and NO rows (like a fresh compose)."""
    engine = create_db_engine(to_sqlalchemy_url(database_url()))
    if not database_is_up(engine):
        engine.dispose()
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")
    connection = engine.connect()
    outer = connection.begin()
    schema = f"test_demo_{uuid.uuid4().hex[:8]}"
    connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
    connection.exec_driver_sql(f"SET search_path TO {schema}")
    raw = connection.connection.driver_connection
    for name in SQL_FILES:
        raw.execute((SQL_DIR / name).read_text(encoding="utf-8"))
    yield connection
    outer.rollback()
    connection.close()
    engine.dispose()


@pytest.fixture
def seeded(empty_pg: Connection, trucks: list[D.DemoTruck],
           predictor: P.Predictor) -> Iterator[Connection]:  # noqa: F811
    """The demo written into the empty schema, inside a savepoint undone after the test."""
    savepoint = empty_pg.begin_nested()
    with Session(bind=empty_pg, join_transaction_mode="create_savepoint") as session:
        D.insert_demo(session, trucks, predictor, CONTACT)
        session.commit()
    yield empty_pg
    savepoint.rollback()


@pytest.fixture
def client(seeded: Connection, model_dir: Path) -> Iterator[TestClient]:  # noqa: F811
    def test_session() -> Iterator[Session]:
        with Session(bind=seeded, join_transaction_mode="create_savepoint") as session:
            yield session

    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=model_dir)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_today] = lambda: TODAY
    app.dependency_overrides[get_contact] = lambda: CONTACT
    with TestClient(app) as test_client:
        yield test_client


def test_segments_all_four(client: TestClient) -> None:
    body = client.get("/stats/segments").json()
    assert body["total"] == 40
    assert all(body["counts"][s] > 0 for s in ("new", "returning", "loyal", "at_risk")), body


def test_due_list_5_to_10_and_matches_the_build(client: TestClient, trucks: list[D.DemoTruck],
                                               predictor: P.Predictor) -> None:  # noqa: F811
    due = client.get("/reminders/due").json()["reminders"]
    assert 5 <= len(due) <= 10
    expected = {t.plate_normalized for t in trucks if D.is_due(t, predictor, TODAY)}
    assert {r["plate_normalized"] for r in due} == expected
    assert D.PLATE_OVERDUE in expected and D.PLATE_AT_RISK not in expected  # sent reminders are left out


@pytest.mark.parametrize("q", ["1001 УБА", "1001уба", "1002 УБЕ", "1003 УНА", "1004 УБВ"])
def test_documented_plates_are_found(client: TestClient, q: str) -> None:
    result = client.get("/vehicles/lookup", params={"q": q}).json()
    assert result["match_type"] == "plate"
    assert [v["plate_normalized"] for v in result["vehicles"]] == [normalize_plate(q)]
    card = result["vehicles"][0]
    assert card["prediction"] is not None and card["history"]


def test_documented_cards(client: TestClient) -> None:
    def card(q: str) -> dict:
        return client.get("/vehicles/lookup", params={"q": q}).json()["vehicles"][0]
    loyal = card("1001 УБА")
    assert (loyal["segment"], loyal["service_count"], loyal["prediction"]["method"]) == ("loyal", 5, "ridge")
    assert loyal["last_service"]["destination"]["name_mn"]  # Mongolian label (migration 002)
    assert card("1002 УБЕ")["prediction"]["status"] == "overdue"
    assert (card("1003 УНА")["segment"], card("1003 УНА")["prediction"]["method"]) == ("new", "b1")
    assert card("1004 УБВ")["segment"] == "at_risk"


def test_shared_phone_finds_two_trucks(client: TestClient, trucks: list[D.DemoTruck]) -> None:
    phone = by_plate(trucks, D.PLATE_OVERDUE).services[-1].driver_phone
    result = client.get("/vehicles/lookup", params={"q": phone}).json()
    assert result["match_type"] == "phone"
    assert {v["plate_normalized"] for v in result["vehicles"]} == {D.PLATE_OVERDUE, D.PLATE_LOYAL}


def test_sent_reminders_stored_like_the_api_would(seeded: Connection, trucks: list[D.DemoTruck]) -> None:
    with Session(bind=seeded) as session:
        rows = session.scalars(select(ReminderSent)).all()
        assert len(rows) == sum(t.reminder_sent for t in trucks) == 2
        for row in rows:
            assert row.send_on <= row.predicted_date and row.sent_at.date() == row.send_on
            assert "Geo-Expert: 99000001" in row.message_text


def test_seed_refuses_a_database_that_is_not_empty(seeded: Connection, trucks: list[D.DemoTruck],
                                                   predictor: P.Predictor) -> None:  # noqa: F811
    with Session(bind=seeded, join_transaction_mode="create_savepoint") as session:
        before = session.scalar(select(func.count()).select_from(ReminderSent))
        with pytest.raises(RuntimeError, match="not empty"):
            D.insert_demo(session, trucks, predictor, CONTACT)
        assert session.scalar(select(func.count()).select_from(ReminderSent)) == before
