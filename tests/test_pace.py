"""Tests for task 9.14a: the km/day engine (src/api/pace.py). Pure: no database, made-up numbers."""

from __future__ import annotations

from datetime import date, timedelta

import pytest

from src.api.config import ReminderRules
from src.api.pace import (MAX_KM_PER_DAY, MIN_KM_PER_DAY, NO_PACE, Reading, flag_of, new_reading_flag, next_due,
                          pace_of, rate, schedule)

RULES = ReminderRules(reminder_days=75, at_risk_days=150, lead_days=5, km_check_days=34)
DAY = date(2026, 8, 1)
SERVICE = Reading(DAY, 100_000)


def after(days: int, value: float) -> Reading:
    return Reading(DAY + timedelta(days=days), value)


def test_limits_are_the_decided_constants() -> None:
    assert (MIN_KM_PER_DAY, MAX_KM_PER_DAY) == (20, 1200)


def test_rate() -> None:
    assert rate(SERVICE, after(10, 103_000)) == 300
    assert rate(SERVICE, after(0, 103_000)) is None            # same day: no days to divide by


@pytest.mark.parametrize(("later", "flag"), [
    (after(10, 100_000), "not_higher"),                       # equal
    (after(10, 99_000), "not_higher"),                        # lower (a typo or a new odometer)
    (after(0, 100_500), "too_fast"),                          # higher on the same day: endless pace
    (after(10, 100_199), "too_slow"),                         # 19.9 km/day
    (after(10, 100_200), None),                               # 20 km/day: the lowest usable
    (after(10, 112_000), None),                               # 1200 km/day: the highest usable
    (after(10, 112_001), "too_fast"),                         # 1200.1 km/day
])
def test_flag_of_km(later: Reading, flag: str | None) -> None:
    assert flag_of(SERVICE, later, "km") == flag


@pytest.mark.parametrize(("later", "flag"), [
    (after(10, 100_005), None),                               # 0.5 h/day: no lower limit for hours
    (after(10, 100_240), None),                               # 24 h/day
    (after(10, 100_241), "too_fast"),                         # more hours than the day has
    (after(10, 99_999), "not_higher"),
])
def test_flag_of_hours(later: Reading, flag: str | None) -> None:
    assert flag_of(SERVICE, later, "hours") == flag


def test_new_reading_must_beat_an_earlier_usable_reply() -> None:
    first = after(10, 103_000)
    assert new_reading_flag("km", SERVICE, [first], after(20, 102_500)) == "not_higher"  # lower than day 10
    assert new_reading_flag("km", SERVICE, [first], after(20, 106_000)) is None
    assert new_reading_flag("km", SERVICE, [after(30, 110_000)], after(20, 106_000)) is None  # a LATER one: ignored
    assert new_reading_flag("km", SERVICE, [], after(20, 99_000)) == "not_higher"


def test_pace_from_the_newest_usable_reply_first() -> None:
    replies = [after(10, 103_000), after(20, 108_000)]
    pace = pace_of("km", SERVICE, Reading(DAY - timedelta(days=50), 90_000), replies)
    assert (pace.rate_per_day, pace.source, pace.reading, pace.known_on) == (400, "reading", replies[1], replies[1].day)


def test_unusable_reply_falls_back_to_an_older_one_then_to_the_services() -> None:
    previous = Reading(DAY - timedelta(days=50), 90_000)       # 200 km/day between the services
    older, typo = after(10, 103_000), after(20, 900_000)       # the typo: 40 000 km/day
    assert pace_of("km", SERVICE, previous, [older, typo]).reading == older
    pace = pace_of("km", SERVICE, previous, [typo])
    assert (pace.rate_per_day, pace.source, pace.reading, pace.known_on) == (200, "services", None, DAY)


def test_reply_from_before_the_service_is_ignored() -> None:
    assert pace_of("km", SERVICE, None, [Reading(DAY - timedelta(days=1), 99_000), after(0, 100_100)]) == NO_PACE


def test_no_pace_without_a_usable_pair() -> None:
    assert pace_of("km", SERVICE, None, []) == NO_PACE                                   # first visit
    assert pace_of("km", SERVICE, Reading(DAY - timedelta(days=50), 100_500), []) == NO_PACE  # odometer went down
    assert pace_of("km", SERVICE, Reading(DAY - timedelta(days=50), 99_900), []) == NO_PACE   # 2 km/day


def test_next_due_rounds_down() -> None:
    assert next_due(DAY, 12_000, 286.585) == DAY + timedelta(days=41)   # 41.87 days -> rather a day early
    assert next_due(DAY, 12_000, 300) == DAY + timedelta(days=40)


def test_schedule_with_a_pace() -> None:
    plan = schedule("km", SERVICE, Reading(DAY - timedelta(days=50), 85_000), [], 12_000, RULES)  # 300 km/day
    assert (plan.basis, plan.next_due, plan.reminder_on) == ("pace", DAY + timedelta(days=40), DAY + timedelta(days=35))
    assert (plan.km_check_on, plan.interval_km, plan.unit) == (None, 12_000, "km")


def test_late_reply_makes_the_reminder_due_on_its_day() -> None:
    """1000 km/day -> due day 12, reminder day 7; the reply only came on day 34 -> reminder day 34."""
    plan = schedule("km", SERVICE, None, [after(34, 134_000)], 12_000, RULES)
    assert (plan.next_due, plan.reminder_on) == (DAY + timedelta(days=12), DAY + timedelta(days=34))


def test_slow_truck_is_reminded_before_it_counts_as_at_risk() -> None:
    """PM 9.14a-2 #2: 25 km/day -> due day 480; reminder capped at AT_RISK_DAYS - 5 = day 145."""
    plan = schedule("km", SERVICE, None, [after(40, 101_000)], 12_000, RULES)
    assert (plan.next_due, plan.reminder_on) == (DAY + timedelta(days=480), DAY + timedelta(days=145))
    late = schedule("km", SERVICE, None, [after(160, 104_000)], 12_000, RULES)  # reply after the cap
    assert late.reminder_on == DAY + timedelta(days=145)


def test_no_pace_75_days_and_a_km_check_at_34() -> None:
    plan = schedule("km", SERVICE, None, [], 12_000, RULES)
    assert (plan.basis, plan.reminder_on, plan.km_check_on, plan.next_due) == \
        ("fixed", DAY + timedelta(days=75), DAY + timedelta(days=34), None)


def test_pace_without_a_stored_interval_keeps_75_days_and_no_km_check() -> None:
    """A service written outside the API (no interval_km): its pace is known, its due day is not."""
    plan = schedule("km", SERVICE, Reading(DAY - timedelta(days=50), 85_000), [], None, RULES)
    assert (plan.pace.rate_per_day, plan.basis, plan.reminder_on, plan.km_check_on) == \
        (300, "fixed", DAY + timedelta(days=75), None)


def test_mine_truck_hours_per_day_only() -> None:
    """PM 9.14a-2 #1: hours per day is shown; no due day, no reminder, no km check."""
    plan = schedule("hours", Reading(DAY, 12_980.5), Reading(DAY - timedelta(days=55), 12_500), [], None, RULES)
    assert round(plan.pace.rate_per_day, 1) == 8.7
    assert (plan.next_due, plan.reminder_on, plan.basis, plan.km_check_on) == (None, None, None, None)


def test_rules_are_settings() -> None:
    rules = ReminderRules(reminder_days=60, at_risk_days=150, lead_days=10, km_check_days=20)
    paced = schedule("km", SERVICE, Reading(DAY - timedelta(days=50), 85_000), [], 12_000, rules)
    assert paced.reminder_on == DAY + timedelta(days=30)
    fixed = schedule("km", SERVICE, None, [], 12_000, rules)
    assert (fixed.reminder_on, fixed.km_check_on) == (DAY + timedelta(days=60), DAY + timedelta(days=20))
