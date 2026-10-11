"""Tests for src/ml/train.py (Task 2.3b). Small fake fleet, tiny searches — no data files."""

import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.features import FEATURE_COLUMNS, Route, build_features
from src.ml import train as T
from src.ml.dataset import TARGET, add_target

ROUTES = {"Beijing": Route("mn_china", 1330, 500.0), "Kyakhta": Route("mn_russia", 351, 210.0)}


def fake_train(n_vehicles: int = 24, visits: int = 6, seed: int = 0) -> pd.DataFrame:
    """Fake visits with features + target; each truck has its own pace."""
    rng = np.random.default_rng(seed)
    rows = []
    for v in range(n_vehicles):
        day, odo, gap = pd.Timestamp("2024-01-01"), 100_000.0, int(rng.integers(40, 80))
        dest = ["Beijing", "Kyakhta", None][v % 3]
        for _ in range(visits):
            rows.append({"vehicle_key": f"V{v:02d}", "service_date": day, "odometer_km": odo,
                         "destination_name": dest, "route": ROUTES[dest].route if dest else None})
            step = gap + int(rng.integers(-5, 6))
            day += pd.Timedelta(days=step)
            odo += step * 300.0
    records = pd.DataFrame(rows)
    df = records[["vehicle_key", "service_date", "odometer_km"]].join(build_features(records, ROUTES))  # as build_dataset
    df[TARGET] = add_target(records, "vehicle_key")
    return df[df[TARGET].notna()]


CFG = {"seed": 0, "vehicle_col": "vehicle_key",
       "baselines": {"b1_interval_km": 17_500},
       "reminder": {"window_days_early": [3, 7]},
       "models": {"cv_folds": 3, "n_iter": 2, "buffer_range_days": [0, 10], "bootstrap_resamples": 200}}


# --- buffer ----------------------------------------------------------------

def test_tune_buffer_finds_the_shift_into_the_window() -> None:
    y = pd.Series([60.0] * 10)
    pred = pd.Series([60.0] * 10)  # reminder on the due day = too late; 3–7 days early needed
    assert T.tune_buffer(y, pred, (3, 7), (0, 20)) == 3  # smallest buffer with a full hit


def test_tune_buffer_stays_in_range() -> None:
    y, pred = pd.Series([100.0]), pd.Series([40.0])  # far too early, no buffer helps
    assert T.tune_buffer(y, pred, (3, 7), (0, 5)) == 0


# --- validation without leakage --------------------------------------------

def test_oof_b0_never_uses_its_own_truck() -> None:
    y = pd.Series([10.0, 10.0, 50.0, 50.0, 90.0, 90.0])
    groups = pd.Series(["a", "a", "b", "b", "c", "c"])
    oof = T.oof_b0(y, groups, folds=3)
    # truck a's value = median of b and c (70), not including its own 10s
    assert oof[0] == oof[1] == 70.0
    assert oof[4] == 30.0


def test_preprocessor_handles_unknown_category_and_nan() -> None:
    df = fake_train()
    pipe = T.model_specs(0)["Ridge"].pipeline().fit(df[FEATURE_COLUMNS], df[TARGET])
    new = df[FEATURE_COLUMNS].iloc[[0]].copy()
    new["destination_name"] = "Somewhere new"
    new["km_per_day_hist"] = np.nan
    assert np.isfinite(pipe.predict(new)).all()


SMOKE = """
import json
from tests.test_ml_train import CFG, fake_train
from src.ml import train as T
train = fake_train()
models, val_scores, buffers, best = T.validate(train, CFG)
print(json.dumps({
    "models": sorted(models), "scored": sorted(val_scores), "buffered": sorted(buffers), "best": best,
    "best_by_val_mae": min(models, key=lambda n: val_scores[n]["MAE"]),
    "oof_ok": all(r.oof.index.equals(train.index) and r.oof.notna().all() for r in models.values()),
    "buffers_in_range": all(0 <= r.buffer_days <= 10 for r in models.values()),
}))
"""


def test_fit_models_smoke_and_best_choice_uses_validation_only() -> None:
    """Runs in a separate Python: XGBoost and torch (OCR tests) must not share a process on macOS."""
    root = Path(__file__).resolve().parents[1]
    done = subprocess.run([sys.executable, "-c", SMOKE], cwd=root, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["models"] == ["Random Forest", "Ridge", "XGBoost"]
    assert out["scored"] == out["buffered"] == sorted(["B0 (median)", "B1 (17,500 km)", *out["models"]])
    assert out["best"] == out["best_by_val_mae"]
    assert out["oof_ok"] and out["buffers_in_range"]


def test_importing_train_does_not_load_xgboost() -> None:
    done = subprocess.run([sys.executable, "-c", "import sys, src.ml.train; print('xgboost' in sys.modules)"],
                          cwd=Path(__file__).resolve().parents[1], capture_output=True, text=True, timeout=120)
    assert done.stdout.strip() == "False"


# --- test-set statistics ---------------------------------------------------

def test_bootstrap_gain_zero_for_identical_predictions() -> None:
    y = pd.Series([50.0, 60, 70, 80])
    p = pd.Series([55.0, 55, 65, 85])
    g, lo, hi = T.bootstrap_mae_gain(y, p, p, pd.Series(list("aabb")), n=100, seed=0)
    assert g == lo == hi == 0.0


def test_bootstrap_gain_positive_when_clearly_better() -> None:
    y = pd.Series(np.arange(40.0))
    good, bad = y + 1, y + 10
    g, lo, hi = T.bootstrap_mae_gain(y, good, bad, pd.Series(np.arange(40) // 2), n=200, seed=0)
    assert g == pytest.approx(9.0) and lo > 0


def test_save_model_roundtrip(tmp_path, monkeypatch) -> None:
    import joblib
    train = fake_train()
    pipe = T.model_specs(0)["Ridge"].pipeline().fit(train[FEATURE_COLUMNS], train[TARGET])
    result = T.TrainResult("Ridge", pipe, {"model__alpha": 1.0}, pd.Series(dtype=float), buffer_days=4)
    split = type("S", (), {"cutoff": pd.Timestamp("2025-01-01")})()
    cfg = CFG | {"input": "fake.csv", "models": CFG["models"] | {"model_dir": str(tmp_path)}}
    path = T.save_model(result, cfg, split)
    loaded = joblib.load(path)
    assert loaded["buffer_days"] == 4 and loaded["features"] == FEATURE_COLUMNS
    assert np.allclose(loaded["pipeline"].predict(train[FEATURE_COLUMNS]), pipe.predict(train[FEATURE_COLUMNS]))
