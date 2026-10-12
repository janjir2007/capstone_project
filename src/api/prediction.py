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

Reminders (task 4.4, D-036): send_on = predicted date − buffer of the method
that answered (ridge from the model file, b0/b1 from serving_params.json).
Segments (D-007): at_risk = predicted date + 7 days grace < as_of (the
prediction is always based on the newest service, so "not returned" holds);
else new (1 service) / returning (2) / loyal (3+).
"""

from __future__ import annotations

import hashlib
import json
from collections.abc import Mapping, Sequence
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
AT_RISK_GRACE_DAYS = 7  # D-007: at risk = overdue + 7 days grace, no new record
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


def segment_of(service_count: int, predicted_date: date | None, as_of: date,
               grace_days: int = AT_RISK_GRACE_DAYS) -> str:
    """D-007 segment; at_risk wins (same rule as the SQL function vehicle_segments, which reads stored predictions)."""
    if predicted_date is not None and predicted_date + timedelta(days=grace_days) < as_of:
        return "at_risk"
    return "new" if service_count == 1 else "returning" if service_count == 2 else "loyal"


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
        # Reminder buffer per method (days early), tuned on validation: never typed in by hand here.
        self.buffers = {"ridge": int(bundle["buffer_days"]), "b0": int(params["buffers"]["b0"]),
                        "b1": int(params["buffers"]["b1"])}

    def features(self, histories: Mapping[int, Sequence[Visit]]) -> pd.DataFrame:
        """Feature row of every vehicle's newest visit, index = vehicle id (visits oldest first), via build_features (R8)."""
        rows = [(vid, v) for vid, visits in histories.items() for v in visits]
        records = pd.DataFrame({
            "vehicle_key": [vid for vid, _ in rows],
            "service_date": pd.to_datetime([v.service_date for _, v in rows]),
            "odometer_km": [float("nan") if v.odometer_km is None else float(v.odometer_km) for _, v in rows],
            "destination_name": [v.destination_name for _, v in rows],
            "route": [v.route for _, v in rows],
        })
        features = build_features(records, self.routes, "vehicle_key", late_km=self.late_km)
        last_rows = records.groupby("vehicle_key", sort=False).tail(1).index  # newest = last given
        return features.loc[last_rows].set_axis(records.loc[last_rows, "vehicle_key"].to_numpy())

    def method_for(self, last: Visit, row: pd.Series) -> tuple[str, str | None]:
        """(method, fallback_reason) by the rules in the module docstring."""
        if last.route not in MODELLED_ROUTES:
            return "b0", "route_not_modelled"
        if last.destination_id is None and last.destination_raw is not None:
            return "b0", "destination_raw_only"
        if last.destination_name not in self.routes:
            return "b0", "unknown_destination"
        if row["has_history"] == 0:
            return "b1", "first_visit"
        return "ridge", None

    def predict_many(self, histories: Mapping[int, Sequence[Visit]], today: date) -> dict[int, Prediction]:
        """Predictions for many vehicles at once ({vehicle_id: visits oldest first}); one Ridge call for all."""
        if any(not visits for visits in histories.values()):
            raise ValueError("vehicle has no service")
        if not histories:
            return {}
        rows = self.features(histories)
        methods = {vid: self.method_for(histories[vid][-1], rows.loc[vid]) for vid in histories}
        ridge_ids = [vid for vid, (m, _) in methods.items() if m == "ridge"]
        days = {vid: float(d) for vid, d in zip(ridge_ids, self.pipeline.predict(rows.loc[ridge_ids, FEATURE_COLUMNS]))} \
            if ridge_ids else {}
        out = {}
        for vid, (method, reason) in methods.items():
            last = histories[vid][-1]
            if method == "b0":
                days[vid] = self.b0_days
            elif method == "b1":
                days[vid] = self.b1_interval_km / self.routes[last.destination_name].km_per_day  # baselines.predict_b1
            d = max(days[vid], MIN_DAYS)
            predicted = last.service_date + timedelta(days=round(d))
            days_left = (predicted - today).days
            out[vid] = Prediction(vid, method, reason, self.version, last.id, last.service_date, round(d, 1),
                                  predicted, today, days_left, status_of(days_left))
        return out

    def predict(self, vehicle_id: int, visits: Sequence[Visit], today: date) -> Prediction:
        """Prediction for the next change after the newest of ``visits`` (oldest first, at least one)."""
        return self.predict_many({vehicle_id: visits}, today)[vehicle_id]

    def send_on(self, prediction: Prediction) -> date:
        """Reminder day: predicted date − the buffer of the method that answered (D-036)."""
        return prediction.predicted_date - timedelta(days=self.buffers[prediction.method])


def load_predictor(model_dir: Path) -> Predictor:
    """Predictor from ``model_dir`` (FileNotFoundError / ValueError if files are missing or do not match)."""
    return Predictor(model_dir)
