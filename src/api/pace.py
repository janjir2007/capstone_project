"""A truck's own pace (km per day) and the dates that follow from it (task 9.14a). Pure: no database.

Not in src/common/features.py on purpose: this is a reminder RULE, not a model feature (the model's
km_per_day_hist is a different measure, first -> last odometer over the whole history).

Rules (PM-approved 9.14a plan + decisions of 9.14a-2):
- pace s = (later reading - earlier reading) / days between them. Source, in this order:
  1. the newest usable DRIVER reading (manual now, Messenger later) after the latest service,
     counted from that service's odometer ("reading");
  2. else the previous service -> the latest service ("services");
  3. else none.
- usable = higher than the reading it is counted from, and MIN_KM_PER_DAY <= s <= MAX_KM_PER_DAY.
  Anything else is flagged and never used. Two readings on the same day = an endless pace: flagged.
- next due day = service day + floor(interval / s) (floor: rather a day early than late).
- reminder day = due - REMINDER_LEAD_DAYS, never before the day the pace became known (a late reply
  makes it due that day), and never after service + AT_RISK_DAYS - REMINDER_LEAD_DAYS (PM 9.14a-2 #2:
  a very slow truck is reminded before it counts as «Эргэж ирээгүй»).
- no pace -> reminder REMINDER_DAYS (75) after the service (D-119), and a «Км шалгах» message
  KM_CHECK_DAYS (34) after it, asking the driver for his km (PM 9.14a-2 #4: any truck without a pace).
- mine trucks (engine hours only): hours per day is shown; no due day, no reminder, no km check
  (PM 9.14a-2 #1: the interval in hours is not decided).
"""

from __future__ import annotations

import math
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Literal

from src.api.config import ReminderRules

MIN_KM_PER_DAY = 20      # slower = a wrong reading (or a truck standing still: no basis for a date)
MAX_KM_PER_DAY = 1200    # faster = a typo (50 km/h for 24 hours)
MAX_HOURS_PER_DAY = 24   # an engine cannot run more hours than the day has

Unit = Literal["km", "hours"]
Flag = Literal["not_higher", "too_slow", "too_fast"]
Source = Literal["reading", "services"]
Basis = Literal["pace", "fixed"]


@dataclass(frozen=True)
class Reading:
    """One meter value on one day (a service's odometer / engine hours, or a driver's reply)."""

    day: date
    value: float


def rate(base: Reading, later: Reading) -> float | None:
    """Units per day from ``base`` to ``later``; None when they are on the same day (or out of order)."""
    days = (later.day - base.day).days
    return (later.value - base.value) / days if days > 0 else None


def flag_of(base: Reading, later: Reading, unit: Unit) -> Flag | None:
    """Why ``later`` cannot be used after ``base`` (None = usable)."""
    if later.value <= base.value:
        return "not_higher"
    per_day = rate(base, later)
    if per_day is None:  # higher on the same day: an endless pace
        return "too_fast"
    if unit == "km":
        if per_day < MIN_KM_PER_DAY:
            return "too_slow"
        if per_day > MAX_KM_PER_DAY:
            return "too_fast"
    elif per_day > MAX_HOURS_PER_DAY:
        return "too_fast"
    return None


def new_reading_flag(unit: Unit, service: Reading, earlier_ok: Sequence[Reading], new: Reading) -> Flag | None:
    """Flag of a driver reading when it is saved: not higher than an earlier usable reading of the
    same cycle (on or before its day), else the rule against the latest service."""
    if any(r.value >= new.value for r in earlier_ok if r.day <= new.day):
        return "not_higher"
    return flag_of(service, new, unit)


@dataclass(frozen=True)
class Pace:
    """The truck's pace, or all None when there is no usable one."""

    rate_per_day: float | None
    source: Source | None
    reading: Reading | None  # the driver reading used (source "reading")
    known_on: date | None    # the day the pace became known: that reading's day, or the latest service's


NO_PACE = Pace(None, None, None, None)


def pace_of(unit: Unit, service: Reading, previous: Reading | None, readings: Sequence[Reading]) -> Pace:
    """The pace after ``service`` (the latest one). ``previous`` = the service before it (same unit),
    ``readings`` = driver readings not flagged when saved, oldest first."""
    for reading in reversed([r for r in readings if r.day > service.day]):  # newest first
        if flag_of(service, reading, unit) is None:
            return Pace(rate(service, reading), "reading", reading, reading.day)
    if previous is not None and flag_of(previous, service, unit) is None:
        return Pace(rate(previous, service), "services", None, service.day)
    return NO_PACE


def next_due(service_day: date, interval: int, per_day: float) -> date:
    """The day the interval is used up at this pace (whole days, rounded down)."""
    return service_day + timedelta(days=math.floor(interval / per_day))


@dataclass(frozen=True)
class Schedule:
    """Everything the card, the reminder list and the km-check list need about one latest service."""

    unit: Unit
    pace: Pace
    interval_km: int | None   # the interval stored on the service (None: hours, or not stored)
    next_due: date | None     # only with a pace and an interval
    reminder_on: date | None  # None = no reminder (mine trucks)
    basis: Basis | None       # "pace" = from km/day, "fixed" = REMINDER_DAYS (D-119)
    km_check_on: date | None  # only km trucks without a pace


def schedule(unit: Unit, service: Reading, previous: Reading | None, readings: Sequence[Reading],
             interval_km: int | None, rules: ReminderRules) -> Schedule:
    """The dates of the truck's latest ``service`` (see the module docstring)."""
    pace = pace_of(unit, service, previous, readings)
    if unit == "hours":
        return Schedule(unit, pace, None, None, None, None, None)
    if pace.rate_per_day is not None and interval_km is not None:
        due = next_due(service.day, interval_km, pace.rate_per_day)
        latest = service.day + timedelta(days=rules.at_risk_days - rules.lead_days)
        reminder = min(max(due - timedelta(days=rules.lead_days), pace.known_on), latest)
        return Schedule(unit, pace, interval_km, due, reminder, "pace", None)
    check = service.day + timedelta(days=rules.km_check_days) if pace.rate_per_day is None else None
    return Schedule(unit, pace, interval_km, None, service.day + timedelta(days=rules.reminder_days), "fixed", check)
