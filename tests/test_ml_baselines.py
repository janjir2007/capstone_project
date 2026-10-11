"""Tests for src/ml/dataset.py and src/ml/baselines.py (Tasks 2.1–2.3a). Fake data only."""

import numpy as np
import pandas as pd
import pytest

from src.ml import baselines as B
from src.ml import dataset as D


def fake_fleet(n_vehicles: int = 20, visits: int = 8, seed: int = 0) -> pd.DataFrame:
    """Trucks visiting every 40–80 days from 2024-01-01."""
    rng = np.random.default_rng(seed)
    rows = []
    for v in range(n_vehicles):
        day = pd.Timestamp("2024-01-01") + pd.Timedelta(days=int(rng.integers(0, 60)))
        for _ in range(visits):
            rows.append({"vehicle_key": f"V{v:02d}", "service_date": day})
            day += pd.Timedelta(days=int(rng.integers(40, 81)))
    df = pd.DataFrame(rows)
    df[D.TARGET] = D.add_target(df, "vehicle_key")
    return df


# --- dataset ---------------------------------------------------------------

def test_add_target_is_days_to_same_vehicles_next_visit() -> None:
    df = pd.DataFrame({"vehicle_key": ["A", "B", "A", "A"],
                       "service_date": pd.to_datetime(["2025-03-01", "2025-01-01", "2025-01-01", "2025-02-01"])})
    t = D.add_target(df, "vehicle_key")
    assert np.isnan(t[0]) and np.isnan(t[1])  # last visit of A, only visit of B
    assert t[2] == 31 and t[3] == 28


def test_split_has_no_shared_vehicle_and_respects_cutoff() -> None:
    df = fake_fleet()
    s = D.split_by_vehicle_and_time(df, "vehicle_key", 0.25, 0.6, seed=1)
    train, test = df.loc[s.train], df.loc[s.test]
    assert set(train["vehicle_key"]).isdisjoint(test["vehicle_key"])
    assert set(test["vehicle_key"]) <= s.test_vehicles
    next_visit = train["service_date"] + pd.to_timedelta(train[D.TARGET], unit="D")
    assert (next_visit < s.cutoff).all()
    assert (test["service_date"] >= s.cutoff).all()
    assert train[D.TARGET].notna().all() and test[D.TARGET].notna().all()
    assert len(train) > 0 and len(test) > 0


def test_split_is_reproducible() -> None:
    df = fake_fleet()
    a = D.split_by_vehicle_and_time(df, "vehicle_key", 0.25, 0.6, seed=7)
    b = D.split_by_vehicle_and_time(df, "vehicle_key", 0.25, 0.6, seed=7)
    assert a.train.equals(b.train) and a.test.equals(b.test)


def test_route_table_uses_formula_midpoints() -> None:
    cfg = {"destinations": [{"name": "X", "route_category": "mn_russia", "one_way_km": 400}],
           "trip": {"round_trip_factor": {"value": 2}, "speed_kmh": {"min": 90, "max": 110},
                    "driving_hours_per_day": {"min": 8, "max": 12}, "waiting_days_per_trip": {"min": 0, "max": 2}},
           "interval": {"min_km": {"value": 15000}}}
    r = D.route_table(cfg)["X"]
    # 800 km ÷ (100 km/h × 10 h) = 0.8 driving days + 1 waiting day = 1.8 days
    assert r.route == "mn_russia" and r.km_per_day == pytest.approx(800 / 1.8)


# --- baselines -------------------------------------------------------------

def test_b0_is_train_median() -> None:
    p = B.predict_b0(pd.Series([10, 20, 90]), pd.Index([5, 6]))
    assert p.tolist() == [20.0, 20.0] and list(p.index) == [5, 6]


def test_b1_formula_and_fallback() -> None:
    km_per_day = pd.Series([300.0, np.nan, 0.0])
    p = B.predict_b1(km_per_day, 15_000, fallback=pd.Series([58.0, 58.0, 58.0]))
    assert p.tolist() == [50.0, 58.0, 58.0]


def test_regression_metrics_known_values() -> None:
    m = B.regression_metrics(pd.Series([10.0, 20.0]), pd.Series([12.0, 16.0]))
    assert m["MAE"] == pytest.approx(3.0)
    assert m["RMSE"] == pytest.approx(np.sqrt((4 + 16) / 2))
    assert B.regression_metrics(pd.Series([1.0, 2, 3]), pd.Series([1.0, 2, 3]))["R2"] == 1.0


def test_reminder_outcomes_window_edges() -> None:
    y = pd.Series([60, 60, 60, 60, 60])
    pred = pd.Series([57, 53, 52, 58, 50.4])  # lead 3 (hit), 7 (hit), 8 (early), 2 (late), 10 (early, rounds to 50)
    out = B.reminder_outcomes(y, pred, (3, 7))
    assert out == {"hit_rate": 0.4, "too_early": 0.4, "too_late": 0.2}


def test_reminder_buffer_moves_reminder_earlier() -> None:
    y, pred = pd.Series([60]), pd.Series([59])
    assert B.reminder_outcomes(y, pred, (3, 7))["too_late"] == 1.0
    assert B.reminder_outcomes(y, pred, (3, 7), buffer_days=3)["hit_rate"] == 1.0


def test_shares_sum_to_one() -> None:
    rng = np.random.default_rng(0)
    y, pred = pd.Series(rng.integers(20, 100, 200)), pd.Series(rng.normal(60, 10, 200))
    out = B.reminder_outcomes(y, pred, (3, 7))
    assert sum(out.values()) == pytest.approx(1.0)
