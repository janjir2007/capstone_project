"""Reminders (task 9.5b, month stages; was 4.4 / D-036 prediction timing): who to remind today.

GET    /reminders/due?as_of=                   trucks whose month stage (1m/2m/3m) is due and not sent
POST   /reminders/{service_id}/sent?stage=2m   "I sent it" for that stage (idempotent)
GET    /reminders/stops                         phones that asked for no more messages
POST   /reminders/stops      {phone}            add one (idempotent)
DELETE /reminders/stops/{phone}                 remove one (a mistaken tap)

Rules (src/api/reminders.py): stage = days since the truck's LATEST service (30 / 60 / 90); only
the highest stage reached, each stage once per service; a new service starts again. No reminder
for a truck without an odometer (mine trucks: engine hours only) or to a stopped phone.
The ML model is not needed here (prediction code stays for the card's model API, D-065).
No SMS / Viber is sent by the API (D-010): the manager sends the text and marks it sent.
"""

from collections import defaultdict
from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.clock import get_today
from src.api.config import Contact, oil_interval_km, reminder_contact
from src.api.db import get_session
from src.api.history import records_as_of, service_records
from src.api.models import ReminderSent, ReminderStop, ServiceRecord, Vehicle
from src.api.reminders import days_since, due_stage, message_mn, segment_of, stage_day
from src.api.schemas import (DueReminder, DueReminders, ReminderSentOut, ReminderStage, StopIn, StopOut,
                             normalize_phone)

router = APIRouter(prefix="/reminders", tags=["reminders"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def get_contact() -> Contact:
    """FastAPI dependency: the oil changer's contact from the environment (override in tests)."""
    return reminder_contact()


ContactDep = Annotated[Contact, Depends(get_contact)]


def stopped_phones(session: Session) -> set[str]:
    return set(session.scalars(select(ReminderStop.phone)).all())


def text_for(vehicle: Vehicle, service: ServiceRecord, stage: str, contact: Contact) -> str:
    """The stage message for one truck's latest service (it has an odometer: checked by the callers)."""
    return message_mn(stage, vehicle.identifier, service.service_date, service.oil_grade,
                      service.odometer_km + oil_interval_km(), contact)


@router.get("/due", response_model=DueReminders)
def due_reminders(
    session: SessionDep,
    today: TodayDep,
    contact: ContactDep,
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Uses only services up to this day")] = None,
) -> DueReminders:
    """Trucks whose highest month stage reached on as_of is not sent yet (oldest stage day first)."""
    as_of = as_of or today
    records = records_as_of(session, as_of)  # {vehicle_id: services oldest first}
    latest = {vid: rs[-1] for vid, rs in records.items()}
    sent: dict[int, set[str]] = defaultdict(set)
    for service_id, stage in session.execute(
            select(ReminderSent.service_id, ReminderSent.stage).where(
                ReminderSent.service_id.in_([s.id for s in latest.values()]), ReminderSent.stage.is_not(None))):
        sent[service_id].add(stage)
    stops = stopped_phones(session)
    due = {}
    for vid, service in latest.items():
        if service.odometer_km is None or (service.driver_phone and service.driver_phone in stops):
            continue  # mine truck (engine hours only) / driver asked to stop
        stage = due_stage(service.service_date, as_of, sent[service.id])
        if stage is not None:
            due[vid] = stage
    vehicles = {v.id: v for v in session.scalars(
        select(Vehicle).options(selectinload(Vehicle.company)).where(Vehicle.id.in_(due))).all()}
    items = []
    for vid, stage in due.items():
        vehicle, service = vehicles[vid], latest[vid]
        items.append(DueReminder(
            service_id=service.id, vehicle_id=vid, identifier_type=vehicle.identifier_type,
            identifier=vehicle.identifier, plate_normalized=vehicle.plate_normalized, company=vehicle.company.name,
            phone=service.driver_phone, driver_name=service.driver_name, last_change_date=service.service_date,
            oil_grade=service.oil_grade, liters=float(service.liters), odometer_km=service.odometer_km,
            target_km=service.odometer_km + oil_interval_km(), stage=stage,
            days_since=days_since(service.service_date, as_of), send_on=stage_day(service.service_date, stage),
            segment=segment_of(len(records[vid]), service.service_date, as_of),
            message_mn=text_for(vehicle, service, stage, contact),
        ))
    items.sort(key=lambda r: (r.send_on, r.vehicle_id))
    return DueReminders(as_of=as_of, contact_is_placeholder=contact.is_placeholder, reminders=items)


def _existing(session: Session, service_id: int, stage: str) -> ReminderSent | None:
    return session.scalar(select(ReminderSent).where(ReminderSent.service_id == service_id,
                                                     ReminderSent.stage == stage))


def _already(response: Response, row: ReminderSent) -> ReminderSentOut:
    response.status_code = status.HTTP_200_OK
    return ReminderSentOut.model_validate(row).model_copy(update={"already_sent": True})


@router.post("/{service_id}/sent", response_model=ReminderSentOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Already marked before: the stored reminder, unchanged"}})
def mark_sent(service_id: int, response: Response, session: SessionDep, today: TodayDep, contact: ContactDep,
              stage: Annotated[ReminderStage, Query(description="The stage whose message was sent")]) -> ReminderSentOut:
    """Store "sent" for (service, stage). Idempotent: a second call returns the same row (200).

    404 unknown service · 409 a newer service exists (the list is out of date) · 422 the stage has
    not started yet, the truck has no odometer (mine truck) or its phone asked to stop.
    """
    existing = _existing(session, service_id, stage)
    if existing is not None:
        return _already(response, existing)
    service = session.get(ServiceRecord, service_id)
    if service is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"service {service_id} not found")
    records = service_records(session, service.vehicle_id)  # newest first
    if records[0].id != service_id:
        raise HTTPException(status.HTTP_409_CONFLICT, {
            "code": "not_latest_service",
            "message": "the truck has a newer service; reload the due list",
            "latest_service_id": records[0].id,
        })
    if stage_day(service.service_date, stage) > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, f"stage {stage} has not started yet")
    if service.odometer_km is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no reminders for a truck without odometer")
    if service.driver_phone and service.driver_phone in stopped_phones(session):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "this phone asked for no more messages")
    vehicle = session.get(Vehicle, service.vehicle_id)
    row = ReminderSent(vehicle_id=service.vehicle_id, service_id=service_id, stage=stage, phone=service.driver_phone,
                       message_text=text_for(vehicle, service, stage, contact),
                       send_on=stage_day(service.service_date, stage))
    session.add(row)
    try:
        session.commit()
    except IntegrityError:  # marked at the same moment by another request: return that row
        session.rollback()
        return _already(response, _existing(session, service_id, stage))
    session.refresh(row)
    return ReminderSentOut.model_validate(row)


@router.get("/stops", response_model=list[StopOut])
def list_stops(session: SessionDep) -> list[StopOut]:
    """Phones that get no reminders, newest first."""
    rows = session.scalars(select(ReminderStop).order_by(ReminderStop.created_at.desc(), ReminderStop.phone)).all()
    return [StopOut.model_validate(r) for r in rows]


@router.post("/stops", response_model=StopOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Already stopped: the stored row"}})
def add_stop(body: StopIn, response: Response, session: SessionDep) -> StopOut:
    """The driver asked for no more messages: none of his trucks' reminders go to this phone."""
    existing = session.get(ReminderStop, body.phone)
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return StopOut.model_validate(existing)
    row = ReminderStop(phone=body.phone)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:
        session.rollback()
        response.status_code = status.HTTP_200_OK
        row = session.get(ReminderStop, body.phone)
        return StopOut.model_validate(row)
    session.refresh(row)
    return StopOut.model_validate(row)


@router.delete("/stops/{phone}", status_code=status.HTTP_204_NO_CONTENT)
def remove_stop(phone: str, session: SessionDep) -> Response:
    """Send reminders to this phone again (undo a mistaken «stop»). Unknown phone -> 204 too."""
    try:
        phone = normalize_phone(phone)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    row = session.get(ReminderStop, phone)
    if row is not None:
        session.delete(row)
        session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
