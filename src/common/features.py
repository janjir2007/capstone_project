"""Feature engineering — the ONLY place features are built (CLAUDE.md, R8).

Training (src/ml/) and the API (task 4.x) both call ``build_features`` so a
feature is computed the same way in both places (no train–serve skew).

Rule against leakage: the features of a visit use ONLY that visit and the
same vehicle's EARLIER visits — never a later one. So a vehicle's first
visit has empty (NaN) history features; the model or the B1 fallback must
handle that (D-035).

Input: one row per service visit with the columns in ``INPUT_COLUMNS``
(vehicle column name is a parameter: ``vehicle_key`` in the cleaned file,
the database id in the API). The API passes one vehicle's past visits plus
the new visit and takes the LAST row.

Route numbers (one-way km, km/day) are NOT read here: the caller passes a
``Route`` table. Training builds it from configs/generator.yaml [ESTIMATE]
ranges; the API will build it from the destinations table (task 1.1c).
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

import numpy as np
import pandas as pd

INPUT_COLUMNS = ["service_date", "odometer_km", "destination_name", "route"]

UNKNOWN = "unknown"  # category value when destination / route is empty

# Late interval = more km than the actual-behavior maximum (D-030: drivers change
# at 15,000–20,000 km; later than 20,000 = late, same rule as the generator, D-047).
DEFAULT_LATE_KM = 20_000

# Same months as the generator (src/data/generator.py SEASON_BY_MONTH; a test checks they match).
SEASON_BY_MONTH: dict[int, str] = {
    12: "winter", 1: "winter", 2: "winter",
    3: "spring", 4: "spring", 5: "spring",
    6: "summer", 7: "summer", 8: "summer",
    9: "autumn", 10: "autumn", 11: "autumn",
}

CATEGORICAL_FEATURES = ["destination_name", "route", "season"]
NUMERIC_FEATURES = [
    "one_way_km",             # route distance (from the Route table)
    "route_km_per_day",       # route's typical km/day (from the Route table) -> B1 uses it
    "has_history",            # 0 on the first visit, 1 after (D-058: a visit COUNT grows with the
                              # calendar and leaks the split cutoff; only "any history?" is kept)
    "days_since_prev_visit",  # last observed interval (NaN on first visit)
    "past_interval_mean_days",  # mean days between this vehicle's earlier visits
    "km_per_day_hist",        # vehicle's own pace from its odometer readings so far
    "past_late_share",        # share of earlier intervals driven past late_km
]
FEATURE_COLUMNS = CATEGORICAL_FEATURES + NUMERIC_FEATURES


@dataclass(frozen=True)
class Route:
    """What we know about one destination."""

    route: str          # route category, e.g. "mn_china"
    one_way_km: float
    km_per_day: float   # round-trip km ÷ round-trip days incl. waiting (D-035)


def season_of(day: pd.Timestamp) -> str:
    """Season name of a date (Dec–Feb = winter, ...)."""
    return SEASON_BY_MONTH[day.month]


def _route_columns(df: pd.DataFrame, routes: Mapping[str, Route]) -> pd.DataFrame:
    """Destination-based features. Unknown destination -> 'unknown' + NaN numbers."""
    dest = df["destination_name"].where(df["destination_name"].notna(), None)
    info = [routes.get(d) if d is not None else None for d in dest]
    route_from_table = pd.Series([r.route if r else None for r in info], index=df.index)
    return pd.DataFrame({
        "destination_name": dest.fillna(UNKNOWN),
        # the row's own route first; else the table's route for that destination
        "route": df["route"].where(df["route"].notna(), route_from_table).fillna(UNKNOWN),
        "season": df["service_date"].map(season_of),
        "one_way_km": [r.one_way_km if r else np.nan for r in info],
        "route_km_per_day": [r.km_per_day if r else np.nan for r in info],
    }, index=df.index)


def _km_per_day(days: list[pd.Timestamp], kms: list[float]) -> float:
    """Pace from the first to the last KNOWN odometer reading (NaN if < 2 readings or no time between)."""
    known = [(d, k) for d, k in zip(days, kms) if not pd.isna(k)]
    if len(known) < 2:
        return np.nan
    (d0, k0), (d1, k1) = known[0], known[-1]
    span = (d1 - d0).days
    return (k1 - k0) / span if span > 0 else np.nan


def _late_share(kms: list[float], late_km: float) -> float:
    """Share of consecutive-visit intervals with more than late_km driven (only intervals with both readings)."""
    driven = [b - a for a, b in zip(kms, kms[1:]) if not (pd.isna(a) or pd.isna(b))]
    return float(np.mean([km > late_km for km in driven])) if driven else np.nan


def _history_columns(visits: pd.DataFrame, late_km: float) -> pd.DataFrame:
    """History features for ONE vehicle; ``visits`` sorted oldest first.

    Row i only looks at rows 0..i (its own visit and earlier ones).
    """
    days = list(visits["service_date"])
    kms = list(visits["odometer_km"].astype(float))
    rows = []
    for i in range(len(visits)):
        gaps = [(b - a).days for a, b in zip(days[: i + 1], days[1 : i + 1])]
        rows.append({
            "has_history": int(i > 0),
            "days_since_prev_visit": gaps[-1] if gaps else np.nan,
            "past_interval_mean_days": float(np.mean(gaps)) if gaps else np.nan,
            "km_per_day_hist": _km_per_day(days[: i + 1], kms[: i + 1]),
            "past_late_share": _late_share(kms[: i + 1], late_km),
        })
    return pd.DataFrame(rows, index=visits.index)


def sort_visits(records: pd.DataFrame, vehicle_col: str) -> pd.DataFrame:
    """Oldest visit first per vehicle; stable, so same-day rows keep their input order."""
    return records.sort_values([vehicle_col, "service_date"], kind="stable")


def build_features(records: pd.DataFrame, routes: Mapping[str, Route], vehicle_col: str = "vehicle_key",
                   late_km: float = DEFAULT_LATE_KM) -> pd.DataFrame:
    """Feature table (``FEATURE_COLUMNS``) with the same index as ``records``.

    ``service_date`` must be datetime; ``odometer_km`` may be empty (NaN).
    """
    missing = [c for c in [vehicle_col, *INPUT_COLUMNS] if c not in records.columns]
    if missing:
        raise ValueError(f"records are missing column(s): {', '.join(missing)}")
    if records.empty:
        return pd.DataFrame(columns=FEATURE_COLUMNS, index=records.index)
    ordered = sort_visits(records, vehicle_col)
    history = pd.concat([_history_columns(g, late_km) for _, g in ordered.groupby(vehicle_col, sort=False)])
    out = _route_columns(records, routes).join(history)
    return out[FEATURE_COLUMNS]
