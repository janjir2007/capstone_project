"""Pure helpers for the Streamlit screens: Mongolian labels, form pre-fill,
request payload, error messages. No Streamlit, no network — easy to test.

Business rules are enforced by the API (docs/api_contract.md). The checks in
`build_service_payload` only catch obvious gaps early, with a Mongolian
message; the API stays the source of truth. Plate and phone normalization are
NOT repeated here (they live in the backend / src/common/plates.py).
"""

from datetime import date
from typing import Any
from urllib.parse import quote

# --- Labels (UI text in Mongolian) ------------------------------------------

SEGMENT_LABELS: dict[str, str] = {
    "new": "Шинэ",
    "returning": "Давтан",
    "loyal": "Байнгын",
    "at_risk": "Эрсдэлтэй",
}
# small colored dot next to the segment word (T7: the word carries the meaning, the dot is a hint)
SEGMENT_DOTS: dict[str, str] = {
    "new": "#1F4E9D",
    "returning": "#1E7A4C",
    "loyal": "#6D28D9",
    "at_risk": "#B42318",
}

ROUTE_LABELS: dict[str, str] = {
    "ub_city": "Улаанбаатар хот",
    "mn_china": "Монгол – Хятад",
    "mn_russia": "Монгол – Орос",
    "mine_site": "Уурхай",
    "mixed": "Холимог",
}

IDENTIFIER_TYPE_LABELS: dict[str, str] = {
    "plate": "Улсын дугаар",
    "fleet_no": "Парк дугаар",
}

PREDICTION_STATUS_LABELS: dict[str, str] = {
    "ok": "Хэвийн",
    "due_soon": "Удахгүй",
    "overdue": "Хэтэрсэн",
}
# (text color, soft tint) per status, same on card + dashboard, always shown with the word.
# T7 values (Ari): WCAG AA on the tint (4.75 / 4.87 / 5.76 : 1), tested >= 4.5.
STATUS_COLORS: dict[str, tuple[str, str]] = {
    "ok": ("#1E7A4C", "#E8F5EE"),
    "due_soon": ("#A05A00", "#FFF4E0"),
    "overdue": ("#B42318", "#FDECEC"),
}
PENDING_COLORS = ("#4B5563", "#F3F4F6")  # grey block while prediction is null (6.9:1)

# Prediction.method / fallback_reason (contract v0.5) -> short Mongolian note
METHOD_LABELS: dict[str, str] = {
    "ridge": "Загварын таамаглал",
    "b1": "Маршрутын тооцоо",
    "b0": "Дундаж хугацаа",
}
FALLBACK_LABELS: dict[str, str] = {
    "first_visit": "анхны үйлчилгээ",
    "destination_raw_only": "газрыг гараар бичсэн",
    "route_not_modelled": "энэ маршрутад загвар байхгүй",
    "unknown_destination": "очих газар тодорхойгүй",
}

# POST /plates/recognize reason -> what the oil changer should do
RECOGNIZE_REASONS: dict[str, str] = {
    "no_plate": "Зурган дээр дугаар олдсонгүй — гараар оруулна уу.",
    "empty": "Дугаар уншигдсангүй — гараар оруулна уу.",
    "invalid_format": "Дугаар бүрэн уншигдсангүй — шалгаад засна уу.",
    "low_confidence": "Дугаар тодорхой биш — шалгаад засна уу.",
}

PREDICTION_PENDING = "Таамаглал удахгүй нэмэгдэнэ"
NOT_GIVEN = "—"

# Known English API validation messages -> Mongolian (substring match).
API_MESSAGES_MN: dict[str, str] = {
    "odometer_km or engine_hours": "Гүйлт (км) эсвэл моторын цагийн аль нэгийг оруулна уу.",
    "exactly one of destination_id or destination_raw": "Очих газраа сонгоно уу.",
    "route is required": "Жагсаалтад байхгүй газарт маршрутын төрөл сонгоно уу.",
    "phone must be 8 digits": "Утасны дугаар 8 оронтой байх ёстой.",
    "company_name is required": "Компанийн нэр (эсвэл эзэмшигч) заавал оруулна.",
    "is in the future": "Ирээдүйн огноо оруулах боломжгүй.",
    "does not exist": "Сонгосон газар олдсонгүй. Жагсаалтыг дахин ачаална уу.",
    "conflicts with destination": "Маршрут нь сонгосон газартай таарахгүй байна.",
}


def segment_label(segment: str | None) -> str:
    """Mongolian name of a segment; '—' when unknown/null."""
    return SEGMENT_LABELS.get(segment or "", NOT_GIVEN)


def route_label(route: str | None) -> str:
    """Mongolian name of a route category; '—' when null."""
    return ROUTE_LABELS.get(route or "", NOT_GIVEN)


def destination_label(dest: dict | None) -> str:
    """Name to show for a destination: name_mn if present, else name (D-040, D-071).

    name_mn is nullable (contract v0.6): null, "" or spaces-only all mean "not labelled yet".
    """
    if not dest:
        return NOT_GIVEN
    return (dest.get("name_mn") or "").strip() or dest.get("name") or NOT_GIVEN


def service_destination_text(service: dict) -> str:
    """Where the truck went after this service: list destination, free text, or route."""
    if service.get("destination"):
        return destination_label(service["destination"])
    if service.get("destination_raw"):
        return service["destination_raw"]
    return route_label(service.get("route"))


def format_number(value: float | int | None, unit: str = "") -> str:
    """'205000' -> '205 000 км'; drops '.0'; None -> '—'."""
    if value is None:
        return NOT_GIVEN
    if float(value).is_integer():
        text = f"{int(value):,}".replace(",", " ")
    else:
        text = f"{value:,.1f}".replace(",", " ")
    return f"{text} {unit}".strip()


def service_meter_text(service: dict) -> str:
    """Odometer and/or engine hours of one service, e.g. '205 000 км · 1 200 мц'."""
    parts = []
    if service.get("odometer_km") is not None:
        parts.append(format_number(service["odometer_km"], "км"))
    if service.get("engine_hours") is not None:
        parts.append(format_number(service["engine_hours"], "мц"))
    return " · ".join(parts) or NOT_GIVEN


def oil_pair_text(last_service: dict | None, usual_liters: float | None) -> str:
    """Card «Тос» pair: '15W-40 · ердийн 30 л' (T8: usual liters back); last liters if no usual."""
    if not last_service:
        return NOT_GIVEN
    grade = last_service.get("oil_grade") or NOT_GIVEN
    # non-breaking spaces: '32 л' never splits over two lines at 390 px
    if usual_liters:
        return f"{grade} · ердийн\u00a0{format_number(usual_liters, 'л')}".replace(" л", "\u00a0л")
    return f"{grade} · {format_number(last_service.get('liters'), 'л')}".replace(" л", "\u00a0л")


def service_line(service: dict) -> str:
    """One compact history line that fits a ~390 px phone screen."""
    return " · ".join(
        [
            service.get("service_date", NOT_GIVEN),
            service_meter_text(service),
            f"{service.get('oil_grade', NOT_GIVEN)} {format_number(service.get('liters'), 'л')}",
            service_destination_text(service),
        ]
    )


def _parse_date(text: str | None) -> date | None:
    try:
        return date.fromisoformat(text) if text else None
    except ValueError:
        return None


def prediction_view(prediction: dict | None) -> dict[str, Any]:
    """Everything the prediction card shows, from a Prediction (contract v0.5) or null.

    Keys: pending, big ("5 хоног" / "Өнөөдөр"), sub ("үлдсэн" / "хэтэрсэн"),
    date, date_line, range_line ("(low – high)" or ""), status_label, fg, bg, progress (0–1 share of the interval used),
    note (method + fallback reason), version.
    """
    fg, bg = PENDING_COLORS
    view: dict[str, Any] = {
        "pending": True, "big": PREDICTION_PENDING, "sub": "", "date": None,
        "status_label": "", "fg": fg, "bg": bg, "progress": None, "note": "", "version": "", "range_line": "",
    }
    if not prediction or prediction.get("days_left") is None:
        return view
    days = int(prediction["days_left"])
    status = prediction.get("status") or ("overdue" if days < 0 else "ok")
    fg, bg = STATUS_COLORS.get(status, PENDING_COLORS)
    if days == 0:
        big, sub = "Өнөөдөр", ""
    else:
        big, sub = f"{abs(days)} хоног", "үлдсэн" if days > 0 else "хоцорсон"  # T9 mockup wording

    progress = None
    start, end = _parse_date(prediction.get("last_service_date")), _parse_date(prediction.get("predicted_date"))
    today = _parse_date(prediction.get("today"))
    if start and end and today and end > start:
        progress = min(max((today - start).days / (end - start).days, 0.0), 1.0)

    note = METHOD_LABELS.get(prediction.get("method", ""), "")
    reason = FALLBACK_LABELS.get(prediction.get("fallback_reason") or "")
    if reason:
        note = f"{note} ({reason})" if note else reason
    # Task 2.9 (contract v0.9): 80% range -> "≈ date" + "(low – high)"; older API without it -> date only.
    low, high = prediction.get("range_low_date"), prediction.get("range_high_date")
    approx = "≈ " if low and high else ""
    view.update(
        pending=False, big=big, sub=sub, date=prediction.get("predicted_date"),
        date_line=f"{'Солих ёстой байсан' if days < 0 else 'Дараагийн солилт'}: "
                  f"{approx}{month_day_text(prediction.get('predicted_date'))}",
        range_line=f"({month_day_text(low)} – {month_day_text(high)})" if approx else "",
        status_label=PREDICTION_STATUS_LABELS.get(status, status), fg=fg, bg=bg,
        progress=progress, note=note, version=prediction.get("model_version") or "",
    )
    return view


def recognize_outcome(result: dict) -> tuple[str, bool, str]:
    """(plate to put in the field, needs_manual, message) from POST /plates/recognize.

    Contract: pre-fill with plate_normalized (else plate_raw); needs_manual -> the
    oil changer must check/type the plate before it is looked up.
    """
    plate = result.get("plate_normalized") or result.get("plate_raw") or ""
    needs_manual = bool(result.get("needs_manual")) or not plate
    if needs_manual:
        message = RECOGNIZE_REASONS.get(result.get("reason") or "", "Дугаараа шалгаад засна уу.")
        return plate, True, message
    return plate, False, f"Дугаар уншигдлаа: {plate}"


# Photo types for the uploaders. HEIC/HEIF = iPhone default (RISK-17); the API
# converts them (pillow-heif, contract v0.5). Same list everywhere in the UI.
UPLOAD_TYPES = ["jpg", "jpeg", "png", "heic", "heif"]
_CONTENT_TYPES = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
                  "heic": "image/heic", "heif": "image/heif"}


def photo_content_type(filename: str | None, browser_type: str | None) -> str:
    """Content type to send with the photo: the browser's, else from the extension.

    Some browsers send HEIC with an empty type; the API decodes the bytes anyway,
    but a correct label helps logs and debugging.
    """
    if browser_type:
        return browser_type
    ext = (filename or "").rsplit(".", 1)[-1].lower()
    return _CONTENT_TYPES.get(ext, "image/jpeg")


def recognize_error_message(status: int) -> str:
    """Mongolian message when POST /plates/recognize fails; always ends in 'type it'."""
    if status == 503:
        return "Автомат таних одоогоор ажиллахгүй байна — дугаараа гараар оруулна уу."
    if status == 413:
        return "Зураг хэт том байна (15 MB-аас их) — гараар оруулна уу."
    if status == 422:
        return "Зураг уншигдсангүй — дахин авах эсвэл гараар оруулна уу."
    if status == 0:
        return "Сервертэй холбогдож чадсангүй — дугаараа гараар оруулна уу."
    return f"Таних үед алдаа гарлаа ({status}) — гараар оруулна уу."


# --- Reminders dashboard (5.4) ---------------------------------------------------

SEGMENT_ORDER = ("new", "returning", "loyal", "at_risk")


def is_at_risk(reminder: dict) -> bool:
    """True if this due reminder belongs to «Эрсдэлтэй». The API decides (contract v0.7 `segment`,
    D-074): the D-007 grace rule lives only in the backend."""
    return reminder.get("segment") == "at_risk"


WEEKDAYS_MN = ("Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням")


def today_text(day: date) -> str:
    """Home date line: '10-р сарын 11, Бямба'."""
    return f"{day.month}-р сарын {day.day}, {WEEKDAYS_MN[day.weekday()]}"


def split_reminders(reminders: list[dict]) -> tuple[list[dict], list[dict]]:
    """(«Илгээх», «Эрсдэлтэй») keeping the API order (oldest send_on first)."""
    to_send = [r for r in reminders if not is_at_risk(r)]
    at_risk = [r for r in reminders if is_at_risk(r)]
    return to_send, at_risk


def days_left_text(days_left: int | None) -> str:
    """'5 хоног үлдсэн' / '3 хоног хэтэрсэн' / 'Өнөөдөр'."""
    if days_left is None:
        return NOT_GIVEN
    if days_left == 0:
        return "Өнөөдөр"
    return f"{abs(days_left)} хоног {'үлдсэн' if days_left > 0 else 'хэтэрсэн'}"


# --- T9 (mockup): short Mongolian texts for the new layouts ---------------------------

def month_day_text(text: str | None) -> str:
    """'2026-10-07' -> '10-р сарын 7' (mockup date style); '—' when missing/invalid."""
    day = _parse_date(text)
    return f"{day.month}-р сарын {day.day}" if day else NOT_GIVEN


def phone_text(phone: str | None) -> str:
    """'99110008' -> '9911 0008' (easier to read aloud); anything else unchanged."""
    if phone and len(phone) == 8 and phone.isdigit():
        return f"{phone[:4]} {phone[4:]}"
    return phone or ""


def driver_text(name: str | None, phone: str | None) -> str:
    """'Түмэн О. · 9911 0008' (only filled parts)."""
    return " · ".join(p for p in (name, phone_text(phone)) if p) or NOT_GIVEN


def prev_visit_text(service: dict | None) -> str:
    """«Өмнөх удаа» line: '08-19 · 186 300 км · Замын-Үүд'."""
    if not service:
        return NOT_GIVEN
    day = _parse_date(service.get("service_date"))
    parts = [day.strftime("%m-%d") if day else None, service_meter_text(service), service_destination_text(service)]
    return " · ".join(p for p in parts if p and p != NOT_GIVEN) or NOT_GIVEN


def arrival_view(prediction: dict | None) -> dict[str, str] | None:
    """How this visit compares with the prediction made after the last one (recognized truck).

    days_left > 14 -> «Эрт ирсэн» · 0–14 -> «Цагтаа ирсэн» · < 0 -> «Хоцорсон». Same colors as
    the status block (word + dot, never color alone). None when there is no prediction.
    """
    if not prediction or prediction.get("days_left") is None:
        return None
    days = int(prediction["days_left"])
    if days < 0:
        label, (fg, bg), big, sub = "Хоцорсон", STATUS_COLORS["overdue"], f"{-days} хоног", "хоцорсон"
    elif days > 14:
        label, (fg, bg), big, sub = "Эрт ирсэн", ("#1F4E9D", "#EAF0FA"), f"{days} хоног", "эрт ирсэн"
    elif days == 0:
        label, (fg, bg), big, sub = "Цагтаа ирсэн", STATUS_COLORS["ok"], "Яг", "хугацаандаа"
    else:
        label, (fg, bg), big, sub = "Цагтаа ирсэн", STATUS_COLORS["ok"], f"{days} хоног", "эрт ирсэн"
    return {"label": label, "fg": fg, "bg": bg, "big": big, "sub": sub,
            "date": month_day_text(prediction.get("predicted_date"))}


def destination_change_note(last_service: dict | None, chosen_id: int | None) -> str | None:
    """'Өмнө нь Замын-Үүд байсан → шинэ чиглэлээр дахин таамаглана' when the chosen
    destination differs from the last service's; None otherwise (or nothing to compare)."""
    if not last_service or chosen_id is None:
        return None
    before = (last_service.get("destination") or {}).get("id")
    if before is None or before == chosen_id:
        return None
    return f"Өмнө нь {service_destination_text(last_service)} байсан → шинэ чиглэлээр дахин таамаглана"


def reminder_counts(reminders: list[dict]) -> dict[str, int]:
    """Home / «Сануулга» numbers: to send today («Илгээх» group), overdue, at risk."""
    to_send, at_risk = split_reminders(reminders)
    return {"to_send": len(to_send), "at_risk": len(at_risk),
            "overdue": sum(1 for r in reminders if (r.get("days_left") or 0) < 0)}


VIBER_FORWARD = "viber://forward?text="  # D-091: opens Viber's share screen, the manager picks the chat


def viber_forward_url(message: str | None) -> str | None:
    """«Viber-ээр илгээх» link with the reminder text pre-filled, or None when there is no text.

    quote(safe="") percent-encodes everything except A-Z a-z 0-9 _.-~ as UTF-8, so Cyrillic,
    spaces (%20, not "+"), newlines and the reserved "&", "#", "+", "?", "=" all survive.
    """
    if not message or not message.strip():
        return None
    return VIBER_FORWARD + quote(message, safe="")

# --- Choice lists (T6): tap/select instead of typing ---------------------------------

OTHER_CHOICE = "Бусад"  # last option of a choice list -> free-text field

# Truck models seen in Mongolia (T6 brief). The DB field stays free text (D-019): a value
# not in this list (old records, «Бусад») is still shown and saved as typed.
VEHICLE_MODELS = (
    "Volvo FH", "Volvo FM", "Volvo FMX", "Scania R", "Scania G", "Scania P", "Scania S",
    "MAN TGX", "MAN TGS", "Mercedes-Benz Actros", "Mercedes-Benz Arocs", "DAF XF",
    "Renault T", "Iveco Stralis", "Shacman X3000", "Shacman F3000", "Shacman X6000",
    "HOWO (Sinotruk)", "FAW J6", "Foton Auman", "Dongfeng", "Beiben", "Hyundai Xcient",
    "Isuzu Giga", "Hino 700", "KAMAZ",
)
OIL_GRADES = ("15W-40", "10W-40", "20W-50")
DEFAULT_OIL_GRADE = "15W-40"


def model_options(current: str | None = None) -> list[str]:
    """Selectbox options: the list (+ the current value first if it is not in it) + «Бусад»."""
    options = list(VEHICLE_MODELS)
    if current and current not in options:
        options.insert(0, current)
    return [*options, OTHER_CHOICE]


def split_choice(value: str | None, presets: tuple[str, ...] | list[str], default: str | None = None
                 ) -> tuple[str | None, str | None]:
    """(choice, other_text) for a stored value: a preset -> (preset, None); anything else ->
    («Бусад», value); empty -> (default, None)."""
    value = (value or "").strip()
    if not value:
        return default, None
    if value in presets:
        return value, None
    return OTHER_CHOICE, value


def resolve_choice(choice: str | None, other: str | None) -> str | None:
    """The value to save: the chosen preset, or the free text when «Бусад» is chosen."""
    if choice == OTHER_CHOICE:
        return (other or "").strip() or None
    return choice


# --- Recording form ----------------------------------------------------------

# Keys of the recording form in st.session_state (prefix avoids clashes).
FORM_FIELDS = (
    "company_name",
    "vehicle_model",
    "odometer_km",
    "engine_hours",
    "oil_grade",
    "liters",
    "destination_id",
    "destination_raw",
    "route",
    "driver_name",
    "driver_phone",
)
OTHER_DESTINATION = -1  # sentinel option: "not in the list" -> free text + route


def picker_destinations(destinations: list[dict]) -> list[dict]:
    """Destinations to offer as pills: every list row EXCEPT one labelled like the «Бусад» option.

    Migration 004 gave 'Other / several / unknown' the label «Бусад», the same text as the form's
    own «Бусад» (OTHER_DESTINATION -> place name + route, D-039), so the form showed two «Бусад»
    pills (task 7.2). The form's option asks for more (the place), so the list row is hidden.
    """
    return [d for d in destinations if destination_label(d) != OTHER_CHOICE]


def empty_form() -> dict[str, Any]:
    """Blank form values for a new vehicle."""
    return {name: None for name in FORM_FIELDS}


def prefill_from_card(card: dict | None) -> dict[str, Any]:
    """Form values for an existing vehicle, from its last service.

    Pre-filled: oil grade, liters, driver, phone (scope §1). Liters fall back to
    usual_liters. NOT pre-filled (always fresh, D-033): odometer, engine hours,
    destination. Company / model are shown but ignored by the API for an
    existing plate vehicle.
    """
    form = empty_form()
    if not card:
        return form
    form["company_name"] = (card.get("company") or {}).get("name")
    form["vehicle_model"] = card.get("vehicle_model")
    last = card.get("last_service") or {}
    form["oil_grade"] = last.get("oil_grade")
    form["liters"] = last.get("liters") if last.get("liters") is not None else card.get("usual_liters")
    form["driver_name"] = last.get("driver_name")
    form["driver_phone"] = last.get("driver_phone")
    return form


def prev_summary(form: dict[str, Any]) -> str:
    """One line for «Өмнөхөөс авсан»: '32 л · Тест Д. · 99110001' (only filled parts)."""
    parts = [
        format_number(form["liters"], "л") if form.get("liters") is not None else None,
        form.get("driver_name"),
        form.get("driver_phone"),
    ]
    return " · ".join(str(p) for p in parts if p) or NOT_GIVEN


def _clean(value: Any) -> Any:
    """Strip strings; blank string -> None."""
    if isinstance(value, str):
        value = value.strip()
        return value or None
    return value


# T8 (Ari): no company field for plate vehicles. A NEW plate vehicle gets this value because the
# API still requires company_name for new vehicles (D-042). Backend may make company_name
# optional later -> then remove this default and send nothing.
UNKNOWN_COMPANY = "Тодорхойгүй"


def build_service_payload(
    identifier_type: str,
    identifier: str | None,
    is_new_vehicle: bool,
    form: dict[str, Any],
) -> tuple[dict[str, Any], list[str]]:
    """Turn form values into a POST /services body.

    Returns (payload, errors). `errors` holds Mongolian messages; when it is
    not empty, do not send the payload. Company: new plate vehicle -> UNKNOWN_COMPANY; new or
    existing fleet number -> the typed / chosen company (fleet numbers are unique per company). service_date is not sent: the API
    uses today in Ulaanbaatar (scope §1 "date automatic").
    """
    errors: list[str] = []  # oil_changer is not sent (T6: field removed; optional in the contract)
    identifier = _clean(identifier)
    company = _clean(form.get("company_name"))
    if is_new_vehicle and identifier_type == "plate":
        company = UNKNOWN_COMPANY  # field hidden for plates (T8); fleet numbers still type it
    oil_grade = _clean(form.get("oil_grade"))
    liters = form.get("liters")
    odometer = form.get("odometer_km")
    hours = form.get("engine_hours")
    dest_id = form.get("destination_id")
    dest_raw = _clean(form.get("destination_raw"))
    route = form.get("route")

    if not identifier:
        errors.append("Улсын дугаар эсвэл парк дугаараа оруулна уу.")
    needs_company = is_new_vehicle or identifier_type == "fleet_no"
    if needs_company and not company:
        errors.append("Компанийн нэр (эсвэл эзэмшигч) оруулна уу.")
    if odometer is None and hours is None:
        errors.append("Гүйлт (км) эсвэл моторын цагийн аль нэгийг оруулна уу.")
    if not oil_grade:
        errors.append("Тосны төрөл оруулна уу.")
    if liters is None or liters <= 0:
        errors.append("Литр 0-ээс их байх ёстой.")
    if dest_id is None:
        errors.append("Дараа нь хаашаа явахыг сонгоно уу.")
    elif dest_id == OTHER_DESTINATION:
        if not dest_raw:
            errors.append("Очих газрын нэрийг бичнэ үү.")
        if not route:
            errors.append("Маршрутын төрөл сонгоно уу.")

    payload: dict[str, Any] = {
        "identifier_type": identifier_type,
        "identifier": identifier,
        "oil_grade": oil_grade,
        "liters": round(float(liters), 1) if liters is not None else None,
    }
    if needs_company:
        payload["company_name"] = company
    if is_new_vehicle and _clean(form.get("vehicle_model")):
        payload["vehicle_model"] = _clean(form.get("vehicle_model"))
    if odometer is not None:
        payload["odometer_km"] = int(odometer)
    if hours is not None:
        payload["engine_hours"] = round(float(hours), 1)
    if dest_id == OTHER_DESTINATION:
        payload["destination_raw"] = dest_raw
        payload["route"] = route
    elif dest_id is not None:
        payload["destination_id"] = int(dest_id)
    for name in ("driver_name", "driver_phone"):
        if _clean(form.get(name)):
            payload[name] = _clean(form.get(name))
    return payload, errors


# --- Errors ------------------------------------------------------------------

def _translate(message: str) -> str:
    for needle, mongolian in API_MESSAGES_MN.items():
        if needle in message:
            return mongolian
    return message


def error_messages(status: int, detail: Any) -> list[str]:
    """Mongolian messages for an API error (ApiError.status / .detail).

    422 detail is a list of pydantic errors or a plain string; known English
    messages are translated, unknown ones shown as they are.
    """
    if status == 0:
        return ["Сервертэй холбогдож чадсангүй. Интернэт болон API-г шалгана уу."]
    if status == 404:
        return ["Олдсонгүй."]
    if status == 409:
        return ["Мэдээлэл давхцлаа, юу ч хадгалагдаагүй. Дахин оролдоно уу."]
    if status == 422:
        if isinstance(detail, list):
            msgs = []
            for item in detail:
                msg = str(item.get("msg", item)) if isinstance(item, dict) else str(item)
                msgs.append(_translate(msg.removeprefix("Value error, ")))
            return list(dict.fromkeys(msgs)) or ["Буруу мэдээлэл."]
        return [_translate(str(detail))]
    return [f"Серверийн алдаа ({status}). Дахин оролдоно уу."]
