"""Service history from the database in the shape the predictor needs (tasks 4.3, 4.4).

Shared by the vehicle card, the due-reminder list and the segment counts, so
all three see the same visits in the same order (oldest first, id breaks
same-day ties, like v_vehicle_service_summary).

Task 9.14a: also the driver readings and each truck's Schedule (src/api/pace.py) from those rows,
for the card, the reminder list and the km-check list.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.api.config import ReminderRules
from src.api.models import OdometerReading, ServiceRecord
from src.api.pace import Reading, Schedule, Unit, flag_of, rate, schedule
from src.api.prediction import Visit
from src.api.schemas import PaceOut

DRIVER_SOURCES = ("manual", "messenger")


def service_records(session: Session, vehicle_id: int) -> Sequence[ServiceRecord]:
    """All services of one vehicle, newest first (same order as v_vehicle_service_summary)."""
    return session.scalars(
        select(ServiceRecord)
        .options(selectinload(ServiceRecord.destination))  # load destinations in 1 extra query
        .where(ServiceRecord.vehicle_id == vehicle_id)
        .order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc())
    ).all()


def to_visit(record: ServiceRecord) -> Visit:
    """One service row -> the predictor's input."""
    return Visit(id=record.id, service_date=record.service_date, odometer_km=record.odometer_km, route=record.route,
                 destination_id=record.destination_id,
                 destination_name=record.destination.name if record.destination else None,
                 destination_raw=record.destination_raw)


def visits_oldest_first(records_newest_first: Sequence[ServiceRecord]) -> list[Visit]:
    """Service rows -> the prediction's input, oldest first (newest service = last row, as in training)."""
    return [to_visit(r) for r in reversed(records_newest_first)]


def records_as_of(session: Session, as_of: date) -> dict[int, list[ServiceRecord]]:
    """Every vehicle's services on or before ``as_of``, oldest first, in one query: {vehicle_id: records}."""
    rows = session.scalars(
        select(ServiceRecord)
        .options(selectinload(ServiceRecord.destination))
        .where(ServiceRecord.service_date <= as_of)
        .order_by(ServiceRecord.vehicle_id, ServiceRecord.service_date, ServiceRecord.id)
    ).all()
    out: dict[int, list[ServiceRecord]] = defaultdict(list)
    for r in rows:
        out[r.vehicle_id].append(r)
    return dict(out)


def driver_readings(session: Session, vehicle_ids: Sequence[int],
                    as_of: date | None = None) -> dict[int, list[OdometerReading]]:
    """Driver readings (manual / messenger) NOT flagged when saved, oldest first, up to ``as_of``:
    {vehicle_id: readings}. One query for all the vehicles."""
    if not vehicle_ids:
        return {}
    query = (select(OdometerReading)
             .where(OdometerReading.vehicle_id.in_(list(vehicle_ids)), OdometerReading.source.in_(DRIVER_SOURCES),
                    OdometerReading.status == "ok")
             .order_by(OdometerReading.vehicle_id, OdometerReading.reading_date, OdometerReading.id))
    if as_of is not None:
        query = query.where(OdometerReading.reading_date <= as_of)
    out: dict[int, list[OdometerReading]] = defaultdict(list)
    for r in session.scalars(query).all():
        out[r.vehicle_id].append(r)
    return dict(out)


def meter(record: ServiceRecord) -> tuple[Unit, Reading]:
    """A service's own meter: the odometer, else engine hours (mine trucks); the schema needs one."""
    if record.odometer_km is not None:
        return "km", Reading(record.service_date, float(record.odometer_km))
    return "hours", Reading(record.service_date, float(record.engine_hours))


def meter_in(record: ServiceRecord, unit: Unit) -> Reading | None:
    """A service's meter in ``unit`` (None when that service has no such meter)."""
    value = record.odometer_km if unit == "km" else record.engine_hours
    return None if value is None else Reading(record.service_date, float(value))


def schedule_of(records_oldest_first: Sequence[ServiceRecord], readings: Sequence[OdometerReading],
                rules: ReminderRules) -> Schedule | None:
    """The Schedule of a truck's latest service (None without services). ``readings`` = that truck's
    driver_readings (other units and older cycles are skipped by the engine)."""
    if not records_oldest_first:
        return None
    latest = records_oldest_first[-1]
    unit, service = meter(latest)
    previous = meter_in(records_oldest_first[-2], unit) if len(records_oldest_first) > 1 else None
    points = [Reading(r.reading_date, float(r.value)) for r in readings if r.unit == unit]
    return schedule(unit, service, previous, points, latest.interval_km, rules)


def service_reading(previous: ServiceRecord | None, record: ServiceRecord) -> OdometerReading:
    """The 'service' reading of a just-saved service (it needs its id), checked against the service
    before it (same rules as the migration 010 backfill)."""
    unit, point = meter(record)
    base = meter_in(previous, unit) if previous is not None else None
    flag = flag_of(base, point, unit) if base is not None else None
    per_day = rate(base, point) if base is not None else None
    return OdometerReading(vehicle_id=record.vehicle_id, service_id=record.id, unit=unit,
                           value=record.odometer_km if unit == "km" else record.engine_hours,
                           reading_date=record.service_date, source="service",
                           status="ok" if flag is None else "flagged", flag_reason=flag,
                           rate_per_day=None if per_day is None else round(per_day, 1))


def pace_out(plan: Schedule) -> PaceOut:
    """A Schedule in the API's shape."""
    pace = plan.pace
    return PaceOut(unit=plan.unit, rate_per_day=None if pace.rate_per_day is None else round(pace.rate_per_day, 1),
                   source=pace.source, reading_value=pace.reading.value if pace.reading else None,
                   reading_date=pace.reading.day if pace.reading else None, interval_km=plan.interval_km,
                   next_due_date=plan.next_due, reminder_on=plan.reminder_on, basis=plan.basis,
                   km_check_on=plan.km_check_on)
