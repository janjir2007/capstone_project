"""GET /stats/segments — how many vehicles are in each segment (tasks 4.2, 4.4, 9.5b, 9.5c).
GET /stats/period — the dashboard's work numbers for today / this week / this month (task 9.12-1).

Segments: new (1 service), returning (2), loyal (3+); at_risk wins = AT_RISK_DAYS (150)+ days
since the latest service without coming back (task 9.5c setting; 9.5b had 90, src/api/reminders.segment_of — the same rule as the card,
the dashboard and the reminder list; it replaced the predicted date + 7 days rule of D-007).
Counted as of ``as_of`` (only services up to that day). Needs no model files.
"""

from datetime import date, datetime, time, timedelta
from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.clock import ULAANBAATAR, get_today
from src.api.config import reminder_rules
from src.api.db import get_session
from src.api.history import records_as_of
from src.api.reminders import segment_of
from src.api.models import KmCheck, ReminderSent, ServiceRecord
from src.api.schemas import PeriodStats, SegmentCounts, SegmentStats

router = APIRouter(prefix="/stats", tags=["stats"])


def segment_counts(session: Session, as_of: date) -> dict[str, int]:
    """Vehicles per segment on as_of (vehicles without a service by then are not counted)."""
    counts: dict[str, int] = {}
    rules = reminder_rules()
    for rs in records_as_of(session, as_of).values():  # services oldest first
        segment = segment_of(len(rs), rs[-1].service_date, as_of, rules)
        counts[segment] = counts.get(segment, 0) + 1
    return counts


@router.get("/segments", response_model=SegmentStats)
def segment_stats(
    session: Annotated[Session, Depends(get_session)],
    today: Annotated[date, Depends(get_today)],
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Past dates give past answers")] = None,
) -> SegmentStats:
    """Vehicle count per segment on ``as_of``; all four segments always present."""
    as_of = as_of or today
    counts = segment_counts(session, as_of)
    return SegmentStats(as_of=as_of, total=sum(counts.values()), counts=SegmentCounts(**counts),
                        at_risk_days=reminder_rules().at_risk_days)


Period = Literal["today", "week", "month"]


def period_start(period: Period, end: date) -> date:
    """First day of the period that ends on ``end`` (PM 9.12: week = Monday to today, UB time)."""
    if period == "week":
        return end - timedelta(days=end.weekday())  # Monday = 0
    if period == "month":
        return end.replace(day=1)
    return end


def _ub_midnight(day: date) -> datetime:
    """00:00 Ulaanbaatar time on ``day`` (sent_at is a timestamp with time zone)."""
    return datetime.combine(day, time.min, tzinfo=ULAANBAATAR)


def period_numbers(session: Session, start: date, end: date) -> dict[str, float | int]:
    """Services, liters, new vehicles (first-EVER service in the range, PM 9.12), reminders marked
    sent and km checks marked sent (9.14a; not reminders) — sent_at on a UB day in the range —
    start..end both included."""
    in_range = ServiceRecord.service_date.between(start, end)
    services, liters = session.execute(
        select(func.count(ServiceRecord.id), func.coalesce(func.sum(ServiceRecord.liters), 0)).where(in_range)
    ).one()
    first = (select(ServiceRecord.vehicle_id, func.min(ServiceRecord.service_date).label("first_day"))
             .group_by(ServiceRecord.vehicle_id).subquery())
    new_vehicles = session.scalar(select(func.count()).select_from(first).where(first.c.first_day.between(start, end)))
    since, until = _ub_midnight(start), _ub_midnight(end + timedelta(days=1))
    sent = session.scalar(select(func.count(ReminderSent.id)).where(
        ReminderSent.sent_at >= since, ReminderSent.sent_at < until))
    checks = session.scalar(select(func.count(KmCheck.id)).where(KmCheck.sent_at >= since, KmCheck.sent_at < until))
    return {"services": services, "liters": float(liters), "new_vehicles": new_vehicles or 0,
            "reminders_sent": sent or 0, "km_checks_sent": checks or 0}


@router.get("/period", response_model=PeriodStats)
def period_stats(
    session: Annotated[Session, Depends(get_session)],
    today: Annotated[date, Depends(get_today)],
    period: Annotated[Period, Query(description="today · week (Monday to today) · month (1st to today)")] = "today",
    as_of: Annotated[date | None, Query(description="Period end; default: today (Ulaanbaatar)")] = None,
) -> PeriodStats:
    """Work numbers of one period for the dashboard (task 9.12-1). Read only, needs no model."""
    end = as_of or today
    start = period_start(period, end)
    return PeriodStats(period=period, date_from=start, date_to=end, **period_numbers(session, start, end))
