"""Service history from the database in the shape the predictor needs (tasks 4.3, 4.4).

Shared by the vehicle card, the due-reminder list and the segment counts, so
all three see the same visits in the same order (oldest first, id breaks
same-day ties, like v_vehicle_service_summary).
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Sequence
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from src.api.models import ServiceRecord
from src.api.prediction import Visit


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
