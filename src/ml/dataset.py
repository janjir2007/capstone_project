"""Dataset for the next-oil-change model: target, route table, train/test split (Tasks 2.1–2.3a).

Target (D-006): ``days_to_next_change`` = days from this visit to the SAME
vehicle's next visit. The last visit of a vehicle has no target (it never came
back, or came back after the data ends) and is not used for training or
scoring. On the synthetic data this matches the generator's truth on every
returned visit (checked in task 2.1, see docs/ml_baselines.md).

Split (D-009): grouped by vehicle AND ordered in time.
- Trucks are split into train trucks and test trucks (no truck in both).
- A cutoff date separates past from future:
  train = train trucks' visits whose next visit is before the cutoff,
  test  = test trucks' visits on/after the cutoff.
So the model never sees a test truck, nor anything after the cutoff.
Features of test visits still use those trucks' EARLIER visits, as the app
would in real use.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.common.features import Route, build_features, sort_visits
from src.data.generator import load_config as load_generator_config
from src.data.synthetic_report import formula_days_at_midpoints

TARGET = "days_to_next_change"


def load_ml_config(path: Path = Path("configs/ml.yaml")) -> dict:
    """Read configs/ml.yaml."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def load_records(path: Path) -> pd.DataFrame:
    """Cleaned service records with ``service_date`` as datetime."""
    return pd.read_csv(path, parse_dates=["service_date"], encoding="utf-8")


def add_target(records: pd.DataFrame, vehicle_col: str) -> pd.Series:
    """Days to the same vehicle's next visit (NaN for its last visit). Same index as ``records``."""
    ordered = sort_visits(records, vehicle_col)
    next_date = ordered.groupby(vehicle_col)["service_date"].shift(-1)
    return (next_date - ordered["service_date"]).dt.days.reindex(records.index).rename(TARGET)


def route_table(generator_cfg: dict) -> dict[str, Route]:
    """Destination -> Route, km/day with every [ESTIMATE] range at its middle (B1 formula, D-035)."""
    mid = formula_days_at_midpoints(generator_cfg).set_index("destination_name")
    return {
        d["name"]: Route(route=d["route_category"], one_way_km=float(d["one_way_km"]),
                         km_per_day=float(mid.loc[d["name"], "km_per_day_mid"]))
        for d in generator_cfg["destinations"]
    }


@dataclass(frozen=True)
class Split:
    """Index labels of train and test rows, plus how they were chosen."""

    train: pd.Index
    test: pd.Index
    cutoff: pd.Timestamp
    test_vehicles: frozenset


def split_by_vehicle_and_time(df: pd.DataFrame, vehicle_col: str, test_vehicle_share: float,
                              cutoff_quantile: float, seed: int) -> Split:
    """Vehicle-grouped, time-ordered split (D-009). Only rows that have a target are used."""
    vehicles = np.array(sorted(df[vehicle_col].unique()))
    rng = np.random.default_rng(seed)
    n_test = max(1, round(len(vehicles) * test_vehicle_share))
    test_vehicles = frozenset(rng.choice(vehicles, size=n_test, replace=False))
    cutoff = df["service_date"].quantile(cutoff_quantile).normalize()

    has_target = df[TARGET].notna()
    is_test_vehicle = df[vehicle_col].isin(test_vehicles)
    next_visit = df["service_date"] + pd.to_timedelta(df[TARGET], unit="D")
    train = df.index[has_target & ~is_test_vehicle & (next_visit < cutoff)]
    test = df.index[has_target & is_test_vehicle & (df["service_date"] >= cutoff)]
    return Split(train=train, test=test, cutoff=cutoff, test_vehicles=test_vehicles)


def build_dataset_from_records(records: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, dict[str, Route]]:
    """Records (already loaded) + target + features in one table (all rows, also those without target).

    Used by ``build_dataset`` (cleaned CSV) and by the D-038 check (task 2.4), which
    builds its records in memory with the generator's variation switched off.
    """
    vehicle_col = cfg["vehicle_col"]
    routes = route_table(load_generator_config(Path(cfg["generator_config"])))
    features = build_features(records, routes, vehicle_col, late_km=cfg["features"]["late_km"])
    df = records[[vehicle_col, "record_id", "service_date", "odometer_km"]].join(features)
    df[TARGET] = add_target(records, vehicle_col)
    return df, routes


def build_dataset(cfg: dict) -> tuple[pd.DataFrame, dict[str, Route]]:
    """Cleaned CSV from configs/ml.yaml -> records + target + features."""
    return build_dataset_from_records(load_records(Path(cfg["input"])), cfg)


def make_split(df: pd.DataFrame, cfg: dict) -> Split:
    """The project's one split, from configs/ml.yaml (2.3b must use this same function)."""
    s = cfg["split"]
    return split_by_vehicle_and_time(df, cfg["vehicle_col"], s["test_vehicle_share"], s["cutoff_quantile"],
                                     cfg["seed"])
