"""Vehicle lookup and vehicle card (task 4.2).

GET /vehicles/lookup?q=   plate or phone -> matching vehicle cards
GET /vehicles/{id}        one vehicle card

The card = last service (pre-fills the recording form), usual liters, full
history, service count and today's segment. prediction is always null until
task 4.3 serves the model.
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from src.api.clock import get_today
from src.api.db import get_session
from src.api.models import ServiceRecord, Vehicle
from src.api.schemas import CompanyOut, LookupResult, ServiceOut, VehicleCard, normalize_phone
from src.common.plates import normalize_plate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def usual_liters(liters_newest_first: Sequence[Decimal]) -> Decimal | None:
    """Most frequent oil amount; on a tie, the one used most recently.

    The mode (not the mean) because a truck's sump size is fixed: one odd
    top-up should not shift the 'usual' value to a number never actually used.
    """
    if not liters_newest_first:
        return None
    counts = Counter(liters_newest_first)
    best = max(counts.values())
    return next(value for value in liters_newest_first if counts[value] == best)


def vehicle_segment(session: Session, vehicle_id: int, as_of: date) -> str | None:
    """Segment from the database function vehicle_segments (data_dictionary §3)."""
    return session.execute(
        text("SELECT segment FROM vehicle_segments(:as_of) WHERE vehicle_id = :vehicle_id"),
        {"as_of": as_of, "vehicle_id": vehicle_id},
    ).scalar_one_or_none()


def build_card(session: Session, vehicle: Vehicle, today: date) -> VehicleCard:
    """Assemble the vehicle card from the vehicle row and its service records."""
    records = session.scalars(
        select(ServiceRecord)
        .options(selectinload(ServiceRecord.destination))  # load destinations in 1 extra query
        .where(ServiceRecord.vehicle_id == vehicle.id)
        # Same order as v_vehicle_service_summary: newest date first, id breaks ties.
        .order_by(ServiceRecord.service_date.desc(), ServiceRecord.id.desc())
    ).all()
    history = [ServiceOut.model_validate(record) for record in records]
    liters = usual_liters([record.liters for record in records])
    return VehicleCard(
        id=vehicle.id,
        identifier_type=vehicle.identifier_type,
        identifier=vehicle.identifier,
        plate_normalized=vehicle.plate_normalized,
        vehicle_model=vehicle.vehicle_model,
        company=CompanyOut.model_validate(vehicle.company),
        service_count=len(history),
        segment=vehicle_segment(session, vehicle.id, today),
        usual_liters=None if liters is None else float(liters),
        last_service=history[0] if history else None,
        history=history,
        prediction=None,
    )


def vehicles_by_phone(session: Session, phone: str) -> Sequence[Vehicle]:
    """Every vehicle this phone ever appeared on (drivers change trucks, D-004).

    Newest service first, like the lookup_by_phone example query.
    """
    last_service = (
        select(ServiceRecord.vehicle_id, func.max(ServiceRecord.service_date).label("last_date"))
        .group_by(ServiceRecord.vehicle_id)
        .subquery()
    )
    used_phone = select(ServiceRecord.vehicle_id).where(ServiceRecord.driver_phone == phone)
    return session.scalars(
        select(Vehicle)
        .join(last_service, last_service.c.vehicle_id == Vehicle.id)
        .where(Vehicle.id.in_(used_phone))
        .order_by(last_service.c.last_date.desc(), Vehicle.id)
    ).all()


def vehicles_by_plate(session: Session, plate_normalized: str) -> Sequence[Vehicle]:
    """The vehicle with this normalized plate (0 or 1: the column is unique)."""
    return session.scalars(select(Vehicle).where(Vehicle.plate_normalized == plate_normalized)).all()


@router.get("/lookup", response_model=LookupResult)
def lookup(
    session: SessionDep,
    today: TodayDep,
    q: Annotated[str, Query(min_length=1, description="Plate (any spacing/case) or 8-digit phone")],
) -> LookupResult:
    """Find vehicles by plate or driver phone.

    If ``q`` is a valid phone (8 digits, +976 optional) it is searched as a
    phone, otherwise as a plate. Plates never consist of digits only, so the
    two cannot be confused. No match -> 200 with an empty list (the app then
    opens the new-vehicle form), not 404: an empty search is a normal result.
    """
    try:
        phone = normalize_phone(q)
    except ValueError:
        phone = None

    if phone is not None:
        match_type, normalized, vehicles = "phone", phone, vehicles_by_phone(session, phone)
    else:
        try:
            plate = normalize_plate(q)
        except ValueError as exc:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "q is blank") from exc
        match_type, normalized, vehicles = "plate", plate, vehicles_by_plate(session, plate)

    return LookupResult(
        query=q,
        match_type=match_type,
        normalized=normalized,
        vehicles=[build_card(session, vehicle, today) for vehicle in vehicles],
    )


@router.get("/{vehicle_id}", response_model=VehicleCard)
def get_vehicle(vehicle_id: int, session: SessionDep, today: TodayDep) -> VehicleCard:
    """The vehicle card. 404 if the id does not exist."""
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"vehicle {vehicle_id} not found")
    return build_card(session, vehicle, today)
