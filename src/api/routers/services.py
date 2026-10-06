"""POST /services — save one oil change (task 4.2).

Steps, all in ONE transaction (either everything is saved or nothing):
1. service_date: given or today (Ulaanbaatar); never in the future.
2. route (D-039): destination_id set -> route = that destination's
   route_category (the user cannot override it); destination_raw only ->
   route as given (required, checked in schemas.ServiceCreate).
3. vehicle: found by normalized plate (or company + fleet number). Unknown ->
   vehicle created, and its company too if the name is new.
4. service record inserted.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.clock import get_today
from src.api.db import get_session
from src.api.models import Company, Destination, ServiceRecord, Vehicle
from src.api.schemas import ServiceCreate, ServiceCreated, ServiceOut
from src.common.plates import normalize_plate

router = APIRouter(tags=["services"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def unprocessable(message: str) -> HTTPException:
    """422 for a request that is well-formed but breaks a business rule."""
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def resolve_route(session: Session, body: ServiceCreate) -> str | None:
    """Route to store, following D-039.

    With destination_id the route comes from the destinations table. A route
    sent together with it must agree; a different one is rejected (422)
    rather than silently replaced, so the client sees the conflict.
    """
    if body.destination_id is None:
        return body.route  # destination_raw case: required by ServiceCreate
    destination = session.get(Destination, body.destination_id)
    if destination is None:
        raise unprocessable(f"destination_id {body.destination_id} does not exist")
    if body.route is not None and body.route != destination.route_category:
        raise unprocessable(
            f"route '{body.route}' conflicts with destination '{destination.name}' "
            f"(route {destination.route_category}); leave route empty (D-039)"
        )
    return destination.route_category


def get_or_create_company(session: Session, name: str) -> tuple[Company, bool]:
    """Company with exactly this name, created if missing. Returns (company, created)."""
    company = session.scalar(select(Company).where(Company.name == name))
    if company is not None:
        return company, False
    company = Company(name=name)
    session.add(company)
    return company, True


def find_vehicle(session: Session, body: ServiceCreate) -> Vehicle | None:
    """Existing vehicle for the request, or None.

    Plates are unique in the whole database (normalized). Fleet numbers are
    only unique inside one company (D-005), so they need company_name.
    """
    if body.identifier_type == "plate":
        plate = normalize_plate(body.identifier)
        return session.scalar(select(Vehicle).where(Vehicle.plate_normalized == plate))
    if body.company_name is None:
        raise unprocessable("company_name is required for a fleet number (unique only per company)")
    return session.scalar(
        select(Vehicle)
        .join(Company)
        .where(
            Company.name == body.company_name,
            Vehicle.identifier_type == "fleet_no",
            Vehicle.identifier == body.identifier,
        )
    )


def create_vehicle(session: Session, body: ServiceCreate) -> tuple[Vehicle, bool]:
    """New vehicle (+ company if new). Returns (vehicle, company_created)."""
    if body.company_name is None:
        raise unprocessable("new vehicle: company_name is required (private owner = owner's name)")
    company, company_created = get_or_create_company(session, body.company_name)
    vehicle = Vehicle(
        company=company,
        identifier_type=body.identifier_type,
        identifier=body.identifier,
        plate_normalized=normalize_plate(body.identifier) if body.identifier_type == "plate" else None,
        vehicle_model=body.vehicle_model,
    )
    session.add(vehicle)
    return vehicle, company_created


@router.post("/services", status_code=status.HTTP_201_CREATED, response_model=ServiceCreated)
def create_service(body: ServiceCreate, session: SessionDep, today: TodayDep) -> ServiceCreated:
    """Save one oil change; create the vehicle (and company) if the plate is new."""
    service_date = body.service_date or today
    if service_date > today:
        raise unprocessable(f"service_date {service_date} is in the future (today is {today})")

    route = resolve_route(session, body)
    vehicle = find_vehicle(session, body)
    vehicle_created = company_created = False
    if vehicle is None:
        vehicle, company_created = create_vehicle(session, body)
        vehicle_created = True

    record = ServiceRecord(
        vehicle=vehicle,
        service_date=service_date,
        odometer_km=body.odometer_km,
        engine_hours=body.engine_hours,
        oil_grade=body.oil_grade,
        liters=body.liters,
        route=route,
        destination_id=body.destination_id,
        destination_raw=body.destination_raw,
        driver_name=body.driver_name,
        driver_phone=body.driver_phone,
        oil_changer=body.oil_changer,
        photo_ref=body.photo_ref,
    )
    session.add(record)
    try:
        session.commit()
    except IntegrityError as exc:
        # E.g. the same new plate saved twice at the same moment: the unique
        # index wins, nothing is saved, and the client can simply retry.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "conflict with existing data; nothing saved, retry") from exc

    return ServiceCreated(
        service=ServiceOut.model_validate(record),
        vehicle_id=vehicle.id,
        vehicle_created=vehicle_created,
        company_created=company_created,
    )
