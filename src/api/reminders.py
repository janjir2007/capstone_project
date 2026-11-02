"""One reminder per service (task 9.5c, D-119; replaces the 1m/2m/3m month stages of 9.5b, D-113).

A truck is due on its latest service date + REMINDER_DAYS (default 75), once per service:
reminders_sent stores it as stage 'single' (UNIQUE (service_id, stage)). Any older 1m / 2m / 3m
row of the same service counts as sent too (PM, 9.5c). A new service has a new id, so its
reminder is due again: a new cycle.
A truck AT_RISK_DAYS (default 150) past its latest service without coming back is «Эрсдэлтэй»
(at_risk) — the one segment rule for the card, dashboard, stats and the reminder list.
Both day counts are settings (src/api/config.py reminder_rules), not fixed here.

No SMS / Viber is sent by the API: the manager sends the text and marks it sent.
Wording = approved by PM + Ari (9.5c); change it only here.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.api.config import Contact, ReminderRules

STAGE = "single"                 # the 9.5c reminder's value in reminders_sent.stage
OLD_STAGES = ("1m", "2m", "3m")  # 9.5b rows: kept as history, count as "sent" for their service

# ≤ 160 characters with a usual plate / oil grade (test_reminders.py checks it).
MESSAGE = ("Сайн байна уу! {plate} машины тосыг {date}-нд солиулсан ({oil}). Дахин солих хугацаа болж "
           "байна. Wolf Oil - Гео-Эксперт: {contact}")


def days_since(last_service: date, as_of: date) -> int:
    return (as_of - last_service).days


def reminder_day(last_service: date, rules: ReminderRules) -> date:
    """The day the reminder is due: last service + REMINDER_DAYS."""
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
