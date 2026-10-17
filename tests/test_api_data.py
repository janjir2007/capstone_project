"""Data endpoint tests (tasks 4.2 + 4.2b): lookup, POST /services, vehicle card,
segments, destinations.

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
from src.api.matching import clean_company_name, company_key, fleet_no_key
from src.api.routers.vehicles import usual_liters
from src.api.schemas import ServiceCreate, normalize_phone
from tests.test_schema import database_url

SQL_DIR = Path(__file__).resolve().parent.parent / "src" / "data"
SQL_FILES = ["schema.sql", "migrations/001_destinations.up.sql", "migrations/002_destinations_name_mn.up.sql",
             "migrations/003_reminders_sent.up.sql", "migrations/004_destinations_name_mn_rest.up.sql",
             "migrations/005_destinations_cross_border.up.sql", "sample_data.sql"]
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


@pytest.mark.parametrize(
    "typed",
    ["Говь Тээвэр ХХК", "говь тээвэр ххк", "  ГОВЬ   тээвэр  ХХК ", "Говь\tТээвэр ХХК"],
)
def test_company_key_ignores_case_and_extra_spaces(typed: str) -> None:
    assert company_key(typed) == company_key("Говь Тээвэр ХХК")


def test_company_key_keeps_words_apart() -> None:
    """Only EXTRA spaces are ignored: removing a space is a different name."""
    assert company_key("ГовьТээвэр ХХК") != company_key("Говь Тээвэр ХХК")


def test_clean_company_name_keeps_case() -> None:
    assert clean_company_name("  Шинэ   Тээвэр  ХХК ") == "Шинэ Тээвэр ХХК"


@pytest.mark.parametrize("typed", ["HT-12", "ht-12", " Ht - 12 ", "HT -12", "HT12", "h-t 1-2"])
def test_fleet_no_key_ignores_case_spaces_and_dashes(typed: str) -> None:
    assert fleet_no_key(typed) == "ht12"  # task 4.4: dashes no longer count


def test_fleet_no_key_keeps_other_characters() -> None:
    assert fleet_no_key("HT-12") != fleet_no_key("HT-13")
    assert fleet_no_key("HT/12") != fleet_no_key("HT12")


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
    # No model files here (predictions are tested in tests/test_serving.py): prediction = null.
    app = create_app(engine=dummy_engine, model_dir=SQL_DIR / "no_models_here")
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
    assert card["prediction"] is None    # model not loaded in this fixture (4.3 tests: test_serving.py)
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


# ==========================================================================
# Task 4.2b
# ==========================================================================

# ---------------- GET /destinations ----------------

def test_destinations_list(client: TestClient) -> None:
    """The 7 rows seeded by migration 001, in seeded order, short form only (+ name_mn, contract v0.6)."""
    response = client.get("/destinations")
    assert response.status_code == 200
    destinations = response.json()
    assert len(destinations) == 11  # 7 from migration 001 + 4 from 005 (task 1.6)
    assert set(destinations[0]) == {"id", "name", "name_mn", "route_category"}
    assert destinations[0] == {"id": destinations[0]["id"], "name": "Ulaanbaatar city (local work)",
                               "name_mn": "Улаанбаатар хот", "route_category": "ub_city"}
    assert destinations[-1]["route_category"] == "mixed"  # "Other / several / unknown" last, also after 005's rows
    rest = [d["id"] for d in destinations[:-1]]
    assert rest == sorted(rest)


def test_destinations_have_mongolian_labels(client: TestClient) -> None:
    """Migrations 002 + 004 + 005 (D-040, tasks 6.1, 1.6): every destination shows a Mongolian label."""
    labels = {d["name"]: d["name_mn"] for d in client.get("/destinations").json()}
    assert labels == {
        "Ulaanbaatar city (local work)": "Улаанбаатар хот",
        "Zamyn-Uud (MN–CN border)": "Замын-Үүд",
        "Erenhot (CN side of border)": "Эрээн",
        "Beijing": "Бээжин",
        "Altanbulag (MN–RU border)": "Алтанбулаг",
        "Kyakhta (RU side of border)": "Хиагт",
        "Ganqimaodu (CN side of Gashuunsukhait border)": "Ганцмод",
        "Ceke (CN side of Shiveekhuren border)": "Сэхээ",
        "Ulan-Ude (via Altanbulag–Kyakhta)": "Улаан-Үд",
        "Kosh-Agach (via Tsagaannuur–Tashanta)": "Кош-Агач",
        "Other / several / unknown": "Бусад",
    }


def test_destination_ids_work_in_post_services(client: TestClient) -> None:
    """An id from the picker is accepted by POST /services, route taken from it (D-039)."""
    beijing = next(d for d in client.get("/destinations").json() if d["name"] == "Beijing")
    body = service_body(destination_raw=None, route=None, destination_id=beijing["id"])
    service = client.post("/services", json=body).json()["service"]
    assert service["route"] == beijing["route_category"] == "mn_china"


# ---------------- lookup by fleet number ----------------

@pytest.mark.parametrize("q", ["HT-12", "ht-12", " Ht - 12 ", "HT12", "ht 12"])
def test_lookup_fleet_number(client: TestClient, q: str) -> None:
    result = client.get("/vehicles/lookup", params={"q": q}).json()
    assert (result["match_type"], result["normalized"]) == ("fleet_no", "ht12")
    assert [v["id"] for v in result["vehicles"]] == [5]
    assert result["vehicles"][0]["identifier_type"] == "fleet_no"


def test_lookup_same_fleet_number_in_two_companies(client: TestClient) -> None:
    """Fleet numbers are unique only per company (D-005): both trucks are returned."""
    body = service_body(identifier_type="fleet_no", identifier="HT-12", company_name="Говь Тээвэр ХХК")
    other = client.post("/services", json=body).json()
    assert other["vehicle_created"] is True
    result = client.get("/vehicles/lookup", params={"q": "ht-12"}).json()
    assert [v["id"] for v in result["vehicles"]] == [5, other["vehicle_id"]]


def test_lookup_plate_unchanged_by_fleet_search(client: TestClient) -> None:
    result = client.get("/vehicles/lookup", params={"q": "1234 УБА"}).json()
    assert (result["match_type"], [v["id"] for v in result["vehicles"]]) == ("plate", [1])


def test_lookup_unknown_identifier_is_plate_type(client: TestClient) -> None:
    result = client.get("/vehicles/lookup", params={"q": "HT-77"}).json()
    assert (result["match_type"], result["vehicles"]) == ("plate", [])


# ---------------- company name ignores case + extra spaces ----------------

def test_new_plate_company_matched_ignoring_case_and_spaces(client: TestClient, pg: Connection) -> None:
    companies_before = count(pg, "companies")
    created = client.post("/services", json=service_body(company_name="  говь   ТЭЭВЭР ххк ")).json()
    assert (created["vehicle_created"], created["company_created"]) == (True, False)
    assert client.get(f"/vehicles/{created['vehicle_id']}").json()["company"]["id"] == 1
    assert count(pg, "companies") == companies_before


def test_existing_fleet_number_found_with_sloppy_company_name(client: TestClient) -> None:
    body = service_body(
        identifier_type="fleet_no", identifier="HT-12", company_name="өмнөд  уурхай ххк",
        odometer_km=None, engine_hours=13400.0, liters=90.0,
    )
    created = client.post("/services", json=body).json()
    assert (created["vehicle_id"], created["vehicle_created"], created["company_created"]) == (5, False, False)


def test_new_company_stored_with_clean_spacing(client: TestClient) -> None:
    created = client.post("/services", json=service_body(company_name="  Шинэ   Тээвэр  ХХК ")).json()
    assert created["company_created"] is True
    assert client.get(f"/vehicles/{created['vehicle_id']}").json()["company"]["name"] == "Шинэ Тээвэр ХХК"


# ---------------- same vehicle + same date -> 409 unless force ----------------

def test_same_vehicle_same_date_is_409_and_saves_nothing(client: TestClient, pg: Connection) -> None:
    """Vehicle 1 already has service 3 on 2026-08-10 (sample data)."""
    before = count(pg, "service_records")
    body = service_body(identifier="1234 УБА", company_name=None, service_date="2026-08-10")
    response = client.post("/services", json=body)
    assert response.status_code == 409
    detail = response.json()["detail"]
    assert (detail["code"], detail["existing_service_id"]) == ("duplicate_service", 3)
    assert "force=true" in detail["message"]
    assert count(pg, "service_records") == before


def test_same_date_twice_today_second_is_409(client: TestClient) -> None:
    """The real case: the form is sent twice (default date = today)."""
    body = service_body(identifier="1234 УБА", company_name=None)
    first = client.post("/services", json=body)
    second = client.post("/services", json=body)
    assert (first.status_code, second.status_code) == (201, 409)
    assert second.json()["detail"]["existing_service_id"] == first.json()["service"]["id"]


def test_same_date_with_force_is_saved(client: TestClient) -> None:
    body = service_body(identifier="1234 УБА", company_name=None, service_date="2026-08-10")
    response = client.post("/services", params={"force": "true"}, json=body)
    assert response.status_code == 201
    card = client.get("/vehicles/1").json()
    assert [s["service_date"] for s in card["history"]].count("2026-08-10") == 2


def test_force_false_still_checks(client: TestClient) -> None:
    body = service_body(identifier="1234 УБА", company_name=None, service_date="2026-08-10")
    assert client.post("/services", params={"force": "false"}, json=body).status_code == 409


def test_same_vehicle_other_date_not_a_duplicate(client: TestClient) -> None:
    body = service_body(identifier="1234 УБА", company_name=None, service_date="2026-08-11")
    assert client.post("/services", json=body).status_code == 201


def test_fleet_truck_same_date_is_409(client: TestClient) -> None:
    """Vehicle 5 (HT-12) already has service 9 on 2026-08-25."""
    body = service_body(
        identifier_type="fleet_no", identifier="HT-12", company_name="Өмнөд Уурхай ХХК",
        odometer_km=None, engine_hours=13400.0, service_date="2026-08-25",
    )
    response = client.post("/services", json=body)
    assert response.status_code == 409
    assert response.json()["detail"]["existing_service_id"] == 9
