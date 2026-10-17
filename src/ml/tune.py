"""Honest tuning + noise floor + prediction range (Task 2.9).

Three commands, run in this order:

    python -m src.ml.tune cv       # TRAIN only: grids, Ridge+XGB average, keep rule -> models/tune_cv.joblib
    python -m src.ml.tune test     # ONCE: oracle, B0, B1, current Ridge, best tuned on test -> docs/ml_tuning.json
    python -m src.ml.tune report   # re-renders the 2.9 section of docs/ml_results.md + chart (no data read)

Rules (brief 2.9, D-093 fixed BEFORE results):
- Every choice is made with GroupKFold(5) by truck on TRAIN — the same folds as task 2.3b.
- Keep rule: a new served model only if its CV MAE beats the CURRENT served Ridge
  (models/next_change_model.joblib) by at least ``KEEP_MARGIN_DAYS``.
- ``test`` refuses to run a second time (marker file), whatever it showed.
- Features, generator and noise are not touched (features come from src/common/features.py).

Prediction range: 10th–90th percentile of the out-of-fold residuals (actual − predicted)
on TRAIN, added to the prediction ("≈ date (low – high)"). Coverage = share of test
visits whose actual day falls inside it (80% intended).
"""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import joblib
import numpy as np
import pandas as pd
from sklearn.base import clone
from sklearn.ensemble import RandomForestRegressor
from sklearn.linear_model import Ridge
from sklearn.model_selection import GridSearchCV, GroupKFold
from sklearn.pipeline import Pipeline

from src.common.features import FEATURE_COLUMNS
from src.data.generator import load_config as load_generator_config
from src.ml.baselines import _md_table, predict_b0, predict_b1
from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split
from src.ml.noise_floor import DEFAULT_SIMS, oracle_for_split, oracle_mae
from src.ml.train import MODEL_FILE, bootstrap_mae_gain, oof_b0, oof_predictions, preprocessor

KEEP_MARGIN_DAYS = 0.3  # D-093: fixed before any result of this task
RANGE_QUANTILES = (0.10, 0.90)  # prediction range = these residual percentiles (80% band)
BLEND_WEIGHTS = (0.0, 0.25, 0.5, 0.75, 1.0)  # weight of Ridge in w·Ridge + (1−w)·XGB
CV_FILE = "tune_cv.joblib"
TEST_MARKER = "tune_test_done.json"
RESULTS_JSON = Path("docs/ml_tuning.json")
CHART = "ml_noise_floor.png"
SECTION_START, SECTION_END = "<!-- task 2.9 start -->", "<!-- task 2.9 end -->"


# ---------------------------------------------------------------------------
# Grids (small on purpose: time box 1.5 h, ~1,750 train visits)
# ---------------------------------------------------------------------------

def grids(seed: int) -> dict[str, tuple[Pipeline, dict]]:
    """Ridge / Random Forest / XGBoost pipelines (same preprocessing as 2.3b) and their grids."""
    from xgboost import XGBRegressor  # lazy: see train.model_specs (libomp clash with torch)

    def pipe(model: object, scale: bool) -> Pipeline:
        return Pipeline([("prep", preprocessor(scale)), ("model", model)])

    return {
        "Ridge": (pipe(Ridge(), True), {"model__alpha": [0.1, 1, 3, 10, 30, 100, 300, 1000, 3000]}),
        "Random Forest": (pipe(RandomForestRegressor(n_estimators=300, random_state=seed, n_jobs=-1), False),
                          {"model__max_depth": [6, 10, None], "model__min_samples_leaf": [10, 30, 60],
                           "model__max_features": [0.3, 0.6]}),
        # objective: squared error predicts the MEAN, absolute error the MEDIAN — and MAE is scored.
        "XGBoost": (pipe(XGBRegressor(random_state=seed, n_jobs=4, tree_method="hist", subsample=0.8,
                                      colsample_bytree=0.8, min_child_weight=20), False),
                    {"model__objective": ["reg:squarederror", "reg:absoluteerror"],
                     "model__max_depth": [2, 3, 4], "model__learning_rate": [0.02, 0.05],
                     "model__n_estimators": [300, 600]}),
    }


# ---------------------------------------------------------------------------
# CV on TRAIN
# ---------------------------------------------------------------------------

@dataclass
class Candidate:
    """One tuned model: refit on all of TRAIN, its params and out-of-fold predictions."""

    name: str
    estimators: list  # 1 pipeline, or [Ridge, XGB] for the average
    weights: list[float]
    params: dict
    oof: pd.Series

    def predict(self, X: pd.DataFrame) -> np.ndarray:
        return sum(w * e.predict(X) for w, e in zip(self.weights, self.estimators))


def mae(y: pd.Series, pred: pd.Series) -> float:
    """Mean absolute error (days)."""
    return float((y - pred).abs().mean())


def residual_range(y: pd.Series, pred: pd.Series, quantiles: tuple[float, float] = RANGE_QUANTILES
                   ) -> tuple[float, float]:
    """(low, high) days to add to a prediction: percentiles of actual − predicted."""
    res = np.asarray(y, dtype=float) - np.asarray(pred, dtype=float)
    return float(np.quantile(res, quantiles[0])), float(np.quantile(res, quantiles[1]))


def coverage(y: pd.Series, pred: pd.Series, band: tuple[float, float]) -> float:
    """Share of rows with pred + low ≤ actual ≤ pred + high."""
    y, pred = np.asarray(y, dtype=float), np.asarray(pred, dtype=float)
    return float(np.mean((y >= pred + band[0]) & (y <= pred + band[1])))


def tune_family(pipeline: Pipeline, grid: dict, X: pd.DataFrame, y: pd.Series, groups: pd.Series,
                folds: int) -> GridSearchCV:
    """Grid search, GroupKFold by truck, scored by MAE; refits the best on all TRAIN."""
    search = GridSearchCV(pipeline, grid, cv=GroupKFold(n_splits=folds), scoring="neg_mean_absolute_error",
                          n_jobs=1)
    return search.fit(X, y, groups=groups)


def best_blend(y: pd.Series, ridge: Candidate, xgb: Candidate, weights=BLEND_WEIGHTS) -> tuple[float, pd.Series]:
    """Ridge weight with the lowest MAE of w·Ridge + (1−w)·XGB on out-of-fold predictions."""
    scored = [(mae(y, w * ridge.oof + (1 - w) * xgb.oof), w) for w in weights]
    _, w = min(scored)
    return w, w * ridge.oof + (1 - w) * xgb.oof


def keep_decision(current_cv: float, best_cv: float, margin: float = KEEP_MARGIN_DAYS) -> bool:
    """D-093: serve the new model only if CV MAE is lower by at least ``margin`` days."""
    return current_cv - best_cv >= margin


def run_cv(cfg: dict) -> dict:
    """Step 2 + range on TRAIN. Returns everything ``test`` needs (no test row is touched)."""
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    train = df.loc[split.train]
    X, y, groups = train[FEATURE_COLUMNS], train[TARGET], train[cfg["vehicle_col"]]
    folds = cfg["models"]["cv_folds"]

    current = joblib.load(Path(cfg["models"]["model_dir"]) / MODEL_FILE)
    current_oof = oof_predictions(current["pipeline"], X, y, groups, folds)
    cands: dict[str, Candidate] = {}
    for name, (pipeline, grid) in grids(cfg["seed"]).items():
        search = tune_family(pipeline, grid, X, y, groups, folds)
        oof = oof_predictions(search.best_estimator_, X, y, groups, folds)
        cands[name] = Candidate(name, [search.best_estimator_], [1.0], search.best_params_, oof)
        print(f"  {name}: CV MAE {mae(y, oof):.3f}  {search.best_params_}")
    w, blend_oof = best_blend(y, cands["Ridge"], cands["XGBoost"])
    cands["Ridge+XGB average"] = Candidate("Ridge+XGB average", [cands["Ridge"].estimators[0],
                                           cands["XGBoost"].estimators[0]], [w, 1 - w], {"ridge_weight": w},
                                           blend_oof)

    cv_mae = {n: mae(y, c.oof) for n, c in cands.items()}
    best = min(cv_mae, key=cv_mae.get)
    current_cv = mae(y, current_oof)
    b0_oof = oof_b0(y, groups, folds)
    b1_train = predict_b1(train["route_km_per_day"], cfg["baselines"]["b1_interval_km"], b0_oof)
    return {
        "split_cutoff": f"{split.cutoff:%Y-%m-%d}", "n_train": len(train), "n_train_trucks": int(groups.nunique()),
        "current": {"model": current["model"], "params": current["best_params"], "cv_mae": current_cv},
        "candidates": cands, "cv_mae": cv_mae, "best": best,
        "keep": keep_decision(current_cv, cv_mae[best]),
        "cv_mae_b0": mae(y, b0_oof), "cv_mae_b1": mae(y, b1_train),
        "ranges": {"current": residual_range(y, current_oof), "best": residual_range(y, cands[best].oof),
                   "b0": residual_range(y, b0_oof), "b1": residual_range(y, b1_train)},
        "train_coverage_current": coverage(y, current_oof, residual_range(y, current_oof)),
    }


# ---------------------------------------------------------------------------
# Test (once)
# ---------------------------------------------------------------------------

def run_test(cfg: dict, cv: dict, n_sims: int) -> dict:
    """Step 4: oracle, B0, B1, current Ridge and the best tuned model on test, once."""
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    if f"{split.cutoff:%Y-%m-%d}" != cv["split_cutoff"]:
        raise RuntimeError("split changed since `cv` was run")
    train, test = df.loc[split.train], df.loc[split.test]
    y, groups, X = test[TARGET], test[cfg["vehicle_col"]], test[FEATURE_COLUMNS]
    current = joblib.load(Path(cfg["models"]["model_dir"]) / MODEL_FILE)
    b0 = predict_b0(train[TARGET], test.index)
    best = cv["candidates"][cv["best"]]
    preds = {
        "Oracle (noise floor)": oracle_for_split(df, split, load_generator_config(Path(cfg["generator_config"])),
                                                 "test", n_sims, cfg["seed"]),
        "B0 (median)": b0,
        f"B1 ({cfg['baselines']['b1_interval_km']:,} km)": predict_b1(test["route_km_per_day"],
                                                                      cfg["baselines"]["b1_interval_km"], b0),
        f"Current {current['model']} (served)": pd.Series(current["pipeline"].predict(X), index=test.index),
        f"Best tuned: {cv['best']}": pd.Series(best.predict(X), index=test.index),
    }
    n_boot, seed = cfg["models"]["bootstrap_resamples"], cfg["seed"]
    rows = {}
    for name, p in preds.items():
        rows[name] = {"mae": oracle_mae(y, p) if name.startswith("Oracle") else mae(y, p),
                      "rmse": float(np.sqrt(((y - p) ** 2).mean())),
                      "gain_vs_b0": bootstrap_mae_gain(y, p, b0, groups, n_boot, seed)}
    served_name = f"Current {current['model']} (served)"
    tuned_name = f"Best tuned: {cv['best']}"
    return {
        "n_test": len(test), "n_test_trucks": int(groups.nunique()), "rows": rows, "n_sims": n_sims,
        "tuned_vs_current": bootstrap_mae_gain(y, preds[tuned_name], preds[served_name], groups, n_boot, seed),
        "coverage": {"current": coverage(y, preds[served_name], cv["ranges"]["current"]),
                     "best": coverage(y, preds[tuned_name], cv["ranges"]["best"]),
                     "b0": coverage(y, b0, cv["ranges"]["b0"])},
        "range_width_days": {k: v[1] - v[0] for k, v in cv["ranges"].items()},
        "run_date": date.today().isoformat(),
    }


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def cv_summary(cv: dict) -> dict:
    """JSON-safe part of the cv result (no estimators)."""
    return {"split_cutoff": cv["split_cutoff"], "n_train": cv["n_train"], "n_train_trucks": cv["n_train_trucks"],
            "current": cv["current"], "best": cv["best"], "keep": cv["keep"], "keep_margin_days": KEEP_MARGIN_DAYS,
            "cv_mae": cv["cv_mae"], "cv_mae_b0": cv["cv_mae_b0"], "cv_mae_b1": cv["cv_mae_b1"],
            "params": {n: {k.removeprefix("model__"): (v.item() if hasattr(v, "item") else v)
                           for k, v in c.params.items()} for n, c in cv["candidates"].items()},
            "ranges": cv["ranges"], "range_quantiles": list(RANGE_QUANTILES),
            "train_coverage_current": cv["train_coverage_current"]}


def plot_noise_floor(test: dict, path: Path) -> None:
    """One chart: test MAE per model, with the oracle as a dashed reference line."""
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    from src.ml.baselines import BLUE, GRID, ORANGE, SURFACE, TEXT, TEXT_MUTED, mark_synthetic

    rows = {n: r for n, r in test["rows"].items() if not n.startswith("Oracle")}
    floor = test["rows"]["Oracle (noise floor)"]["mae"]
    names = list(rows)
    vals = [rows[n]["mae"] for n in names]
    fig, ax = plt.subplots(figsize=(8, 3.4), facecolor=SURFACE)
    yy = np.arange(len(names))
    ax.barh(yy, vals, color=BLUE, height=0.5)
    for yi, v in zip(yy, vals):
        ax.text(v + 0.15, yi, f"{v:.1f}  (+{v - floor:.1f} above floor)", va="center", color=TEXT, fontsize=9)
    ax.axvline(floor, color=ORANGE, linestyle="--", linewidth=1.5)
    ax.text(floor + 0.15, -0.6, f"noise floor (oracle) {floor:.1f}", color=ORANGE, fontsize=9, va="center")
    ax.set_yticks(yy, names)
    ax.set_xlim(0, max(vals) * 1.5)
    ax.set_ylim(len(names) - 0.5, -0.9)  # room above the first bar for the floor label
    ax.set_title(f"Test MAE (days, lower is better) vs the best possible — {test['n_test']} visits",
                 color=TEXT, fontsize=10, loc="left")
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9)
    ax.grid(axis="x", color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    fig.tight_layout()
    fig.subplots_adjust(top=0.85)
    mark_synthetic(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE)
    plt.close(fig)


def _gain_text(g: list | tuple) -> str:
    return f"{g[0]:+.2f} ({g[1]:+.2f} to {g[2]:+.2f})"


def section_text(res: dict) -> str:
    """Markdown section for docs/ml_results.md from docs/ml_tuning.json."""
    cv, test = res["cv"], res["test"]
    floor = test["rows"]["Oracle (noise floor)"]["mae"]
    cv_rows = pd.DataFrame(
        [{"Model": f"Current {cv['current']['model']} (served)", "CV MAE (train)": f"{cv['current']['cv_mae']:.2f}",
          "Δ vs current": "—", "Parameters": f"alpha={cv['current']['params'].get('model__alpha', 0):.3g}"}]
        + [{"Model": n, "CV MAE (train)": f"{m:.2f}", "Δ vs current": f"{cv['current']['cv_mae'] - m:+.2f}",
            "Parameters": ", ".join(f"{k}={v:.3g}" if isinstance(v, float) else f"{k}={v}"
                                    for k, v in sorted(cv["params"][n].items()))}
           for n, m in cv["cv_mae"].items()]
        + [{"Model": "B0 (median)", "CV MAE (train)": f"{cv['cv_mae_b0']:.2f}", "Δ vs current": "—", "Parameters": "—"},
           {"Model": "B1 (17,500 km)", "CV MAE (train)": f"{cv['cv_mae_b1']:.2f}", "Δ vs current": "—",
            "Parameters": "—"}])
    test_rows = pd.DataFrame([{"Model": n, "MAE (days)": f"{r['mae']:.2f}", "RMSE (days)": f"{r['rmse']:.1f}",
                               "Above floor (days)": "—" if n.startswith("Oracle") else f"{r['mae'] - floor:+.2f}",
                               "MAE gain vs B0 (95% CI)": "—" if n == "B0 (median)" else _gain_text(r["gain_vs_b0"])}
                              for n, r in test["rows"].items()])
    rg = cv["ranges"]
    cov = test["coverage"]
    q = cv["range_quantiles"]
    served = f"Current {cv['current']['model']} (served)"
    gap_served = test["rows"][served]["mae"] - floor
    gap_b0 = test["rows"]["B0 (median)"]["mae"] - floor
    keep_text = (f"**KEPT: {cv['best']}** — CV MAE {cv['cv_mae'][cv['best']]:.2f} beats the served "
                 f"{cv['current']['model']} ({cv['current']['cv_mae']:.2f}) by ≥ {cv['keep_margin_days']} days."
                 if cv["keep"] else
                 f"**Not kept — the served {cv['current']['model']} stays.** Best tuned = {cv['best']}, CV MAE "
                 f"{cv['cv_mae'][cv['best']]:.2f} vs {cv['current']['cv_mae']:.2f} "
                 f"(Δ {cv['current']['cv_mae'] - cv['cv_mae'][cv['best']]:+.2f} days; rule needs ≥ "
                 f"+{cv['keep_margin_days']}).")
    return f"""{SECTION_START}
## 5. Task 2.9 — noise floor, honest tuning, prediction range

Generated by `python -m src.ml.tune` (cv → test once on {test['run_date']} → report). SYNTHETIC data, same
split as above (train {cv['n_train']:,} visits / {cv['n_train_trucks']} trucks, test {test['n_test']} visits /
{test['n_test_trucks']} trucks). Keep rule D-093, fixed before results: a new served model only if its
GroupKFold(5)-by-truck CV MAE on TRAIN beats the served model by ≥ {cv['keep_margin_days']} days.

**Noise floor (oracle).** A predictor that knows the generator's hidden truck values (speed, driving
hours, late chance), the true destination and the date, but not the random draws after the service
(on time/late, the km the driver changes at, trip noise, waiting, route switches). Its best guess for
MAE is the median of {test['n_sims']:,} re-simulations of `generator.simulate_interval` per visit
(src/ml/noise_floor.py; generator seed 42, not changed). No model with our features can be expected to beat it.

### 5.1 Tuning on TRAIN (GroupKFold by truck; test not used)

{_md_table(cv_rows)}

{keep_text}

### 5.2 Test, run once

![Noise floor](figures/{CHART})

{_md_table(test_rows)}

Best tuned vs served on test: MAE gain {_gain_text(test['tuned_vs_current'])} days (95% CI, whole trucks resampled).

Reading: the served model is **{gap_served:.1f} days above the noise floor**; B0 is {gap_b0:.1f} days above
it. Most of the error is randomness the generator adds after the service, which no model can predict.

### 5.3 Prediction range ("≈ date (low – high)")

Range = prediction + [{q[0]:.0%}, {q[1]:.0%}] percentiles of out-of-fold residuals on TRAIN
(an {q[1] - q[0]:.0%} band), per method: served model {rg['current'][0]:+.0f} / {rg['current'][1]:+.0f} days,
B0 {rg['b0'][0]:+.0f} / {rg['b0'][1]:+.0f}, B1 {rg['b1'][0]:+.0f} / {rg['b1'][1]:+.0f}.

| | Coverage on test (intended {q[1] - q[0]:.0%}) | Width (days) |
|---|---|---|
| Served model | {cov['current']:.1%} | {test['range_width_days']['current']:.0f} |
| Best tuned ({cv['best']}) | {cov['best']:.1%} | {test['range_width_days']['best']:.0f} |
| B0 | {cov['b0']:.1%} | {test['range_width_days']['b0']:.0f} |

The API returns the range for every method (`range_low_date`, `range_high_date`; contract v0.9);
the vehicle card shows "≈ date (low – high)".
{SECTION_END}"""


def write_section(text: str, path: Path) -> None:
    """Replace the 2.9 section in ``path`` (or append it). Rerunning train.py drops it → run ``report``."""
    doc = path.read_text(encoding="utf-8")
    if SECTION_START in doc:
        before, rest = doc.split(SECTION_START, 1)
        doc = before + text + rest.split(SECTION_END, 1)[1]
    else:
        doc = doc.rstrip("\n") + "\n\n" + text + "\n"
    path.write_text(doc, encoding="utf-8")


def report(cfg: dict) -> None:
    """Section + chart from docs/ml_tuning.json (no data read, test not re-run)."""
    res = json.loads(RESULTS_JSON.read_text(encoding="utf-8"))
    plot_noise_floor(res["test"], Path(cfg["figures_dir"]) / CHART)
    write_section(section_text(res), Path(cfg["models"]["results_path"]))


def main(argv: list[str] | None = None) -> int:
    """CLI: cv | test | report (see module docstring)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("step", choices=["cv", "test", "report"])
    parser.add_argument("--config", type=Path, default=Path("configs/ml.yaml"))
    parser.add_argument("--sims", type=int, default=DEFAULT_SIMS)
    args = parser.parse_args(argv)
    cfg = load_ml_config(args.config)
    model_dir = Path(cfg["models"]["model_dir"])

    if args.step == "cv":
        cv = run_cv(cfg)
        joblib.dump(cv, model_dir / CV_FILE)
        print(json.dumps(cv_summary(cv), indent=2, default=float))
    elif args.step == "test":
        marker = model_dir / TEST_MARKER
        if marker.exists():
            raise SystemExit(f"test was already run ({marker}); the brief allows ONE test run")
        cv = joblib.load(model_dir / CV_FILE)
        marker.write_text(json.dumps({"started": date.today().isoformat()}), encoding="utf-8")  # before scoring
        test = run_test(cfg, cv, args.sims)
        RESULTS_JSON.write_text(json.dumps({"cv": cv_summary(cv), "test": test}, indent=2, default=float),
                                encoding="utf-8")
        print(json.dumps(test, indent=2, default=float))
        report(cfg)
    else:
        report(cfg)
    return 0


if __name__ == "__main__":
    # Run from the imported module, not __main__, so pickled Candidates in models/tune_cv.joblib
    # point to src.ml.tune.Candidate and load in any process.
    from src.ml.tune import main as _main

    raise SystemExit(_main())
