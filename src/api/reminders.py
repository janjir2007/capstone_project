"""One reminder per service (task 9.5c, D-119; replaces the 1m/2m/3m month stages of 9.5b, D-113).

Reminder day (task 9.14a, src/api/pace.py): from the truck's own km/day when it is known (due day -
REMINDER_LEAD_DAYS, at most AT_RISK_DAYS - REMINDER_LEAD_DAYS after the service), else the truck's
latest service date + REMINDER_DAYS (default 75, ``reminder_day`` below). Once per service:
reminders_sent stores it as stage 'single' (UNIQUE (service_id, stage)). Any older 1m / 2m / 3m
row of the same service counts as sent too (PM, 9.5c). A new service has a new id, so its
reminder is due again: a new cycle.
A truck AT_RISK_DAYS (default 150) past its latest service without coming back is «Эрсдэлтэй»
(at_risk) — the one segment rule for the card, dashboard, stats and the reminder list.
The day counts are settings (src/api/config.py reminder_rules), not fixed here.

No SMS / Viber is sent by the API: the manager sends the text and marks it sent.
Wording = approved by PM + Ari (9.5c; the km-check text 9.14a); change it only here.
"""

from __future__ import annotations

import math
from datetime import date, timedelta

from src.api.config import Contact, ReminderRules

STAGE = "single"                 # the 9.5c reminder's value in reminders_sent.stage
OLD_STAGES = ("1m", "2m", "3m")  # 9.5b rows: kept as history, count as "sent" for their service

# 9.14a: Cyrillic -> UCS-2: this text is 3 SMS parts with a usual plate / oil grade (sms_parts;
# test_reminders.py pins it). Shorter wordings are proposed to Ari, not changed here.
MESSAGE = ("Сайн байна уу! {plate} машины тосыг {date}-нд солиулсан ({oil}). Дахин солих хугацаа болж "
           "байна. Wolf Oil - Гео-Эксперт: {contact}")


# Task 9.14a: «Км шалгах» — asks the driver for his km when the truck's pace is not known
# (2 SMS parts with a usual plate and phone; test_reminders.py checks the worst case).
KM_CHECK_MESSAGE = ("Сайн байна уу! {plate} машины тосыг {date}-нд солиулсан. Одоогийн км-ээ хариу бичнэ үү. "
                    "Wolf Oil - Гео-Эксперт: {contact}")

# GSM 03.38: the basic set (1 unit each) and the extension set (2 units: escape + char). Anything else
# (Cyrillic, emoji) sends the whole SMS as UCS-2.
GSM_BASIC = ("@£$¥èéùìòÇ\nØø\rÅåΔ_ΦΓΛΩΠΨΣΘΞÆæßÉ !\"#¤%&'()*+,-./0123456789:;<=>?"
             "¡ABCDEFGHIJKLMNOPQRSTUVWXYZÄÖÑÜ§¿abcdefghijklmnopqrstuvwxyzäöñüà")
GSM_EXTENSION = "^{}\\[~]|€\f"


def sms_parts(text: str) -> int:
    """How many SMS parts ``text`` takes. GSM-7: 160 units in one SMS, 153 per part when split;
    UCS-2 (any other character, e.g. Cyrillic): 70 UTF-16 units, 67 per part. 0 for empty text."""
    if all(c in GSM_BASIC or c in GSM_EXTENSION for c in text):
        units, single, multi = sum(2 if c in GSM_EXTENSION else 1 for c in text), 160, 153
    else:
        units, single, multi = len(text.encode("utf-16-le")) // 2, 70, 67
    if units == 0:
        return 0
    return 1 if units <= single else math.ceil(units / multi)


def days_since(last_service: date, as_of: date) -> int:
    return (as_of - last_service).days


def reminder_day(last_service: date, rules: ReminderRules) -> date:
    """The fixed reminder day: last service + REMINDER_DAYS (trucks without a km/day, 9.14a)."""
    return last_service + timedelta(days=rules.reminder_days)


def is_due(last_service: date, as_of: date, already_sent: bool, rules: ReminderRules) -> bool:
    """True if the reminder day has come on as_of and nothing was sent for this service yet."""
    return not already_sent and reminder_day(last_service, rules) <= as_of


def segment_of(service_count: int, last_service: date, as_of: date, rules: ReminderRules) -> str:
    """Segment on as_of: at_risk = AT_RISK_DAYS+ since the latest service (wins); else new
    (1 service), returning (2), loyal (3+)."""
    if days_since(last_service, as_of) >= rules.at_risk_days:
        return "at_risk"
    return "new" if service_count == 1 else "returning" if service_count == 2 else "loyal"


def format_day(day: date) -> str:
    """2026-08-10 -> '2026.08.10' (the usual written form in Mongolia)."""
    return f"{day:%Y.%m.%d}"


def message_mn(plate: str, last_service: date, oil_grade: str, contact: Contact) -> str:
    """The reminder text. {contact} = the oil changer's phone (CONTACT_PHONE)."""
    return MESSAGE.format(plate=plate, date=format_day(last_service), oil=oil_grade, contact=contact.phone)


def km_check_message(plate: str, last_service: date, contact: Contact) -> str:
    """The «Км шалгах» text. {contact} = the oil changer's phone (CONTACT_PHONE)."""
    return KM_CHECK_MESSAGE.format(plate=plate, date=format_day(last_service), contact=contact.phone)
