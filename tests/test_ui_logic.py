"""Tests for src/ui/logic.py and src/ui/auth.py (no Streamlit, no network).

All plates, names and phones are invented (RISK-06).
"""

from datetime import date
from pathlib import Path
from urllib.parse import unquote

import pytest

from src.ui import auth, logic

SERVICE = {
    "id": 1,
    "vehicle_id": 1,
    "service_date": "2026-09-01",
    "odometer_km": 205000,
    "target_km": 220000,  # 9.5a: odometer + OIL_INTERVAL_KM, computed by the API
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
    assert (view["fg"], view["bg"]) == ("#A05A00", "#FFF4E0")
    assert view["date"] == "2026-10-21"
    assert view["progress"] == 0.8  # 40 of 50 days used
    assert view["note"] == "Загварын таамаглал"
    assert view["version"] == "ridge-0000abcd"


def test_prediction_overdue_and_fallback_note() -> None:
    pred = {**PREDICTION, "days_left": -5, "status": "overdue", "method": "b0",
            "fallback_reason": "route_not_modelled", "today": "2026-10-26"}
    view = logic.prediction_view(pred)
    assert (view["big"], view["sub"], view["status_label"]) == ("5 хоног", "хоцорсон", "Хэтэрсэн")  # T9 mockup wording
    assert view["fg"] == "#B42318"
    assert view["progress"] == 1.0  # clipped
    assert view["note"] == "Дундаж хугацаа (энэ маршрутад загвар байхгүй)"


def test_prediction_ok_and_today() -> None:
    ok = logic.prediction_view({**PREDICTION, "days_left": 30, "status": "ok"})
    assert ok["status_label"] == "Хэвийн" and ok["fg"] == "#1E7A4C"
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
    # always entered fresh
    assert form["odometer_km"] is None
    assert form["engine_hours"] is None
    assert "destination_id" not in form  # 9.5a: no destination in the form


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
        "company_name": "Тодорхойгүй",  # T8: new plate vehicle -> default, typed value ignored
        "vehicle_model": "Howo A7",
        "odometer_km": 120000,
        "driver_phone": "99110001",
    }
    assert not {"destination_id", "destination_raw", "route"} & set(payload)  # 9.5a: not asked any more
    assert "oil_changer" not in payload  # T6: field removed (optional in the contract)
    assert "service_date" not in payload  # API uses today (Ulaanbaatar)


def test_payload_new_fleet_no_sends_typed_company() -> None:
    payload, errors = logic.build_service_payload("fleet_no", "HT-12", True, _filled())
    assert errors == []
    assert payload["company_name"] == "Туршилт   ХХК"  # inner spacing is cleaned by the API


def test_payload_new_fleet_no_requires_company() -> None:
    _, errors = logic.build_service_payload("fleet_no", "HT-12", True, _filled(company_name=" "))
    assert "Компанийн нэр (эсвэл эзэмшигч) оруулна уу." in errors


def test_payload_existing_plate_omits_company_and_model() -> None:
    payload, errors = logic.build_service_payload("plate", "0001 ТЕС", False, _filled())
    assert errors == []
    assert "company_name" not in payload
    assert "vehicle_model" not in payload


def test_payload_existing_fleet_no_keeps_company() -> None:
    payload, errors = logic.build_service_payload("fleet_no", "HT-12", False, _filled())
    assert errors == []
    assert payload["company_name"] == "Туршилт   ХХК"


def test_payload_engine_hours_only() -> None:
    form = _filled(odometer_km=None, engine_hours=1200.5)
    payload, errors = logic.build_service_payload("fleet_no", "HT-12", True, form)
    assert errors == []
    assert payload["engine_hours"] == 1200.5
    assert "odometer_km" not in payload


def test_payload_errors_for_empty_form() -> None:
    _, errors = logic.build_service_payload("plate", "  ", True, logic.empty_form())
    assert len(errors) == 4  # identifier, meter, oil, liters (plate: company is automatic, T8; 9.5a: no destination)
    _, errors = logic.build_service_payload("fleet_no", "  ", True, logic.empty_form())
    assert len(errors) == 5  # + company (fleet number)


# --- target km + odometer check (9.5a) -------------------------------------------------

def test_target_text() -> None:
    assert logic.target_text(SERVICE) == "220 000 км"
    assert logic.target_text({**SERVICE, "odometer_km": None, "target_km": None}) == "—"  # mine truck
    assert logic.target_text(None) == "—"


def test_last_odometer_skips_engine_hours_only_services() -> None:
    hours_only = {**SERVICE, "odometer_km": None, "engine_hours": 1200.0}
    older = {**SERVICE, "odometer_km": 190000}
    assert logic.last_odometer({"history": [hours_only, SERVICE, older]}) == 205000
    assert logic.last_odometer({"history": [hours_only]}) is None
    assert logic.last_odometer(None) is None


def test_odometer_question_shows_both_numbers() -> None:
    assert logic.odometer_question(20500, 205000) == "Гүйлт зөв үү? Өмнөх: 205 000 км · одоо: 20 500 км"


@pytest.mark.parametrize(("new_km", "last_km", "warns"), [
    (210000, 205000, False),  # higher: fine
    (205000, 205000, True),   # same: must be higher
    (20500, 205000, True),    # a digit missing
    (None, 205000, False),    # not typed yet
    (150000, None, False),    # nothing to compare (new truck / mine truck)
])
def test_odometer_warning(new_km, last_km, warns) -> None:
    warning = logic.odometer_warning(new_km, last_km)
    assert (warning is not None) == warns
    if warns:
        assert "205 000 км" in warning


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


VIEWS = ("home.py", "record.py", "search.py", "dashboard.py", "card.py", "reminders.py")


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

def test_split_reminders_uses_api_segment() -> None:
    """D-074: the API's `segment` decides «Эрсдэлтэй»; days_left alone no longer does (no D-007 copy in the UI)."""
    reminders = [{"service_id": 1, "days_left": 3, "segment": "loyal"},
                 {"service_id": 2, "days_left": -8, "segment": "at_risk"},
                 {"service_id": 3, "days_left": -30, "segment": "returning"},
                 {"service_id": 4, "days_left": -30, "segment": "at_risk"},
                 {"service_id": 5, "days_left": -30}]
    to_send, at_risk = logic.split_reminders(reminders)
    assert [r["service_id"] for r in to_send] == [1, 3, 5]
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


def test_oil_pair_text_usual_liters() -> None:
    """T8: «Тос» pair shows usual liters; last liters only when there is no usual value."""
    nb = "\u00a0"
    assert logic.oil_pair_text({"oil_grade": "15W-40", "liters": 28.0}, 30.0) == f"15W-40 · ердийн{nb}30{nb}л"
    assert logic.oil_pair_text({"oil_grade": "15W-40", "liters": 28.0}, None) == f"15W-40 · 28{nb}л"
    assert logic.oil_pair_text(None, 30.0) == logic.NOT_GIVEN


def test_today_text_mongolian() -> None:
    assert logic.today_text(date(2026, 10, 11)) == "10-р сарын 11, Ням"
    assert logic.today_text(date(2026, 10, 12)) == "10-р сарын 12, Даваа"


def test_status_colors_are_readable() -> None:
    """Status text on its soft tint must pass WCAG AA (>= 4.5:1). T7 tints (Ari) are 4.75–5.76."""
    def lum(h: str) -> float:
        c = [int(h[i:i + 2], 16) / 255 for i in (1, 3, 5)]
        c = [x / 12.92 if x <= 0.03928 else ((x + 0.055) / 1.055) ** 2.4 for x in c]
        return 0.2126 * c[0] + 0.7152 * c[1] + 0.0722 * c[2]

    for fg, bg in [*logic.STATUS_COLORS.values(), logic.PENDING_COLORS]:
        hi, lo = sorted((lum(fg), lum(bg)), reverse=True)
        assert (hi + 0.05) / (lo + 0.05) >= 4.5, (fg, bg)


# --- T9 (mockup) helpers ---------------------------------------------------------------

def test_month_day_and_phone_text() -> None:
    assert logic.month_day_text("2026-10-07") == "10-р сарын 7"
    assert logic.month_day_text(None) == "—" and logic.month_day_text("bad") == "—"
    assert logic.phone_text("99110008") == "9911 0008"
    assert logic.phone_text("+97699") == "+97699" and logic.phone_text(None) == ""
    assert logic.driver_text("Түмэн О.", "99110008") == "Түмэн О. · 9911 0008"
    assert logic.driver_text(None, None) == "—"


def test_prediction_date_line() -> None:
    late = logic.prediction_view({**PREDICTION, "days_left": -5, "status": "overdue", "predicted_date": "2026-10-07"})
    assert late["date_line"] == "Солих ёстой байсан: 10-р сарын 7"
    soon = logic.prediction_view({**PREDICTION, "days_left": 9, "predicted_date": "2026-10-21"})
    assert soon["date_line"] == "Дараагийн солилт: 10-р сарын 21"


def test_prediction_range_line() -> None:
    """Task 2.9 (contract v0.9): "≈ date" + "(low – high)" when the API sends a range."""
    view = logic.prediction_view({**PREDICTION, "range_low_date": "2026-10-03", "range_high_date": "2026-11-12"})
    assert view["date_line"] == "Дараагийн солилт: ≈ 10-р сарын 21"
    assert view["range_line"] == "(10-р сарын 3 – 11-р сарын 12)"
    old = logic.prediction_view({**PREDICTION, "range_low_date": None, "range_high_date": None})
    assert old["range_line"] == "" and "≈" not in old["date_line"]
    assert logic.prediction_view(None)["range_line"] == ""


def test_arrival_view() -> None:
    assert logic.arrival_view(None) is None
    on_time = logic.arrival_view({**PREDICTION, "days_left": 2, "predicted_date": "2026-10-14"})
    assert (on_time["label"], on_time["big"], on_time["sub"], on_time["date"]) == (
        "Цагтаа ирсэн", "2 хоног", "эрт ирсэн", "10-р сарын 14")
    assert logic.arrival_view({**PREDICTION, "days_left": 0})["sub"] == "хугацаандаа"
    assert logic.arrival_view({**PREDICTION, "days_left": 30})["label"] == "Эрт ирсэн"
    late = logic.arrival_view({**PREDICTION, "days_left": -4})
    assert (late["label"], late["big"], late["fg"]) == ("Хоцорсон", "4 хоног", logic.STATUS_COLORS["overdue"][0])


def test_prev_visit_text() -> None:
    last = {"service_date": "2026-08-19", "odometer_km": 186300,
            "destination": {"id": 2, "name": "Zamyn-Uud", "name_mn": "Замын-Үүд"}}
    assert logic.prev_visit_text(last) == "08-19 · 186 300 км · Замын-Үүд"
    assert logic.prev_visit_text(None) == "—"
    assert logic.prev_visit_text({"service_date": "2026-10-29", "odometer_km": 190000}) == "10-29 · 190 000 км"  # 9.5a


def test_reminder_counts() -> None:
    """9.5b: every due item is a message to send; per stage; at risk = 3m (90+ days, API segment)."""
    rows = [{"stage": "1m", "segment": "loyal"}, {"stage": "1m", "segment": "new"},
            {"stage": "2m", "segment": "returning"}, {"stage": "3m", "segment": "at_risk"}]
    assert logic.reminder_counts(rows) == {"to_send": 4, "at_risk": 1, "1m": 2, "2m": 1, "3m": 1}
    assert logic.reminder_counts([]) == {"to_send": 0, "at_risk": 0, "1m": 0, "2m": 0, "3m": 0}


def test_stage_label_colors_and_days_since() -> None:
    assert [logic.stage_label(s) for s in ("1m", "2m", "3m", None)] == ["1 сар", "2 сар", "3 сар", "—"]
    assert logic.STAGE_COLORS["3m"] == logic.STATUS_COLORS["overdue"]  # AA pair, red = time to change
    assert logic.days_since_text(65) == "65 хоногийн өмнө" and logic.days_since_text(None) == "—"


# --- Viber link (5.5, D-091) ---------------------------------------------------------

def test_viber_forward_url_encodes_cyrillic_as_utf8() -> None:
    assert logic.viber_forward_url("Тос") == "viber://forward?text=%D0%A2%D0%BE%D1%81"


def test_viber_forward_url_round_trips_real_message_shape() -> None:
    """Spaces -> %20 (not "+"), newline and reserved URL characters encoded, text comes back exact."""
    message = "Сайн байна уу! 1234 УБА машины тос солих хугацаа 10/20.\nХолбогдох: +976 9911-0002 & #ГеоЭксперт?=1"
    url = logic.viber_forward_url(message)
    query = url.removeprefix("viber://forward?text=")
    assert url.startswith("viber://forward?text=")
    assert all(ch not in query for ch in " \n+&#?=/") and query.isascii()
    assert "%20" in query and "%0A" in query and "%2B976" in query
    assert unquote(query) == message


@pytest.mark.parametrize("message", [None, "", "   "])
def test_viber_forward_url_none_without_text(message) -> None:
    assert logic.viber_forward_url(message) is None


# --- «Хяналтын самбар» search (9.1) ------------------------------------------------------

ROW = {"id": 1, "identifier_type": "plate", "identifier": "0001 ТЕС", "vehicle_model": None,
       "company": {"id": 1, "name": "Туршилт ХХК"}, "service_count": 3, "last_service": SERVICE,
       "segment": "loyal", "status": None, "days_left": None, "matched_on": ["company"]}


def test_search_summary() -> None:
    assert logic.search_summary("", 40, 40) == "Бүх машин · 40"
    assert logic.search_summary(" говь ", 2, 2) == "«говь» · 2 машин"
    assert logic.search_summary("", 250, 200) == "Бүх машин · 250 (эхний 200 харагдаж байна)"
    assert logic.search_summary("", 8, 8, filtered=True) == "Шүүсэн · 8 машин"


def test_search_table_rows_keeps_numbers() -> None:
    [row] = logic.search_table_rows([ROW])
    assert row == {"Дугаар": "0001 ТЕС", "Компани": "Туршилт ХХК", "Сүүлд солисон": "2026-09-01",
                   "Гүйлт (км)": 205000, "Дараагийн солилт (км)": 220000, "Тос": "15W-40", "Литр": 30.0,
                   "Жолооч": "Тест Д.", "Утас": "9911 0001", "Удаа": 3}  # 9.5a: target instead of «Төлөв»


def test_search_table_rows_without_service() -> None:
    [row] = logic.search_table_rows([{**ROW, "last_service": None, "service_count": 0}])
    assert (row["Сүүлд солисон"], row["Гүйлт (км)"], row["Утас"]) == (None, None, None)


def test_filter_errors_and_count() -> None:
    from datetime import date as d
    assert logic.filter_errors({"date_from": d(2026, 10, 2), "date_to": d(2026, 10, 1)}) == [logic.FILTER_ORDER_ERROR]
    assert logic.filter_errors({"date_from": d(2026, 10, 1), "date_to": d(2026, 10, 1)}) == []
    assert logic.filter_errors({"date_to": d(2026, 10, 1)}) == []
    assert logic.active_filter_count({"date_from": None, "company_id": 3, "route": "mn_china", "oil_grade": ""}) == 2


def test_filters_text() -> None:
    from datetime import date as d
    filters = {"date_from": d(2026, 10, 1), "date_to": None, "company_id": 3, "route": "mn_china", "oil_grade": "15W-40"}
    assert logic.filters_text(" говь ", filters, {3: "Туршилт ХХК"}) == (
        "Хайлт: «говь» · Огноо: 2026-10-01 – … · Компани: Туршилт ХХК · Маршрут: Монгол – Хятад · Тос: 15W-40")
    assert logic.filters_text("", {}, {}) == "Шүүлтүүргүй — бүх машин"


def test_history_table_rows() -> None:
    mine = {**SERVICE, "odometer_km": None, "target_km": None, "engine_hours": 12980.5,
            "driver_name": None, "driver_phone": None}
    assert logic.history_table_rows([SERVICE, mine]) == [
        ("2026-09-01", "205 000 км", "220 000 км", "15W-40", "30 л", "Тест Д.", "9911 0001"),
        ("2026-09-01", "12 980.5 мц", "—", "15W-40", "30 л", "—", "—"),  # mine truck: no target
    ]
    assert len(logic.HISTORY_COLUMNS) == 7
