"""POST /services — save one oil change (task 4.2).

Steps, all in ONE transaction (either everything is saved or nothing):
1. service_date: given or today (Ulaanbaatar); never in the future.
2. route (D-039): destination_id set -> route = that destination's
   route_category (the user cannot override it); destination_raw only ->
   route as given (required, checked in schemas.ServiceCreate).
3. vehicle: found by normalized plate (or company + fleet number). Unknown ->
   vehicle created, and its company too if the name is new. Company names
   match ignoring case and extra spaces (task 4.2b, src/api/matching.py).
4. duplicate guard (task 4.2b): the same vehicle already has a service on
   the same date -> 409, unless the request has ?force=true.
5. service record inserted with interval_km = OIL_INTERVAL_KM and target_km = odometer_km + it
   (task 9.14a: stored, so a later change of the setting does not move old targets; none for mine
   trucks), plus its 'service' odometer reading, checked against the service before it.
6. task 9.15a: its Messenger ref code (the m.me link of its km-check SMS); none for mine trucks.
7. task 9.16b: optional price_mnt; the answer carries the payment status («Хүлээгдэж байна», or
   «Төлсөн» for price 0).

Task 9.16b, manual payment (migration 013, plan docs/plans/9.16b_plan.md):
POST /services/{id}/payment   «Төлсөн» (paid) · «Авлага» (unpaid) · «Буцаах» (undo_paid)
PUT  /services/{id}/price     change / clear the price after saving (PM Q2)
Both answer the updated service; the status itself is computed (src/api/payments.py manual_status).
"""

from datetime import date, datetime
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from src.api.clock import get_now, get_today
from src.api.config import oil_interval_km, payment_due_hours
from src.api.db import get_session
from src.api.history import service_reading, service_records
from src.api.matching import clean_company_name, company_key, fleet_no_key
from src.api.messenger.refs import add_ref
from src.api.models import Company, Destination, ServiceRecord, Vehicle
from src.api.payments import MANUAL_PAID
from src.api.routers.vehicles import service_out
from src.api.schemas import PaymentIn, PriceIn, ServiceCreate, ServiceCreated, ServiceOut
from src.common.plates import normalize_plate

router = APIRouter(tags=["services"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]
NowDep = Annotated[datetime, Depends(get_now)]


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


def find_company(session: Session, name: str) -> Company | None:
    """Existing company whose name matches ignoring case and extra spaces.

    If old data holds two names with the same key, the oldest (lowest id) wins,
    so the answer is always the same.
    """
    key = company_key(name)
    companies = session.scalars(select(Company).order_by(Company.id)).all()
    return next((company for company in companies if company_key(company.name) == key), None)


def get_or_create_company(session: Session, name: str) -> tuple[Company, bool]:
    """Matching company, or a new one with the cleaned name. Returns (company, created)."""
    company = find_company(session, name)
    if company is not None:
        return company, False
    company = Company(name=clean_company_name(name))
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
    company = find_company(session, body.company_name)
    if company is None:
        return None
    # Same forgiving key as the lookup (src/api/matching.py, task 4.4): "ht 12" finds "HT-12".
    key = fleet_no_key(body.identifier)
    fleet = session.scalars(
        select(Vehicle)
        .where(Vehicle.company_id == company.id, Vehicle.identifier_type == "fleet_no")
        .order_by(Vehicle.id)  # if old data has two spellings of one truck, the oldest wins
    ).all()
    return next((v for v in fleet if fleet_no_key(v.identifier) == key), None)


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


def reject_same_day_duplicate(session: Session, vehicle: Vehicle, service_date: date) -> None:
    """409 if this vehicle already has a service on service_date.

    Usually the form was sent twice (double tap, retry on a slow network). A
    real second oil change on the same day is rare, so the client must confirm
    it with ?force=true. ``detail`` is an object so the app can show the
    existing record and offer "save anyway".
    """
    existing_id = session.scalar(
        select(ServiceRecord.id)
        .where(ServiceRecord.vehicle_id == vehicle.id, ServiceRecord.service_date == service_date)
        .order_by(ServiceRecord.id)
        .limit(1)
    )
    if existing_id is not None:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            {
                "code": "duplicate_service",
                "message": f"vehicle {vehicle.id} already has a service on {service_date}; "
                "nothing saved. Send again with ?force=true to save a second one",
                "existing_service_id": existing_id,
            },
        )


@router.post("/services", status_code=status.HTTP_201_CREATED, response_model=ServiceCreated)
def create_service(
    body: ServiceCreate,
    session: SessionDep,
    today: TodayDep,
    now: NowDep,
    force: Annotated[bool, Query(description="true = save even if this vehicle already has a service that day")] = False,
) -> ServiceCreated:
    """Save one oil change; create the vehicle (and company) if the plate is new."""
    service_date = body.service_date or today
    if service_date > today:
        raise unprocessable(f"service_date {service_date} is in the future (today is {today})")

    route = resolve_route(session, body)
    vehicle = find_vehicle(session, body)
    if vehicle is not None and not force:
        reject_same_day_duplicate(session, vehicle, service_date)
    vehicle_created = company_created = False
    if vehicle is None:
        vehicle, company_created = create_vehicle(session, body)
        vehicle_created = True

    # 9.14a: the service before this one (on or before its day; an existing same-day service counts as
    # before it) -> its 'service' reading is checked against that one.
    previous = None if vehicle_created else next(
        (r for r in service_records(session, vehicle.id) if r.service_date <= service_date), None)
    interval = oil_interval_km() if body.odometer_km is not None else None  # 9.14a: stored, not computed later
    record = ServiceRecord(
        vehicle=vehicle,
        service_date=service_date,
        odometer_km=body.odometer_km,
        interval_km=interval,
        target_km=None if interval is None else body.odometer_km + interval,
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
        price_mnt=body.price_mnt,  # 9.16b; payment_tracked = true (column default)
    )
    session.add(record)
    try:
        session.flush()  # the service's id, for its 'service' reading (9.14a)
        session.add(service_reading(previous, record))
        add_ref(session, record)  # 9.15a
        session.commit()
    except IntegrityError as exc:
        # E.g. the same new plate saved twice at the same moment: the unique
        # index wins, nothing is saved, and the client can simply retry.
        session.rollback()
        raise HTTPException(status.HTTP_409_CONFLICT, "conflict with existing data; nothing saved, retry") from exc

    session.refresh(record)  # created_at + payment_tracked come from the database
    return ServiceCreated(
        service=service_out(record, now, payment_due_hours()),
        vehicle_id=vehicle.id,
        vehicle_created=vehicle_created,
        company_created=company_created,
    )


# ---------------------------------------------------------------- task 9.16b: manual payment


def tracked_service(session: Session, service_id: int) -> ServiceRecord:
    """The service, locked for this change. 404 unknown; 409 saved before 9.16b (no payment status)."""
    record = session.get(ServiceRecord, service_id, with_for_update=True)
    if record is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"service {service_id} not found")
    if not record.payment_tracked:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "not_tracked",
            "message": "Энэ үйлчилгээ төлбөрийн бүртгэлээс өмнө хадгалагдсан (no payment status)"})
    return record


@router.post("/services/{service_id}/payment", response_model=ServiceOut)
def set_payment(service_id: int, body: PaymentIn, session: SessionDep, now: NowDep) -> ServiceOut:
    """«Төлсөн» / «Авлага» / «Буцаах» on one service (any of the truck's services, not only the newest).

    - paid: paid_at = now (kept if already set: a second tap changes nothing)
    - unpaid: marked_unpaid_at = now (kept if already set) and paid_at cleared (corrects a «Төлсөн»)
    - undo_paid: paid_at cleared; the rule decides again (pending, or «Авлага» after 24 h)
    Price 0 = nothing owed, always «Төлсөн»: unpaid / undo_paid -> 409 (change the price first).
    """
    record = tracked_service(session, service_id)
    if record.price_mnt == 0 and body.action != MANUAL_PAID:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "price_zero",
            "message": "Үнэ 0₮: төлөх зүйлгүй. Эхлээд үнээ засна уу (nothing owed; change the price first)"})
    if body.action == "paid":
        record.paid_at = record.paid_at or now
    elif body.action == "unpaid":
        record.marked_unpaid_at = record.marked_unpaid_at or now
        record.paid_at = None
    else:  # undo_paid
        record.paid_at = None
    session.commit()
    session.refresh(record)
    return service_out(record, now, payment_due_hours())


@router.put("/services/{service_id}/price", response_model=ServiceOut)
def set_price(service_id: int, body: PriceIn, session: SessionDep, now: NowDep) -> ServiceOut:
    """Change the price after saving (PM Q2). null clears it. Clicks are kept: a paid service stays paid;
    price 0 makes it «Төлсөн» (nothing owed)."""
    record = tracked_service(session, service_id)
    record.price_mnt = body.price_mnt
    session.commit()
    session.refresh(record)
    return service_out(record, now, payment_due_hours())
