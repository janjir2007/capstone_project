"""Next-oil-change prediction for the API (task 4.3).

Inputs are built ONLY with ``src.common.features.build_features`` (R8), from
the vehicle's own service history in the database, exactly like training:
the newest service is the last row, earlier services give the history features.

Which method (brief 4.3, D-035, D-047), checked on the NEWEST service:
1. route is not MN–China / MN–Russia (the only routes generated)  -> B0 route_not_modelled
2. only ``destination_raw`` (typed by hand, no list destination)   -> B0 destination_raw_only
3. no destination at all (records older than migration 001), or a
   destination missing from the training route table              -> B0 unknown_destination
4. first visit (no earlier service)                                -> B1 first_visit
5. otherwise                                                       -> Ridge
B0 = median train interval, B1 = b1_interval_km ÷ route km/day; both from
models/serving_params.json (``python -m src.ml.export_serving``).

Status (D-007): days_left = predicted date − today (Ulaanbaatar);
ok > 14, due_soon 0–14, overdue < 0. Predicted date = service date +
round(days), as in the 2.4 evaluation.
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import date, timedelta
from pathlib import Path

import joblib
import pandas as pd

from src.common.features import FEATURE_COLUMNS, Route, build_features

MODEL_FILE = "next_change_model.joblib"
PARAMS_FILE = "serving_params.json"
MODELLED_ROUTES = frozenset({"mn_china", "mn_russia"})  # D-047: generator has only these
DUE_SOON_DAYS = 14  # D-007 (adjustable, Ari)
MIN_DAYS = 1.0  # a prediction is never earlier than the day after the service


@dataclass(frozen=True)
class Visit:
    """One service record, as much as the prediction needs."""

    id: int
    service_date: date
    odometer_km: int | None
    route: str | None
    destination_id: int | None
    destination_name: str | None
    destination_raw: str | None


@dataclass(frozen=True)
class Prediction:
    """Result before it becomes a PredictionOut (same fields)."""

    vehicle_id: int
    method: str
    fallback_reason: str | None
    model_version: str
    based_on_service_id: int
    last_service_date: date
    predicted_days: float
    predicted_date: date
    today: date
    days_left: int
    status: str


def status_of(days_left: int, due_soon_days: int = DUE_SOON_DAYS) -> str:
    """D-007 buckets (same rule as src.ml.evaluate.status_of)."""
    if days_left < 0:
        return "overdue"
    return "due_soon" if days_left <= due_soon_days else "ok"


def file_version(path: Path, name: str) -> str:
    """e.g. 'ridge-1a2b3c4d': model name + first 8 hex of the file's SHA-256 (changes when the file does)."""
    return f"{name.lower()}-{hashlib.sha256(path.read_bytes()).hexdigest()[:8]}"


class Predictor:
    """Ridge pipeline + fallback numbers, loaded once at API startup."""

    def __init__(self, model_dir: Path) -> None:
        bundle = joblib.load(model_dir / MODEL_FILE)
        if list(bundle["features"]) != FEATURE_COLUMNS:
            # The model was trained with other features than features.py builds now: refuse (train–serve skew).
            raise ValueError(f"{MODEL_FILE} features {bundle['features']} != features.py {FEATURE_COLUMNS}")
        params = json.loads((model_dir / PARAMS_FILE).read_text(encoding="utf-8"))
        self.pipeline = bundle["pipeline"]
        self.version = file_version(model_dir / MODEL_FILE, bundle["model"])
        self.b0_days = float(params["b0_days"])
        self.b1_interval_km = float(params["b1_interval_km"])
        self.late_km = float(params["late_km"])
        self.routes = {name: Route(**r) for name, r in params["routes"].items()}

    def features(self, visits: Sequence[Visit]) -> pd.DataFrame:
        """Feature row of the newest visit as a 1-row table (visits oldest first), via build_features (R8)."""
        records = pd.DataFrame({
            "vehicle_key": 0,  # one vehicle
            "service_date": pd.to_datetime([v.service_date for v in visits]),
            "odometer_km": [float("nan") if v.odometer_km is None else float(v.odometer_km) for v in visits],
            "destination_name": [v.destination_name for v in visits],
            "route": [v.route for v in visits],
        })
        return build_features(records, self.routes, "vehicle_key", late_km=self.late_km).iloc[[-1]]

    def method_for(self, last: Visit, row: pd.DataFrame) -> tuple[str, str | None]:
        """(method, fallback_reason) by the rules in the module docstring."""
        if last.route not in MODELLED_ROUTES:
            return "b0", "route_not_modelled"
        if last.destination_id is None and last.destination_raw is not None:
            return "b0", "destination_raw_only"
        if last.destination_name not in self.routes:
            return "b0", "unknown_destination"
        if row["has_history"].iloc[0] == 0:
            return "b1", "first_visit"
        return "ridge", None

    def predict_days(self, method: str, last: Visit, row: pd.DataFrame) -> float:
        """Days from the newest service to the next oil change."""
        if method == "b0":
            return self.b0_days
        if method == "b1":
            return self.b1_interval_km / self.routes[last.destination_name].km_per_day  # baselines.predict_b1
        return float(self.pipeline.predict(row[FEATURE_COLUMNS])[0])

    def predict(self, vehicle_id: int, visits: Sequence[Visit], today: date) -> Prediction:
        """Prediction for the next change after the newest of ``visits`` (oldest first, at least one)."""
        if not visits:
            raise ValueError("vehicle has no service")
        last = visits[-1]
        row = self.features(visits)
        method, reason = self.method_for(last, row)
        days = max(self.predict_days(method, last, row), MIN_DAYS)
        predicted = last.service_date + timedelta(days=round(days))
        days_left = (predicted - today).days
        return Prediction(vehicle_id, method, reason, self.version, last.id, last.service_date, round(days, 1),
                          predicted, today, days_left, status_of(days_left))


def load_predictor(model_dir: Path) -> Predictor:
    """Predictor from ``model_dir`` (FileNotFoundError / ValueError if files are missing or do not match)."""
    return Predictor(model_dir)
