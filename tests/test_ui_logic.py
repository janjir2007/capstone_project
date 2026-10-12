"""Tests for src/ui/logic.py and src/ui/auth.py (no Streamlit, no network).

All plates, names and phones are invented (RISK-06).
"""

from pathlib import Path

import pytest

from src.ui import auth, logic

SERVICE = {
    "id": 1,
    "vehicle_id": 1,
    "service_date": "2026-09-01",
    "odometer_km": 205000,
    "engine_hours": None,
    "oil_grade": "15W-40",
    "liters": 30.0,
    "route": "mn_china",
    "destination": {"id": 2, "name": "Zamyn-Uud (MN–CN border)", "route_category": "mn_china"},
    "destination_raw": None,
    "driver_name": "Тест Д.",
    "driver_phone": "99110001",
    "oil_changer": "A",
    "photo_ref": None,
    "created_at": "2026-09-01T10:00:00+08:00",
}
CARD = {
    "id": 1,
    "identifier_type": "plate",
    "identifier": "0001 ТЕС",
    "plate_normalized": "0001ТЕС",
    "vehicle_model": "Howo A7",
    "company": {"id": 1, "name": "Туршилт ХХК"},
    "service_count": 1,
    "segment": "new",
    "usual_liters": 30.0,
    "last_service": SERVICE,
    "history": [SERVICE],
    "prediction": None,
}


# --- labels / formatting ---------------------------------------------------------

def test_segment_label_known_and_null() -> None:
    assert logic.segment_label("at_risk") == "Эрсдэлтэй"
    assert logic.segment_label(None) == logic.NOT_GIVEN


def test_destination_label_prefers_name_mn() -> None:
    dest = {"id": 2, "name": "Zamyn-Uud", "route_category": "mn_china"}
    assert logic.destination_label(dest) == "Zamyn-Uud"
    assert logic.destination_label({**dest, "name_mn": "Замын-Үүд"}) == "Замын-Үүд"
    assert logic.destination_label({**dest, "name_mn": None}) == "Zamyn-Uud"
    assert logic.destination_label(None) == logic.NOT_GIVEN


def test_service_destination_text_fallbacks() -> None:
    assert logic.service_destination_text(SERVICE) == "Zamyn-Uud (MN–CN border)"
    raw = {**SERVICE, "destination": None, "destination_raw": "Сайншанд"}
    assert logic.service_destination_text(raw) == "Сайншанд"
    only_route = {**raw, "destination_raw": None}
    assert logic.service_destination_text(only_route) == "Монгол – Хятад"


@pytest.mark.parametrize(
    ("value", "unit", "expected"),
    [(205000, "км", "205 000 км"), (30.0, "л", "30 л"), (28.5, "л", "28.5 л"), (None, "л", "—")],
)
def test_format_number(value, unit, expected) -> None:
    assert logic.format_number(value, unit) == expected


def test_service_line_is_compact() -> None:
    line = logic.service_line(SERVICE)
    assert line == "2026-09-01 · 205 000 км · 15W-40 30 л · Zamyn-Uud (MN–CN border)"


def test_service_meter_text_engine_hours_only() -> None:
    mine = {**SERVICE, "odometer_km": None, "engine_hours": 1200.5}
    assert logic.service_meter_text(mine) == "1 200.5 мц"


def test_prediction_null_shows_coming_soon() -> None:
    assert logic.prediction_text(None) == "Таамаглал удахгүй нэмэгдэнэ"


def test_prediction_present_is_shown() -> None:
    text = logic.prediction_text({"predicted_date": "2026-11-01", "days_left": 5, "status": "due_soon"})
    assert text == "Дараагийн солилт: 2026-11-01 · 5 хоног үлдсэн · Удахгүй"


# --- form pre-fill -------------------------------------------------------------------

def test_prefill_from_card_keeps_fresh_fields_empty() -> None:
    form = logic.prefill_from_card(CARD)
    assert form["oil_grade"] == "15W-40"
    assert form["liters"] == 30.0
    assert form["driver_phone"] == "99110001"
    assert form["company_name"] == "Туршилт ХХК"
    # D-033: always entered fresh
    assert form["odometer_km"] is None
    assert form["engine_hours"] is None
    assert form["destination_id"] is None


def test_prefill_liters_falls_back_to_usual() -> None:
    card = {**CARD, "last_service": {**SERVICE, "liters": None}, "usual_liters": 32.0}
    assert logic.prefill_from_card(card)["liters"] == 32.0


def test_prefill_none_is_empty_form() -> None:
    assert logic.prefill_from_card(None) == logic.empty_form()


# --- payload ---------------------------------------------------------------------------

def _filled(**overrides) -> dict:
    form = logic.empty_form()
    form.update(
        company_name="  Туршилт   ХХК ",
        vehicle_model="Howo A7",
        odometer_km=120000,
        oil_grade=" 15W-40 ",
        liters=28.54,
        destination_id=2,
        driver_name="",
        driver_phone="99110001",
    )
    form.update(overrides)
    return form


def test_payload_new_vehicle() -> None:
    payload, errors = logic.build_service_payload("plate", " 0001 ТЕС ", True, _filled(), "  A ")
    assert errors == []
    assert payload == {
        "identifier_type": "plate",
        "identifier": "0001 ТЕС",
        "oil_grade": "15W-40",
        "liters": 28.5,
        "company_name": "Туршилт   ХХК",  # inner spacing is cleaned by the API
        "vehicle_model": "Howo A7",
        "odometer_km": 120000,
        "destination_id": 2,
        "driver_phone": "99110001",
        "oil_changer": "A",
    }
    assert "service_date" not in payload  # API uses today (Ulaanbaatar)


def test_payload_existing_plate_omits_company_and_model() -> None:
    payload, errors = logic.build_service_payload("plate", "0001 ТЕС", False, _filled())
    assert errors == []
    assert "company_name" not in payload
    assert "vehicle_model" not in payload


def test_payload_existing_fleet_no_keeps_company() -> None:
    payload, errors = logic.build_service_payload("fleet_no", "HT-12", False, _filled())
    assert errors == []
    assert payload["company_name"] == "Туршилт   ХХК"


def test_payload_other_destination_sends_raw_and_route() -> None:
    form = _filled(destination_id=logic.OTHER_DESTINATION, destination_raw=" Сайншанд ", route="mixed")
    payload, errors = logic.build_service_payload("plate", "0001 ТЕС", False, form)
    assert errors == []
    assert payload["destination_raw"] == "Сайншанд"
    assert payload["route"] == "mixed"
    assert "destination_id" not in payload


def test_payload_engine_hours_only() -> None:
    form = _filled(odometer_km=None, engine_hours=1200.5)
    payload, errors = logic.build_service_payload("fleet_no", "HT-12", True, form)
    assert errors == []
    assert payload["engine_hours"] == 1200.5
    assert "odometer_km" not in payload


def test_payload_errors_for_empty_form() -> None:
    _, errors = logic.build_service_payload("plate", "  ", True, logic.empty_form())
    assert len(errors) == 6  # identifier, company, meter, oil, liters, destination


def test_payload_other_destination_needs_name_and_route() -> None:
    form = _filled(destination_id=logic.OTHER_DESTINATION)
    _, errors = logic.build_service_payload("plate", "0001 ТЕС", False, form)
    assert errors == ["Очих газрын нэрийг бичнэ үү.", "Маршрутын төрөл сонгоно уу."]


# --- error messages --------------------------------------------------------------------

def test_error_messages_pydantic_list_translated() -> None:
    detail = [
        {"type": "value_error", "msg": "Value error, give odometer_km or engine_hours (at least one)"},
        {"type": "value_error", "msg": "Value error, phone must be 8 digits (Mongolian number, +976 optional)"},
    ]
    assert logic.error_messages(422, detail) == [
        "Гүйлт (км) эсвэл моторын цагийн аль нэгийг оруулна уу.",
        "Утасны дугаар 8 оронтой байх ёстой.",
    ]


def test_error_messages_string_detail() -> None:
    msg = "new vehicle: company_name is required (private owner = owner's name)"
    assert logic.error_messages(422, msg) == ["Компанийн нэр (эсвэл эзэмшигч) заавал оруулна."]
    assert logic.error_messages(422, "something new") == ["something new"]


def test_error_messages_connection_and_server() -> None:
    assert "холбогдож" in logic.error_messages(0, "refused")[0]
    assert "500" in logic.error_messages(500, None)[0]


# --- auth (D-061) -------------------------------------------------------------------------

def test_no_password_means_no_login(monkeypatch) -> None:
    monkeypatch.delenv("UI_PASSWORD", raising=False)
    assert not auth.login_required()
    assert auth.check_password("")


def test_empty_password_env_means_no_login(monkeypatch) -> None:
    monkeypatch.setenv("UI_PASSWORD", "")
    assert not auth.login_required()


def test_password_checked(monkeypatch) -> None:
    monkeypatch.setenv("UI_PASSWORD", "demo-pass")
    assert auth.login_required()
    assert auth.check_password("demo-pass")
    assert not auth.check_password("wrong")
    assert not auth.check_password(None)


def test_no_streamlit_pages_folder() -> None:
    """A folder named src/ui/pages/ would let /lookup open without app.py,
    i.e. without the login gate (Streamlit legacy multipage mode)."""
    ui = Path(__file__).resolve().parent.parent / "src" / "ui"
    assert not (ui / "pages").exists()
    assert (ui / "views" / "record.py").exists()
