"""Vehicle lookup and vehicle card (task 4.2).

GET /vehicles/lookup?q=          plate, fleet number or phone -> matching vehicle cards
GET /vehicles/search?q=&limit=   dashboard: any part of plate / fleet no / company / phone -> rows (task 9.1)
GET /vehicles/{id}               one vehicle card
GET /vehicles/{id}/prediction    next oil change only (task 4.3)

The card = last service (pre-fills the recording form), usual liters, full
history, service count, today's segment and the prediction (task 4.3; null
when the model is not loaded).
"""

from collections import Counter
from collections.abc import Sequence
from datetime import date
from decimal import Decimal
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Query, Request, status
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session, selectinload

from src.api.clock import get_today
from src.api.db import get_session
from src.api.history import records_as_of, service_records, to_visit, visits_oldest_first
from src.api.matching import fleet_no_key, search_matches
from src.api.models import ServiceRecord, Vehicle
from src.api.prediction import Predictor, segment_of
from src.api.schemas import (CompanyOut, LookupResult, PredictionOut, ServiceOut, VehicleCard, VehicleRow,
                             VehicleSearch, normalize_phone)
from src.common.plates import normalize_plate

router = APIRouter(prefix="/vehicles", tags=["vehicles"])



def get_predictor(request: Request) -> Predictor | None:
    """FastAPI dependency: the model loaded at startup (None if its files were missing)."""
    return getattr(request.app.state, "predictor", None)


SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]
PredictorDep = Annotated[Predictor | None, Depends(get_predictor)]


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


def predict(predictor: Predictor | None, vehicle_id: int, records: Sequence[ServiceRecord],
            today: date) -> PredictionOut | None:
    """Prediction for the card; None without model or without services."""
    if predictor is None or not records:
        return None
    return PredictionOut.model_validate(predictor.predict(vehicle_id, visits_oldest_first(records), today),
                                        from_attributes=True)


def build_card(session: Session, vehicle: Vehicle, today: date, predictor: Predictor | None = None) -> VehicleCard:
    """Assemble the vehicle card from the vehicle row and its service records."""
    records = service_records(session, vehicle.id)
    history = [ServiceOut.model_validate(record) for record in records]
    liters = usual_liters([record.liters for record in records])
    prediction = predict(predictor, vehicle.id, records, today)
    # Same rule as GET /stats/segments: with a prediction, at_risk comes from it (D-007, task 4.4);
    # without the model, the database function (count-based) answers.
    segment = (segment_of(len(records), prediction.predicted_date, today) if prediction is not None
               else vehicle_segment(session, vehicle.id, today))
    return VehicleCard(
        id=vehicle.id,
        identifier_type=vehicle.identifier_type,
        identifier=vehicle.identifier,
        plate_normalized=vehicle.plate_normalized,
        vehicle_model=vehicle.vehicle_model,
        company=CompanyOut.model_validate(vehicle.company),
        service_count=len(history),
        segment=segment if records else None,
        usual_liters=None if liters is None else float(liters),
        last_service=history[0] if history else None,
        history=history,
        prediction=prediction,
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


def vehicles_by_fleet_no(session: Session, query: str) -> list[Vehicle]:
    """Fleet trucks whose number matches ignoring case and spaces (task 4.2b).

    Fleet numbers are unique only per company (D-005), so "HT-12" can return
    several trucks. Compared in Python (see src/api/matching.py).
    """
    key = fleet_no_key(query)
    fleet = session.scalars(
        select(Vehicle).where(Vehicle.identifier_type == "fleet_no").order_by(Vehicle.id)
    ).all()
    return [vehicle for vehicle in fleet if fleet_no_key(vehicle.identifier) == key]


@router.get("/lookup", response_model=LookupResult)
def lookup(
    session: SessionDep,
    today: TodayDep,
    predictor: PredictorDep,
    q: Annotated[str, Query(min_length=1, description="Plate or fleet number (any spacing/case) or 8-digit phone")],
) -> LookupResult:
    """Find vehicles by plate, fleet number or driver phone.

    If ``q`` is a valid phone (8 digits, +976 optional) it is searched as a
    phone. Otherwise it is searched as a plate AND as a fleet number (the
    oil changer does not have to say which): plate matches come first.
    match_type is "fleet_no" only when every match is a fleet number; with no
    match it stays "plate". Plates never consist of digits only, so a plate
    and a phone cannot be confused. No match -> 200 with an empty list (the
    app then opens the new-vehicle form), not 404: an empty search is normal.
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
        by_plate = vehicles_by_plate(session, plate)
        by_fleet_no = vehicles_by_fleet_no(session, q)
        vehicles = [*by_plate, *by_fleet_no]
        match_type = "fleet_no" if by_fleet_no and not by_plate else "plate"
        normalized = fleet_no_key(q) if match_type == "fleet_no" else plate

    return LookupResult(
        query=q,
        match_type=match_type,
        normalized=normalized,
        vehicles=[build_card(session, vehicle, today, predictor) for vehicle in vehicles],
    )


def search_rows(session: Session, query: str, today: date, predictor: Predictor | None) -> list[VehicleRow]:
    """Every truck matching ``query`` (blank = all), newest service first (task 9.1).

    Matching is done in Python (src/api/matching.py, D-043: Cyrillic casefold does not depend on
    the database locale). Read only: one query for vehicles + companies, one for all services
    (records_as_of, the same rows GET /stats/segments reads), predictions in one Ridge call.
    """
    vehicles = session.scalars(select(Vehicle).options(selectinload(Vehicle.company))).all()
    records = records_as_of(session, today)  # {vehicle_id: services oldest first}
    rows: list[tuple[Vehicle, list[str]]] = []
    for vehicle in vehicles:
        own = records.get(vehicle.id, [])
        phones = {r.driver_phone for r in own if r.driver_phone}
        matched = search_matches(query, vehicle.identifier_type, vehicle.identifier, vehicle.plate_normalized,
                                 vehicle.company.name, phones)
        if matched or not query.strip():
            rows.append((vehicle, matched))

    histories = {v.id: [to_visit(r) for r in records[v.id]] for v, _ in rows if v.id in records}
    predictions = predictor.predict_many(histories, today) if predictor is not None else {}
    out = []
    for vehicle, matched in rows:
        own = records.get(vehicle.id, [])
        prediction = predictions.get(vehicle.id)
        out.append(VehicleRow(
            id=vehicle.id,
            identifier_type=vehicle.identifier_type,
            identifier=vehicle.identifier,
            vehicle_model=vehicle.vehicle_model,
            company=CompanyOut.model_validate(vehicle.company),
            service_count=len(own),
            last_service=ServiceOut.model_validate(own[-1]) if own else None,
            segment=segment_of(len(own), prediction.predicted_date if prediction else None, today) if own else None,
            status=prediction.status if prediction else None,
            days_left=prediction.days_left if prediction else None,
            matched_on=matched,
        ))
    # Newest service first; trucks without a service last; id keeps the order stable.
    out.sort(key=lambda row: (row.last_service is not None,
                              row.last_service.service_date if row.last_service else date.min, row.id), reverse=True)
    return out


@router.get("/search", response_model=VehicleSearch)
def search(
    session: SessionDep,
    today: TodayDep,
    predictor: PredictorDep,
    q: Annotated[str, Query(max_length=100, description="Plate, fleet number, company or phone — any part. "
                                                        "Blank = every truck")] = "",
    limit: Annotated[int, Query(ge=1, le=1000, description="Rows returned (total counts all matches)")] = 200,
) -> VehicleSearch:
    """Dashboard search (task 9.1): trucks whose plate, fleet number, company or any driver phone
    CONTAINS ``q``. Read only. Unlike /lookup (one exact truck for the oil changer) this is for
    browsing the database. Declared before /{vehicle_id} so "search" is not read as an id.
    """
    rows = search_rows(session, q, today, predictor)
    return VehicleSearch(query=q, total=len(rows), vehicles=rows[:limit])


@router.get("/{vehicle_id}", response_model=VehicleCard)
def get_vehicle(vehicle_id: int, session: SessionDep, today: TodayDep, predictor: PredictorDep) -> VehicleCard:
    """The vehicle card. 404 if the id does not exist."""
    vehicle = session.get(Vehicle, vehicle_id)
    if vehicle is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"vehicle {vehicle_id} not found")
    return build_card(session, vehicle, today, predictor)


@router.get("/{vehicle_id}/prediction", response_model=PredictionOut)
def get_prediction(vehicle_id: int, session: SessionDep, today: TodayDep, predictor: PredictorDep) -> PredictionOut:
    """Next oil change after the vehicle's newest service.

    404 unknown vehicle or no service yet; 503 if the model files were not loaded.
    """
    if predictor is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "prediction model not loaded")
    if session.get(Vehicle, vehicle_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"vehicle {vehicle_id} not found")
    result = predict(predictor, vehicle_id, service_records(session, vehicle_id), today)
    if result is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"vehicle {vehicle_id} has no service yet")
    return result
