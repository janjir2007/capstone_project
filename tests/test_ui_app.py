"""Screen tests for the Streamlit app (tasks 5.1–5.3c, DESIGN v2) with a FAKE backend.

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
        self.prediction: dict | None = None        # returned on every card (None = model not loaded)
        self.recognize: tuple[int, dict] = (503, {"detail": "plate recognizer not loaded"})
        self.uploads: list[bytes] = []              # raw multipart bodies sent to /plates/recognize

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
            "prediction": {**self.prediction, "vehicle_id": vehicle["id"]} if self.prediction and n else None,
        }

    # -- endpoints ----------------------------------------------------------
    def handle(self, request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path == "/destinations":
            return httpx.Response(200, json=DESTINATIONS)
        if path.startswith("/vehicles/") and path.split("/")[-1].isdigit():
            vid = int(path.split("/")[-1])
            vehicle = next((v for v in self.vehicles if v["id"] == vid), None)
            return httpx.Response(200, json=self.card(vehicle)) if vehicle else httpx.Response(404, json={"detail": "unknown"})
        if path == "/vehicles/lookup":
            return self._lookup(request.url.params["q"])
        if path == "/plates/recognize" and request.method == "POST":
            self.uploads.append(request.read())
            status, body = self.recognize
            return httpx.Response(status, json=body)
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
    fake = FakeApi()
    api_client.set_transport(httpx.MockTransport(fake.handle))
    st.cache_data.clear()
    yield fake
    api_client.set_transport(None)


HOME, RECORD, SEARCH, CARD = "views/home.py", "views/record.py", "views/search.py", "views/card.py"

PREDICTION = {
    "method": "ridge", "fallback_reason": None, "model_version": "ridge-0000abcd",
    "based_on_service_id": 1, "last_service_date": "2026-09-01", "predicted_days": 50.0,
    "predicted_date": "2026-10-21", "today": TODAY, "days_left": 9, "status": "due_soon",
}
RECOGNIZED = {"plate_raw": "0002ТЕС", "plate_normalized": "0002ТЕС", "confidence": 0.95,
              "needs_manual": False, "reason": None, "detection": None,
              "detector": "yolo26n (onnx)", "recognizer": "char_cnn (onnx)", "ms": 80.0}


def run_app(page: str | None = None) -> AppTest:
    at = AppTest.from_file(APP, default_timeout=10).run()
    return at.switch_page(page).run() if page else at


def on(at: AppTest, page: str) -> AppTest:
    """AppTest does not remember an in-app st.switch_page for the NEXT run
    (a browser does, via the URL): select the page again before interacting."""
    return at.switch_page(page)


def click(at: AppTest, label: str) -> AppTest:
    """Click the button with this label and rerun."""
    matches = [b for b in at.button if b.label == label]
    assert matches, f"no button {label!r}; have {[b.label for b in at.button]}"
    return matches[0].click().run()


def texts(elements) -> list[str]:
    return [e.value for e in elements]


def html_blocks(at: AppTest) -> str:
    return "\n".join(texts(at.markdown))


def step(at: AppTest) -> str:
    return at.session_state["rec_step"]


def type_plate(at: AppTest, plate: str, kind: str = "plate") -> AppTest:
    """Record: manual entry -> «Шалгах» -> confirm step."""
    at = click(at, "Дугаарыг гараар оруулах")
    at.radio(key="rec_type").set_value(kind)
    at.text_input(key="rec_manual").set_value(plate).run()
    return click(at, "Шалгах")


def to_form(at: AppTest, plate: str, kind: str = "plate") -> AppTest:
    return click(type_plate(at, plate, kind), "Зөв, үргэлжлүүлэх")


def fill_new_vehicle(at: AppTest, company: str = "Туршилт Тээвэр ХХК") -> AppTest:
    at.number_input(key="f_odometer_km").set_value(120000)
    at.pills(key="f_destination_id").set_value(2)
    at.text_input(key="f_company_name").set_value(company)
    at.text_input(key="f_vehicle_model").set_value("Howo A7")
    at.text_input(key="f_oil_grade").set_value("15W-40")
    at.number_input(key="f_liters").set_value(28.5)
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


def upload_photo(at: AppTest, key: str) -> AppTest:
    return at.file_uploader(key=key).upload("truck.jpg", b"fake-jpeg", "image/jpeg").run()


# --- login (D-061) + home ------------------------------------------------------------

def test_no_password_env_opens_home(fake_api) -> None:
    at = run_app()
    assert not at.exception
    assert texts(at.title) == ["Тос солилт"]
    assert {"📷  Бүртгэх", "🔍  Хайх"} <= {b.label for b in at.button}
    assert "Гео-Эксперт" in html_blocks(at)


def test_login_required_and_works(fake_api, monkeypatch) -> None:
    monkeypatch.setenv("UI_PASSWORD", "demo-pass")
    at = run_app()
    assert texts(at.title) == ["Нэвтрэх"]
    at.text_input[0].set_value("wrong")
    at = click(at, "Нэвтрэх")
    assert "Нууц үг буруу байна." in texts(at.error)
    at.text_input[0].set_value("demo-pass")
    at = click(at, "Нэвтрэх")
    assert texts(at.title) == ["Тос солилт"]


ALL_VIEWS = [HOME, RECORD, SEARCH, CARD]


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_logged_out_cannot_open_any_view(fake_api, monkeypatch, view) -> None:
    """Login-bypass guard: with UI_PASSWORD set and not logged in, no screen is a
    navigation page at all, so a direct URL only gets the login screen."""
    monkeypatch.setenv("UI_PASSWORD", "demo-pass")
    at = run_app()
    with pytest.raises(ValueError, match="Could not find a navigation page"):
        at.switch_page(view)
    assert texts(at.title) == ["Нэвтрэх"]


@pytest.mark.parametrize("view", ALL_VIEWS)
def test_logged_in_can_open_every_view(fake_api, view) -> None:
    """Counter-check for the test above: the same views ARE pages once allowed."""
    at = run_app(view)
    assert not at.exception
    assert texts(at.title) and texts(at.title) != ["Нэвтрэх"]


def test_home_buttons_open_screens(fake_api) -> None:
    at = click(run_app(), "📷  Бүртгэх")
    assert texts(at.title) == ["Бүртгэх"] and step(at) == "capture"
    at = click(run_app(), "🔍  Хайх")
    assert texts(at.title) == ["Хайх"]


def test_back_button_goes_home(fake_api) -> None:
    at = click(run_app(SEARCH), "‹ Буцах")
    assert texts(at.title) == ["Тос солилт"]


# --- record flow (5.2 / DESIGN v2) ------------------------------------------------------

def test_new_vehicle_full_flow(fake_api) -> None:
    at = type_plate(run_app(RECORD), "0001 ТЕС")
    assert step(at) == "confirm"
    assert '<div class="plate-box">0001 ТЕС</div>' in html_blocks(at)
    assert "Шинэ машин" in html_blocks(at)

    at = click(at, "Зөв, үргэлжлүүлэх")
    assert step(at) == "form"
    at = click(fill_new_vehicle(at), "Хадгалах")
    assert not at.exception, at.exception
    body, force = fake_api.posts[-1]
    assert force is False
    assert body == {
        "identifier_type": "plate", "identifier": "0001 ТЕС", "oil_grade": "15W-40", "liters": 28.5,
        "company_name": "Туршилт Тээвэр ХХК", "vehicle_model": "Howo A7", "odometer_km": 120000,
        "destination_id": 2, "driver_name": "Тест Б.", "driver_phone": "99110099",
        "oil_changer": "Тос солигч Т",
    }
    assert step(at) == "success"
    assert "Хадгалагдлаа" in html_blocks(at)
    assert {"Дараагийн машин", "Машины карт үзэх"} <= {b.label for b in at.button}

    at = click(at, "Дараагийн машин")
    assert step(at) == "capture"
    assert at.session_state["f_oil_changer"] == "Тос солигч Т"  # remembered


def test_existing_vehicle_confirm_chip_and_prefill(fake_api) -> None:
    seed_existing(fake_api)
    at = type_plate(run_app(RECORD), "0002тес")
    assert "Бүртгэлтэй · 1 удаа ирсэн" in html_blocks(at)
    at = click(at, "Зөв, үргэлжлүүлэх")
    state = at.session_state
    assert (state["f_oil_grade"], state["f_liters"], state["f_driver_phone"]) == ("10W-40", 32.0, "99110002")
    assert state["f_odometer_km"] is None and state["f_destination_id"] is None  # D-033 fresh
    assert "Өмнөхөөс авсан" in html_blocks(at)
    assert "10W-40 · 32 л · Жолооч Д. · 99110002" in html_blocks(at)
    assert at.expander[0].label == "Засах"


def test_wrong_plate_goes_back_to_edit(fake_api) -> None:
    at = click(type_plate(run_app(RECORD), "0001 ТЕС"), "Буруу байна — засах")
    assert step(at) == "manual"
    assert at.text_input(key="rec_manual").value == "0001 ТЕС"


def test_empty_form_shows_mongolian_errors_and_sends_nothing(fake_api) -> None:
    at = click(to_form(run_app(RECORD), "0001 ТЕС"), "Хадгалах")
    assert "Тосны төрөл оруулна уу." in texts(at.error)
    assert fake_api.posts == []


def test_destination_pills_with_name_mn_and_other(fake_api) -> None:
    seed_existing(fake_api)
    at = to_form(run_app(RECORD), "0002 ТЕС")
    pills = at.pills(key="f_destination_id")
    assert "Замын-Үүд" in pills.options and "Бусад" in pills.options
    at.number_input(key="f_odometer_km").set_value(215000)
    pills.set_value(-1).run()
    at.text_input(key="f_destination_raw").set_value("Сайншанд")
    at.pills(key="f_route").set_value("mixed").run()
    at = click(at, "Хадгалах")
    body, _ = fake_api.posts[-1]
    assert (body["destination_raw"], body["route"]) == ("Сайншанд", "mixed")
    assert "destination_id" not in body and "company_name" not in body


def test_duplicate_then_force_save(fake_api) -> None:
    vehicle = seed_existing(fake_api)
    fake_api._add_service(vehicle["id"], {"oil_grade": "10W-40", "liters": 32.0, "odometer_km": 210000})
    at = to_form(run_app(RECORD), "0002 ТЕС")
    at.number_input(key="f_odometer_km").set_value(210050)
    at.pills(key="f_destination_id").set_value(1).run()
    at = click(at, "Хадгалах")
    assert any("аль хэдийн бүртгэгдсэн" in t for t in texts(at.warning))
    count = len(fake_api.services)
    at = click(at, "Ингээд хадгалах")
    assert fake_api.posts[-1][1] is True
    assert len(fake_api.services) == count + 1
    assert step(at) == "success"


def test_duplicate_cancel(fake_api) -> None:
    vehicle = seed_existing(fake_api)
    fake_api._add_service(vehicle["id"], {"oil_grade": "10W-40", "liters": 32.0, "odometer_km": 210000})
    at = to_form(run_app(RECORD), "0002 ТЕС")
    at.number_input(key="f_odometer_km").set_value(210050)
    at.pills(key="f_destination_id").set_value(1).run()
    at = click(click(at, "Хадгалах"), "Болих")
    assert "Хадгалах" in [b.label for b in at.button]
    assert len(fake_api.posts) == 1


def test_fleet_number_in_two_companies(fake_api) -> None:
    fake_api.add_vehicle("HT-12", "Уурхай А ХХК", "fleet_no", oil_grade="15W-40", liters=40.0, engine_hours=1000.0)
    fake_api.add_vehicle("HT-12", "Уурхай Б ХХК", "fleet_no", oil_grade="10W-30", liters=45.0, engine_hours=2000.0)
    at = type_plate(run_app(RECORD), "ht-12", kind="fleet_no")
    at.radio(key="rec_choice").set_value(1).run()
    at = click(at, "Зөв, үргэлжлүүлэх")
    assert at.session_state["f_company_name"] == "Уурхай Б ХХК"
    assert at.session_state["f_oil_grade"] == "10W-30"
    assert at.number_input(key="f_engine_hours")  # mine trucks: engine hours shown


def test_api_down_shows_message(fake_api) -> None:
    def down(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    api_client.set_transport(httpx.MockTransport(down))
    at = type_plate(run_app(RECORD), "0001 ТЕС")
    assert not at.exception
    assert any("холбогдож" in t for t in texts(at.error))
    assert step(at) == "manual"


# --- photo -> recognize ------------------------------------------------------------------

def test_photo_recognized_goes_to_confirm(fake_api) -> None:
    seed_existing(fake_api)
    fake_api.recognize = (200, RECOGNIZED)
    at = upload_photo(run_app(RECORD), "rec_upload")
    assert not at.exception
    assert b'name="file"' in fake_api.uploads[0]
    assert step(at) == "confirm"
    assert "Дугаар уншигдлаа: 0002ТЕС" in texts(at.info)
    assert "Бүртгэлтэй · 1 удаа ирсэн" in html_blocks(at)


def test_photo_needs_manual_opens_manual_with_text(fake_api) -> None:
    fake_api.recognize = (200, {**RECOGNIZED, "plate_normalized": None, "plate_raw": "0002ТЕ",
                                "needs_manual": True, "reason": "invalid_format"})
    at = upload_photo(run_app(RECORD), "rec_upload")
    assert step(at) == "manual"
    assert at.text_input(key="rec_manual").value == "0002ТЕ"
    assert any("шалгаад" in t for t in texts(at.warning))


def test_recognizer_down_falls_back_to_manual(fake_api) -> None:
    at = upload_photo(run_app(RECORD), "rec_upload")  # default fake answer: 503
    assert not at.exception
    assert step(at) == "manual"
    assert any("гараар" in t for t in texts(at.warning))


# --- search + card (5.3 / DESIGN v2) ----------------------------------------------------------

def search(at: AppTest, query: str) -> AppTest:
    at.text_input(key="search_q").set_value(query).run()
    return click(at, "Хайх")


def test_single_match_opens_card(fake_api) -> None:
    seed_existing(fake_api)
    at = search(run_app(SEARCH), "0002 тес")
    assert not at.exception
    assert texts(at.title) == ["Машины карт"]
    page = html_blocks(at)
    assert '<div class="plate-box">0002 ТЕС</div>' in page
    assert "Таамаглал удахгүй нэмэгдэнэ" in page               # prediction null -> grey card
    assert ":blue-badge[Шинэ]" in page                         # segment
    assert "ердийн 32 л" in page                               # usual liters
    assert "Сүүлд солисон" in page and "10W-40 · 32 л" in page  # 3 tiles
    assert 'href="tel:99110002"' in page and "Залгах" in page  # call row


def test_card_shows_prediction(fake_api) -> None:
    seed_existing(fake_api)
    fake_api.prediction = PREDICTION
    at = search(run_app(SEARCH), "0002 ТЕС")
    card = next(t for t in texts(at.markdown) if 'class="pc"' in t)
    assert "9 хоног" in card and "үлдсэн" in card and "Удахгүй" in card and "2026-10-21" in card
    assert "#fbefd6" in card


def test_search_by_phone_and_recent(fake_api) -> None:
    seed_existing(fake_api)
    at = search(run_app(SEARCH), "+976 9911-0002")
    assert texts(at.title) == ["Машины карт"]
    at = click(on(at, CARD), "‹ Буцах")
    assert texts(at.title) == ["Хайх"]
    assert "Сүүлд үзсэн" in texts(at.subheader)
    assert "0002 ТЕС · Говь Тест ХХК" in [b.label for b in at.button]


def test_several_matches_listed(fake_api) -> None:
    fake_api.add_vehicle("HT-12", "Уурхай А ХХК", "fleet_no", oil_grade="15W-40", liters=40.0, engine_hours=1000.0)
    fake_api.add_vehicle("HT-12", "Уурхай Б ХХК", "fleet_no", oil_grade="10W-30", liters=45.0, engine_hours=2000.0)
    at = search(run_app(SEARCH), "HT-12")
    assert texts(at.title) == ["Хайх"]
    labels = [b.label for b in at.button]
    assert "HT-12 · Уурхай А ХХК · Шинэ" in labels and "HT-12 · Уурхай Б ХХК · Шинэ" in labels


def test_unknown_offers_new_vehicle_form(fake_api) -> None:
    at = search(run_app(SEARCH), "0404 ТЕС")
    assert "Олдсонгүй" in html_blocks(at)
    at = click(at, "Шинэ машин бүртгэх")
    assert texts(at.title) == ["Бүртгэх"]
    assert step(at) == "form"
    assert "Шинэ машин" in html_blocks(at)


def test_search_by_camera(fake_api) -> None:
    seed_existing(fake_api)
    fake_api.recognize = (200, RECOGNIZED)
    at = click(run_app(SEARCH), "📷  Камераар хайх")
    at = upload_photo(at, "search_upload")
    assert texts(at.title) == ["Машины карт"]


def test_card_record_button_opens_prefilled_form(fake_api) -> None:
    seed_existing(fake_api)
    at = click(on(search(run_app(SEARCH), "0002 ТЕС"), CARD), "Тос солилт бүртгэх")
    assert texts(at.title) == ["Бүртгэх"]
    assert step(at) == "form"
    assert at.session_state["f_oil_grade"] == "10W-40"


def test_save_then_find_by_plate_and_phone(fake_api) -> None:
    """DONE-WHEN path: save a new truck, then find it by plate AND by phone."""
    at = click(fill_new_vehicle(to_form(run_app(RECORD), "0001 ТЕС")), "Хадгалах")
    at = click(at, "Машины карт үзэх")
    assert texts(at.title) == ["Машины карт"]
    assert '<div class="plate-box">0001 ТЕС</div>' in html_blocks(at)

    at = search(run_app(SEARCH), "0001 ТЕС")
    assert '<div class="plate-box">0001 ТЕС</div>' in html_blocks(at)
    at = search(run_app(SEARCH), "99110099")
    assert '<div class="plate-box">0001 ТЕС</div>' in html_blocks(at)
    assert "Туршилт Тээвэр ХХК" in html_blocks(at)
