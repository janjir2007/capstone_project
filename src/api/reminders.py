"""Month-based reminders (task 9.5b): stage rules, the at-risk rule and the Mongolian messages.

Stages count days since the truck's LATEST service: 1m = 30, 2m = 60, 3m = 90 days. Only the
highest stage reached is offered, and each stage only once per service (reminders_sent, UNIQUE
(service_id, stage)). A new service has a new id, so its stages start from zero again.
A truck 90+ days past its latest service without coming back is «Эрсдэлтэй» (at_risk) — the one
segment rule for the card, dashboard, stats and the reminder list.

No SMS / Viber is sent by the API: the manager sends the text and marks it sent.
Wording = Ari's text from the 9.5b brief; change it only here.
"""

from __future__ import annotations

from datetime import date, timedelta

from src.api.config import Contact

STAGES = ("1m", "2m", "3m")
STAGE_DAYS = {"1m": 30, "2m": 60, "3m": 90}
AT_RISK_DAYS = 90  # = the 3m stage: 90+ days without a new service

MESSAGES = {
    "1m": ("Сайн байна уу! Гео-Эксперт ХХК-ийн тосыг сонгосонд баярлалаа. {plate} машины тос солиулснаас "
           "хойш 1 сар боллоо ({date}, {oil}). Дараагийн солилт: {target_km} км-т. Гүйлтээ шалгаарай. "
           "Сайн яваарай! {contact}"),
    "2m": ("Сайн байна уу! {plate} машины тос солиулснаас хойш 2 сар боллоо. Дараагийн солилт: "
           "{target_km} км-т. Гүйлтээ шалгахаа мартуузай. {contact}"),
    "3m": ("Сайн байна уу! {plate} машин {target_km} км-т хүрсэн бол тосоо солих цаг боллоо. "
           "Бид таны байгаа газар очиж сольж өгнө. {contact}"),
}


def days_since(last_service: date, as_of: date) -> int:
    return (as_of - last_service).days


def stage_reached(last_service: date, as_of: date) -> str | None:
    """Highest stage whose day has come on as_of, e.g. day 65 -> '2m'; before day 30 -> None."""
    days = days_since(last_service, as_of)
    reached = [s for s in STAGES if days >= STAGE_DAYS[s]]
    return reached[-1] if reached else None


def due_stage(last_service: date, as_of: date, sent: set[str]) -> str | None:
    """The stage to send today: the highest one reached, if it was not sent yet.
    Lower stages that were missed are skipped (day 65 with nothing sent -> only '2m')."""
    stage = stage_reached(last_service, as_of)
    return stage if stage is not None and stage not in sent else None


def stage_day(last_service: date, stage: str) -> date:
    """The day a stage starts: last service + 30 / 60 / 90."""
    return last_service + timedelta(days=STAGE_DAYS[stage])


def segment_of(service_count: int, last_service: date, as_of: date) -> str:
    """Segment on as_of: at_risk = 90+ days since the latest service (wins); else new (1 service),
    returning (2), loyal (3+). Replaces the predicted-date + 7 days rule (D-007) in 9.5b."""
    if days_since(last_service, as_of) >= AT_RISK_DAYS:
        return "at_risk"
    return "new" if service_count == 1 else "returning" if service_count == 2 else "loyal"


def format_day(day: date) -> str:
    """2026-08-10 -> '2026.08.10' (the usual written form in Mongolia)."""
    return f"{day:%Y.%m.%d}"


def format_km(km: int) -> str:
    """526548 -> '526 548' (the message adds 'км-т')."""
    return f"{km:,}".replace(",", " ")


def message_mn(stage: str, plate: str, last_service: date, oil_grade: str, target_km: int,
               contact: Contact) -> str:
    """The month message for one stage. {contact} = the oil changer's phone (CONTACT_PHONE)."""
    return MESSAGES[stage].format(plate=plate, date=format_day(last_service), oil=oil_grade,
                                  target_km=format_km(target_km), contact=contact.phone)
