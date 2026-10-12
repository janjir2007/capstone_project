"""Tests for src/ml/evaluate.py and src/ml/explain.py (Task 2.4). Fake fleets only — no data files."""

import copy
import json
import subprocess
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.common.features import FEATURE_COLUMNS
from src.data.generator import load_config as load_generator_config
from src.ml import evaluate as E
from src.ml import explain as X
from src.ml import train as T
from src.ml.dataset import TARGET
from tests.test_ml_train import fake_train

ROOT = Path(__file__).resolve().parents[1]


# --- Part 3: status classes (D-007) -----------------------------------------

def test_status_boundaries_follow_d007() -> None:
    assert list(E.status_of([15, 14, 0, -1], 14)) == ["ok", "due_soon", "due_soon", "overdue"]


def test_status_checks_grid_runs_until_after_due() -> None:
    checks = E.status_checks(pd.Series([20.0]), pd.Series([20.4]), every=7, after_due=14)
    assert list(checks["t"]) == [0, 7, 14, 21, 28]          # 35 > 20 + 14
    assert list(checks["true_left"]) == [20, 13, 6, -1, -8]
    assert list(checks["pred_left"]) == [20, 13, 6, -1, -8]  # round(20.4) = 20


def test_perfect_prediction_scores_one() -> None:
    y = pd.Series([30.0, 45, 60, 75, 90])
    m = E.status_metrics(E.status_checks(y, y, 7, 14), 14)
    assert m["f1_macro"] == m["accuracy"] == 1.0
    assert m["auc_overdue"] == m["auc_attention"] == m["auc_overdue_same_day"] == 1.0


def test_constant_prediction_is_guessing_on_the_same_day() -> None:
    y = pd.Series([30.0, 45, 60, 75, 90])
    m = E.status_metrics(E.status_checks(y, pd.Series(60.0, index=y.index), 7, 14), 14)
    assert m["auc_overdue_same_day"] == 0.5
    assert m["auc_overdue"] > 0.5  # pooled: elapsed time alone already helps (why both are reported)


# --- Part 4: reminder -------------------------------------------------------

def test_hits_match_reminder_outcomes() -> None:
    rng = np.random.default_rng(0)
    y = pd.Series(rng.integers(30, 90, 200).astype(float))
    p = pd.Series(rng.normal(60, 10, 200))
    h = E.hits(y, p, (1, 14), 5)
    assert h.mean() == pytest.approx(T.reminder_outcomes(y, p, (1, 14), 5)["hit_rate"])


def test_bootstrap_rate_gain_zero_for_same_outcomes() -> None:
    a = np.array([1, 0, 1, 1, 0, 0])
    g, lo, hi = E.bootstrap_rate_gain(a, a, pd.Series(list("aabbcc")), n=100, seed=0)
    assert g == lo == hi == 0.0


# --- Part 2: D-038 variation-off check --------------------------------------

def small_generator_cfg() -> dict:
    cfg = load_generator_config(ROOT / "configs/generator.yaml")
    cfg["fleet"]["n_vehicles"]["value"] = 20
    return cfg


def test_generated_records_variation_off_leaves_config_alone() -> None:
    cfg = small_generator_cfg()
    before = copy.deepcopy(cfg)
    off = E.generated_records(cfg, variation=False)
    assert cfg == before                                    # rules/config untouched (brief: do not change generator)
    assert list(off.columns) == ["record_id", "vehicle_key", "service_date", "odometer_km", "destination_name", "route"]
    assert off.groupby("vehicle_key")["destination_name"].nunique().max() == 1  # V6 off: never changes route


def test_generated_records_variation_on_switches_routes() -> None:
    on = E.generated_records(small_generator_cfg(), variation=True)
    assert on.groupby("vehicle_key")["destination_name"].nunique().max() > 1


def test_b1_refit_learns_offset() -> None:
    km_day = pd.Series([200.0, 250, 500, 400] * 5)
    train = pd.DataFrame({"route_km_per_day": km_day, TARGET: 17_500 / km_day + 10})  # B1 + 10 days late
    cfg = {"baselines": {"b1_interval_km": 17_500}}
    assert np.allclose(E.b1_refit(train, train, cfg), train[TARGET])


# --- Part 1: SHAP (Ridge in-process; XGBoost in a subprocess) ---------------

def test_pretty_and_grouped_column_names() -> None:
    assert X.pretty_column("cat__destination_name_Beijing") == "destination_name = Beijing"
    assert X.pretty_column("num__missingindicator_km_per_day_hist") == "km_per_day_hist (empty)"
    assert X.pretty_column("num__one_way_km") == "one_way_km"
    assert X.group_feature("destination_name = Beijing") == "destination_name"
    assert X.group_feature("km_per_day_hist (empty)") == "km_per_day_hist"
    with pytest.raises(ValueError):
        X.group_feature("not_a_feature")


def test_ridge_shap_adds_up_to_prediction() -> None:
    df = fake_train()
    pipe = T.model_specs(0)["Ridge"].pipeline().fit(df[FEATURE_COLUMNS], df[TARGET])
    exp = X.explain("Ridge", pipe, df[FEATURE_COLUMNS], df[FEATURE_COLUMNS])
    assert X.additivity_error(exp, pipe, df[FEATURE_COLUMNS]) < 1e-6
    imp = X.grouped_importance(exp)
    assert sorted(imp.index) == sorted(FEATURE_COLUMNS) and (imp >= 0).all()
    row = df.index[0]
    assert X.row_contributions(exp, row).sum() + exp.base_value == pytest.approx(pipe.predict(df[FEATURE_COLUMNS].loc[[row]])[0])


def test_example_row_needs_history_and_ignores_target() -> None:
    exp = X.Explanation("m", np.array([[5.0, 5.0], [1.0, 0.0], [-3.0, 0.0]]), 50.0, np.zeros((3, 2)), ["a", "b"],
                        pd.Index([10, 11, 12]))
    prior = pd.Series([0, 3, 4], index=[10, 11, 12])
    assert X.pick_example_row(exp, prior, min_prior=2) == 12  # row 10 moves most but has no history


SHAP_XGB = """
import json
from tests.test_ml_train import fake_train
from src.common.features import FEATURE_COLUMNS
from src.ml.dataset import TARGET
from src.ml import explain as X, train as T
df = fake_train()
pipe = T.model_specs(0)["XGBoost"].pipeline().set_params(model__n_estimators=30).fit(df[FEATURE_COLUMNS], df[TARGET])
exp = X.explain("XGBoost", pipe, df[FEATURE_COLUMNS], df[FEATURE_COLUMNS])
print(json.dumps({"err": X.additivity_error(exp, pipe, df[FEATURE_COLUMNS]), "n": len(X.grouped_importance(exp))}))
"""


def test_xgboost_shap_adds_up_to_prediction() -> None:
    """Separate Python: XGBoost and torch (OCR tests) must not share a process on macOS."""
    done = subprocess.run([sys.executable, "-c", SHAP_XGB], cwd=ROOT, capture_output=True, text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["err"] < 1e-3 and out["n"] == len(FEATURE_COLUMNS)


def test_importing_evaluate_does_not_load_xgboost_or_shap() -> None:
    done = subprocess.run([sys.executable, "-c", "import sys, src.ml.evaluate; print('xgboost' in sys.modules, 'shap' in sys.modules)"],
                          cwd=ROOT, capture_output=True, text=True, timeout=120)
    assert done.stdout.strip() == "False False"


# --- Part 5: serving model --------------------------------------------------

def test_serving_model_is_ridge_in_config() -> None:
    from src.ml.dataset import load_ml_config
    cfg = load_ml_config(ROOT / "configs/ml.yaml")
    assert cfg["models"]["serving_model"] == "Ridge"
    assert cfg["reminder"]["window_days_early"] == [1, 14]  # D-051


def test_gap_references_recover_destination_and_season_effects() -> None:
    dest = ["Beijing", "Kyakhta", "Zamyn"] * 20
    season = (["winter"] * 3 + ["summer"] * 3) * 10
    d = pd.DataFrame({"destination_name": dest, "season": season, "has_history": [int(i % 5 > 0) for i in range(60)],
                      "route_km_per_day": [500.0, 210.0, 340.0] * 20})
    d[TARGET] = d["destination_name"].map({"Beijing": 42.0, "Kyakhta": 91.0, "Zamyn": 59.0}) + \
        np.where(d["season"] == "winter", 6.0, 0.0)
    refs = E.gap_references(d, d, {"baselines": {"b1_interval_km": 17_500}})
    assert np.allclose(refs["destination means + season + has_history"], d[TARGET])


def test_prior_visit_count_is_diagnostic_and_counts_all_visits() -> None:
    """2.4b: the count is no longer a feature; the diagnostic helper counts per truck, oldest first."""
    assert "n_prior_visits" not in FEATURE_COLUMNS and "has_history" in FEATURE_COLUMNS
    df = pd.DataFrame({"vehicle_key": ["A", "B", "A", "A"],
                       "service_date": pd.to_datetime(["2025-03-01", "2025-01-01", "2025-01-01", "2025-02-01"])})
    assert E.prior_visit_count(df, "vehicle_key").tolist() == [2, 0, 0, 1]
