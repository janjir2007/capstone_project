"""Tests for task 2.9: src/ml/noise_floor.py and src/ml/tune.py.

All data is SYNTHETIC and built in memory (tiny generator fleet / fake series);
nothing is read from data/ and no xgboost is imported (libomp clash with torch, see train.py).
"""

import copy
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

from src.data.generator import generate_clean, load_config
from src.ml import noise_floor as NF
from src.ml import tune as T

GEN_CFG = load_config(Path("configs/generator.yaml"))


@pytest.fixture(scope="module")
def small_truth() -> pd.DataFrame:
    """Generator truth for 6 trucks (same code and seed as the real file, smaller fleet)."""
    cfg = copy.deepcopy(GEN_CFG)
    cfg["fleet"]["n_vehicles"]["value"] = 6
    return generate_clean(cfg).set_index("record_id")


def returned_rows(truth: pd.DataFrame) -> pd.DataFrame:
    """Rows with a target, shaped like the ML dataset (record_id column, own index)."""
    rows = truth[truth["days_to_next_change"].notna()].reset_index()
    return rows.rename(columns={"days_to_next_change": "y"})


# --- noise floor ---------------------------------------------------------------

def test_simulate_days_respects_the_window_and_rounding(small_truth: pd.DataFrame) -> None:
    t = small_truth.iloc[0]
    rng = np.random.default_rng(0)
    sims = NF.simulate_days(rng, GEN_CFG, NF.visit_vehicle(t), 10, 0, date(2024, 1, 1), last_ok_day=10 + 70, n=200)
    assert len(sims) == 200
    assert sims.min() >= 1 and sims.max() <= 70  # no draw after the window, never earlier than next day
    assert np.allclose(sims, np.round(sims))  # whole days, as in simulate_vehicle


def test_impossible_window_gives_no_draws(small_truth: pd.DataFrame) -> None:
    t = small_truth.iloc[0]
    sims = NF.simulate_days(np.random.default_rng(0), GEN_CFG, NF.visit_vehicle(t), 10, 0, date(2024, 1, 1),
                            last_ok_day=11, n=5)  # 15k km can never be driven in 1 day
    assert len(sims) == 0


def test_oracle_is_reproducible_and_order_independent(small_truth: pd.DataFrame) -> None:
    rows = returned_rows(small_truth).head(8)
    last = NF.last_ok_day_for(rows, GEN_CFG, pd.Timestamp("2026-09-30"), strict=False)
    a = NF.oracle_predictions(rows, small_truth, GEN_CFG, last, n_sims=60, seed=42)
    rev = rows.iloc[::-1]
    b = NF.oracle_predictions(rev, small_truth, GEN_CFG, last.loc[rev.index], n_sims=60, seed=42)
    pd.testing.assert_series_equal(a, b.loc[a.index])
    assert a.notna().all()


def test_oracle_is_close_to_the_truth_on_average(small_truth: pd.DataFrame) -> None:
    """Sanity: the oracle median sits in the generator's typical range (p5 36 / p95 88 days, 1.3)."""
    rows = returned_rows(small_truth)
    last = NF.last_ok_day_for(rows, GEN_CFG, pd.Timestamp("2026-09-30"), strict=False)
    oracle = NF.oracle_predictions(rows, small_truth, GEN_CFG, last, n_sims=100, seed=42)
    assert oracle.between(20, 120).all()
    assert NF.oracle_mae(rows["y"], oracle) < (rows["y"] - rows["y"].mean()).abs().mean() + 5


def test_last_ok_day_strict_is_one_day_earlier() -> None:
    rows = pd.DataFrame(index=[0, 1])
    end = pd.Timestamp("2024-01-31")
    assert (NF.last_ok_day_for(rows, GEN_CFG, end, strict=False) == 30).all()
    assert (NF.last_ok_day_for(rows, GEN_CFG, end, strict=True) == 29).all()


# --- tuning helpers --------------------------------------------------------------

def test_keep_rule_needs_at_least_the_margin() -> None:
    assert T.KEEP_MARGIN_DAYS == 0.3  # D-093, fixed before results
    assert T.keep_decision(12.5, 12.2) is True
    assert T.keep_decision(12.5, 12.21) is False
    assert T.keep_decision(12.5, 12.6) is False


def test_residual_range_and_coverage() -> None:
    y = pd.Series(np.arange(100, dtype=float))
    pred = pd.Series(np.full(100, 50.0))
    low, high = T.residual_range(y, pred)
    assert low == pytest.approx(-40.1) and high == pytest.approx(39.1)
    assert T.coverage(y, pred, (low, high)) == pytest.approx(0.80)
    assert T.coverage(y, pred, (0.0, 0.0)) == pytest.approx(0.01)


def test_best_blend_picks_the_lower_mae_weight() -> None:
    y = pd.Series([10.0, 20.0, 30.0])
    good = T.Candidate("Ridge", [], [1.0], {}, y.copy())
    bad = T.Candidate("XGBoost", [], [1.0], {}, y + 6)
    w, oof = T.best_blend(y, good, bad)
    assert w == 1.0 and oof.equals(y)
    w, _ = T.best_blend(y, bad, good)
    assert w == 0.0


def test_candidate_predict_is_the_weighted_average() -> None:
    class Const:
        def __init__(self, v: float) -> None:
            self.v = v

        def predict(self, X: pd.DataFrame) -> np.ndarray:
            return np.full(len(X), self.v)

    c = T.Candidate("avg", [Const(10), Const(20)], [0.25, 0.75], {}, pd.Series(dtype=float))
    assert np.allclose(c.predict(pd.DataFrame(index=range(3))), 17.5)


def test_write_section_appends_then_replaces(tmp_path: Path) -> None:
    doc = tmp_path / "r.md"
    doc.write_text("# Results\n\ntext\n", encoding="utf-8")
    T.write_section(f"{T.SECTION_START}\nA\n{T.SECTION_END}", doc)
    T.write_section(f"{T.SECTION_START}\nB\n{T.SECTION_END}", doc)
    out = doc.read_text(encoding="utf-8")
    assert out.startswith("# Results") and out.count(T.SECTION_START) == 1 and "\nB\n" in out and "\nA\n" not in out


def test_test_step_refuses_a_second_run(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    (tmp_path / T.TEST_MARKER).write_text("{}", encoding="utf-8")
    cfg_file = tmp_path / "ml.yaml"
    cfg_file.write_text(Path("configs/ml.yaml").read_text(encoding="utf-8").replace(
        "model_dir: models ", f"model_dir: {tmp_path} "), encoding="utf-8")
    with pytest.raises(SystemExit, match="already run"):
        T.main(["test", "--config", str(cfg_file)])
