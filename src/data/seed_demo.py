"""Demo database (task 4.5): ~40 synthetic trucks that show every feature TODAY.

Histories come from the synthetic generator (src/data/generator.py, same
config and seed as training): each demo truck takes the first 1–5 services of
one generated truck (real-looking intervals and odometer readings). Then all
of a truck's dates are shifted by the same number of days, so that the
SERVED model (models/, the same Predictor the API uses) puts its next oil
change where the plan below wants it, counted from today. That gives, as of
today: every status (ok / due_soon / overdue), every segment (new /
returning / loyal / at_risk) and 5–10 trucks on the due-reminder list.

Nothing is real (RISK-06): plates are random in the real format (4 digits +
3 letters of plates.PLATE_LETTERS), companies are "Демо …", phones are
0000xxxx (no Mongolian number starts with 0000), driver names are the
generator's fake names. Oil grade and liters are demo values, not facts.

The dates are relative to the seed day, so the demo slowly goes stale:
re-seed on the demo day (docs/demo_data.md).

Run on an EMPTY database (schema.sql + migrations 001–005), model files in models/:
    POSTGRES_PASSWORD=oil_dev_password python -m src.data.seed_demo [--as-of 2026-10-20]
The script refuses to write into a database that already has companies,
vehicles or service records (it must never mix with real data).
"""

from __future__ import annotations

import argparse
from collections import Counter
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import date, datetime, time, timedelta
from decimal import Decimal
from pathlib import Path

import numpy as np
import pandas as pd
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.api.clock import ULAANBAATAR, today_ulaanbaatar
from src.api.config import Contact, load_settings, model_dir, oil_interval_km, reminder_contact
from src.api.db import create_db_engine
from src.api.models import Company, Destination, ReminderSent, ServiceRecord, Vehicle
from src.api.prediction import Prediction, Predictor, Visit, load_predictor
from src.api.reminders import due_stage, message_mn, segment_of, stage_day, stage_reached
from src.common.plates import normalize_plate
from src.data.generator import DEFAULT_CONFIG, generate_clean, load_config

DEMO_SEED = 42  # fixed: same demo trucks on every run (only the dates follow today)
MAX_FIT_STEPS = 10  # date-shift iterations; 1–2 are normally enough
SCAN_DAYS = 15  # at a season edge: look this many days around for the closest fit

COMPANIES = ("Демо Тээвэр ХХК", "Демо Логистик ХХК", "Демо Карго ХХК", "Демо Транс ХХК",
             "Демо Хил Тээвэр ХХК", "Демо Экспресс ХХК")
OIL_GRADES = ("15W-40", "15W-40", "10W-40")  # demo values, not a fact about Geo-Expert
LITERS = (28.0, 30.0, 32.0, 36.0, 38.0, 40.0)  # demo values
OIL_CHANGER = "Демо ажилтан"
UB_CITY = "Ulaanbaatar city (local work)"
RAW_DESTINATION = "Сайншанд"  # typed by hand, not in the list -> destination_raw + route 'mixed'


@dataclass(frozen=True)
class Slot:
    """One demo truck as planned: how many services, and its next change counted from today.

    days_left = predicted date − today. D-007: ok > 14, due_soon 0–14, overdue < 0,
    at_risk < −7 (predicted date + 7 days grace has passed). Targets sit inside
    their bucket, away from the edges.
    """

    services: int
    days_left: int
    plate: str | None = None  # fixed plate for the trucks in docs/demo_data.md
    newest_destination: str | None = None  # replace the newest service's destination (B0 fallback demo)
    newest_raw: str | None = None  # newest service typed by hand (destination_raw)
    reminder_sent: bool = False  # store "reminder sent" (reminders_sent) -> not on the due list


# Documented in docs/demo_data.md (4 digits + 3 letters, like real plates).
PLATE_LOYAL = "1001УБА"
PLATE_OVERDUE = "1002УБЕ"
PLATE_NEW = "1003УНА"
PLATE_AT_RISK = "1004УБВ"

# Its current driver also drove PLATE_LOYAL's 2 oldest services (drivers change trucks, D-004).
SHARED_DRIVER_PLATE = PLATE_OVERDUE

PLAN: tuple[Slot, ...] = (
    # days_left = the model's predicted date − today (prediction statuses for the model API).
    # Since 9.5b the due list follows month stages (30 / 60 / 90 days after the latest service),
    # not this number: with ~35–60-day predicted intervals most trucks show 1m, a few 2m / 3m.
    # --- new: 1 service, first visit -> B1 (buffer 4 days)
    Slot(1, 10, plate=PLATE_NEW),             # due_soon, not due yet
    Slot(1, 20), Slot(1, 28), Slot(1, 24), Slot(1, 22), Slot(1, 25),  # ok
    Slot(1, 8),                               # due_soon, not due yet
    Slot(1, 0),                               # due_soon, on the due list
    # --- returning: 2 services -> Ridge (buffer 16 days)
    Slot(2, -4, plate=PLATE_OVERDUE),         # overdue, on the due list
    Slot(2, 20), Slot(2, 25), Slot(2, 29), Slot(2, 21), Slot(2, 27),  # ok
    Slot(2, 23), Slot(2, 19),                 # ok
    Slot(2, 3),                               # due_soon, on the due list
    # --- loyal: 3–5 services -> Ridge
    Slot(5, 26, plate=PLATE_LOYAL),           # ok; older services had another driver (phone lookup)
    Slot(3, 21), Slot(4, 24), Slot(5, 19), Slot(3, 22), Slot(4, 27),
    Slot(5, 20), Slot(3, 26), Slot(4, 22),    # ok
    Slot(2, 24), Slot(3, 20), Slot(5, 23),    # ok
    Slot(3, 10),                              # due_soon, on the due list
    Slot(4, 28), Slot(4, 25),                 # ok
    Slot(3, 5),                               # due_soon, on the due list
    Slot(4, -6),                              # overdue (not yet at risk), on the due list
    # --- at_risk (9.5b): 90+ days since the latest service, not back. Predicted intervals are
    # ~35–60 days, so days_left -45…-60 puts the latest service 90+ days ago.
    Slot(3, -50, plate=PLATE_AT_RISK, reminder_sent=True),  # 3m reminder sent, did not come back
    Slot(4, -60, reminder_sent=True),
    Slot(2, -50),                             # 3m on the due list
    Slot(1, -60),                             # 3m on the due list
    # --- B0 fallback (route not modelled / typed by hand), ok, buffer 13 days -> not due yet
    Slot(3, 25, newest_destination=UB_CITY),
    Slot(2, 22, newest_raw=RAW_DESTINATION),
)


def slot_method(slot: Slot) -> str:
    """Which predictor will answer for this slot (prediction.py rules): B0 fallbacks, B1 first visit, else Ridge."""
    if slot.newest_destination == UB_CITY or slot.newest_raw:
        return "b0"
    return "b1" if slot.services == 1 else "ridge"


@dataclass(frozen=True)
class DemoService:
    """One service record to insert (oldest first inside a truck)."""

    service_date: date
    odometer_km: int
    destination: str | None  # destinations.name; None when destination_raw is used
    destination_raw: str | None
    route: str
    oil_grade: str
    liters: float
    driver_name: str
    driver_phone: str


@dataclass(frozen=True)
class DemoTruck:
    """One demo vehicle with its services and what the model says about it on the seed day."""

    plate_normalized: str
    company: str
    services: tuple[DemoService, ...]
    reminder_sent: bool
    prediction: Prediction

    @property
    def identifier(self) -> str:
        """Plate as written on the truck, e.g. '1001 УБА'."""
        return f"{self.plate_normalized[:4]} {self.plate_normalized[4:]}"


# ---------------------------------------------------------------------------
# Build (pure: no database)
# ---------------------------------------------------------------------------

def phone_of(index: int) -> str:
    """Demo phone of truck ``index`` (0-based): 00000001, 00000002, ... never a real number."""
    return f"0000{index + 1:04d}"


def pick_histories(clean: pd.DataFrame, plan: Sequence[Slot], rng: np.random.Generator) -> list[pd.DataFrame]:
    """For every slot, the first ``services`` rows of a different generated truck (oldest first)."""
    sizes = clean.groupby("vehicle_id").size()
    used: set[int] = set()
    out = []
    for slot in plan:
        candidates = sorted(set(sizes[sizes >= slot.services].index) - used)
        vid = int(rng.choice(candidates))
        used.add(vid)
        rows = clean[clean["vehicle_id"] == vid].sort_values("service_date")
        out.append(rows.head(slot.services).reset_index(drop=True))
    return out


def to_visits(services: Sequence[DemoService]) -> list[Visit]:
    """Services -> the predictor's input (oldest first). Ids are placeholders: only the order matters."""
    return [Visit(id=i, service_date=s.service_date, odometer_km=s.odometer_km, route=s.route,
                  destination_id=None if s.destination is None else 0, destination_name=s.destination,
                  destination_raw=s.destination_raw) for i, s in enumerate(services)]


def shift(services: Sequence[DemoService], days: int) -> tuple[DemoService, ...]:
    """Move every service date by ``days`` (intervals between visits stay the same)."""
    return tuple(replace(s, service_date=s.service_date + timedelta(days=days)) for s in services)


def fit_dates(services: Sequence[DemoService], days_left: int, predictor: Predictor,
              today: date) -> tuple[tuple[DemoService, ...], Prediction]:
    """Shift the dates so the prediction lands ``days_left`` days after today.

    The prediction is counted from the newest service, so moving the newest
    date by n days moves the predicted date by n days. Only the season feature
    (season of the newest service) can change with the shift, hence a few
    repeats. Across a season edge the prediction jumps, so some targets cannot
    be hit exactly: then the closest date within ±SCAN_DAYS is taken. The
    newest service is never after today (a service cannot be in the future).
    """
    def predict(candidate: tuple[DemoService, ...]) -> Prediction:
        return predictor.predict(0, to_visits(candidate), today)

    services = shift(services, (today - services[-1].service_date).days)  # start: newest service = today
    prediction = predict(services)
    for _ in range(MAX_FIT_STEPS):
        move = min(days_left - prediction.days_left, (today - services[-1].service_date).days)
        if move == 0:
            break
        services = shift(services, move)
        prediction = predict(services)
    if prediction.days_left != days_left:  # season edge: take the closest reachable date
        room = (today - services[-1].service_date).days
        nearby = [shift(services, m) for m in range(-SCAN_DAYS, min(SCAN_DAYS, room) + 1)]
        services, prediction = min(((c, predict(c)) for c in nearby),
                                   key=lambda cp: abs(cp[1].days_left - days_left))
    return services, prediction


def demo_services(rows: pd.DataFrame, slot: Slot, grade: str, liters: float, driver: str,
                  phone: str) -> list[DemoService]:
    """Generated rows -> demo services (dates not fitted yet), with the slot's destination change."""
    services = [DemoService(service_date=r.service_date, odometer_km=int(r.odometer_km),
                            destination=r.destination_name, destination_raw=None, route=r.route,
                            oil_grade=grade, liters=liters, driver_name=driver, driver_phone=phone)
                for r in rows.itertuples()]
    if slot.newest_destination is not None:
        services[-1] = replace(services[-1], destination=slot.newest_destination, route="ub_city")
    if slot.newest_raw is not None:
        services[-1] = replace(services[-1], destination=None, destination_raw=slot.newest_raw, route="mixed")
    return services


def demo_plates(clean: pd.DataFrame, histories: Sequence[pd.DataFrame], plan: Sequence[Slot]) -> list[str]:
    """Fixed plate for documented slots, else the generated truck's (fake) plate; all different."""
    fixed = {s.plate for s in plan if s.plate}
    plates = [slot.plate or rows["plate_normalized"].iloc[0] for slot, rows in zip(plan, histories)]
    taken = set(fixed)
    spare = (p for p in clean["plate_normalized"].unique() if p not in taken and p not in plates)
    out = []
    for slot, plate in zip(plan, plates):
        if not slot.plate and plate in taken:  # generated plate equals a fixed one: take another
            plate = next(spare)
        taken.add(plate)
        out.append(plate)
    return out


def build_demo(clean: pd.DataFrame, predictor: Predictor, today: date,
               plan: Sequence[Slot] = PLAN, seed: int = DEMO_SEED) -> list[DemoTruck]:
    """All demo trucks, dates fitted to ``today`` with ``predictor``."""
    rng = np.random.default_rng(seed)
    histories = pick_histories(clean, plan, rng)
    plates = demo_plates(clean, histories, plan)
    trucks = []
    for i, (slot, rows, plate) in enumerate(zip(plan, histories, plates)):
        grade = str(rng.choice(OIL_GRADES))
        liters = float(rng.choice(LITERS))
        services = demo_services(rows, slot, grade, liters, rows["driver_name"].iloc[0], phone_of(i))
        services, prediction = fit_dates(services, slot.days_left, predictor, today)
        trucks.append(DemoTruck(plate_normalized=plate, company=COMPANIES[i % len(COMPANIES)],
                                services=services, reminder_sent=slot.reminder_sent, prediction=prediction))
    return share_driver(trucks)


def share_driver(trucks: list[DemoTruck]) -> list[DemoTruck]:
    """D-004 demo: the 2 oldest services of PLATE_LOYAL were driven by the current driver of
    SHARED_DRIVER_PLATE, so looking up that phone finds both trucks."""
    loyal = next(i for i, t in enumerate(trucks) if t.plate_normalized == PLATE_LOYAL)
    other = next(t for t in trucks if t.plate_normalized == SHARED_DRIVER_PLATE).services[-1]
    old = tuple(replace(s, driver_name=other.driver_name, driver_phone=other.driver_phone)
                for s in trucks[loyal].services[:2])
    trucks[loyal] = replace(trucks[loyal], services=old + trucks[loyal].services[2:])
    return trucks


# ---------------------------------------------------------------------------
# What the demo shows
# ---------------------------------------------------------------------------

def segment(truck: DemoTruck, today: date) -> str:
    """Segment, the same rule as GET /stats/segments (9.5b: at_risk = 90+ days since the latest service)."""
    return segment_of(len(truck.services), truck.services[-1].service_date, today)


def sent_stage(truck: DemoTruck, today: date) -> str | None:
    """9.5b: a 'reminder_sent' truck has its highest stage reached marked sent (None before day 30)."""
    return stage_reached(truck.services[-1].service_date, today) if truck.reminder_sent else None


def is_due(truck: DemoTruck, predictor: Predictor, today: date) -> bool:
    """On GET /reminders/due (9.5b): a month stage is reached and not marked sent (demo trucks all
    have an odometer and no stopped phone). ``predictor`` is unused since 9.5b (kept for callers)."""
    sent = {sent_stage(truck, today)} - {None}
    return due_stage(truck.services[-1].service_date, today, sent) is not None


def due_stage_of(truck: DemoTruck, today: date) -> str | None:
    """The month stage this truck shows on GET /reminders/due today (9.5b), or None."""
    return due_stage(truck.services[-1].service_date, today, {sent_stage(truck, today)} - {None})


def summary(trucks: Sequence[DemoTruck], predictor: Predictor, today: date) -> dict[str, Counter | int]:
    """Counts the acceptance check needs: segments, statuses, methods, due list size + its stages."""
    return {
        "segments": Counter(segment(t, today) for t in trucks),
        "statuses": Counter(t.prediction.status for t in trucks),
        "methods": Counter(t.prediction.method for t in trucks),
        "due": sum(is_due(t, predictor, today) for t in trucks),
        "stages": Counter(s for s in (due_stage_of(t, today) for t in trucks) if s),
    }


def problems(summary_: dict) -> list[str]:
    """What is missing for the demo (empty list = all good): every segment, every prediction status
    (model API), and since 9.5b every month stage on the due list (was: 5–10 due trucks)."""
    out = [f"segment {s} is empty" for s in ("new", "returning", "loyal", "at_risk") if not summary_["segments"][s]]
    out += [f"status {s} is empty" for s in ("ok", "due_soon", "overdue") if not summary_["statuses"][s]]
    out += [f"no {s} reminder on the due list" for s in ("1m", "2m", "3m") if not summary_["stages"][s]]
    return out


# ---------------------------------------------------------------------------
# Database
# ---------------------------------------------------------------------------

def database_is_empty(session: Session) -> bool:
    """True if there are no companies, vehicles or service records."""
    return all(session.scalar(select(func.count()).select_from(table)) == 0
               for table in (Company, Vehicle, ServiceRecord))


def insert_demo(session: Session, trucks: Sequence[DemoTruck], predictor: Predictor, contact: Contact) -> None:
    """Write the demo trucks (+ the 'reminder sent' rows) in the caller's transaction.

    Raises RuntimeError if the database is not empty or a destination is missing.
    """
    if not database_is_empty(session):
        raise RuntimeError("database is not empty: the demo seed only runs on an empty database "
                           "(docker compose down -v && docker compose up -d)")
    destinations = {d.name: d.id for d in session.scalars(select(Destination))}
    needed = {s.destination for t in trucks for s in t.services if s.destination}
    if needed - destinations.keys():
        raise RuntimeError(f"destinations missing (run migration 001): {sorted(needed - destinations.keys())}")

    companies = {name: Company(name=name) for name in sorted({t.company for t in trucks})}
    session.add_all(companies.values())
    for truck in trucks:
        vehicle = Vehicle(company=companies[truck.company], identifier_type="plate", identifier=truck.identifier,
                          plate_normalized=normalize_plate(truck.identifier))
        records = [ServiceRecord(vehicle=vehicle, service_date=s.service_date, odometer_km=s.odometer_km,
                                 oil_grade=s.oil_grade, liters=Decimal(str(s.liters)), route=s.route,
                                 destination_id=destinations.get(s.destination) if s.destination else None,
                                 destination_raw=s.destination_raw, driver_name=s.driver_name,
                                 driver_phone=s.driver_phone, oil_changer=OIL_CHANGER)
                   for s in truck.services]
        session.add_all([vehicle, *records])
        stage = sent_stage(truck, truck.prediction.today)  # the seed day
        if stage is not None:
            session.flush()  # ids for the reminder row
            session.add(sent_reminder(vehicle, records[-1], stage, contact))
    session.flush()


def sent_reminder(vehicle: Vehicle, newest: ServiceRecord, stage: str, contact: Contact) -> ReminderSent:
    """The row POST /reminders/{id}/sent?stage= would have stored on the stage day (10:00 UB), 9.5b."""
    send_on = stage_day(newest.service_date, stage)
    return ReminderSent(vehicle_id=vehicle.id, service_id=newest.id, stage=stage, phone=newest.driver_phone,
                        message_text=message_mn(stage, vehicle.identifier, newest.service_date, newest.oil_grade,
                                                newest.odometer_km + oil_interval_km(), contact),
                        send_on=send_on, sent_at=datetime.combine(send_on, time(10, 0), tzinfo=ULAANBAATAR))


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def print_summary(trucks: Sequence[DemoTruck], predictor: Predictor, today: date) -> None:
    """Counts + the documented plates, for the terminal."""
    s = summary(trucks, predictor, today)
    print(f"as of {today}: {len(trucks)} trucks, {sum(len(t.services) for t in trucks)} services")
    for key in ("segments", "statuses", "methods"):
        print(f"  {key}: {dict(sorted(s[key].items()))}")
    print(f"  due reminders: {s['due']} {dict(sorted(s['stages'].items()))}")
    for plate in (PLATE_LOYAL, PLATE_OVERDUE, PLATE_NEW, PLATE_AT_RISK):
        t = next(t for t in trucks if t.plate_normalized == plate)
        print(f"  {t.identifier}: {segment(t, today)}, {t.prediction.status}, {t.prediction.method}, "
              f"days_left {t.prediction.days_left}")


def main(argv: list[str] | None = None) -> int:
    """Build the demo from the generator + served model and write it to the database."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--as-of", type=date.fromisoformat, default=None,
                        help="day the demo is built for (default: today in Ulaanbaatar)")
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG, help="generator config")
    args = parser.parse_args(argv)

    today = args.as_of or today_ulaanbaatar()
    predictor = load_predictor(model_dir())
    trucks = build_demo(generate_clean(load_config(args.config)), predictor, today)
    print_summary(trucks, predictor, today)
    missing = problems(summary(trucks, predictor, today))
    if missing:
        print("NOT seeded:", "; ".join(missing))
        return 1

    engine = create_db_engine(load_settings().database_url)
    try:
        with Session(engine) as session, session.begin():  # one transaction: all or nothing
            insert_demo(session, trucks, predictor, reminder_contact())
    except RuntimeError as exc:
        print(f"NOT seeded: {exc}")
        return 1
    finally:
        engine.dispose()
    print("seeded. Try the plates in docs/demo_data.md")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
