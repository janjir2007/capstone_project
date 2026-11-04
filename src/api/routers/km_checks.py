"""«Км шалгах» (task 9.14a): ask the driver for his current km when the truck's pace is not known.

GET  /km-checks/due?as_of=          trucks to ask today
POST /km-checks/{service_id}/sent   "I sent it" (idempotent)

Rules (src/api/pace.py, PM 9.14a-2 #4): a truck is asked once per service, KM_CHECK_DAYS (34) after
its LATEST service, when it has no usable km/day (one service only, or a flagged reading pair), has an
odometer (not a mine truck) and its phone did not ask to stop. It leaves the list on its reminder day
(REMINDER_DAYS, 75): with no reply, the reminder goes then (D-119). The driver's reply is typed in
with POST /vehicles/{id}/readings, which moves the reminder (src/api/routers/readings.py).
A km check is NOT a reminder: its own table (km_checks), not in reminders_sent nor in the
«Сануулга илгээсэн» count. No SMS is sent by the API: the manager sends the text and marks it sent.
"""

from datetime import date, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.clock import get_today
from src.api.db import get_session
from src.api.history import driver_readings, records_as_of, schedule_of, service_records
from src.api.models import KmCheck, ServiceRecord, Vehicle
from src.api.reminders import days_since, km_check_message, segment_of
from src.api.routers.reminders import ContactDep, RulesDep, stopped_phones
from src.api.schemas import KmCheckDue, KmCheckOut, KmChecksDue

router = APIRouter(prefix="/km-checks", tags=["km checks"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


@router.get("/due", response_model=KmChecksDue)
def due_km_checks(
    session: SessionDep,
    today: TodayDep,
    contact: ContactDep,
    rules: RulesDep,
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Uses only services and "
                                                    "readings up to this day")] = None,
) -> KmChecksDue:
    """Trucks to ask for their km on as_of: check day come, reminder day not yet, no pace, not sent."""
    as_of = as_of or today
    records = records_as_of(session, as_of)  # {vehicle_id: services oldest first}
    latest = {vid: rs[-1] for vid, rs in records.items()}
    logged = set(session.scalars(select(KmCheck.service_id).where(
        KmCheck.service_id.in_([s.id for s in latest.values()]))).all())
    stops = stopped_phones(session)
    readings = driver_readings(session, list(latest), as_of)
    plans = {vid: schedule_of(records[vid], readings.get(vid, []), rules) for vid in latest}
    asked = [vid for vid, service in latest.items()
             if plans[vid].km_check_on is not None                                # km truck without a pace
             and plans[vid].km_check_on <= as_of < plans[vid].reminder_on
             and service.id not in logged
             and not (service.driver_phone and service.driver_phone in stops)]
    vehicles = {v.id: v for v in session.scalars(
        select(Vehicle).options(selectinload(Vehicle.company)).where(Vehicle.id.in_(asked))).all()}
    checks = []
    for vid in asked:
        vehicle, service, plan = vehicles[vid], latest[vid], plans[vid]
        checks.append(KmCheckDue(
            service_id=service.id, vehicle_id=vid, identifier_type=vehicle.identifier_type,
            identifier=vehicle.identifier, plate_normalized=vehicle.plate_normalized, company=vehicle.company.name,
            phone=service.driver_phone, driver_name=service.driver_name, last_change_date=service.service_date,
            odometer_km=service.odometer_km, days_since=days_since(service.service_date, as_of),
            check_on=plan.km_check_on, reminder_on=plan.reminder_on,
            segment=segment_of(len(records[vid]), service.service_date, as_of, rules),
            message_mn=km_check_message(vehicle.identifier, service.service_date, contact),
        ))
    checks.sort(key=lambda c: (c.check_on, c.vehicle_id))
    return KmChecksDue(as_of=as_of, contact_is_placeholder=contact.is_placeholder, checks=checks)


def _already(response: Response, row: KmCheck) -> KmCheckOut:
    response.status_code = status.HTTP_200_OK
    return KmCheckOut.model_validate(row).model_copy(update={"already_sent": True})


@router.post("/{service_id}/sent", response_model=KmCheckOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Already marked before: that row, unchanged"}})
def mark_km_check_sent(service_id: int, response: Response, session: SessionDep, today: TodayDep,
                       contact: ContactDep, rules: RulesDep) -> KmCheckOut:
    """Store "km check sent" for this service. Idempotent: a second call returns the stored row (200).

    404 unknown service · 409 a newer service exists (the list is out of date) · 422 the check day has
    not come, the truck has no odometer (mine truck) or its phone asked to stop.
    """
    existing = session.scalar(select(KmCheck).where(KmCheck.service_id == service_id))
    if existing is not None:
        return _already(response, existing)
    service = session.get(ServiceRecord, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"service {service_id} not found")
    records = service_records(session, service.vehicle_id)  # newest first
    if records[0].id != service_id:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "not_latest_service",
            "message": "the truck has a newer service; reload the km-check list",
            "latest_service_id": records[0].id,
        })
    if service.odometer_km is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no km check for a truck without odometer")
    check_on = service.service_date + timedelta(days=rules.km_check_days)
    if check_on > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the km check is not due yet")
    if service.driver_phone and service.driver_phone in stopped_phones(session):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "this phone asked for no more messages")
    vehicle = session.get(Vehicle, service.vehicle_id)
    row = KmCheck(vehicle_id=service.vehicle_id, service_id=service_id, phone=service.driver_phone,
                  message_text=km_check_message(vehicle.identifier, service.service_date, contact), check_on=check_on)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:  # marked at the same moment by another request: return that row
        session.rollback()
        return _already(response, session.scalar(select(KmCheck).where(KmCheck.service_id == service_id)))
    session.refresh(row)
    return KmCheckOut.model_validate(row)
