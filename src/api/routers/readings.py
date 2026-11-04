"""Driver meter readings (task 9.14a): the driver's current km, typed in by the oil changer.

POST   /vehicles/{vehicle_id}/readings           {value, reading_date?}  store one (source 'manual')
POST   /vehicles/{vehicle_id}/readings/preview   same body: what it WOULD give, nothing stored (9.14a-3:
                                                 the UI's confirm step; the UI has no copy of the rules)
DELETE /readings/{reading_id}                                            remove a manual / Messenger one
                                                                         (a typo, «Буцаах»)

A reading counts from the truck's LATEST service and must be after it (not on the same day) and not
in the future. It is stored even when it cannot be used (status 'flagged' + flag_reason, PM 9.14a:
not lower than the last odometer, 20-1200 km/day), so the oil changer sees why; the pace only uses
'ok' readings (src/api/pace.py). The answer carries the truck's new pace and reminder day.
Task 9.15a: the Messenger bot saves through the SAME store_reading() (source 'messenger'); a plate
mismatch is stored flagged 'plate_mismatch' even when the number itself is plausible.
Mine trucks (engine hours only): the value is engine hours (hours per day is shown, no reminder).
"""

from datetime import date
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from sqlalchemy.orm import Session

from src.api.clock import get_today
from src.api.config import ReminderRules
from src.api.db import get_session
from src.api.history import driver_readings, meter, pace_out, schedule_of, service_records
from src.api.models import OdometerReading, ServiceRecord, Vehicle
from src.api.pace import Flag, Reading, new_reading_flag, rate
from src.api.routers.reminders import RulesDep
from src.api.schemas import ReadingIn, ReadingOut, ReadingPreview, ReadingSaved

router = APIRouter(tags=["readings"])

SessionDep = Annotated[Session, Depends(get_session)]
TodayDep = Annotated[date, Depends(get_today)]

DRIVER_SOURCE_TYPES = ("manual", "messenger")  # the sources DELETE may remove (never 'service')


def unprocessable(message: str) -> HTTPException:
    return HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, message)


def new_reading(session: Session, vehicle_id: int, body: ReadingIn, today: date, source: str = "manual",
                flag: Flag | str | None = None) -> tuple[list[ServiceRecord], OdometerReading]:
    """The checked, NOT yet stored reading + the truck's services (newest first). Raises 404 / 422.
    ``flag`` (9.15a: 'plate_mismatch') flags it whatever the number says."""
    if session.get(Vehicle, vehicle_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"vehicle {vehicle_id} not found")
    records = service_records(session, vehicle_id)  # newest first
    if not records:
        raise unprocessable("the truck has no service yet: a reading counts from its latest service")
    latest = records[0]
    day = body.reading_date or today
    if day > today:
        raise unprocessable(f"reading_date {day} is in the future (today is {today})")
    if day <= latest.service_date:
        raise unprocessable(f"reading_date must be after the latest service ({latest.service_date})")
    unit, service = meter(latest)
    earlier = [Reading(r.reading_date, float(r.value))
               for r in driver_readings(session, [vehicle_id]).get(vehicle_id, [])
               if r.unit == unit and r.reading_date > latest.service_date]
    new = Reading(day, float(body.value))
    flag = flag or new_reading_flag(unit, service, earlier, new)
    per_day = rate(service, new)
    row = OdometerReading(vehicle_id=vehicle_id, service_id=latest.id, unit=unit, value=body.value, reading_date=day,
                          source=source, status="ok" if flag is None else "flagged", flag_reason=flag,
                          rate_per_day=None if per_day is None else round(per_day, 1))
    return list(records), row


def store_reading(session: Session, vehicle_id: int, body: ReadingIn, today: date, rules: ReminderRules,
                  source: str = "manual", flag: Flag | str | None = None) -> ReadingSaved:
    """Check, store and commit one driver reading; the answer has the truck's pace after it.
    The ONE save path of the form (manual) and the Messenger bot (messenger). Raises 404 / 422."""
    records, row = new_reading(session, vehicle_id, body, today, source, flag)
    session.add(row)
    session.commit()
    session.refresh(row)
    plan = schedule_of(list(reversed(records)), driver_readings(session, [vehicle_id]).get(vehicle_id, []), rules)
    return ReadingSaved(reading=ReadingOut.model_validate(row), pace=pace_out(plan))


@router.post("/vehicles/{vehicle_id}/readings", response_model=ReadingSaved, status_code=status.HTTP_201_CREATED)
def add_reading(vehicle_id: int, body: ReadingIn, session: SessionDep, today: TodayDep,
                rules: RulesDep) -> ReadingSaved:
    """Store the driver's reading. 404 unknown truck · 422 no service yet, a day in the future, or a
    day not after the latest service. A reading that cannot be used is stored as 'flagged' (201)."""
    return store_reading(session, vehicle_id, body, today, rules)


@router.post("/vehicles/{vehicle_id}/readings/preview", response_model=ReadingPreview)
def preview_reading(vehicle_id: int, body: ReadingIn, session: SessionDep, today: TodayDep,
                    rules: RulesDep) -> ReadingPreview:
    """What POST /vehicles/{id}/readings WOULD store and the pace it WOULD give; nothing is stored.
    Same 404 / 422 as the real one."""
    records, row = new_reading(session, vehicle_id, body, today)
    usable = driver_readings(session, [vehicle_id]).get(vehicle_id, []) + ([row] if row.status == "ok" else [])
    plan = schedule_of(list(reversed(records)), usable, rules)
    return ReadingPreview(unit=row.unit, value=float(row.value), reading_date=row.reading_date, status=row.status,
                          flag_reason=row.flag_reason,
                          rate_per_day=None if row.rate_per_day is None else float(row.rate_per_day),
                          pace=pace_out(plan))


@router.delete("/readings/{reading_id}", status_code=status.HTTP_204_NO_CONTENT)
def remove_reading(reading_id: int, session: SessionDep) -> Response:
    """Remove a driver reading (PM 9.14a-2 #6: undo a typo; 9.15a / RISK-34: also a Messenger one).
    404 unknown · 422 a 'service' reading (a service's own odometer is part of the service)."""
    row = session.get(OdometerReading, reading_id)
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, f"reading {reading_id} not found")
    if row.source not in DRIVER_SOURCE_TYPES:
        raise unprocessable("only driver readings (source manual or messenger) can be removed")
    session.delete(row)
    session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
