"""Pure helpers for the Streamlit screens: Mongolian labels, form pre-fill,
request payload, error messages. No Streamlit, no network — easy to test.

Business rules are enforced by the API (docs/api_contract.md). The checks in
`build_service_payload` only catch obvious gaps early, with a Mongolian
message; the API stays the source of truth. Plate and phone normalization are
NOT repeated here (they live in the backend / src/common/plates.py).
"""

from datetime import date, datetime, timedelta, timezone
from typing import Any
from urllib.parse import quote

# --- Labels (UI text in Mongolian) ------------------------------------------

SEGMENT_LABELS: dict[str, str] = {
    "new": "Шинэ",
    "returning": "Давтан",
    "loyal": "Байнгын",
    "at_risk": "Эргэж ирээгүй",  # 9.12: was «Эрсдэлтэй» (API value stays at_risk)
}
# small colored dot next to the segment word (T7: the word carries the meaning, the dot is a hint)
SEGMENT_DOTS: dict[str, str] = {
    "new": "#1F4E9D",
    "returning": "#1E7A4C",
    "at_risk": "#B42318",
}
# 9.12-3 (PM, as in the 9.12 mockup): «Байнгын» gets a star instead of a (purple) dot
SEGMENT_ICONS: dict[str, str] = {"loyal": "⭐"}

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
    "at most one of destination_id or destination_raw": "Очих газрыг нэг л удаа сонгоно уу.",
    "route is required": "Жагсаалтад байхгүй газарт маршрутын төрөл сонгоно уу.",
    "phone must be 8 digits": "Утасны дугаар 8 оронтой байх ёстой.",
    "company_name is required": "Компанийн нэр (эсвэл эзэмшигч) заавал оруулна.",
    "is in the future": "Ирээдүйн огноо оруулах боломжгүй.",
    "does not exist": "Сонгосон газар олдсонгүй. Жагсаалтыг дахин ачаална уу.",
    "conflicts with destination": "Маршрут нь сонгосон газартай таарахгүй байна.",
    # 9.14a: km readings + km checks
    "must be after the latest service": "Огноо нь сүүлийн тос солилтоос хойш байх ёстой.",
    "greater than 0": "0-ээс их тоо оруулна уу.",
    "the km check is not due yet": "Км шалгах өдөр хараахан болоогүй байна.",
    "asked for no more messages": "Энэ утас мессеж хүлээж авахгүй гэсэн.",
    "only readings typed in by hand": "Зөвхөн гараар бүртгэсэн км-ийг буцаана.",
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


def target_text(service: dict | None) -> str:
    """Task 9.5a: next oil change odometer of one service ('165 000 км'), from the API's target_km
    (odometer + OIL_INTERVAL_KM). '—' for mine trucks (engine hours only) or no service."""
    return format_number((service or {}).get("target_km"), "км")


def last_odometer(card: dict | None) -> int | None:
    """Newest odometer reading of a truck (history is newest first); skips engine-hours-only services."""
    for service in (card or {}).get("history") or []:
        if service.get("odometer_km") is not None:
            return int(service["odometer_km"])
    return None


def odometer_warning(new_km: float | int | None, last_km: int | None) -> str | None:
    """Task 9.5a: warning when the new odometer is NOT higher than the last one (typo, or a replaced
    meter). Only a warning: the oil changer may still save. None when fine or nothing to compare."""
    if new_km is None or last_km is None or new_km > last_km:
        return None
    return (f"Гүйлт өмнөхөөсөө ({format_number(last_km, 'км')}) их байх ёстой. "
            "Зөв эсэхийг шалгана уу.")


def odometer_question(new_km: float | int, last_km: int) -> str:
    """The question above «Ингээд хадгалах»: both numbers, so a missing digit is easy to see."""
    return f"Гүйлт зөв үү? Өмнөх: {format_number(last_km, 'км')} · одоо: {format_number(new_km, 'км')}"


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


# --- «Хяналтын самбар» 9.12: period KPIs + segment cards ------------------------------

PERIOD_LABELS: dict[str, str] = {"today": "Өнөөдөр", "week": "Энэ 7 хоног", "month": "Энэ сар"}
SEGMENT_CARDS = (None, "loyal", "new", "at_risk")  # None = «Бүгд»; «Давтан» only in «Шүүлтүүр» (approved plan)
ALL_LABEL = "Бүгд"


def period_tiles(stats: dict) -> list[tuple[str, str, str]]:
    """GET /stats/period -> 4 KPI tiles (value, small unit, label): services, first-ever trucks,
    liters, reminders marked sent."""
    return [
        (format_number(stats.get("services", 0)), "", "Үйлчилгээ"),
        (format_number(stats.get("new_vehicles", 0)), "", "Шинэ машин"),
        (format_number(stats.get("liters", 0)), "л", "Литр"),
        (format_number(stats.get("reminders_sent", 0)), "", "Сануулга илгээсэн"),
    ]


def period_range_text(stats: dict) -> str:
    """'2026-10-08' (one day) or '2026-10-06 – 2026-10-08'."""
    start, end = stats.get("date_from", ""), stats.get("date_to", "")
    return end if start == end else f"{start} – {end}"


def segment_cards(stats: dict) -> list[dict[str, Any]]:
    """GET /stats/segments -> the 4 cards: «Бүгд» (hint: how many came twice), «Байнгын»,
    «Шинэ», «Эргэж ирээгүй» (hint: AT_RISK_DAYS+ days, from the API). Count = what the table
    shows after the tap (same API rule, tested in tests/test_api_stats_period.py)."""
    counts = stats.get("counts") or {}
    hints = {None: f"{counts.get('returning', 0)} нь 2 удаа", "loyal": "3+ удаа", "new": "1 удаа",
             "at_risk": f"{stats.get('at_risk_days', 150)}+ хоног"}
    return [{"segment": s, "label": ALL_LABEL if s is None else SEGMENT_LABELS[s],
             "count": stats.get("total", 0) if s is None else counts.get(s, 0),
             "hint": hints[s]} for s in SEGMENT_CARDS]


# Task 9.5c: one reminder per service; the pill says whether the truck is also at risk (API `segment`).
# (label, text color, tint) = the same AA pairs as the status pills.
REMINDER_PILL_DUE = ("Сануулах", *STATUS_COLORS["due_soon"])
REMINDER_PILL_AT_RISK = (SEGMENT_LABELS["at_risk"], *STATUS_COLORS["overdue"])  # «Эргэж ирээгүй»


def reminder_pill(reminder: dict) -> tuple[str, str, str]:
    """(label, color, tint) of a due reminder: «Эргэж ирээгүй» (red) when at risk, else «Сануулах»."""
    return REMINDER_PILL_AT_RISK if is_at_risk(reminder) else REMINDER_PILL_DUE


def days_since_text(days: int | None) -> str:
    """'65 хоногийн өмнө' (since the latest oil change); '—' when missing."""
    return NOT_GIVEN if days is None else f"{days} хоногийн өмнө"


def is_at_risk(reminder: dict) -> bool:
    """True if this due reminder belongs to «Эргэж ирээгүй». The API decides (`segment`, D-074;
    9.5c: AT_RISK_DAYS (150)+ days since the latest service)."""
    return reminder.get("segment") == "at_risk"


WEEKDAYS_MN = ("Даваа", "Мягмар", "Лхагва", "Пүрэв", "Баасан", "Бямба", "Ням")


def today_text(day: date) -> str:
    """Home date line: '10-р сарын 11, Бямба'."""
    return f"{day.month}-р сарын {day.day}, {WEEKDAYS_MN[day.weekday()]}"


def split_reminders(reminders: list[dict]) -> tuple[list[dict], list[dict]]:
    """(«Илгээх», «Эргэж ирээгүй») keeping the API order (oldest send_on first)."""
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


def reminder_counts(reminders: list[dict]) -> dict[str, int]:
    """Home / «Сануулга» numbers (9.5c): every message to send today, the queue part and the at-risk part."""
    queue, at_risk = split_reminders(reminders)
    return {"to_send": len(reminders), "queue": len(queue), "at_risk": len(at_risk)}


# --- «Хяналтын самбар» search (9.1) --------------------------------------------------------

MATCH_LABELS: dict[str, str] = {
    "plate": "улсын дугаар",
    "fleet_no": "парк дугаар",
    "company": "компани",
    "phone": "утас",
}


def search_summary(query: str, total: int, shown: int, filtered: bool = False) -> str:
    """Line above the results: '«говь» · 2 машин' / 'Шүүсэн · 8 машин' / 'Бүх машин · 40'
    (+ how many are shown)."""
    query = (query or "").strip()
    if query:
        head = f"«{query}» · {total} машин"
    else:
        head = f"Шүүсэн · {total} машин" if filtered else f"Бүх машин · {total}"
    return f"{head} (эхний {shown} харагдаж байна)" if shown < total else head


TARGET_COLUMN = "Дараагийн солилт (км)"  # 9.5a: table + Excel


def search_table_rows(vehicles: list[dict]) -> list[dict[str, Any]]:
    """GET /vehicles/search rows -> table rows with Mongolian column names (computer view).

    Numbers stay numbers (sortable); missing values are None (an empty cell), not '—'.
    9.5a: «Дараагийн солилт (км)» (target km of the last service) replaces the prediction status.
    """
    rows = []
    for v in vehicles:
        last = v.get("last_service") or {}
        rows.append({
            "Дугаар": v.get("identifier"),
            "Компани": (v.get("company") or {}).get("name"),
            "Сүүлд солисон": last.get("service_date"),
            "Гүйлт (км)": last.get("odometer_km"),
            TARGET_COLUMN: last.get("target_km"),
            "Тос": last.get("oil_grade"),
            "Литр": last.get("liters"),
            "Жолооч": last.get("driver_name"),
            "Утас": phone_text(last.get("driver_phone")) or None,
            "Удаа": v.get("service_count"),
        })
    return rows


def picked_row(rows: list[int], cells: list[tuple[int, str]]) -> int | None:
    """Row number picked in the dashboard table (9.12-3): its row marker, else the row of the
    clicked cell; None = nothing picked. Row numbers are positions in the rows as sent, also
    after the user sorted the table in the browser (Streamlit keeps the original position)."""
    if rows:
        return rows[0]
    return cells[0][0] if cells else None


FILTER_KEYS = ("date_from", "date_to", "company_id", "route", "oil_grade",
               "payment_status",  # GET /vehicles/search params; payment_status: 9.6b-5, only when connected
               "segment")         # 9.12: a segment card or the «Сегмент» filter (?segment=)
FILTER_ORDER_ERROR = "«Хэднээс» огноо «хэдийг хүртэл»-ээс хойш байна."


def filter_errors(filters: dict[str, Any]) -> list[str]:
    """Mongolian messages for filters the API would refuse (422); [] when they can be sent."""
    start, end = filters.get("date_from"), filters.get("date_to")
    return [FILTER_ORDER_ERROR] if start and end and start > end else []


def active_filter_count(filters: dict[str, Any]) -> int:
    return sum(1 for k in FILTER_KEYS if filters.get(k) not in (None, ""))


def filters_text(query: str, filters: dict[str, Any], company_names: dict[int, str]) -> str:
    """Excel line 2: what the list was filtered by, e.g.
    'Хайлт: «говь» · Огноо: 2026-10-01 – 2026-10-31 · Маршрут: Монгол – Хятад' ('Шүүлтүүргүй' if none)."""
    parts = [f"Хайлт: «{query.strip()}»"] if query and query.strip() else []
    start, end = filters.get("date_from"), filters.get("date_to")
    if start or end:
        parts.append(f"Огноо: {start or '…'} – {end or '…'}")
    if filters.get("company_id") is not None:
        parts.append(f"Компани: {company_names.get(filters['company_id'], filters['company_id'])}")
    if filters.get("route"):
        parts.append(f"Маршрут: {route_label(filters['route'])}")
    if filters.get("oil_grade"):
        parts.append(f"Тос: {filters['oil_grade']}")
    if filters.get("payment_status"):
        parts.append(f"Төлбөр: {PAYMENT_LABELS.get(filters['payment_status'], filters['payment_status'])}")
    if filters.get("segment"):
        parts.append(f"Сегмент: {segment_label(filters['segment'])}")
    return " · ".join(parts) or "Шүүлтүүргүй — бүх машин"


EXPORT_COLUMNS = ("Огноо", "Дугаар", "Компани", "Маршрут", "Тос", "Литр", "Гүйлт (км)", "Моторын цаг",
                  TARGET_COLUMN, "Жолооч", "Утас")


def service_export_rows(vehicles: list[dict]) -> list[dict[str, Any]]:
    """Excel export (9.1): ONE ROW PER SERVICE from GET /vehicles/search?with_services=true,
    newest first (same day -> by plate). Numbers stay numbers; missing values are None."""
    rows = []
    for v in vehicles:
        for s in v.get("services") or []:
            rows.append({
                "Огноо": s.get("service_date"),
                "Дугаар": v.get("identifier"),
                "Компани": (v.get("company") or {}).get("name"),
                "Маршрут": route_label(s.get("route")) if s.get("route") else None,
                "Тос": s.get("oil_grade"),
                "Литр": s.get("liters"),
                "Гүйлт (км)": s.get("odometer_km"),
                TARGET_COLUMN: s.get("target_km"),  # 9.5a: this service's odometer + OIL_INTERVAL_KM
                "Моторын цаг": s.get("engine_hours"),  # 9.1c: mine trucks record hours, not km (D-006)
                "Жолооч": s.get("driver_name"),
                "Утас": phone_text(s.get("driver_phone")) or None,
            })
    rows.sort(key=lambda r: r["Дугаар"] or "")
    rows.sort(key=lambda r: r["Огноо"] or "", reverse=True)  # stable: same date keeps plate order
    return rows


HISTORY_COLUMNS = ("Огноо", "Гүйлт", "Дараагийн", "Тос", "Литр", "Жолооч", "Утас")


def history_table_rows(history: list[dict]) -> list[tuple[str, ...]]:
    """One row of HISTORY_COLUMNS per service (newest first, as the API sends them); '—' when missing."""
    return [
        (
            s.get("service_date") or NOT_GIVEN,
            service_meter_text(s),
            target_text(s),
            s.get("oil_grade") or NOT_GIVEN,
            format_number(s.get("liters"), "л"),
            s.get("driver_name") or NOT_GIVEN,
            phone_text(s.get("driver_phone")) or NOT_GIVEN,
        )
        for s in history
    ]


VIBER_FORWARD = "viber://forward?text="  # D-091: opens Viber's share screen, the manager picks the chat


def viber_forward_url(message: str | None) -> str | None:
    """«Viber-ээр илгээх» link with the reminder text pre-filled, or None when there is no text.

    quote(safe="") percent-encodes everything except A-Z a-z 0-9 _.-~ as UTF-8, so Cyrillic,
    spaces (%20, not "+"), newlines and the reserved "&", "#", "+", "?", "=" all survive.
    """
    if not message or not message.strip():
        return None
    return VIBER_FORWARD + quote(message, safe="")


def sms_url(phone: str | None, message: str | None) -> str | None:
    """«SMS илгээх» link: the phone's SMS app opens with this number and text, or None without both.

    "?&body=" is the form shared by iPhone (reads "&body=") and Android (reads "?body=");
    the body is encoded like the Viber text (UTF-8, %20 for spaces).
    """
    if not phone or not phone.strip() or not message or not message.strip():
        return None
    return f"sms:{quote(phone.strip(), safe='+')}?&body={quote(message, safe='')}"

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
    "driver_name",
    "driver_phone",
)  # 9.5a: no destination / route (the DB columns and old values stay)


def empty_form() -> dict[str, Any]:
    """Blank form values for a new vehicle."""
    return {name: None for name in FORM_FIELDS}


def prefill_from_card(card: dict | None) -> dict[str, Any]:
    """Form values for an existing vehicle, from its last service.

    Pre-filled: oil grade, liters, driver, phone (scope §1). Liters fall back to
    usual_liters. NOT pre-filled (always fresh): odometer, engine hours. Company / model are shown but ignored by the API for an
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


# ---------------------------------------------------------------- task 9.6b-5: Artlab payments (view only)
# The API sends payment fields only once payments are connected (first successful Artlab sync);
# before that every one is null and the screens show NO payment element at all.

PAYMENT_LABELS: dict[str, str] = {
    "paid": "Төлсөн",
    "unpaid": "Төлөөгүй",
    "paid_later": "Төлсөн (дараа)",
    "unknown": "Тодорхойгүй",
}
# (text color, tint): the same AA pairs as the status pills; paid later = the blue segment color.
PAYMENT_COLORS: dict[str, tuple[str, str]] = {
    "paid": STATUS_COLORS["ok"],
    "unpaid": STATUS_COLORS["overdue"],
    "paid_later": ("#1F4E9D", "#E8EEF9"),
    "unknown": PENDING_COLORS,
}
UNLINKED_NOTES: dict[str, str] = {  # why an unpaid receipt has no truck (API match_note)
    "none": "Машин олдсонгүй",
    "multiple": "Хэд хэдэн машин таарсан",
    "conflict": "Дугаар, утас өөр машин заасан",
}
SYNC_STALE_AFTER = timedelta(hours=2)  # PM 9.6b-5: «Сүүлд шинэчилсэн» turns red after 2 h
# PM 9.6b-5 review: the bills sync runs 07:00-22:00 UB only, so from 22:00 to 07:00 age alone is
# never red (only a failed latest run is).
QUIET_FROM_HOUR, QUIET_TO_HOUR = 22, 7
UB = timezone(timedelta(hours=8), name="Asia/Ulaanbaatar")


def payment_badge(service: dict | None) -> tuple[str, str, str] | None:
    """(label, color, tint) for a service's payment, or None when payments are not connected."""
    status = (service or {}).get("payment_status")
    if status not in PAYMENT_LABELS:
        return None
    return (PAYMENT_LABELS[status], *PAYMENT_COLORS[status])


def payments_shown(history: list[dict]) -> bool:
    """True when the API sent payment fields (connected); False -> the card looks exactly as before."""
    return any(s.get("payment_status") for s in history)


def money_text(amount: float | int | None) -> str:
    """60000 -> '60 000₮'; None -> '—'."""
    return NOT_GIVEN if amount is None else f"{format_number(amount)}₮"


def waiting_text(days: int | None) -> str:
    """'50 хоног хүлээж байна'."""
    return NOT_GIVEN if days is None else f"{days} хоног хүлээж байна"


def tel_url(phone: str | None) -> str | None:
    """«Залгах» link for an 8-digit phone, else None."""
    return f"tel:{phone}" if phone and len(phone) == 8 and phone.isdigit() else None


def unpaid_rows(items: list[dict]) -> list[dict[str, Any]]:
    """GET /payments/unpaid items -> what one row of «Төлөөгүй» shows (oldest first, as sent).

    Title = the linked truck, else the first plate found in the receipt. Second line = company,
    else why the receipt has no truck. Phone = the first phone found in the receipt.
    """
    rows = []
    for item in items:
        plates = item.get("plates") or []
        phones = item.get("phones") or []
        title = item.get("identifier") or (plates[0] if plates else "Дугааргүй баримт")
        who = item.get("company_name") or UNLINKED_NOTES.get(item.get("match_note") or "", "Машин олдсонгүй")
        phone = phones[0] if phones else None
        rows.append({
            "title": title, "who": who, "amount": money_text(item.get("amount_due")),
            "waiting": waiting_text(item.get("days_waiting")), "date": item.get("bill_date") or NOT_GIVEN,
            "phone": phone_text(phone) or None, "tel": tel_url(phone), "linked": item.get("vehicle_id") is not None,
            "has_plate": bool(item.get("identifier") or plates),
        })
    return rows


def _when(value: str | None) -> datetime | None:
    try:
        return datetime.fromisoformat(value) if value else None
    except ValueError:
        return None


def sync_view(status: dict | None, now: datetime) -> dict[str, Any] | None:
    """«Сүүлд шинэчилсэн HH:MM» from GET /payments/sync-status; None when not connected (hide it).

    Time = end of the latest SUCCESSFUL bills / nightly run (receipts last read), in UB time; the
    date is added when it was not today. Red when the latest run of any kind failed, or (only
    between 07:00 and 22:00 UB, outside the quiet hours) when that time is more than 2 h ago
    (or there is none).
    """
    if not status or not status.get("connected"):
        return None
    runs = status.get("runs") or []
    latest = max(runs, key=lambda r: _when(r.get("started_at")) or datetime.min.replace(tzinfo=UB), default=None)
    failed = bool(latest) and latest.get("ok") is False
    oks = [t for r in runs if r.get("kind") in ("bills", "nightly") and (t := _when(r.get("last_ok_at")))]
    updated = max(oks) if oks else None
    hour = now.astimezone(UB).hour
    quiet = hour >= QUIET_FROM_HOUR or hour < QUIET_TO_HOUR
    stale = not quiet and (updated is None or now - updated > SYNC_STALE_AFTER)
    if updated is None:
        text = "Сүүлд шинэчилсэн: —"
    else:
        local = updated.astimezone(UB)
        day = "" if local.date() == now.astimezone(UB).date() else f"{local:%m-%d} "
        text = f"Сүүлд шинэчилсэн {day}{local:%H:%M}"
    if failed:
        text += " · сүүлийн оролдлого амжилтгүй"
    return {"text": text, "red": failed or stale}


# ---------------------------------------------------------------- task 9.14a: km/day (contract v0.18)
# The API decides everything (src/api/pace.py); these only turn its fields into Mongolian text.

PACE_LABELS: dict[str, str] = {"km": "Км/өдөр", "hours": "Цаг/өдөр"}
READING_SOURCE_LABELS: dict[str, str] = {"service": "Тос солилт", "manual": "Жолоочийн хариу",
                                         "messenger": "Messenger"}
NO_PACE_TEXT = "Мэдээлэл алга"
NOT_USED_TEXT = "тооцоонд ашиглахгүй"
KM_CHECK_PILL = ("Км асуух", "#1F4E9D", "#EAF0FA")  # brand blue on its tint (not a reminder)


def pace_label(pace: dict | None) -> str:
    """«Км/өдөр» (mine trucks: «Цаг/өдөр»)."""
    return PACE_LABELS.get((pace or {}).get("unit", "km"), PACE_LABELS["km"])


def rate_text(rate: float | None, unit: str = "km") -> str:
    """Pace number: whole km ('287'), engine hours with 1 decimal ('8.7'); '—' when None."""
    if rate is None:
        return NOT_GIVEN
    return format_number(round(rate) if unit == "km" else round(rate, 1))


def pace_text(pace: dict | None) -> str:
    """Card value next to «Км/өдөр»: '287 · жолоочийн хариу (2026-10-11)', '287 · өмнөх 2 үйлчилгээ',
    or «Мэдээлэл алга» when the API knows no usable pace."""
    if not pace or pace.get("rate_per_day") is None:
        return NO_PACE_TEXT
    rate = rate_text(pace["rate_per_day"], pace.get("unit", "km"))
    if pace.get("source") == "reading":
        return f"{rate} · жолоочийн хариу ({pace.get('reading_date') or NOT_GIVEN})"
    return f"{rate} · өмнөх 2 үйлчилгээ"


def next_change_text(card: dict | None) -> str | None:
    """«Дараагийн солилт» value: '~2026-10-01 · 270 500 км' (due day from km/day + stored target km),
    just the km without a pace, None for mine trucks (no target)."""
    card = card or {}
    target = (card.get("last_service") or {}).get("target_km")
    due = (card.get("pace") or {}).get("next_due_date")
    if target is None:
        return None
    km = format_number(target, "км")
    return f"~{due} · {km}" if due else km


def flag_text(reason: str | None, unit: str = "km") -> str:
    """Why a reading is not used, e.g. «Өмнөхөөс бага буюу тэнцүү — тооцоонд ашиглахгүй»; '' when usable."""
    if reason is None:
        return ""
    why = {
        "not_higher": "Өмнөхөөс бага буюу тэнцүү",
        "too_slow": "Өдөрт 20 км-ээс бага" if unit == "km" else "Хэт бага",
        "too_fast": "Өдөрт 1 200 км-ээс их" if unit == "km" else "Өдөрт 24 цагаас их",
    }.get(reason, reason)
    return f"{why} — {NOT_USED_TEXT}"


def reading_text(reading: dict) -> str:
    """One reading row: '2026-10-11 · 116 000 км · Жолоочийн хариу'."""
    unit = "км" if reading.get("unit", "km") == "km" else "мц"
    return " · ".join([reading.get("reading_date") or NOT_GIVEN, format_number(reading.get("value"), unit),
                       READING_SOURCE_LABELS.get(reading.get("source"), reading.get("source") or NOT_GIVEN)])


def preview_rows(preview: dict) -> list[tuple[str, str]]:
    """«Км бүртгэх» confirm step: what saving would give (from POST /vehicles/{id}/readings/preview)."""
    pace = preview.get("pace") or {}
    unit = preview.get("unit", "km")
    rows = [(pace_label(pace), rate_text(preview.get("rate_per_day"), unit))]
    if preview.get("status") == "ok":
        rows.append(("Дараагийн солилт", f"~{pace['next_due_date']}" if pace.get("next_due_date") else NOT_GIVEN))
        if pace.get("reminder_on"):
            rows.append(("Сануулга", pace["reminder_on"]))
    return rows
