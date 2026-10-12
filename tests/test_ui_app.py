"""Screen tests for the Streamlit app (tasks 5.1–5.3) with a FAKE backend.

The app runs in Streamlit's AppTest (no browser). The network is replaced by
httpx.MockTransport + FakeApi, a tiny in-memory imitation of the endpoints in
docs/api_contract.md. No real API, no database, invented data only (RISK-06).

Skipped when Streamlit is not installed (CI installs only requirements.txt;
install requirements-ui.txt to run these).
"""

import json
from pathlib import Path

import httpx
import pytest

st = pytest.importorskip("streamlit")
from streamlit.testing.v1 import AppTest  # noqa: E402

from src.ui import api_client  # noqa: E402

APP = str(Path(__file__).resolve().parent.parent / "src" / "ui" / "app.py")
TODAY = "2026-10-12"

DESTINATIONS = [
    {"id": 1, "name": "Ulaanbaatar city (local work)", "route_category": "ub_city"},
    {"id": 2, "name": "Zamyn-Uud (MN–CN border)", "route_category": "mn_china", "name_mn": "Замын-Үүд"},
    {"id": 7, "name": "Other / several / unknown", "route_category": "mixed"},
]


class FakeApi:
    """In-memory imitation of the data endpoints (only what the UI uses)."""

    def __init__(self) -> None:
        self.vehicles: list[dict] = []
        self.services: list[dict] = []
        self.posts: list[tuple[dict, bool]] = []  # (body, force)

    # -- data ---------------------------------------------------------------
    def add_vehicle(self, identifier: str, company: str, identifier_type: str = "plate", **service) -> dict:
        vehicle = {
            "id": len(self.vehicles) + 1,
            "identifier_type": identifier_type,
            "identifier": identifier,
            "vehicle_model": service.pop("vehicle_model", None),
            "company": {"id": len(self.vehicles) + 1, "name": company},
        }
        self.vehicles.append(vehicle)
        if service:
            self._add_service(vehicle["id"], service)
        return vehicle

    def _add_service(self, vehicle_id: int, body: dict) -> dict:
        dest = next((d for d in DESTINATIONS if d["id"] == body.get("destination_id")), None)
        service = {
            "id": len(self.services) + 1,
            "vehicle_id": vehicle_id,
            "service_date": body.get("service_date", TODAY),
            "odometer_km": body.get("odometer_km"),
            "engine_hours": body.get("engine_hours"),
            "oil_grade": body["oil_grade"],
            "liters": body["liters"],
            "route": dest["route_category"] if dest else body.get("route"),
            "destination": dest,
            "destination_raw": body.get("destination_raw"),
            "driver_name": body.get("driver_name"),
            "driver_phone": body.get("driver_phone"),
            "oil_changer": body.get("oil_changer"),
            "photo_ref": None,
            "created_at": f"{TODAY}T10:00:00+08:00",
        }
        self.services.append(service)
        return service

    @staticmethod
    def _key(text: str) -> str:
        return "".join(text.split()).upper()

    def card(self, vehicle: dict) -> dict:
        history = sorted(
            (s for s in self.services if s["vehicle_id"] == vehicle["id"]),
            key=lambda s: (s["service_date"], s["id"]),
            reverse=True,
        )
        n = len(history)
        return {
            **vehicle,
            "plate_normalized": self._key(vehicle["identifier"]) if vehicle["identifier_type"] == "plate" else None,
            "service_count": n,
            "segment": None if n == 0 else "new" if n == 1 else "returning" if n == 2 else "loyal",
            "usual_liters": history[0]["liters"] if history else None,
            "last_service": history[0] if history else None,
            "history": history,
            "prediction": None,
        }

    # -- endpoints ----------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/destinations":
            return httpx.Response(200, json=DESTINATIONS)
        if path == "/vehicles/lookup":
            return self._lookup(request.url.params["q"])
        if path == "/services" and request.method == "POST":
            return self._post(json.loads(request.content), request.url.params.get("force") == "true")
        return httpx.Response(404, json={"detail": "not found"})

    def _lookup(self, q: str) -> httpx.Response:
        digits = "".join(c for c in q if c.isdigit())
        if digits.startswith("976") and len(digits) == 11:
            digits = digits[3:]
        if len(digits) == 8 and not any(c.isalpha() for c in q):
            ids = {s["vehicle_id"] for s in self.services if s["driver_phone"] == digits}
            found = [v for v in self.vehicles if v["id"] in ids]
            return httpx.Response(200, json={
                "query": q, "match_type": "phone", "normalized": digits,
                "vehicles": [self.card(v) for v in found],
            })
        found = [v for v in self.vehicles if self._key(v["identifier"]) == self._key(q)]
        match_type = "fleet_no" if found and all(v["identifier_type"] == "fleet_no" for v in found) else "plate"
        return httpx.Response(200, json={
            "query": q, "match_type": match_type, "normalized": self._key(q),
            "vehicles": [self.card(v) for v in found],
        })

    def _post(self, body: dict, force: bool) -> httpx.Response:
        self.posts.append((body, force))
        kind = body.get("identifier_type", "plate")
        vehicle = next(
            (v for v in self.vehicles
             if v["identifier_type"] == kind and self._key(v["identifier"]) == self._key(body["identifier"])
             and (kind == "plate" or v["company"]["name"] == body.get("company_name"))),
            None,
        )
        created = vehicle is None
        if created:
            if not body.get("company_name"):
                return httpx.Response(422, json={"detail": "new vehicle: company_name is required (private owner = owner's name)"})
            vehicle = self.add_vehicle(body["identifier"], body["company_name"], kind,
                                       vehicle_model=body.get("vehicle_model"))
        elif not force and any(s["vehicle_id"] == vehicle["id"] and s["service_date"] == TODAY for s in self.services):
            existing = next(s for s in self.services if s["vehicle_id"] == vehicle["id"] and s["service_date"] == TODAY)
            return httpx.Response(409, json={"detail": {
                "code": "duplicate_service", "message": "already has a service on this date",
                "existing_service_id": existing["id"],
            }})
        service = self._add_service(vehicle["id"], body)
        return httpx.Response(201, json={
            "service": service, "vehicle_id": vehicle["id"],
            "vehicle_created": created, "company_created": created,
        })


@pytest.fixture
def fake_api(monkeypatch):
    """Fake backend behind the UI's HTTP client; login off; fresh cache."""
    monkeypatch.delenv("UI_PASSWORD", raising=False)
    monkeypatch.delenv("UI_ENABLE_RECOGNIZE", raising=False)
    fake = FakeApi()
    api_client.set_transport(httpx.MockTransport(fake.handle))
    st.cache_data.clear()
    yield fake
    api_client.set_transport(None)


def run_app() -> AppTest:
    return AppTest.from_file(APP, default_timeout=10).run()


def click(at: AppTest, label: str) -> AppTest:
    """Click the button with this label and rerun."""
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0].click().run()


def texts(elements) -> list[str]:
    return [e.value for e in elements]


def check_plate(at: AppTest, plate: str, kind: str = "plate") -> AppTest:
    at.radio(key="rec_identifier_type").set_value(kind)
    at.text_input(key="rec_identifier").set_value(plate).run()
    return click(at, "Шалгах")


def fill_new_vehicle(at: AppTest, company: str = "Туршилт Тээвэр ХХК") -> AppTest:
    at.text_input(key="f_company_name").set_value(company)
    at.text_input(key="f_vehicle_model").set_value("Howo A7")
    at.number_input(key="f_odometer_km").set_value(120000)
    at.text_input(key="f_oil_grade").set_value("15W-40")
    at.number_input(key="f_liters").set_value(28.5)
    at.selectbox(key="f_destination_id").set_value(2)
    at.text_input(key="f_driver_name").set_value("Тест Б.")
    at.text_input(key="f_driver_phone").set_value("99110099")
    at.text_input(key="f_oil_changer").set_value("Тос солигч Т")
    return at.run()


def seed_existing(fake: FakeApi) -> dict:
    return fake.add_vehicle(
        "0002 ТЕС", "Говь Тест ХХК", vehicle_model="Shacman X3000",
        service_date="2026-09-01", odometer_km=200000, oil_grade="10W-40", liters=32.0,
        destination_id=2, driver_name="Жолооч Д.", driver_phone="99110002",
    )


# --- login (D-061) ---------------------------------------------------------------

def test_no_password_env_skips_login(fake_api) -> None:
    at = run_app()
    assert not at.exception
    assert texts(at.title) == ["🛢️ Үйлчилгээ бүртгэх"]


def test_login_required_and_works(fake_api, monkeypatch) -> None:
    monkeypatch.setenv("UI_PASSWORD", "demo-pass")
    at = run_app()
    assert texts(at.title) == ["🛢️ Тос солилт"]
    at.text_input[0].set_value("wrong")
    at = click(at, "Нэвтрэх")
    assert "Нууц үг буруу байна." in texts(at.error)
    at.text_input[0].set_value("demo-pass")
    at = click(at, "Нэвтрэх")
    assert texts(at.title) == ["🛢️ Үйлчилгээ бүртгэх"]


# --- recording (5.2) ---------------------------------------------------------------

def test_recognize_button_hidden_by_default(fake_api) -> None:
    at = run_app()
    assert "🔎 Дугаар таних" not in [b.label for b in at.button]


def test_new_vehicle_saved(fake_api) -> None:
    at = check_plate(run_app(), "0001 ТЕС")
    assert any("Шинэ машин" in t for t in texts(at.info))
    at = click(fill_new_vehicle(at), "💾 Хадгалах")

    assert not at.exception, at.exception
    body, force = fake_api.posts[-1]
    assert force is False
    assert body == {
        "identifier_type": "plate", "identifier": "0001 ТЕС", "oil_grade": "15W-40", "liters": 28.5,
        "company_name": "Туршилт Тээвэр ХХК", "vehicle_model": "Howo A7", "odometer_km": 120000,
        "destination_id": 2, "driver_name": "Тест Б.", "driver_phone": "99110099",
        "oil_changer": "Тос солигч Т",
    }
    assert any("Хадгалагдлаа: 0001 ТЕС (шинэ машин)" in t for t in texts(at.success))
    # form reset for the next truck, oil changer remembered
    assert at.session_state["rec_identifier"] == ""
    assert at.session_state["f_oil_changer"] == "Тос солигч Т"


def test_empty_form_shows_mongolian_errors_and_sends_nothing(fake_api) -> None:
    at = click(check_plate(run_app(), "0001 ТЕС"), "💾 Хадгалах")
    assert "Тосны төрөл оруулна уу." in texts(at.error)
    assert fake_api.posts == []


def test_existing_vehicle_prefilled_but_fresh_fields_empty(fake_api) -> None:
    seed_existing(fake_api)
    at = check_plate(run_app(), "0002тес")
    assert any("Бүртгэлтэй машин · 1 удаа" in t for t in texts(at.success))
    state = at.session_state
    assert state["f_oil_grade"] == "10W-40"
    assert state["f_liters"] == 32.0
    assert state["f_driver_phone"] == "99110002"
    assert state["f_odometer_km"] is None
    assert state["f_destination_id"] is None
    assert at.text_input(key="f_company_name").disabled


def test_other_destination_sends_raw_and_route(fake_api) -> None:
    seed_existing(fake_api)
    at = check_plate(run_app(), "0002 ТЕС")
    at.number_input(key="f_odometer_km").set_value(215000)
    at.selectbox(key="f_destination_id").set_value(-1).run()
    at.text_input(key="f_destination_raw").set_value("Сайншанд")
    at.selectbox(key="f_route").set_value("mixed").run()
    at = click(at, "💾 Хадгалах")
    body, _ = fake_api.posts[-1]
    assert body["destination_raw"] == "Сайншанд"
    assert body["route"] == "mixed"
    assert "destination_id" not in body
    assert "company_name" not in body  # existing plate vehicle


def test_destination_shows_name_mn_if_present(fake_api) -> None:
    at = check_plate(run_app(), "0001 ТЕС")
    options = at.selectbox(key="f_destination_id").options
    assert "Замын-Үүд" in options
    assert "Ulaanbaatar city (local work)" in options


def test_duplicate_then_force_save(fake_api) -> None:
    vehicle = seed_existing(fake_api)
    fake_api._add_service(vehicle["id"], {"oil_grade": "10W-40", "liters": 32.0, "odometer_km": 210000})
    at = check_plate(run_app(), "0002 ТЕС")
    at.number_input(key="f_odometer_km").set_value(210050)
    at.selectbox(key="f_destination_id").set_value(1).run()
    at = click(at, "💾 Хадгалах")

    assert any("аль хэдийн бүртгэгдсэн" in t for t in texts(at.warning))
    assert "Ингээд хадгалах" in [b.label for b in at.button]
    count_before = len(fake_api.services)

    at = click(at, "Ингээд хадгалах")
    assert fake_api.posts[-1][1] is True  # force=true
    assert len(fake_api.services) == count_before + 1
    assert any("Хадгалагдлаа" in t for t in texts(at.success))


def test_duplicate_cancel(fake_api) -> None:
    vehicle = seed_existing(fake_api)
    fake_api._add_service(vehicle["id"], {"oil_grade": "10W-40", "liters": 32.0, "odometer_km": 210000})
    at = check_plate(run_app(), "0002 ТЕС")
    at.number_input(key="f_odometer_km").set_value(210050)
    at.selectbox(key="f_destination_id").set_value(1).run()
    at = click(click(at, "💾 Хадгалах"), "Болих")
    assert "💾 Хадгалах" in [b.label for b in at.button]
    assert len(fake_api.posts) == 1


def test_fleet_number_in_two_companies(fake_api) -> None:
    fake_api.add_vehicle("HT-12", "Уурхай А ХХК", "fleet_no", oil_grade="15W-40", liters=40.0, engine_hours=1000.0)
    fake_api.add_vehicle("HT-12", "Уурхай Б ХХК", "fleet_no", oil_grade="10W-30", liters=45.0, engine_hours=2000.0)
    at = check_plate(run_app(), "ht-12", kind="fleet_no")
    assert at.session_state["f_company_name"] == "Уурхай А ХХК"
    at.radio(key="rec_choice").set_value(1).run()
    assert at.session_state["f_company_name"] == "Уурхай Б ХХК"
    assert at.session_state["f_oil_grade"] == "10W-30"


def test_changed_plate_requires_new_check(fake_api) -> None:
    at = check_plate(run_app(), "0001 ТЕС")
    at.text_input(key="rec_identifier").set_value("0009 ТЕС").run()
    assert any("Шалгах" in t for t in texts(at.info))
    assert "💾 Хадгалах" not in [b.label for b in at.button]


def test_api_down_shows_message(fake_api) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    api_client.set_transport(httpx.MockTransport(down))
    at = check_plate(run_app(), "0001 ТЕС")
    assert not at.exception
    assert any("холбогдож" in t for t in texts(at.error))


# --- lookup + vehicle card (5.3) ----------------------------------------------------------

def open_lookup(query: str) -> AppTest:
    at = run_app()
    at.switch_page("views/lookup.py").run()
    at.text_input(key="lookup_q").set_value(query).run()
    return click(at, "Хайх")


def test_lookup_by_plate_shows_card(fake_api) -> None:
    seed_existing(fake_api)
    at = open_lookup("0002 тес")
    assert not at.exception
    assert "#### 0002 ТЕС" in texts(at.markdown)
    assert "Таамаглал удахгүй нэмэгдэнэ" in " ".join(texts(at.info))
    grid = next(t for t in texts(at.markdown) if 'class="vc-grid"' in t)
    assert "32 л" in grid            # usual liters
    assert "200 000 км" in grid      # last odometer
    assert ":blue-badge[Шинэ]" in texts(at.markdown)  # segment new (st.badge)


def test_lookup_by_phone_finds_vehicle(fake_api) -> None:
    seed_existing(fake_api)
    at = open_lookup("+976 9911-0002")
    assert "#### 0002 ТЕС" in texts(at.markdown)
    assert any("утасны дугаараар" in t for t in texts(at.caption))


def test_lookup_unknown_offers_new_vehicle(fake_api) -> None:
    at = open_lookup("0404 ТЕС")
    assert any("Олдсонгүй" in t for t in texts(at.info))
    at = click(at, "➕ Шинэ машин бүртгэх")
    assert texts(at.title) == ["🛢️ Үйлчилгээ бүртгэх"]
    assert at.session_state["rec_identifier"] == "0404 ТЕС"
    assert any("Шинэ машин" in t for t in texts(at.info))


def test_card_record_button_opens_prefilled_form(fake_api) -> None:
    seed_existing(fake_api)
    at = click(open_lookup("0002 ТЕС"), "➕ Үйлчилгээ бүртгэх")
    assert texts(at.title) == ["🛢️ Үйлчилгээ бүртгэх"]
    assert at.session_state["f_oil_grade"] == "10W-40"
    assert at.session_state["rec_identifier"] == "0002 ТЕС"


def test_save_then_find_by_plate_and_phone(fake_api) -> None:
    """DONE-WHEN path: save a new truck, then find it by plate AND by phone."""
    at = click(fill_new_vehicle(check_plate(run_app(), "0001 ТЕС")), "💾 Хадгалах")
    at = click(at, "Картыг харах")
    assert texts(at.title) == ["🔍 Машин хайх"]
    assert "#### 0001 ТЕС" in texts(at.markdown)

    # AppTest does not remember an in-app st.switch_page for the NEXT run
    # (a browser does, via the URL), so select the page again before typing.
    at.switch_page("views/lookup.py")
    at.text_input(key="lookup_q").set_value("99110099").run()
    at = click(at, "Хайх")
    assert "#### 0001 ТЕС" in texts(at.markdown)
    assert any("Туршилт Тээвэр ХХК" in t for t in texts(at.caption))
