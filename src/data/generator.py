"""Synthetic service-history generator (Task 1.3).

Builds oil change histories for road trucks from the rules in
docs/synthetic_rules.md, with every number read from configs/generator.yaml
(each one tagged [SOURCE] or [ESTIMATE]).

How one vehicle is simulated:
1. Draw the vehicle once: speed (km/h) and driving hours/day from their ranges,
   its own chance of being late (V5), its home destination (V7).
2. After each service, draw the outcome (D-031): on time / late / never returns.
3. Drive round trips until the oil change is due:
   driving days = round-trip km ÷ (speed × hours), ÷ season factor (V3),
   × per-trip noise (V2), + waiting days. Next trip: same destination with
   probability 0.7, else a new one from the mix (V6).
   - on time: due when km since the service reaches a value in 15k–20k (D-030)
   - late:    due when km passes 20k, plus exponential extra days (max 60)
4. The next service happens on that day; its odometer = km driven so far.

Outputs in data/synthetic/ (git-ignored):
- service_records_clean.csv: truth, incl. target ``days_to_next_change``
- service_records_dirty.csv: same records after noise rules N1–N12, no truth
- noise_log.csv: which noise rule touched which record (for testing cleaning.py)
and docs/synthetic_report.md (+ charts in docs/figures/).

Not used on purpose (D-034): vehicle model, oil grade.

Run:  python -m src.data.generator [--config configs/generator.yaml]
"""

from __future__ import annotations

import argparse
import math
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
import yaml

from src.common.plates import LATIN_TO_CYRILLIC, PLATE_LETTERS

DEFAULT_CONFIG = Path("configs/generator.yaml")

CLEAN_FILE = "service_records_clean.csv"
DIRTY_FILE = "service_records_dirty.csv"
NOISE_LOG_FILE = "noise_log.csv"

# Keys that mark a dict as one parameter (it must then carry a `tag`).
_PARAM_KEYS = {"value", "min", "max", "one_way_km"}
# Groups of values that share one tag.
_TAGGED_GROUPS = (("variation", "season_factor"), ("destination_variants",))

SEASON_BY_MONTH = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}

# Fake people for synthetic rows (not taken from real records).
FAKE_GIVEN_NAMES = ("Бат", "Болд", "Дорж", "Ганбаатар", "Энхбаяр", "Төмөр", "Сүхбаатар", "Мөнх", "Оюун", "Наран")
FAKE_INITIALS = "БГДМНОСТЭ"

# Cyrillic plate letter -> Latin look-alike (N6). "U" is excluded: it is not a look-alike.
CYRILLIC_TO_LATIN = {cyr: lat for lat, cyr in LATIN_TO_CYRILLIC.items() if lat != "U"}


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def untagged_params(node: Any, path: str = "") -> list[str]:
    """Return the paths of parameters in the config that have no `tag`."""
    missing: list[str] = []
    if isinstance(node, dict):
        if _PARAM_KEYS & node.keys() and "tag" not in node:
            missing.append(path)
        for key, child in node.items():
            missing += untagged_params(child, f"{path}.{key}" if path else str(key))
    elif isinstance(node, list):
        for i, child in enumerate(node):
            missing += untagged_params(child, f"{path}[{i}]")
    return missing


def validate_config(cfg: dict) -> None:
    """Raise ValueError if a parameter is untagged or a value is impossible."""
    missing = untagged_params(cfg)
    for group in _TAGGED_GROUPS:
        node = cfg
        for key in group:
            node = node[key]
        if "tag" not in node:
            missing.append(".".join(group))
    if missing:
        raise ValueError(f"parameters without [SOURCE]/[ESTIMATE] tag: {missing}")

    shares = cfg["return_behavior"]
    total = sum(value(shares[k]) for k in ("on_time_share", "late_share", "never_share"))
    if not math.isclose(total, 1.0, abs_tol=1e-9):
        raise ValueError(f"return shares must sum to 1, got {total}")
    if value(cfg["destination_mix"]) != "equal":
        raise ValueError("only destination_mix: equal is implemented")
    if value(cfg["interval"]["shape"]) != "uniform":
        raise ValueError("only interval shape: uniform is implemented")
    if value(cfg["interval"]["min_km"]) > value(cfg["interval"]["max_km"]):
        raise ValueError("interval min_km > max_km")
    for name, node in cfg["trip"].items():
        if "min" in node and node["min"] > node["max"]:
            raise ValueError(f"trip.{name}: min > max")


def load_config(path: Path) -> dict:
    """Read the YAML config and check it (tags, shares, ranges)."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    validate_config(cfg)
    return cfg


def value(node: dict) -> Any:
    """The single value of a tagged parameter."""
    return node["value"]


def midpoint(node: dict) -> float:
    """Middle of a tagged min/max range."""
    return (node["min"] + node["max"]) / 2


def draw_uniform(rng: np.random.Generator, node: dict) -> float:
    """One draw, uniform inside a tagged min/max range."""
    return float(rng.uniform(node["min"], node["max"]))


# ---------------------------------------------------------------------------
# Trip model
# ---------------------------------------------------------------------------

def driving_days(round_trip_km: float, speed_kmh: float, hours_per_day: float) -> float:
    """Days spent driving one round trip: km ÷ (speed × hours) (task 1.3 brief)."""
    return round_trip_km / (speed_kmh * hours_per_day)


def season_of(day: date) -> str:
    """Season name for a date (winter = Dec–Feb, synthetic_rules V3)."""
    return SEASON_BY_MONTH[day.month]


@dataclass(frozen=True)
class Vehicle:
    """Fixed properties of one synthetic truck, drawn once."""

    vehicle_id: int
    speed_kmh: float
    hours_per_day: float
    late_prob: float  # chance of being late, GIVEN the truck comes back (V5)
    home_dest: int  # index into cfg["destinations"] (V7)
    first_day: int  # day offset of the first service from start_date
    start_odometer: int


@dataclass(frozen=True)
class Trip:
    """One round trip UB -> destination -> UB. Times are day offsets."""

    dest: int
    start: float
    end: float
    km: float


@dataclass(frozen=True)
class Interval:
    """What happens between one service and the next."""

    outcome: str  # "on_time", "late" or "never"
    end: float | None  # day offset when the next service happens (None: never)
    km: float | None  # km driven until then
    next_dest: int  # destination stated at the next service


def late_given_return(cfg: dict) -> float:
    """Fleet chance of being late among visits that do come back (0.40 / 0.90)."""
    shares = cfg["return_behavior"]
    return value(shares["late_share"]) / (value(shares["on_time_share"]) + value(shares["late_share"]))


def draw_vehicle(rng: np.random.Generator, cfg: dict, vehicle_id: int) -> Vehicle:
    """Draw one vehicle. With variation off, every vehicle gets the middle values (D-038)."""
    trip, fleet, var = cfg["trip"], cfg["fleet"], cfg["variation"]
    fleet_late = late_given_return(cfg)
    if value(var["enabled"]):
        speed = draw_uniform(rng, trip["speed_kmh"])
        hours = draw_uniform(rng, trip["driving_hours_per_day"])
        conc = value(var["lateness_beta_concentration"])
        late_prob = float(rng.beta(fleet_late * conc, (1 - fleet_late) * conc))
    else:
        speed = midpoint(trip["speed_kmh"])
        hours = midpoint(trip["driving_hours_per_day"])
        late_prob = fleet_late
    odo = fleet["start_odometer_km"]
    return Vehicle(
        vehicle_id=vehicle_id,
        speed_kmh=speed,
        hours_per_day=hours,
        late_prob=late_prob,
        home_dest=int(rng.integers(len(cfg["destinations"]))),
        first_day=int(rng.integers(value(fleet["first_service_spread_days"]))),
        start_odometer=int(rng.integers(odo["min"], odo["max"] + 1)),
    )


def draw_trip(rng: np.random.Generator, cfg: dict, vehicle: Vehicle, dest: int, start: float, start_date: date) -> Trip:
    """Draw one round trip starting at day offset `start`."""
    trip_cfg, var = cfg["trip"], cfg["variation"]
    km = value(trip_cfg["round_trip_factor"]) * cfg["destinations"][dest]["one_way_km"]
    days = driving_days(km, vehicle.speed_kmh, vehicle.hours_per_day)
    season = season_of(start_date + timedelta(days=int(start)))
    days /= var["season_factor"][season]
    if value(var["enabled"]):
        clip = var["trip_noise_clip"]
        days *= float(np.clip(rng.normal(1.0, value(var["trip_noise_sd"])), clip["min"], clip["max"]))
    days += draw_uniform(rng, trip_cfg["waiting_days_per_trip"])
    return Trip(dest=dest, start=start, end=start + days, km=km)


def next_destination(rng: np.random.Generator, cfg: dict, current: int) -> int:
    """Destination of the next trip (V6): same with prob 0.7, else drawn from the equal mix."""
    var = cfg["variation"]
    if not value(var["enabled"]) or rng.random() < value(var["same_destination_prob"]):
        return current
    return int(rng.integers(len(cfg["destinations"])))


def draw_outcome(rng: np.random.Generator, cfg: dict, late_prob: float) -> str:
    """On time / late / never for one visit (D-031, drawn per visit)."""
    if rng.random() < value(cfg["return_behavior"]["never_share"]):
        return "never"
    return "late" if rng.random() < late_prob else "on_time"


def simulate_interval(
    rng: np.random.Generator, cfg: dict, vehicle: Vehicle, start: float, dest: int, start_date: date
) -> Interval:
    """Drive trips from one service until the next one is due.

    Within a trip, km grow linearly with time, so the moment the due km is
    reached is interpolated inside the trip.
    """
    outcome = draw_outcome(rng, cfg, vehicle.late_prob)
    if outcome == "never":
        return Interval("never", None, None, dest)

    interval = cfg["interval"]
    target_km = draw_uniform(rng, {"min": value(interval["min_km"]), "max": value(interval["max_km"])}) \
        if outcome == "on_time" else float(value(interval["max_km"]))

    driven = 0.0  # km of finished trips
    trip = draw_trip(rng, cfg, vehicle, dest, start, start_date)
    while driven + trip.km < target_km:
        driven += trip.km
        trip = draw_trip(rng, cfg, vehicle, next_destination(rng, cfg, trip.dest), trip.end, start_date)
    due = trip.start + (trip.end - trip.start) * (target_km - driven) / trip.km

    if outcome == "on_time":
        return Interval("on_time", due, target_km, next_destination(rng, cfg, trip.dest))

    late = cfg["lateness"]
    extra_days = float(rng.exponential(value(late["extra_days_mean"])))
    if extra_days > value(late["max_days"]):
        return Interval("never", None, None, dest)  # too late counts as never returns (§4)
    moment = due + extra_days
    while trip.end < moment:  # keep driving during the late days
        driven += trip.km
        trip = draw_trip(rng, cfg, vehicle, next_destination(rng, cfg, trip.dest), trip.end, start_date)
    km = driven + trip.km * (moment - trip.start) / (trip.end - trip.start)
    return Interval("late", moment, km, next_destination(rng, cfg, trip.dest))


def simulate_vehicle(rng: np.random.Generator, cfg: dict, vehicle: Vehicle, start_date: date, end_day: int) -> list[dict]:
    """All service records of one vehicle until it never returns or the window ends."""
    rows: list[dict] = []
    day, odometer, dest = vehicle.first_day, vehicle.start_odometer, vehicle.home_dest
    while True:
        row = {"vehicle_id": vehicle.vehicle_id, "service_day": day, "odometer_km": odometer, "dest": dest,
               "days_to_next_change": np.nan, "km_to_next_change": np.nan}
        rows.append(row)
        iv = simulate_interval(rng, cfg, vehicle, float(day), dest, start_date)
        if iv.outcome == "never":
            row["next_outcome"] = "never"
            return rows
        next_day = max(math.floor(iv.end), day + 1)
        if next_day > end_day:
            row["next_outcome"] = "censored"  # next visit falls after the observed window
            return rows
        km = round(iv.km)
        row.update(next_outcome=iv.outcome, days_to_next_change=next_day - day, km_to_next_change=km)
        day, odometer, dest = next_day, odometer + km, iv.next_dest


# ---------------------------------------------------------------------------
# Fake identities
# ---------------------------------------------------------------------------

def make_plate(rng: np.random.Generator) -> str:
    """Fake normalized plate: 4 digits + 3 letters seen on real plates (plates.py)."""
    letters = sorted(PLATE_LETTERS)
    digits = "".join(str(d) for d in rng.integers(0, 10, size=4))
    return digits + "".join(letters[i] for i in rng.integers(0, len(letters), size=3))


def make_phone(rng: np.random.Generator) -> str:
    """Fake 8-digit phone (D-019 format); first digit 8 or 9."""
    return str(rng.choice(["8", "9"])) + "".join(str(d) for d in rng.integers(0, 10, size=7))


def make_driver_name(rng: np.random.Generator) -> str:
    """Fake driver name, e.g. 'Б. Болд'."""
    return f"{FAKE_INITIALS[rng.integers(len(FAKE_INITIALS))]}. {FAKE_GIVEN_NAMES[rng.integers(len(FAKE_GIVEN_NAMES))]}"


def draw_identities(rng: np.random.Generator, n_vehicles: int) -> pd.DataFrame:
    """One plate, company, driver and phone per vehicle (all fake, plates unique)."""
    plates: list[str] = []
    seen: set[str] = set()
    while len(plates) < n_vehicles:
        plate = make_plate(rng)
        if plate not in seen:
            seen.add(plate)
            plates.append(plate)
    n_companies = max(1, n_vehicles // 4)
    return pd.DataFrame({
        "vehicle_id": np.arange(1, n_vehicles + 1),
        "plate_normalized": plates,
        "company_name": [f"Жишээ Тээвэр {k + 1:03d} ХХК" for k in rng.integers(0, n_companies, size=n_vehicles)],
        "driver_name": [make_driver_name(rng) for _ in range(n_vehicles)],
        "driver_phone": [make_phone(rng) for _ in range(n_vehicles)],
    })


# ---------------------------------------------------------------------------
# Clean dataset
# ---------------------------------------------------------------------------

def generate_clean(cfg: dict) -> pd.DataFrame:
    """Simulate the whole fleet -> one row per service record, with truth columns."""
    seed = cfg["seed"]
    rng = np.random.default_rng(seed)
    fleet = cfg["fleet"]
    start_date = date.fromisoformat(value(fleet["start_date"]))
    end_day = (date.fromisoformat(value(fleet["end_date"])) - start_date).days

    vehicles = [draw_vehicle(rng, cfg, i + 1) for i in range(value(fleet["n_vehicles"]))]
    rows = [row for v in vehicles for row in simulate_vehicle(rng, cfg, v, start_date, end_day)]
    df = pd.DataFrame(rows)

    dests = pd.DataFrame(cfg["destinations"]).reset_index(names="dest")
    df = df.merge(dests[["dest", "name", "route_category", "one_way_km"]], on="dest", how="left")
    df = df.rename(columns={"name": "destination_name", "route_category": "route"})

    veh = pd.DataFrame([vars(v) for v in vehicles])[["vehicle_id", "speed_kmh", "hours_per_day", "late_prob"]]
    df = df.merge(veh.add_prefix("veh_").rename(columns={"veh_vehicle_id": "vehicle_id"}), on="vehicle_id")
    # Separate random stream: changing identities never changes the simulated histories.
    df = df.merge(draw_identities(np.random.default_rng([seed, 1]), len(vehicles)), on="vehicle_id")

    df["service_date"] = [start_date + timedelta(days=int(d)) for d in df["service_day"]]
    df["created_at"] = df["service_date"]
    df["season"] = [season_of(d) for d in df["service_date"]]
    df = df.sort_values(["service_date", "vehicle_id"], kind="stable").reset_index(drop=True)
    df.insert(0, "record_id", np.arange(1, len(df) + 1))
    columns = [
        "record_id", "vehicle_id", "company_name", "plate_normalized", "service_date", "created_at",
        "odometer_km", "destination_name", "route", "one_way_km", "driver_name", "driver_phone", "season",
        "next_outcome", "days_to_next_change", "km_to_next_change",
        "veh_speed_kmh", "veh_hours_per_day", "veh_late_prob",
    ]
    return df[columns]


# ---------------------------------------------------------------------------
# Noise -> dirty dataset (synthetic_rules §7)
# ---------------------------------------------------------------------------

def plate_lookalike(plate: str, rng: np.random.Generator) -> str | None:
    """N6: one Cyrillic letter -> its Latin look-alike. None if the plate has none."""
    positions = [i for i, ch in enumerate(plate) if ch in CYRILLIC_TO_LATIN]
    if not positions:
        return None
    i = positions[rng.integers(len(positions))]
    return plate[:i] + CYRILLIC_TO_LATIN[plate[i]] + plate[i + 1:]


def plate_spacing(plate: str, rng: np.random.Generator) -> str:
    """N7: different spacing; plates.normalize removes it again."""
    variants = (f"{plate[:4]} {plate[4:]}", f"{plate[:4]}  {plate[4:]}", f" {plate}", f"{plate} ", f"{plate[:2]} {plate[2:]}")
    return variants[rng.integers(len(variants))]


def phone_format(phone: str, rng: np.random.Generator) -> str:
    """N10: +976 prefix, spaces or dashes (cleaning -> 8 digits, D-019)."""
    variants = (f"+976{phone}", f"+976 {phone[:4]} {phone[4:]}", f"{phone[:4]}-{phone[4:]}", f"{phone[:4]} {phone[4:]}")
    return variants[rng.integers(len(variants))]


def apply_noise(clean: pd.DataFrame, cfg: dict, rng: np.random.Generator) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Turn clean records into 'dirty' ones like real data. Returns (dirty, noise_log).

    The dirty file has no vehicle_id and no truth columns: cleaning.py must
    find the vehicle from the plate, as with real data.
    """
    noise = {k: value(v) for k, v in cfg["noise"].items()}
    variants = cfg["destination_variants"]
    n = len(clean)
    dirty = clean[["record_id", "company_name", "plate_normalized", "service_date", "created_at", "odometer_km",
                   "destination_name", "route", "driver_name", "driver_phone"]].copy()
    dirty = dirty.rename(columns={"plate_normalized": "plate", "destination_name": "destination_raw"}).astype(object)
    log: list[tuple[int, str]] = []

    def pick(rate: float, allowed: np.ndarray | None = None) -> np.ndarray:
        mask = rng.random(n) < rate
        return np.flatnonzero(mask if allowed is None else mask & allowed)

    def mark(rows: np.ndarray, code: str) -> None:
        log.extend((int(dirty.at[i, "record_id"]), code) for i in rows)

    # Phone: format first (N10), then some go missing (N1).
    rows = pick(noise["phone_format"])
    dirty.loc[rows, "driver_phone"] = [phone_format(p, rng) for p in dirty.loc[rows, "driver_phone"]]
    mark(rows, "N10")
    rows = pick(noise["missing_phone"])
    dirty.loc[rows, "driver_phone"] = None
    mark(rows, "N1")
    rows = pick(noise["missing_driver_name"])
    dirty.loc[rows, "driver_name"] = None
    mark(rows, "N2")

    # Destination: other spelling (N5), then missing with route (N3).
    rows = pick(noise["destination_variant"])
    dirty.loc[rows, "destination_raw"] = [
        variants[d][rng.integers(len(variants[d]))] for d in dirty.loc[rows, "destination_raw"]
    ]
    mark(rows, "N5")
    rows = pick(noise["missing_destination"])
    dirty.loc[rows, ["destination_raw", "route"]] = None
    mark(rows, "N3")

    # Plate: Latin look-alike (N6), spacing (N7).
    rows = pick(noise["plate_latin_lookalike"])
    changed = [(i, plate_lookalike(dirty.at[i, "plate"], rng)) for i in rows]
    changed = [(i, p) for i, p in changed if p is not None]
    for i, p in changed:
        dirty.at[i, "plate"] = p
    mark(np.array([i for i, _ in changed], dtype=int), "N6")
    rows = pick(noise["plate_spacing"])
    dirty.loc[rows, "plate"] = [plate_spacing(p, rng) for p in dirty.loc[rows, "plate"]]
    mark(rows, "N7")

    # Odometer: missing (N4), digit error (N8), lower than last service (N9).
    rows = pick(noise["missing_odometer"])
    dirty.loc[rows, "odometer_km"] = None
    mark(rows, "N4")
    has_odo = dirty["odometer_km"].notna().to_numpy()
    rows = pick(noise["odometer_digit_error"], has_odo)
    dirty.loc[rows, "odometer_km"] = [int(o * 10) if rng.random() < 0.5 else int(o // 10) for o in dirty.loc[rows, "odometer_km"]]
    mark(rows, "N8")
    prev_odo = clean.groupby("vehicle_id")["odometer_km"].shift(1)
    rows = pick(noise["odometer_lower_than_last"], has_odo & prev_odo.notna().to_numpy())
    dirty.loc[rows, "odometer_km"] = [max(0, int(p) - int(rng.integers(100, 5001))) for p in prev_odo.iloc[rows]]
    mark(rows, "N9")

    # Late entry (N12): typed in 1–7 days after the service.
    rows = pick(noise["late_entry"])
    dirty.loc[rows, "created_at"] = [d + timedelta(days=int(rng.integers(1, 8))) for d in dirty.loc[rows, "service_date"]]
    mark(rows, "N12")

    # Duplicate record (N11): same truck, same day, new record_id.
    rows = pick(noise["duplicate_record"])
    dupes = dirty.loc[rows].copy()
    dupes["record_id"] = np.arange(n + 1, n + 1 + len(dupes))
    log.extend((int(r), "N11") for r in dupes["record_id"])
    dirty = pd.concat([dirty, dupes], ignore_index=True)
    dirty["odometer_km"] = dirty["odometer_km"].astype("Int64")

    noise_log = pd.DataFrame(log, columns=["record_id", "noise"]).sort_values(["record_id", "noise"]).reset_index(drop=True)
    return dirty, noise_log


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def generate(cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """Clean, dirty and noise log for one config (pure: no files written)."""
    clean = generate_clean(cfg)
    dirty, noise_log = apply_noise(clean, cfg, np.random.default_rng([cfg["seed"], 2]))
    return clean, dirty, noise_log


def write_outputs(clean: pd.DataFrame, dirty: pd.DataFrame, noise_log: pd.DataFrame, out_dir: Path) -> None:
    """Write the three CSV files (UTF-8, for Cyrillic)."""
    out_dir.mkdir(parents=True, exist_ok=True)
    clean.to_csv(out_dir / CLEAN_FILE, index=False, encoding="utf-8")
    dirty.to_csv(out_dir / DIRTY_FILE, index=False, encoding="utf-8")
    noise_log.to_csv(out_dir / NOISE_LOG_FILE, index=False, encoding="utf-8")


def main(argv: list[str] | None = None) -> int:
    """Generate data + report from a config file."""
    from src.data.synthetic_report import write_report  # matplotlib only needed here

    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    clean, dirty, noise_log = generate(cfg)
    write_outputs(clean, dirty, noise_log, Path(cfg["output_dir"]))
    write_report(clean, dirty, noise_log, cfg)
    print(f"{len(clean)} clean rows, {len(dirty)} dirty rows, {clean['vehicle_id'].nunique()} vehicles "
          f"-> {cfg['output_dir']}/ ; report -> {cfg['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
