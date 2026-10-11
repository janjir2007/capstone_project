"""Train Ridge, Random Forest and XGBoost; compare with B0/B1 on the test split (Task 2.3b).

Honesty rules (brief 2.3b, D-049, D-050):
- Hyperparameters: RandomizedSearchCV with GroupKFold by truck, on TRAIN only.
- Validation = out-of-fold (OOF) predictions on TRAIN: every train visit is
  predicted by a model that never saw its truck. The best model and every
  reminder buffer (B0 and B1 included) are chosen on these, never on test.
- Test is used once, at the end (``evaluate_on_test``), to report numbers.

Usage:
    python -m src.ml.train          # writes docs/ml_results.md, chart, models/
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass, field
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from scipy.stats import loguniform, randint, uniform
from sklearn.base import clone
from sklearn.compose import ColumnTransformer
from sklearn.ensemble import RandomForestRegressor
from sklearn.impute import SimpleImputer
from sklearn.linear_model import Ridge
from sklearn.model_selection import GroupKFold, RandomizedSearchCV, cross_val_predict
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import OneHotEncoder, StandardScaler

from src.common.features import CATEGORICAL_FEATURES, FEATURE_COLUMNS, NUMERIC_FEATURES
from src.ml.baselines import (
    _md_table,
    plot_baselines,
    predict_b0,
    predict_b1,
    reminder_outcomes,
    results_table,
    score,
)
from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split

CHART = "ml_results.png"
MODEL_FILE = "next_change_model.joblib"


# ---------------------------------------------------------------------------
# Models
# ---------------------------------------------------------------------------

def preprocessor(scale: bool) -> ColumnTransformer:
    """One-hot categories; numbers: median fill + "was empty" flags (+ scaling for Ridge).

    The fill values are learned inside each CV fold (part of the Pipeline), so no fold
    sees statistics from its validation trucks.
    """
    numeric = [("impute", SimpleImputer(strategy="median", add_indicator=True))]
    if scale:
        numeric.append(("scale", StandardScaler()))
    return ColumnTransformer([
        ("cat", OneHotEncoder(handle_unknown="ignore", sparse_output=False), CATEGORICAL_FEATURES),
        ("num", Pipeline(numeric), NUMERIC_FEATURES),
    ])


@dataclass(frozen=True)
class ModelSpec:
    """One model family: how to build it and which hyperparameters to search."""

    estimator: object
    params: dict
    scale: bool = False

    def pipeline(self) -> Pipeline:
        return Pipeline([("prep", preprocessor(self.scale)), ("model", clone(self.estimator))])


def model_specs(seed: int) -> dict[str, ModelSpec]:
    """The three model families of the brief, with search ranges (not tuned on test)."""
    # Imported here, not at the top: on macOS, xgboost (Homebrew libomp) and torch (its own
    # libomp) in ONE process hang or crash (seen in task 2.3b). Lazy import keeps xgboost out
    # of processes that only import this module (e.g. the test run, which also uses torch).
    from xgboost import XGBRegressor

    return {
        "Ridge": ModelSpec(Ridge(), {"model__alpha": loguniform(1e-3, 1e3)}, scale=True),
        "Random Forest": ModelSpec(
            RandomForestRegressor(random_state=seed, n_jobs=-1),
            {"model__n_estimators": randint(200, 600), "model__max_depth": [None, 4, 6, 8, 12],
             "model__min_samples_leaf": randint(5, 60), "model__max_features": [0.3, 0.5, 0.8, 1.0]}),
        "XGBoost": ModelSpec(
            XGBRegressor(random_state=seed, n_jobs=4, tree_method="hist"),
            {"model__n_estimators": randint(100, 800), "model__max_depth": randint(2, 7),
             "model__learning_rate": loguniform(0.01, 0.2), "model__subsample": uniform(0.6, 0.4),
             "model__colsample_bytree": uniform(0.5, 0.5), "model__min_child_weight": randint(1, 30),
             "model__reg_lambda": loguniform(0.1, 10)}),
    }


# ---------------------------------------------------------------------------
# Tuning on TRAIN only
# ---------------------------------------------------------------------------

@dataclass
class TrainResult:
    """What one model learned from TRAIN: fitted pipeline, best params, OOF predictions."""

    name: str
    estimator: Pipeline
    best_params: dict
    oof: pd.Series
    oof_scores: dict = field(default_factory=dict)
    buffer_days: int = 0


def search_model(spec: ModelSpec, X: pd.DataFrame, y: pd.Series, groups: pd.Series, folds: int,
                 n_iter: int, seed: int) -> RandomizedSearchCV:
    """RandomizedSearchCV, grouped by truck, scored by MAE; refits the best on all of TRAIN."""
    search = RandomizedSearchCV(spec.pipeline(), spec.params, n_iter=n_iter, cv=GroupKFold(n_splits=folds),
                                scoring="neg_mean_absolute_error", random_state=seed, n_jobs=1)
    return search.fit(X, y, groups=groups)


def oof_predictions(estimator: Pipeline, X: pd.DataFrame, y: pd.Series, groups: pd.Series, folds: int) -> pd.Series:
    """Each train visit predicted by a copy of the model fitted without its truck."""
    pred = cross_val_predict(clone(estimator), X, y, groups=groups, cv=GroupKFold(n_splits=folds))
    return pd.Series(pred, index=X.index)


def oof_b0(y: pd.Series, groups: pd.Series, folds: int) -> pd.Series:
    """B0 out-of-fold: each fold gets the median of the OTHER folds' targets."""
    out = pd.Series(np.nan, index=y.index)
    for fit_idx, val_idx in GroupKFold(n_splits=folds).split(y, y, groups):
        out.iloc[val_idx] = y.iloc[fit_idx].median()
    return out


def tune_buffer(y: pd.Series, pred: pd.Series, window: tuple[int, int], buffer_range: tuple[int, int]) -> int:
    """Days early that maximize the hit rate; ties -> fewer late reminders, then the smaller buffer."""
    best_key, best = None, buffer_range[0]
    for b in range(buffer_range[0], buffer_range[1] + 1):
        out = reminder_outcomes(y, pred, window, b)
        key = (out["hit_rate"], -out["too_late"], -b)
        if best_key is None or key > best_key:
            best_key, best = key, b
    return best


def fit_models(train: pd.DataFrame, cfg: dict) -> dict[str, TrainResult]:
    """Search + OOF predictions for every model family. Sees TRAIN rows only."""
    m = cfg["models"]
    X, y, groups = train[FEATURE_COLUMNS], train[TARGET], train[cfg["vehicle_col"]]
    results = {}
    for name, spec in model_specs(cfg["seed"]).items():
        search = search_model(spec, X, y, groups, m["cv_folds"], m["n_iter"], cfg["seed"])
        oof = oof_predictions(search.best_estimator_, X, y, groups, m["cv_folds"])
        results[name] = TrainResult(name, search.best_estimator_, search.best_params_, oof)
        print(f"  {name}: CV MAE {-search.best_score_:.2f}")
    return results


def baseline_validation(train: pd.DataFrame, cfg: dict) -> dict[str, pd.Series]:
    """B0 and B1 predictions on TRAIN, as validation for their buffers (B1 learns nothing)."""
    y, groups = train[TARGET], train[cfg["vehicle_col"]]
    b0 = oof_b0(y, groups, cfg["models"]["cv_folds"])
    b1 = predict_b1(train["route_km_per_day"], cfg["baselines"]["b1_interval_km"], b0)
    return {"B0 (median)": b0, f"B1 ({cfg['baselines']['b1_interval_km']:,} km)": b1}


def validate(train: pd.DataFrame, cfg: dict) -> tuple[dict[str, TrainResult], dict[str, dict], dict[str, int], str]:
    """Everything decided on TRAIN: models, validation scores, buffers, best model."""
    window = tuple(cfg["reminder"]["window_days_early"])
    buffer_range = tuple(cfg["models"]["buffer_range_days"])
    y = train[TARGET]
    models = fit_models(train, cfg)
    val_preds = baseline_validation(train, cfg) | {n: r.oof for n, r in models.items()}
    buffers = {n: tune_buffer(y, p, window, buffer_range) for n, p in val_preds.items()}
    val_scores = {n: score(y, p, window, buffers[n]) for n, p in val_preds.items()}
    for name, r in models.items():
        r.buffer_days, r.oof_scores = buffers[name], val_scores[name]
    best = min(models, key=lambda n: val_scores[n]["MAE"])
    return models, val_scores, buffers, best


# ---------------------------------------------------------------------------
# Test (used once)
# ---------------------------------------------------------------------------

def predict_test(train: pd.DataFrame, test: pd.DataFrame, models: dict[str, TrainResult], cfg: dict
                     ) -> dict[str, pd.Series]:
    """Predictions of all five on the test rows (B0 = TRAIN median)."""
    b0 = predict_b0(train[TARGET], test.index)
    preds = {"B0 (median)": b0,
             f"B1 ({cfg['baselines']['b1_interval_km']:,} km)":
                 predict_b1(test["route_km_per_day"], cfg["baselines"]["b1_interval_km"], b0)}
    for name, r in models.items():
        preds[name] = pd.Series(r.estimator.predict(test[FEATURE_COLUMNS]), index=test.index)
    return preds


def bootstrap_mae_gain(y: pd.Series, pred: pd.Series, ref: pd.Series, groups: pd.Series, n: int, seed: int
                       ) -> tuple[float, float, float]:
    """MAE(ref) − MAE(pred) on test, with a 95% interval from resampling whole trucks.

    Positive = ``pred`` is better than ``ref``. Trucks, not visits, are resampled
    because visits of one truck are not independent.
    """
    err = pd.DataFrame({"g": groups.values, "a": (y - pred).abs().values, "r": (y - ref).abs().values})
    per_truck = err.groupby("g").agg(a=("a", "sum"), r=("r", "sum"), n=("a", "size"))
    rng = np.random.default_rng(seed)
    idx = rng.integers(0, len(per_truck), size=(n, len(per_truck)))
    a, r, cnt = (per_truck[c].to_numpy()[idx].sum(axis=1) for c in ("a", "r", "n"))
    diffs = (r - a) / cnt
    point = float((err["r"].mean()) - err["a"].mean())
    return point, float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def evaluate_on_test(train: pd.DataFrame, test: pd.DataFrame, models: dict[str, TrainResult],
                     buffers: dict[str, int], cfg: dict) -> tuple[dict[str, dict], dict[str, tuple]]:
    """Score all five on test with the buffers chosen on TRAIN; MAE gain vs B0 with intervals."""
    window = tuple(cfg["reminder"]["window_days_early"])
    preds = predict_test(train, test, models, cfg)
    y, groups = test[TARGET], test[cfg["vehicle_col"]]
    scores = {}
    for name, p in preds.items():
        scores[name] = score(y, p, window, buffers[name])
        scores[name]["hit_rate_no_buffer"] = reminder_outcomes(y, p, window, 0)["hit_rate"]
    b0 = preds["B0 (median)"]
    gains = {name: bootstrap_mae_gain(y, preds[name], b0, groups, cfg["models"]["bootstrap_resamples"], cfg["seed"])
             for name in preds if name != "B0 (median)"}
    return scores, gains


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _params_text(params: dict) -> str:
    """Best hyperparameters, short."""
    return ", ".join(f"{k.removeprefix('model__')}={v:.3g}" if isinstance(v, float)
                     else f"{k.removeprefix('model__')}={v}" for k, v in sorted(params.items()))


def build_report(cfg: dict, train: pd.DataFrame, test: pd.DataFrame, split, models: dict[str, TrainResult],
                 val_scores: dict, buffers: dict, best: str, test_scores: dict, gains: dict,
                 b1_check: str) -> str:
    """Whole Markdown report."""
    vc = cfg["vehicle_col"]
    window = cfg["reminder"]["window_days_early"]
    m = cfg["models"]
    test_table = results_table(test_scores)
    test_table.insert(1, "Buffer (days early)", [buffers[n] for n in test_scores])
    test_table["Hit rate, no buffer"] = [f"{test_scores[n]['hit_rate_no_buffer']:.1%}" for n in test_scores]
    val_table = results_table(val_scores)
    val_table.insert(1, "Buffer (days early)", [buffers[n] for n in val_scores])
    gain_rows = pd.DataFrame([{"vs B0": n, "MAE gain (days)": f"{g:+.2f}", "95% interval": f"{lo:+.2f} to {hi:+.2f}",
                               "Clearly better than B0?": "yes" if lo > 0 else ("worse" if hi < 0 else "no (interval includes 0)")}
                              for n, (g, lo, hi) in gains.items()])
    params_rows = pd.DataFrame([{"Model": n, "CV MAE (train)": f"{r.oof_scores['MAE']:.2f}",
                                 "Best hyperparameters": _params_text(r.best_params)} for n, r in models.items()])
    best_val, b0_val = val_scores[best], val_scores["B0 (median)"]
    best_test, b0_test = test_scores[best], test_scores["B0 (median)"]
    g, lo, hi = gains[best]
    if lo > 0:
        verdict = (f"**{best} beats B0** on test: MAE {best_test['MAE']:.1f} vs {b0_test['MAE']:.1f} days "
                   f"(gain {g:+.2f}, 95% interval {lo:+.2f} to {hi:+.2f}).")
    else:
        verdict = (f"**No model clearly beats B0.** The best model ({best}) has test MAE "
                   f"{best_test['MAE']:.1f} vs B0 {b0_test['MAE']:.1f} days; the 95% interval of the gain "
                   f"({lo:+.2f} to {hi:+.2f} days) includes 0, so the difference may be noise.")
    return f"""# ML results (Task 2.3b)

Generated by `python -m src.ml.train` from `configs/ml.yaml` (seed {cfg['seed']}).
Data: **SYNTHETIC** (`{cfg['input']}`). Same split as docs/ml_baselines.md
(`make_split`: cutoff {split.cutoff:%Y-%m-%d}; train {len(train):,} visits / {train[vc].nunique()} trucks,
test {len(test):,} visits / {test[vc].nunique()} trucks; no truck in both).

## Verdict

{verdict}

## 1. B1 check: does route km/day include waiting? (brief step 1)

{b1_check}

## 2. How the models were chosen (TRAIN only)

- Features: `src/common/features.py` ({len(FEATURE_COLUMNS)} columns; vehicle model and oil grade not used).
  Categories one-hot; numbers median-filled with "was empty" flags (fitted inside each fold).
- RandomizedSearchCV, {m['n_iter']} draws per model, GroupKFold({m['cv_folds']}) by truck, scored by MAE.
- Validation = out-of-fold predictions on TRAIN (each visit predicted without its truck).
  **Best model = lowest validation MAE → {best}.** Test was not looked at for this choice.
- Reminder buffer per model (B0 and B1 too) = days early that maximize the validation hit
  rate (range {m['buffer_range_days'][0]}–{m['buffer_range_days'][1]} days; ties → fewer late reminders).

{_md_table(params_rows)}

Validation (TRAIN, out-of-fold):

{_md_table(val_table)}

## 3. Results on the test split ({len(test)} visits, {test[vc].nunique()} trucks)

![Results](figures/{CHART})

{_md_table(test_table)}

Hit = reminder arrives {window[0]}–{window[1]} days before the actual visit (D-036/D-049),
sent on predicted day − buffer. "Hit rate, no buffer" = same prediction sent on the predicted day.

**MAE difference vs B0 on test** (positive = better than B0; 95% interval from
{m['bootstrap_resamples']:,} resamples of whole test trucks):

{_md_table(gain_rows)}

## 4. Reading

- Best model on validation: **{best}** (validation MAE {best_val['MAE']:.2f} vs B0 {b0_val['MAE']:.2f}).
- On this synthetic data the truck's history features are weak (|r| ≤ 0.16, task 2.1),
  so a large gain over a fixed interval was not expected (RISK-13). Per D-050 the generator
  was NOT changed to make ML win; the next step is calibrating it to the real repeat-truck
  intervals (1.4b) and reporting before/after.
- The buffer matters as much as the model for the business metric: compare "Hit rate,
  no buffer" with the tuned column.
- Test has {len(test)} visits from {test[vc].nunique()} trucks; read small differences with the intervals above.
- Saved: `{m['model_dir']}/{MODEL_FILE}` (git-ignored) = {best} pipeline + its buffer
  ({buffers[best]} days) + feature list. SHAP is task 2.4.
"""


def b1_check_text(cfg: dict) -> str:
    """Brief step 1 as text (numbers from the Monte Carlo check run in task 2.3b, see handoff)."""
    return (
        "Yes. `route_table` → `formula_days_at_midpoints` adds the middle waiting days "
        "(2.5 per round trip) to the middle driving days, exactly like the generator adds "
        "waiting to every trip. Checked against the generator itself (its own `draw_trip` / "
        "`simulate_interval`, 4,000 trips and 3,000 on-time intervals per destination, no "
        "records): per-trip km/day agrees within ~3 % (Beijing 502 formula vs 486 generator), and "
        "with route switching (V6) turned off, B1 at 17,500 km equals the generator's median "
        "on-time interval (Beijing 35 = 35, Kyakhta 81 = 81). **Not a bug.** The Beijing gap "
        "(B1 35 vs actual ~54 days) comes from V6: a truck changes route between oil changes, so "
        "every destination drifts toward the fleet average (Beijing 35 → 44, Russian border 82 → 57 "
        "with V6 on), plus late visits on top. Official B1 switched to "
        f"{cfg['baselines']['b1_interval_km']:,} km (D-049)."
    )


def save_model(result: TrainResult, cfg: dict, split) -> Path:
    """Best pipeline + buffer + feature list -> models/ (git-ignored)."""
    out = Path(cfg["models"]["model_dir"])
    out.mkdir(parents=True, exist_ok=True)
    meta = {"model": result.name, "buffer_days": result.buffer_days, "features": FEATURE_COLUMNS,
            "target": TARGET, "window_days_early": cfg["reminder"]["window_days_early"],
            "best_params": {k: (v.item() if hasattr(v, "item") else v) for k, v in result.best_params.items()},
            "split_cutoff": f"{split.cutoff:%Y-%m-%d}", "seed": cfg["seed"], "data": cfg["input"]}
    joblib.dump({"pipeline": result.estimator, **meta}, out / MODEL_FILE)
    (out / MODEL_FILE.replace(".joblib", ".json")).write_text(json.dumps(meta, indent=2), encoding="utf-8")
    return out / MODEL_FILE


def main(argv: list[str] | None = None) -> int:
    """Tune on TRAIN, then score all five on test once, write report, chart and model."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/ml.yaml"))
    args = parser.parse_args(argv)

    cfg = load_ml_config(args.config)
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    train, test = df.loc[split.train], df.loc[split.test]

    print("tuning on TRAIN ...")
    models, val_scores, buffers, best = validate(train, cfg)
    print(f"best on validation: {best}; buffers {buffers}")

    test_scores, gains = evaluate_on_test(train, test, models, buffers, cfg)
    plot_baselines(test_scores, tuple(cfg["reminder"]["window_days_early"]), Path(cfg["figures_dir"]) / CHART,
                   outcome_title="Reminder outcome on test (buffer tuned on train)")
    text = build_report(cfg, train, test, split, models, val_scores, buffers, best, test_scores, gains,
                        b1_check_text(cfg))
    Path(cfg["models"]["results_path"]).write_text(text, encoding="utf-8")
    path = save_model(models[best], cfg, split)
    print(results_table(test_scores).to_string(index=False))
    print(f"report -> {cfg['models']['results_path']}, model -> {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
