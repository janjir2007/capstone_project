"""Data endpoint tests (task 4.2): lookup, POST /services, vehicle card, segments.

Part 1 needs no database (phone normalization, request rules, usual liters)
and runs in CI.

Part 2 calls the endpoints against the REAL local Postgres with schema.sql +
migration 001 + sample_data.sql loaded into a throwaway schema (the endpoints
use Postgres-only features: vehicle_segments(), DISTINCT ON). SKIPPED if
Postgres is not running, like tests/test_schema.py (CI gets Postgres in 6.2).

Isolation: one outer transaction per module (rolled back at the end) and one
savepoint per test (rolled back after the test), so tests do not see each
other's writes and the dev database is never changed. "Today" is frozen at
2026-09-30, the date the sample data's expected segments are written for
(docs/data_dictionary.md §5).
"""

import uuid
from collections.abc import Iterator
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from sqlalchemy import Connection, create_engine, text
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api.clock import get_today
from src.api.config import to_sqlalchemy_url
from src.api.db import create_db_engine, database_is_up, get_session
from src.api.main import create_app
from src.api.routers.vehicles import usual_liters
from src.api.schemas import ServiceCreate, normalize_phone
from tests.test_schema import database_url

SQL_DIR = Path(__file__).resolve().parent.parent / "src" / "data"
SQL_FILES = ["schema.sql", "migrations/001_destinations.up.sql", "sample_data.sql"]
TODAY = date(2026, 9, 30)


# ==========================================================================
# Part 1 — no database
# ==========================================================================

@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("99110001", "99110001"),
        ("9911 0001", "99110001"),
        ("9911-0001", "99110001"),
        ("+976 9911 0001", "99110001"),
        ("97699110001", "99110001"),
        ("(+976) 9911-0001", "99110001"),
    ],
)
def test_normalize_phone(raw: str, expected: str) -> None:
    assert normalize_phone(raw) == expected


@pytest.mark.parametrize("raw", ["9911000", "991100011", "1234УБА", "+7 9911 0001", "", "+976"])
def test_invalid_phone_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_phone(raw)


def service_body(**overrides: Any) -> dict[str, Any]:
    """A valid POST /services body (synthetic values); override any field."""
    body: dict[str, Any] = {
        "identifier": "4321 УБД",
        "company_name": "Туршилт Тээвэр ХХК",
        "odometer_km": 120000,
        "oil_grade": "15W-40",
        "liters": 30.0,
        "destination_raw": "Сайншанд",
        "route": "mixed",
        "driver_name": "Туршилт Ж.",
        "driver_phone": "99110009",
    }
    body.update(overrides)
    return body


def test_valid_body_accepted_and_cleaned() -> None:
    body = ServiceCreate.model_validate(
        service_body(oil_grade=" 15W-40 ", driver_name="  ", driver_phone="+976 9911-0009")
    )
    assert body.oil_grade == "15W-40"        # stripped
    assert body.driver_name is None          # blank -> not given
    assert body.driver_phone == "99110009"   # normalized
    assert body.liters == Decimal("30.0")


@pytest.mark.parametrize(
    ("overrides", "message"),
    [
        ({"odometer_km": None}, "odometer_km or engine_hours"),
        ({"destination_raw": None}, "exactly one of destination_id or destination_raw"),
        ({"destination_id": 2}, "exactly one of destination_id or destination_raw"),
        ({"route": None}, "route is required"),                  # D-039: free text -> route required
        ({"destination_raw": "   ", "destination_id": None}, "exactly one"),  # blank text = not given
        ({"driver_phone": "12345"}, "8 digits"),
        ({"liters": 0}, "greater than 0"),
        ({"liters": 30.25}, "decimal place"),                     # NUMERIC(5,1)
        ({"oil_grade": "  "}, "at least 1 character"),
        ({"route": "mars"}, "route"),
        ({"identifier_type": "vin"}, "identifier_type"),
        ({"odometr_km": 5}, "Extra inputs are not permitted"),     # typo in field name
    ],
)
def test_invalid_body_rejected(overrides: dict[str, Any], message: str) -> None:
    with pytest.raises(ValidationError, match=message):
        ServiceCreate.model_validate(service_body(**overrides))


def test_engine_hours_alone_is_enough() -> None:
    """Mine trucks: engine hours instead of km (schema CHECK has_meter)."""
    body = ServiceCreate.model_validate(service_body(odometer_km=None, engine_hours=12500.5))
    assert body.engine_hours == Decimal("12500.5")


@pytest.mark.parametrize(
    ("liters", "expected"),
    [
        ([], None),
        ([Decimal("32.0")], Decimal("32.0")),
        ([Decimal("32.0"), Decimal("30.0"), Decimal("32.0")], Decimal("32.0")),  # mode
        ([Decimal("30.0"), Decimal("32.0")], Decimal("30.0")),                     # tie -> newest
        ([Decimal("28.0"), Decimal("32.0"), Decimal("32.0"), Decimal("28.0")], Decimal("28.0")),
    ],
)
def test_usual_liters(liters: list[Decimal], expected: Decimal | None) -> None:
    """Input is newest first, like the card's history."""
    assert usual_liters(liters) == expected


# ==========================================================================
# Part 2 — endpoints on the real local Postgres
# ==========================================================================

@pytest.fixture(scope="module")
def pg() -> Iterator[Connection]:
    """One connection with schema + migration 001 + sample data in a temporary schema."""
    engine = create_db_engine(to_sqlalchemy_url(database_url()))
    if not database_is_up(engine):
        engine.dispose()
        pytest.skip("PostgreSQL not reachable (run `docker compose up -d db`)")

    connection = engine.connect()
    outer = connection.begin()
    schema = f"test_api_{uuid.uuid4().hex[:8]}"
    connection.exec_driver_sql(f"CREATE SCHEMA {schema}")
    connection.exec_driver_sql(f"SET search_path TO {schema}")
    # The raw psycopg connection runs a whole multi-statement SQL file at once.
    raw = connection.connection.driver_connection
    for name in SQL_FILES:
        raw.execute((SQL_DIR / name).read_text(encoding="utf-8"))
    yield connection
    outer.rollback()  # drops the temporary schema and everything in it
    connection.close()
    engine.dispose()


@pytest.fixture
def client(pg: Connection) -> Iterator[TestClient]:
    """TestClient whose sessions use the test connection inside a per-test savepoint.

    join_transaction_mode="create_savepoint": session.commit() in an endpoint
    only releases its own savepoint, so the test can still roll everything back.
    """
    savepoint = pg.begin_nested()

    def test_session() -> Iterator[Session]:
        with Session(bind=pg, join_transaction_mode="create_savepoint") as session:
            yield session

    # The app's own engine is unused (sessions are overridden); SQLite keeps
    # startup/shutdown away from the Postgres test connection.
    dummy_engine = create_engine("sqlite://", poolclass=StaticPool)
    app = create_app(engine=dummy_engine)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_today] = lambda: TODAY
    with TestClient(app) as test_client:
        yield test_client
    savepoint.rollback()


def destination_id(pg: Connection, name_start: str) -> int:
    """id of the seeded destination whose name starts with name_start."""
    return pg.execute(
        text("SELECT id FROM destinations WHERE name LIKE :p"), {"p": f"{name_start}%"}
    ).scalar_one()


def count(pg: Connection, table: str) -> int:
    """Rows in a table of the test schema."""
    return pg.execute(text(f"SELECT COUNT(*) FROM {table}")).scalar_one()


# ---------------- GET /vehicles/lookup ----------------

def test_lookup_plate_any_spacing_and_case(client: TestClient) -> None:
    response = client.get("/vehicles/lookup", params={"q": " 1234 уба "})
    assert response.status_code == 200
    result = response.json()
    assert (result["match_type"], result["normalized"]) == ("plate", "1234УБА")
    assert [v["id"] for v in result["vehicles"]] == [1]
    card = result["vehicles"][0]
    assert card["service_count"] == 3
    assert card["last_service"]["service_date"] == "2026-08-10"
    assert card["last_service"]["driver_phone"] == "99110002"  # latest driver, D-004


def test_lookup_phone_finds_every_vehicle_driven(client: TestClient) -> None:
    """99110002 drove vehicles 1 and 6 -> both, newest service first."""
    result = client.get("/vehicles/lookup", params={"q": "+976 9911-0002"}).json()
    assert (result["match_type"], result["normalized"]) == ("phone", "99110002")
    assert [v["id"] for v in result["vehicles"]] == [6, 1]


def test_lookup_unknown_plate_is_empty_not_404(client: TestClient) -> None:
    response = client.get("/vehicles/lookup", params={"q": "0000 ЯЯЯ"})
    assert response.status_code == 200
    assert response.json()["vehicles"] == []


def test_lookup_unknown_phone_is_empty(client: TestClient) -> None:
    assert client.get("/vehicles/lookup", params={"q": "88000000"}).json()["vehicles"] == []


@pytest.mark.parametrize("params", [{"q": "   "}, {"q": ""}, {}])
def test_lookup_blank_or_missing_q_is_422(client: TestClient, params: dict[str, str]) -> None:
    assert client.get("/vehicles/lookup", params=params).status_code == 422


# ---------------- GET /vehicles/{id} ----------------

def test_vehicle_card_fields(client: TestClient) -> None:
    card = client.get("/vehicles/1").json()
    assert card["identifier"] == "1234 УБА"
    assert card["plate_normalized"] == "1234УБА"
    assert card["company"]["name"] == "Говь Тээвэр ХХК"
    assert card["service_count"] == 3
    assert card["segment"] == "loyal"
    assert card["usual_liters"] == 32.0  # a JSON number, not "32.0"
    assert card["prediction"] is None    # until task 4.3
    assert [s["service_date"] for s in card["history"]] == ["2026-08-10", "2026-05-20", "2026-03-05"]
    assert card["last_service"] == card["history"][0]


@pytest.mark.parametrize(
    ("vehicle_id", "segment"),
    [(1, "loyal"), (2, "returning"), (3, "new"), (4, "at_risk"), (5, "returning"), (6, "returning")],
)
def test_vehicle_card_segment(client: TestClient, vehicle_id: int, segment: str) -> None:
    """Same segments as data_dictionary §5 (as of 2026-09-30)."""
    assert client.get(f"/vehicles/{vehicle_id}").json()["segment"] == segment


def test_vehicle_card_fleet_truck_engine_hours(client: TestClient) -> None:
    card = client.get("/vehicles/5").json()
    assert (card["identifier_type"], card["plate_normalized"]) == ("fleet_no", None)
    assert card["last_service"]["engine_hours"] == 12980.5
    assert card["last_service"]["odometer_km"] is None


def test_vehicle_card_unknown_id_404(client: TestClient) -> None:
    assert client.get("/vehicles/999999").status_code == 404


# ---------------- GET /stats/segments ----------------

def test_segment_stats_sample_data(client: TestClient) -> None:
    """Expected counts from data_dictionary §5."""
    stats = client.get("/stats/segments", params={"as_of": "2026-09-30"}).json()
    assert stats == {
        "as_of": "2026-09-30",
        "total": 6,
        "counts": {"new": 1, "returning": 3, "loyal": 1, "at_risk": 1},
    }


def test_segment_stats_default_is_today(client: TestClient) -> None:
    assert client.get("/stats/segments").json()["as_of"] == TODAY.isoformat()


def test_segment_stats_before_any_service_all_zero(client: TestClient) -> None:
    stats = client.get("/stats/segments", params={"as_of": "2020-01-01"}).json()
    assert stats["total"] == 0
    assert stats["counts"] == {"new": 0, "returning": 0, "loyal": 0, "at_risk": 0}


# ---------------- POST /services ----------------

def test_new_plate_creates_vehicle_and_company(client: TestClient, pg: Connection) -> None:
    zamyn_uud = destination_id(pg, "Zamyn-Uud")
    body = service_body(identifier="4321 убд", destination_raw=None, route=None, destination_id=zamyn_uud)

    response = client.post("/services", json=body)

    assert response.status_code == 201
    created = response.json()
    assert (created["vehicle_created"], created["company_created"]) == (True, True)
    service = created["service"]
    assert service["service_date"] == TODAY.isoformat()  # date automatic
    assert service["route"] == "mn_china"                 # D-039: from the destination
    assert service["destination"]["id"] == zamyn_uud
    # The new truck is found by plate, in any spelling, as a "new" customer.
    card = client.get("/vehicles/lookup", params={"q": "4321УБД"}).json()["vehicles"][0]
    assert card["id"] == created["vehicle_id"]
    assert (card["identifier"], card["plate_normalized"]) == ("4321 убд", "4321УБД")
    assert (card["service_count"], card["segment"]) == (1, "new")
    assert card["company"]["name"] == "Туршилт Тээвэр ХХК"


def test_existing_plate_adds_service_only(client: TestClient, pg: Connection) -> None:
    vehicles_before, companies_before = count(pg, "vehicles"), count(pg, "companies")
    body = service_body(identifier="1234уба", company_name=None, odometer_km=278000)

    created = client.post("/services", json=body).json()

    assert created["vehicle_id"] == 1
    assert (created["vehicle_created"], created["company_created"]) == (False, False)
    assert (count(pg, "vehicles"), count(pg, "companies")) == (vehicles_before, companies_before)
    card = client.get("/vehicles/1").json()
    assert card["service_count"] == 4
    assert card["last_service"]["odometer_km"] == 278000


def test_new_plate_existing_company_reused(client: TestClient) -> None:
    created = client.post("/services", json=service_body(company_name="Говь Тээвэр ХХК")).json()
    assert (created["vehicle_created"], created["company_created"]) == (True, False)
    assert client.get(f"/vehicles/{created['vehicle_id']}").json()["company"]["id"] == 1


def test_new_plate_without_company_is_422_and_saves_nothing(client: TestClient, pg: Connection) -> None:
    before = count(pg, "service_records"), count(pg, "vehicles")
    response = client.post("/services", json=service_body(company_name=None))
    assert response.status_code == 422
    assert "company_name" in response.json()["detail"]
    assert (count(pg, "service_records"), count(pg, "vehicles")) == before


def test_destination_raw_keeps_route_given(client: TestClient) -> None:
    """D-039: free-text destination -> the oil changer's route is stored."""
    service = client.post("/services", json=service_body(route="mine_site")).json()["service"]
    assert (service["route"], service["destination"], service["destination_raw"]) == ("mine_site", None, "Сайншанд")


def test_destination_id_with_same_route_accepted(client: TestClient, pg: Connection) -> None:
    body = service_body(destination_raw=None, destination_id=destination_id(pg, "Altanbulag"), route="mn_russia")
    response = client.post("/services", json=body)
    assert response.status_code == 201
    assert response.json()["service"]["route"] == "mn_russia"


def test_destination_id_with_other_route_is_422(client: TestClient, pg: Connection) -> None:
    """D-039: the user cannot override the destination's route."""
    body = service_body(destination_raw=None, destination_id=destination_id(pg, "Beijing"), route="ub_city")
    response = client.post("/services", json=body)
    assert response.status_code == 422
    assert "D-039" in response.json()["detail"]


def test_destination_raw_without_route_is_422(client: TestClient) -> None:
    assert client.post("/services", json=service_body(route=None)).status_code == 422


def test_unknown_destination_id_is_422(client: TestClient) -> None:
    response = client.post("/services", json=service_body(destination_raw=None, destination_id=999999, route=None))
    assert response.status_code == 422
    assert "999999" in response.json()["detail"]


def test_future_service_date_is_422(client: TestClient) -> None:
    assert client.post("/services", json=service_body(service_date="2026-10-01")).status_code == 422


def test_past_service_date_allowed_for_late_entry(client: TestClient) -> None:
    service = client.post("/services", json=service_body(service_date="2026-09-01")).json()["service"]
    assert service["service_date"] == "2026-09-01"


def test_phone_stored_normalized(client: TestClient) -> None:
    service = client.post("/services", json=service_body(driver_phone="+976 9911-0009")).json()["service"]
    assert service["driver_phone"] == "99110009"


def test_existing_fleet_number_found_within_company(client: TestClient) -> None:
    body = service_body(
        identifier_type="fleet_no", identifier="HT-12", company_name="Өмнөд Уурхай ХХК",
        odometer_km=None, engine_hours=13400.0, liters=90.0,
    )
    created = client.post("/services", json=body).json()
    assert (created["vehicle_id"], created["vehicle_created"]) == (5, False)


def test_fleet_number_without_company_is_422(client: TestClient) -> None:
    body = service_body(identifier_type="fleet_no", identifier="HT-12", company_name=None)
    assert client.post("/services", json=body).status_code == 422


def test_new_fleet_number_has_no_plate(client: TestClient) -> None:
    body = service_body(identifier_type="fleet_no", identifier="HT-99", company_name="Өмнөд Уурхай ХХК")
    created = client.post("/services", json=body).json()
    card = client.get(f"/vehicles/{created['vehicle_id']}").json()
    assert (card["identifier_type"], card["plate_normalized"], card["company"]["id"]) == ("fleet_no", None, 4)
