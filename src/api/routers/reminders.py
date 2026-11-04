"""Reminders (task 9.5c, one reminder per service; was 9.5b month stages, 4.4 / D-036 prediction timing).

GET    /reminders/due?as_of=                   trucks whose reminder is due and not sent
POST   /reminders/{service_id}/sent            "I sent it" (idempotent)
GET    /reminders/stops                         phones that asked for no more messages
POST   /reminders/stops      {phone}            add one (idempotent)
DELETE /reminders/stops/{phone}                 remove one (a mistaken tap)

Rules (src/api/reminders.py, D-119): due on the reminder day of the truck's LATEST service, once per
service. Task 9.14a (src/api/pace.py): with the truck's km/day known, the reminder day is its due day
- REMINDER_LEAD_DAYS (5) (at most AT_RISK_DAYS - 5 after the service); without, REMINDER_DAYS (75)
after the service. A 1m / 2m / 3m row of 9.5b for that service counts as sent; a new service starts a
new cycle. A truck AT_RISK_DAYS (150) past it stays on the list (segment at_risk) until it is marked sent
or comes back. No reminder for a truck without an odometer (mine trucks: engine hours only) or to a
stopped phone. The ML model is not needed here (prediction code stays for the card's model API, D-065).
No SMS / Viber is sent by the API (D-010): the manager sends the text and marks it sent (channel 'manual').
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.clock import get_today
from src.api.config import Contact, ReminderRules, reminder_contact, reminder_rules
from src.api.db import get_session
from src.api.history import driver_readings, records_as_of, schedule_of, service_records
from src.api.models import ReminderSent, ReminderStop, ServiceRecord, Vehicle
from src.api.reminders import STAGE, days_since, message_mn, segment_of
from src.api.schemas import DueReminder, DueReminders, ReminderSentOut, StopIn, StopOut, normalize_phone

router = APIRouter(prefix="/reminders", tags=["reminders"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def get_contact() -> Contact:
    """FastAPI dependency: the oil changer's contact from the environment (override in tests)."""
    return reminder_contact()


def get_rules() -> ReminderRules:
    """FastAPI dependency: REMINDER_DAYS / AT_RISK_DAYS from the environment (checked at startup)."""
    return reminder_rules()


ContactDep = Annotated[Contact, Depends(get_contact)]
RulesDep = Annotated[ReminderRules, Depends(get_rules)]


def stopped_phones(session: Session) -> set[str]:
    return set(session.scalars(select(ReminderStop.phone)).all())


def text_for(vehicle: Vehicle, service: ServiceRecord, contact: Contact) -> str:
    """The reminder text for one truck's latest service."""
    return message_mn(vehicle.identifier, service.service_date, service.oil_grade, contact)


@router.get("/due", response_model=DueReminders)
def due_reminders(
    session: SessionDep,
    today: TodayDep,
    contact: ContactDep,
    rules: RulesDep,
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Uses only services up to this day")] = None,
) -> DueReminders:
    """Trucks whose reminder day has come on as_of and nothing was sent for that service (oldest first)."""
    as_of = as_of or today
    records = records_as_of(session, as_of)  # {vehicle_id: services oldest first}
    latest = {vid: rs[-1] for vid, rs in records.items()}
    # Any stage row (9.5c 'single' or an old 9.5b 1m/2m/3m) = this service was reminded already.
    sent = set(session.scalars(select(ReminderSent.service_id).where(
        ReminderSent.service_id.in_([s.id for s in latest.values()]), ReminderSent.stage.is_not(None))).all())
    stops = stopped_phones(session)
    readings = driver_readings(session, list(latest), as_of)  # 9.14a: only readings known on as_of
    plans = {vid: schedule_of(records[vid], readings.get(vid, []), rules) for vid in latest}
    due = [vid for vid, service in latest.items()
           if service.odometer_km is not None                                      # not a mine truck
           and not (service.driver_phone and service.driver_phone in stops)        # driver did not say stop
           and service.id not in sent and plans[vid].reminder_on <= as_of]
    vehicles = {v.id: v for v in session.scalars(
        select(Vehicle).options(selectinload(Vehicle.company)).where(Vehicle.id.in_(due))).all()}
    items = []
    for vid in due:
        vehicle, service, plan = vehicles[vid], latest[vid], plans[vid]
        items.append(DueReminder(
            service_id=service.id, vehicle_id=vid, identifier_type=vehicle.identifier_type,
            identifier=vehicle.identifier, plate_normalized=vehicle.plate_normalized, company=vehicle.company.name,
            phone=service.driver_phone, driver_name=service.driver_name, last_change_date=service.service_date,
            oil_grade=service.oil_grade, liters=float(service.liters), odometer_km=service.odometer_km,
            target_km=service.target_km, days_since=days_since(service.service_date, as_of), send_on=plan.reminder_on,
            next_due_date=plan.next_due,
            rate_per_day=None if plan.pace.rate_per_day is None else round(plan.pace.rate_per_day, 1),
            pace_source=plan.pace.source, basis=plan.basis,
            segment=segment_of(len(records[vid]), service.service_date, as_of, rules),
            message_mn=text_for(vehicle, service, contact),
        ))
    items.sort(key=lambda r: (r.send_on, r.vehicle_id))
    return DueReminders(as_of=as_of, contact_is_placeholder=contact.is_placeholder, reminders=items)


def _existing(session: Session, service_id: int) -> ReminderSent | None:
    """The stage row already stored for this service: 'single', else the newest old 1m/2m/3m row."""
    rows = session.scalars(select(ReminderSent).where(ReminderSent.service_id == service_id,
                                                      ReminderSent.stage.is_not(None))).all()
    return max(rows, key=lambda r: (r.stage == STAGE, r.sent_at, r.id), default=None)


def _already(response: Response, row: ReminderSent) -> ReminderSentOut:
    response.status_code = status.HTTP_200_OK
    return ReminderSentOut.model_validate(row).model_copy(update={"already_sent": True})


@router.post("/{service_id}/sent", response_model=ReminderSentOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Already marked before (also a 9.5b 1m/2m/3m row): that row, unchanged"}})
def mark_sent(service_id: int, response: Response, session: SessionDep, today: TodayDep, contact: ContactDep,
              rules: RulesDep) -> ReminderSentOut:
    """Store "sent" for this service. Idempotent: a second call returns the stored row (200).

    404 unknown service · 409 a newer service exists (the list is out of date) · 422 the reminder is
    not due yet, the truck has no odometer (mine truck) or its phone asked to stop.
    """
    existing = _existing(session, service_id)
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
    if service.odometer_km is None:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "no reminders for a truck without odometer")
    plan = schedule_of(list(reversed(records)), driver_readings(session, [service.vehicle_id], today).get(
        service.vehicle_id, []), rules)
    if plan.reminder_on > today:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "the reminder is not due yet")
    if service.driver_phone and service.driver_phone in stopped_phones(session):
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "this phone asked for no more messages")
    vehicle = session.get(Vehicle, service.vehicle_id)
    row = ReminderSent(vehicle_id=service.vehicle_id, service_id=service_id, stage=STAGE, phone=service.driver_phone,
                       message_text=text_for(vehicle, service, contact), send_on=plan.reminder_on)
    session.add(row)
    try:
        session.commit()
    except IntegrityError:  # marked at the same moment by another request: return that row
        session.rollback()
        return _already(response, _existing(session, service_id))
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
