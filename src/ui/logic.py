"""Pure helpers for the Streamlit screens: Mongolian labels, form pre-fill,
request payload, error messages. No Streamlit, no network — easy to test.

Business rules are enforced by the API (docs/api_contract.md). The checks in
`build_service_payload` only catch obvious gaps early, with a Mongolian
message; the API stays the source of truth. Plate and phone normalization are
NOT repeated here (they live in the backend / src/common/plates.py).
"""

from datetime import date
from typing import Any

# --- Labels (UI text in Mongolian) ------------------------------------------

SEGMENT_LABELS: dict[str, str] = {
    "new": "Шинэ",
    "returning": "Давтан",
    "loyal": "Байнгын",
    "at_risk": "Эрсдэлтэй",
}
# st.badge colors
SEGMENT_COLORS: dict[str, str] = {
    "new": "blue",
    "returning": "green",
    "loyal": "violet",
    "at_risk": "red",
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
# (text color, background) per status — DESIGN v2
STATUS_COLORS: dict[str, tuple[str, str]] = {
    "ok": ("#1e6b34", "#e3f1e7"),
    "due_soon": ("#8a5300", "#fbefd6"),
    "overdue": ("#b3261e", "#f9e3e1"),
}
PENDING_COLORS = ("#5f6368", "#eceef1")  # grey card while prediction is null

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
    date, status_label, fg, bg, progress (0–1 share of the interval used),
    note (method + fallback reason), version.
    """
    fg, bg = PENDING_COLORS
    view: dict[str, Any] = {
        "pending": True, "big": PREDICTION_PENDING, "sub": "", "date": None,
        "status_label": "", "fg": fg, "bg": bg, "progress": None, "note": "", "version": "",
    }
    if not prediction or prediction.get("days_left") is None:
        return view
    days = int(prediction["days_left"])
    status = prediction.get("status") or ("overdue" if days < 0 else "ok")
    fg, bg = STATUS_COLORS.get(status, PENDING_COLORS)
    if days == 0:
        big, sub = "Өнөөдөр", ""
    else:
        big, sub = f"{abs(days)} хоног", "үлдсэн" if days > 0 else "хэтэрсэн"

    progress = None
    start, end = _parse_date(prediction.get("last_service_date")), _parse_date(prediction.get("predicted_date"))
    today = _parse_date(prediction.get("today"))
    if start and end and today and end > start:
        progress = min(max((today - start).days / (end - start).days, 0.0), 1.0)

    note = METHOD_LABELS.get(prediction.get("method", ""), "")
    reason = FALLBACK_LABELS.get(prediction.get("fallback_reason") or "")
    if reason:
        note = f"{note} ({reason})" if note else reason
    view.update(
        pending=False, big=big, sub=sub, date=prediction.get("predicted_date"),
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

# At risk = predicted date + AT_RISK_GRACE_DAYS < as_of, i.e. days_left < -AT_RISK_GRACE_DAYS.
# The only copy of this number in src/ui (D-052: no backend imports).
AT_RISK_GRACE_DAYS = 7  # mirrors D-007 / backend; remove when API adds segment field
SEGMENT_ORDER = ("new", "returning", "loyal", "at_risk")


def is_at_risk(reminder: dict) -> bool:
    """True if this due reminder belongs to «Эрсдэлтэй» (overdue beyond the grace)."""
    days_left = reminder.get("days_left")
    return days_left is not None and days_left < -AT_RISK_GRACE_DAYS


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
    """One line for «Өмнөхөөс авсан»: '15W-40 · 32 л · Тест Д. · 99110001' (only filled parts)."""
    parts = [
        form.get("oil_grade"),
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


def build_service_payload(
    identifier_type: str,
    identifier: str | None,
    is_new_vehicle: bool,
    form: dict[str, Any],
    oil_changer: str | None = None,
) -> tuple[dict[str, Any], list[str]]:
    """Turn form values into a POST /services body.

    Returns (payload, errors). `errors` holds Mongolian messages; when it is
    not empty, do not send the payload. service_date is not sent: the API
    uses today in Ulaanbaatar (scope §1 "date automatic").
    """
    errors: list[str] = []
    identifier = _clean(identifier)
    company = _clean(form.get("company_name"))
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
    if _clean(oil_changer):
        payload["oil_changer"] = _clean(oil_changer)
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
