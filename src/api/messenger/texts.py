"""The bot's Mongolian replies (task 9.15a, plan §4). Change wording only here; Ari proofreads it.

These are replies inside Meta's 24 h window (the driver just wrote). The SMS texts (km check,
reminder) stay in src/api/reminders.py; the km-check SMS with the m.me link is task 9.15a-3.
"""

from __future__ import annotations

from datetime import date

from src.api.reminders import format_day

GREETING = "Сайн байна уу! Машиныхаа улсын дугаар болон одоогийн км-ээ бичнэ үү. Жишээ: 9988НАА 871234"
STAFF_WILL_CHECK = "Баярлалаа, манай ажилтан шалгаад холбогдоно."
FLAGGED_THANKS = "Баярлалаа, хүлээж авлаа. Манай ажилтан шалгаад холбогдоно."
HOURS_THANKS = "Баярлалаа, хүлээж авлаа."
WRITE_AGAIN = "Дахин бичнэ үү: улсын дугаар + км"
YES, NO = "Тийм", "Үгүй"
YES_PAYLOAD, NO_PAYLOAD = "KM_YES", "KM_NO"
OTN_TITLE = "Тос солих өдрөөс өмнө сануулах уу?"


def thousands(value: float) -> str:
    """871234 -> '871 234' (space between groups, the usual Mongolian way)."""
    return f"{round(value):,}".replace(",", " ")


def confirm_question(plate: str, km: float) -> str:
    """«9988НАА — 871 234 км. Зөв үү?»"""
    return f"{plate} — {thousands(km)} км. Зөв үү?"


def usable_thanks(plate: str, per_day: float, due: date | None, target_km: int | None) -> str:
    """«Баярлалаа! 9988НАА өдөрт ~310 км явж байна. Дараагийн тос солих: ~2026.12.15 (883 234 км).»"""
    text = f"Баярлалаа! {plate} өдөрт ~{round(per_day)} км явж байна."
    if due is not None:
        text += f" Дараагийн тос солих: ~{format_day(due)}"
        text += f" ({thousands(target_km)} км)." if target_km is not None else "."
    return text
