"""Mongolian reminder message + reminder rules (task 4.4).

The message names the truck, the last oil change (date + oil used) and the
Geo-Expert contact (config.reminder_contact, from the environment). Dates are
written 2026.08.10 and put after a label ("Сүүлд сольсон: ..."), so no
Mongolian case ending has to follow a number (those depend on vowel harmony).

WORDING IS A DRAFT for Ari to approve (task 4.4 handoff); change it only here.
No SMS is sent by the API: the oil changer copies the text and marks it sent.
"""

from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.api.config import Contact

GREETING = "Сайн байна уу!"
# "<plate> дугаартай машины тос солих хугацаа ойртлоо." = "the oil change time of truck <plate> is near."
DUE_TEXT = "{plate} дугаартай машины тос солих хугацаа ойртлоо."
# Overdue: "... хугацаа болсон байна." = "... time has come (passed)."
OVERDUE_TEXT = "{plate} дугаартай машины тос солих хугацаа болсон байна."
# "Last changed: 2026.08.10 (15W-40, 32 л)."  л = liters
LAST_CHANGE_TEXT = "Сүүлд сольсон: {day} ({oil_grade}, {liters} л)."
CONTACT_TEXT = "{name}: {phone}"


def format_day(day: date) -> str:
    """2026-08-10 -> '2026.08.10' (the usual written form in Mongolia)."""
    return f"{day:%Y.%m.%d}"


def format_liters(liters: Decimal | float) -> str:
    """32.0 -> '32', 32.5 -> '32.5' (DB keeps 1 decimal)."""
    value = Decimal(str(liters)).normalize()
    return f"{value:f}"


def message_mn(plate: str, last_change: date, oil_grade: str, liters: Decimal | float, overdue: bool,
               contact: Contact) -> str:
    """Reminder text: greeting, truck + due/overdue, last change (date, oil), contact. One line, spaces between."""
    due = (OVERDUE_TEXT if overdue else DUE_TEXT).format(plate=plate)
    last = LAST_CHANGE_TEXT.format(day=format_day(last_change), oil_grade=oil_grade, liters=format_liters(liters))
    return " ".join([GREETING, due, last, CONTACT_TEXT.format(name=contact.name, phone=contact.phone)])
