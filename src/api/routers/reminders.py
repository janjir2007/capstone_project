"""Reminders (tasks 4.4, 4.4b, D-036): who to remind today, and "I sent it".

GET  /reminders/due?as_of=              vehicles whose reminder day has come and is not sent yet
POST /reminders/{service_id}/sent       mark the reminder for that (vehicle, newest service) as sent

send_on = predicted date − buffer of the method that answered (ridge from the
model file, b0/b1 from models/serving_params.json; never typed in here).
One reminder per (vehicle, newest service): when the truck comes back, its new
service starts a new cycle. No SMS is sent by the API (no gateway, D-010):
the oil changer copies message_mn and then marks it sent.
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from src.api.clock import get_today
from src.api.config import Contact, reminder_contact
from src.api.db import get_session
from src.api.history import records_as_of, service_records, to_visit
from src.api.models import ReminderSent, ServiceRecord, Vehicle
from src.api.prediction import Prediction, Predictor, segment_of
from src.api.reminders import message_mn
from src.api.routers.vehicles import get_predictor
from src.api.schemas import DueReminder, DueReminders, ReminderSentOut

router = APIRouter(prefix="/reminders", tags=["reminders"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]


def require_predictor(predictor: Annotated[Predictor | None, Depends(get_predictor)]) -> Predictor:
    """Reminders need the model: 503 if its files were not loaded."""
    if predictor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "prediction model not loaded")
    return predictor


def get_contact() -> Contact:
    """FastAPI dependency: Geo-Expert contact from the environment (override in tests)."""
    return reminder_contact()


PredictorDep = Annotated[Predictor, Depends(require_predictor)]
ContactDep = Annotated[Contact, Depends(get_contact)]


def text_for(vehicle: Vehicle, service: ServiceRecord, prediction: Prediction, contact: Contact) -> str:
    """The Mongolian message for one vehicle's newest service."""
    return message_mn(vehicle.identifier, service.service_date, service.oil_grade, service.liters,
                      overdue=prediction.status == "overdue", contact=contact)


@router.get("/due", response_model=DueReminders)
def due_reminders(
    session: SessionDep,
    today: TodayDep,
    predictor: PredictorDep,
    contact: ContactDep,
    as_of: Annotated[date | None, Query(description="Default: today (Ulaanbaatar). Uses only services up to this day")] = None,
) -> DueReminders:
    """Vehicles with send_on <= as_of whose reminder for the newest service is not sent yet."""
    as_of = as_of or today
    records = records_as_of(session, as_of)
    predictions = predictor.predict_many({vid: [to_visit(r) for r in rs] for vid, rs in records.items()}, as_of)
    sent = set(session.scalars(select(ReminderSent.service_id)).all())
    due = {vid: p for vid, p in predictions.items()
           if predictor.send_on(p) <= as_of and p.based_on_service_id not in sent}
    vehicles = {v.id: v for v in session.scalars(
        select(Vehicle).options(selectinload(Vehicle.company)).where(Vehicle.id.in_(due))).all()}
    items = []
    for vid, p in due.items():
        vehicle, service = vehicles[vid], records[vid][-1]
        items.append(DueReminder(
            service_id=service.id, vehicle_id=vid, identifier_type=vehicle.identifier_type,
            identifier=vehicle.identifier, plate_normalized=vehicle.plate_normalized, company=vehicle.company.name,
            phone=service.driver_phone, driver_name=service.driver_name, last_change_date=service.service_date,
            oil_grade=service.oil_grade, liters=float(service.liters), method=p.method,
            buffer_days=predictor.buffers[p.method], predicted_date=p.predicted_date, send_on=predictor.send_on(p),
            days_left=p.days_left, status=p.status,
            segment=segment_of(len(records[vid]), p.predicted_date, as_of),  # D-074: the UI keeps no copy of D-007
            message_mn=text_for(vehicle, service, p, contact),
        ))
    items.sort(key=lambda r: (r.send_on, r.vehicle_id))
    return DueReminders(as_of=as_of, contact_is_placeholder=contact.is_placeholder, reminders=items)


@router.post("/{service_id}/sent", response_model=ReminderSentOut, status_code=status.HTTP_201_CREATED,
             responses={200: {"description": "Already marked before: the stored reminder, unchanged"}})
def mark_sent(service_id: int, response: Response, session: SessionDep, today: TodayDep, predictor: PredictorDep,
              contact: ContactDep) -> ReminderSentOut:
    """Store "reminder sent" for this service. Idempotent: a second call returns the same row (200).

    404 unknown service · 409 a newer service exists for the vehicle (the due item is out of date) ·
    503 model not loaded.
    """
    existing = session.scalar(select(ReminderSent).where(ReminderSent.service_id == service_id))
    if existing is not None:
        response.status_code = status.HTTP_200_OK
        return ReminderSentOut.model_validate(existing).model_copy(update={"already_sent": True})
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
    prediction = predictor.predict(service.vehicle_id, [to_visit(r) for r in reversed(records)], today)
    vehicle = session.get(Vehicle, service.vehicle_id)
    row = ReminderSent(vehicle_id=service.vehicle_id, service_id=service_id, phone=service.driver_phone,
                       message_text=text_for(vehicle, service, prediction, contact), method=prediction.method,
                       model_version=prediction.model_version, predicted_date=prediction.predicted_date,
                       send_on=predictor.send_on(prediction))
    session.add(row)
    try:
        session.commit()
    except IntegrityError:  # marked at the same moment by another request: return that row
        session.rollback()
        response.status_code = status.HTTP_200_OK
        row = session.scalar(select(ReminderSent).where(ReminderSent.service_id == service_id))
        return ReminderSentOut.model_validate(row).model_copy(update={"already_sent": True})
    session.refresh(row)
    return ReminderSentOut.model_validate(row)
