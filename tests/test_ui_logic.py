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

def test_segment_labels_match_pm_list() -> None:
    assert [logic.segment_label(s) for s in ("new", "returning", "loyal", "at_risk")] == [
        "Шинэ", "Давтан", "Байнгын", "Эрсдэлтэй"]
    assert logic.segment_label(None) == logic.NOT_GIVEN


def test_destination_label_prefers_name_mn() -> None:
    dest = {"id": 2, "name": "Zamyn-Uud", "route_category": "mn_china"}
    assert logic.destination_label(dest) == "Zamyn-Uud"
    assert logic.destination_label({**dest, "name_mn": "Замын-Үүд"}) == "Замын-Үүд"
    assert logic.destination_label({**dest, "name_mn": None}) == "Zamyn-Uud"
    assert logic.destination_label({**dest, "name_mn": ""}) == "Zamyn-Uud"     # D-071: empty -> name
    assert logic.destination_label({**dest, "name_mn": "   "}) == "Zamyn-Uud"
    assert logic.destination_label({**dest, "name_mn": " Замын-Үүд "}) == "Замын-Үүд"
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


PREDICTION = {  # shape from docs/api_contract.md v0.5
    "vehicle_id": 1, "method": "ridge", "fallback_reason": None, "model_version": "ridge-0000abcd",
    "based_on_service_id": 1, "last_service_date": "2026-09-01", "predicted_days": 50.0,
    "predicted_date": "2026-10-21", "today": "2026-10-11", "days_left": 10, "status": "due_soon",
}


def test_prediction_null_is_grey_pending() -> None:
    view = logic.prediction_view(None)
    assert view["pending"] is True
    assert view["big"] == "Таамаглал удахгүй нэмэгдэнэ"
    assert (view["fg"], view["bg"]) == logic.PENDING_COLORS


def test_prediction_due_soon() -> None:
    view = logic.prediction_view(PREDICTION)
    assert view["pending"] is False
    assert (view["big"], view["sub"]) == ("10 хоног", "үлдсэн")
    assert view["status_label"] == "Удахгүй"
    assert (view["fg"], view["bg"]) == ("#6B3F00", "#FBEFD6")
    assert view["date"] == "2026-10-21"
    assert view["progress"] == 0.8  # 40 of 50 days used
    assert view["note"] == "Загварын таамаглал"
    assert view["version"] == "ridge-0000abcd"


def test_prediction_overdue_and_fallback_note() -> None:
    pred = {**PREDICTION, "days_left": -5, "status": "overdue", "method": "b0",
            "fallback_reason": "route_not_modelled", "today": "2026-10-26"}
    view = logic.prediction_view(pred)
    assert (view["big"], view["sub"], view["status_label"]) == ("5 хоног", "хэтэрсэн", "Хэтэрсэн")
    assert view["fg"] == "#8C1D18"
    assert view["progress"] == 1.0  # clipped
    assert view["note"] == "Дундаж хугацаа (энэ маршрутад загвар байхгүй)"


def test_prediction_ok_and_today() -> None:
    ok = logic.prediction_view({**PREDICTION, "days_left": 30, "status": "ok"})
    assert ok["status_label"] == "Хэвийн" and ok["fg"] == "#14532D"
    today = logic.prediction_view({**PREDICTION, "days_left": 0, "status": "due_soon"})
    assert (today["big"], today["sub"]) == ("Өнөөдөр", "")


def test_recognize_outcome_clear_read() -> None:
    result = {"plate_raw": "0001ТЕС", "plate_normalized": "0001ТЕС", "confidence": 0.93,
              "needs_manual": False, "reason": None}
    assert logic.recognize_outcome(result) == ("0001ТЕС", False, "Дугаар уншигдлаа: 0001ТЕС")


def test_recognize_outcome_needs_manual() -> None:
    low = {"plate_raw": "0001ТЕ5", "plate_normalized": None, "needs_manual": True, "reason": "low_confidence"}
    plate, manual, msg = logic.recognize_outcome(low)
    assert (plate, manual) == ("0001ТЕ5", True)  # raw text kept for the oil changer to fix
    assert "шалгаад" in msg
    none = {"plate_raw": "", "plate_normalized": None, "needs_manual": True, "reason": "no_plate"}
    assert logic.recognize_outcome(none) == ("", True, logic.RECOGNIZE_REASONS["no_plate"])


def test_recognize_error_messages_say_type_it() -> None:
    for status in (0, 413, 422, 500, 503):
        assert "гараар" in logic.recognize_error_message(status)


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
    payload, errors = logic.build_service_payload("plate", " 0001 ТЕС ", True, _filled())
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
    }
    assert "oil_changer" not in payload  # T6: field removed (optional in the contract)
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


VIEWS = ("home.py", "record.py", "search.py", "card.py", "reminders.py")


def test_no_streamlit_pages_folder() -> None:
    """A folder named src/ui/pages/ would let a screen URL open without app.py,
    i.e. without the login gate (Streamlit legacy multipage mode). Every screen
    must live in views/; behaviour is tested in test_ui_app.py."""
    ui = Path(__file__).resolve().parent.parent / "src" / "ui"
    assert not (ui / "pages").exists()
    assert sorted(p.name for p in (ui / "views").glob("*.py")) == sorted(VIEWS)


def test_prev_summary_only_filled_parts() -> None:
    form = logic.prefill_from_card(CARD)
    assert logic.prev_summary(form) == "30 л · Тест Д. · 99110001"
    assert logic.prev_summary({**form, "driver_name": None, "driver_phone": ""}) == "30 л"
    assert logic.prev_summary(logic.empty_form()) == "—"


# --- reminders dashboard (5.4) ----------------------------------------------------------

def test_split_reminders_uses_d007_grace() -> None:
    reminders = [{"service_id": 1, "days_left": 3}, {"service_id": 2, "days_left": -8},
                 {"service_id": 3, "days_left": -7}, {"service_id": 4, "days_left": -30}]
    to_send, at_risk = logic.split_reminders(reminders)
    assert [r["service_id"] for r in to_send] == [1, 3]   # -7 = exactly the grace -> not yet at risk
    assert [r["service_id"] for r in at_risk] == [2, 4]   # order kept


def test_days_left_text() -> None:
    assert logic.days_left_text(5) == "5 хоног үлдсэн"
    assert logic.days_left_text(-3) == "3 хоног хэтэрсэн"
    assert logic.days_left_text(0) == "Өнөөдөр"
    assert logic.days_left_text(None) == "—"


def test_photo_content_type() -> None:
    assert logic.photo_content_type("IMG_0001.HEIC", "") == "image/heic"   # iPhone, empty browser type
    assert logic.photo_content_type("IMG_0001.heif", None) == "image/heif"
    assert logic.photo_content_type("truck.png", None) == "image/png"
    assert logic.photo_content_type("truck.jpg", "image/jpeg") == "image/jpeg"  # browser type wins
    assert logic.photo_content_type(None, None) == "image/jpeg"
    assert {"heic", "heif"} <= set(logic.UPLOAD_TYPES)


# --- T6 choice lists ----------------------------------------------------------------------

def test_vehicle_model_list_and_old_value_still_shown() -> None:
    assert len(logic.VEHICLE_MODELS) == 26 and "KAMAZ" in logic.VEHICLE_MODELS
    opts = logic.model_options()
    assert opts[-1] == "Бусад" and opts[0] == "Volvo FH"
    old = logic.model_options("Howo A7")            # free-text DB value not in the list (D-019)
    assert old[0] == "Howo A7" and old[-1] == "Бусад" and len(old) == 28


def test_oil_grade_split_and_resolve() -> None:
    assert logic.split_choice("10W-40", logic.OIL_GRADES, logic.DEFAULT_OIL_GRADE) == ("10W-40", None)
    assert logic.split_choice("5W-30", logic.OIL_GRADES, logic.DEFAULT_OIL_GRADE) == ("Бусад", "5W-30")
    assert logic.split_choice(None, logic.OIL_GRADES, logic.DEFAULT_OIL_GRADE) == ("15W-40", None)
    assert logic.resolve_choice("20W-50", None) == "20W-50"
    assert logic.resolve_choice("Бусад", " 5W-30 ") == "5W-30"
    assert logic.resolve_choice("Бусад", "  ") is None


def test_status_colors_are_aaa_contrast() -> None:
    """T6: status text on its tint must stay readable outdoors (WCAG AAA, >= 7:1)."""
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    for fg, bg in [*logic.STATUS_COLORS.values(), logic.PENDING_COLORS]:
        hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 7, (fg, bg)
