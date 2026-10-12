"""Explain the models and finish the evaluation (Task 2.4) -> docs/ml_evaluation.md + charts.

Parts (brief 2.4):
1. SHAP for Ridge (linear) and XGBoost (tree): summary plots + one example truck.
2. D-038 check: generator variation OFF (separate in-memory run, rules unchanged) -> retrain -> ML ≈ B1?
3. Status classes OK / due soon / overdue (D-007): F1 + ROC-AUC for all five predictors.
4. Reminder hit rate with the 1–14 day window (D-051, configurable); buffers retuned on validation.
5. Save Ridge as the serving model (configs/ml.yaml models.serving_model).

Honesty rules are the same as src/ml/train.py: everything is chosen on TRAIN
(out-of-fold predictions); test is only scored. Nothing here reads data/raw/.

Usage:
    python -m src.ml.evaluate        # ~10–15 min: trains the three models three times
"""

from __future__ import annotations

import argparse
import copy
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.linear_model import LinearRegression  # noqa: E402
from sklearn.metrics import f1_score, mean_absolute_error, roc_auc_score  # noqa: E402

from src.common.features import FEATURE_COLUMNS  # noqa: E402
from src.data.generator import generate_clean  # noqa: E402
from src.data.generator import load_config as load_generator_config  # noqa: E402
from src.ml import explain as X  # noqa: E402
from src.ml.baselines import (  # noqa: E402
    BLUE,
    ORANGE,
    SURFACE,
    TEXT,
    TEXT_MUTED,
    _md_table,
    plot_baselines,
    predict_b1,
    regression_metrics,
    reminder_outcomes,
    results_table,
    score,
)
from src.ml.dataset import TARGET, build_dataset, build_dataset_from_records, load_ml_config, make_split  # noqa: E402
from src.ml.train import (  # noqa: E402
    MODEL_FILE,
    TrainResult,
    baseline_validation,
    bootstrap_mae_gain,
    predict_test,
    save_model,
    tune_buffer,
    validate,
)

STATUSES = ("ok", "due_soon", "overdue")
FIG = {"shap_ridge": "ml_shap_ridge.png", "shap_xgb": "ml_shap_xgboost.png", "shap_imp": "ml_shap_importance.png",
       "shap_example": "ml_shap_example.png", "d038": "ml_d038_variation_off.png", "status": "ml_status.png",
       "reminder": "ml_reminder.png"}
B1_REFIT = "B1 refit (a·B1+b)"


# ---------------------------------------------------------------------------
# Part 3: status classes (D-007)
# ---------------------------------------------------------------------------

def status_of(days_left, due_soon_days: int) -> np.ndarray:
    """D-007: overdue if < 0 days left, due soon if 0..due_soon_days, else OK."""
    d = np.asarray(days_left, dtype=float)
    return np.where(d < 0, "overdue", np.where(d <= due_soon_days, "due_soon", "ok"))


def status_checks(y: pd.Series, pred: pd.Series, every: int, after_due: int) -> pd.DataFrame:
    """One row per (visit, check day t): true and predicted days left on day t after the service.

    t = 0, every, 2·every, ... up to the actual next visit + ``after_due`` days.
    True due date = actual next visit (the only due date we observe, on real data too).
    Predicted due date = round(prediction), the date the vehicle card shows (no reminder buffer).
    """
    rows = []
    for idx, yi, pi in zip(y.index, y.to_numpy(dtype=float), np.round(pred.to_numpy(dtype=float))):
        for t in range(0, int(yi) + after_due + 1, every):
            rows.append((idx, t, yi - t, pi - t))
    return pd.DataFrame(rows, columns=["row", "t", "true_left", "pred_left"])


def _auc(truth: np.ndarray, score_: np.ndarray) -> float:
    """ROC-AUC, NaN when only one class is present."""
    return float(roc_auc_score(truth, score_)) if 0 < truth.sum() < len(truth) else float("nan")


def status_metrics(checks: pd.DataFrame, due_soon_days: int) -> dict[str, float]:
    """F1 per class + macro, and three ROC-AUCs. Score for AUC = days past the predicted date.

    - auc_overdue: overdue vs not, all check days pooled. Elapsed time alone already
      ranks well here (B0 gets a high value too), so read it together with:
    - auc_overdue_same_day: same, but only comparing trucks on the SAME check day
      (mean over check days, weighted by rows). A constant prediction (B0) scores 0.5.
    - auc_attention: "due soon or overdue" vs OK (who needs a reminder), pooled.
    """
    true = status_of(checks["true_left"], due_soon_days)
    pred = status_of(checks["pred_left"], due_soon_days)
    f1 = f1_score(true, pred, labels=list(STATUSES), average=None, zero_division=0)
    score_ = -checks["pred_left"].to_numpy()
    same_day, weights = [], []
    for _, g in checks.groupby("t"):
        a = _auc((g["true_left"] < 0).to_numpy(), -g["pred_left"].to_numpy())
        if not np.isnan(a):
            same_day.append(a)
            weights.append(len(g))
    return {
        **{f"f1_{s}": float(v) for s, v in zip(STATUSES, f1)},
        "f1_macro": float(np.mean(f1)),
        "accuracy": float(np.mean(true == pred)),
        "auc_overdue": _auc((checks["true_left"] < 0).to_numpy(), score_),
        "auc_overdue_same_day": float(np.average(same_day, weights=weights)) if same_day else float("nan"),
        "auc_attention": _auc((checks["true_left"] <= due_soon_days).to_numpy(), score_),
    }


def class_shares(checks: pd.DataFrame, due_soon_days: int) -> dict[str, float]:
    """Share of check rows in each TRUE class (how balanced the classification problem is)."""
    true = pd.Series(status_of(checks["true_left"], due_soon_days))
    return {s: float((true == s).mean()) for s in STATUSES}


# ---------------------------------------------------------------------------
# Part 4: reminder window
# ---------------------------------------------------------------------------

def bootstrap_rate_gain(a: np.ndarray, b: np.ndarray, groups: pd.Series, n: int, seed: int
                        ) -> tuple[float, float, float]:
    """mean(a) − mean(b) for 0/1 outcomes, 95% interval from resampling whole trucks."""
    df = pd.DataFrame({"g": groups.to_numpy(), "a": a.astype(float), "b": b.astype(float)})
    per = df.groupby("g").agg(a=("a", "sum"), b=("b", "sum"), n=("a", "size"))
    idx = np.random.default_rng(seed).integers(0, len(per), size=(n, len(per)))
    sa, sb, cnt = (per[c].to_numpy()[idx].sum(axis=1) for c in ("a", "b", "n"))
    diffs = (sa - sb) / cnt
    return float(df["a"].mean() - df["b"].mean()), float(np.percentile(diffs, 2.5)), float(np.percentile(diffs, 97.5))


def hits(y: pd.Series, pred: pd.Series, window: tuple[int, int], buffer_days: int) -> np.ndarray:
    """1 where the reminder lands inside the window (same rule as baselines.reminder_outcomes)."""
    lead = y.to_numpy(dtype=float) - (np.round(pred.to_numpy(dtype=float)) - buffer_days)
    return (lead >= window[0]) & (lead <= window[1])


def buffers_for_window(train: pd.DataFrame, models: dict[str, TrainResult], cfg: dict,
                       window: tuple[int, int]) -> dict[str, int]:
    """Buffer per predictor for another window, tuned on the same TRAIN out-of-fold predictions."""
    val = baseline_validation(train, cfg) | {n: r.oof for n, r in models.items()}
    rng = tuple(cfg["models"]["buffer_range_days"])
    return {n: tune_buffer(train[TARGET], p, window, rng) for n, p in val.items()}


# ---------------------------------------------------------------------------
# Part 2: D-038 variation-off check
# ---------------------------------------------------------------------------

def generated_records(gen_cfg: dict, variation: bool) -> pd.DataFrame:
    """Generator CLEAN records in memory with variation on/off. Writes no file; ``gen_cfg`` is not changed.

    Only the D-038 master switch ``variation.enabled`` differs; every rule and number stays
    as in configs/generator.yaml. No noise/cleaning step, so ON vs OFF differ ONLY by variation.
    """
    cfg = copy.deepcopy(gen_cfg)
    cfg["variation"]["enabled"]["value"] = variation
    clean = generate_clean(cfg)
    rec = clean.assign(vehicle_key=[f"V{i:04d}" for i in clean["vehicle_id"]],
                       service_date=pd.to_datetime(clean["service_date"]))
    return rec[["record_id", "vehicle_key", "service_date", "odometer_km", "destination_name", "route"]]


def b1_refit(train: pd.DataFrame, test: pd.DataFrame, cfg: dict) -> pd.Series:
    """B1 with a straight line fitted on TRAIN: a·B1 + b. Learns B1's average offset (e.g. late visits).

    Diagnostic for D-038: what the route formula achieves once its overall bias is removed.
    """
    km = cfg["baselines"]["b1_interval_km"]
    b0 = float(train[TARGET].median())
    b1_train = predict_b1(train["route_km_per_day"], km, pd.Series(b0, index=train.index))
    a, b = np.polyfit(b1_train.to_numpy(), train[TARGET].to_numpy(dtype=float), deg=1)
    return a * predict_b1(test["route_km_per_day"], km, pd.Series(b0, index=test.index)) + b


# What B1 cannot know but the features carry legitimately (D-038 "what explains the gap").
GAP_REFERENCES = {
    "B1 refit + season": ["b1", "season"],
    "B1 refit + n_prior_visits": ["b1", "n_prior_visits"],
    "destination means + season + n_prior_visits": ["destination_name", "season", "n_prior_visits"],
}


def _gap_design(d: pd.DataFrame, cols: list[str], km: float) -> pd.DataFrame:
    """Small design matrix: B1 days, one-hot categories, raw numbers."""
    parts = []
    for c in cols:
        if c == "b1":
            parts.append((km / d["route_km_per_day"]).rename("b1").to_frame())
        elif c in ("destination_name", "season"):
            parts.append(pd.get_dummies(d[c], prefix=c, dtype=float))
        else:
            parts.append(d[[c]].astype(float))
    return pd.concat(parts, axis=1)


def gap_references(train: pd.DataFrame, test: pd.DataFrame, cfg: dict) -> dict[str, pd.Series]:
    """Plain least-squares fits on TRAIN (nothing tuned), predictions on test.

    Only meaningful on the generator's clean data (every visit has a destination).
    """
    km = cfg["baselines"]["b1_interval_km"]
    out = {}
    for name, cols in GAP_REFERENCES.items():
        Xtr = _gap_design(train, cols, km)
        Xte = _gap_design(test, cols, km).reindex(columns=Xtr.columns, fill_value=0.0)
        out[name] = pd.Series(LinearRegression().fit(Xtr, train[TARGET]).predict(Xte), index=test.index)
    return out


@dataclass
class VariationRun:
    """Test results of one generator setting."""

    label: str
    n_train: int
    n_test: int
    test_trucks: int
    best: str
    metrics: dict[str, dict[str, float]]
    gain_vs_b1: dict[str, tuple[float, float, float]]
    gain_vs_refit: dict[str, tuple[float, float, float]]
    gap_refs: dict[str, tuple[float, tuple[float, float, float]]]   # name -> (test MAE, gain vs B1 refit)
    gain_vs_explained: dict[str, tuple[float, float, float]]        # ML vs the last gap reference


def run_variation(cfg: dict, gen_cfg: dict, variation: bool) -> VariationRun:
    """Same pipeline as the main run (make_split, validate on TRAIN, test once) on in-memory data."""
    df, _ = build_dataset_from_records(generated_records(gen_cfg, variation), cfg)
    split = make_split(df, cfg)
    train, test = df.loc[split.train], df.loc[split.test]
    models, _, _, best = validate(train, cfg)
    preds = predict_test(train, test, models, cfg)
    b1 = next(n for n in preds if n.startswith("B1"))
    preds = {n: preds[n] for n in ("B0 (median)", b1)} | {B1_REFIT: b1_refit(train, test, cfg)} | \
        {n: preds[n] for n in models}
    y, groups = test[TARGET], test[cfg["vehicle_col"]]
    n, seed = cfg["models"]["bootstrap_resamples"], cfg["seed"]
    refs = gap_references(train, test, cfg)
    explained = refs[list(GAP_REFERENCES)[-1]]
    return VariationRun(
        label="ON" if variation else "OFF", n_train=len(train), n_test=len(test),
        test_trucks=test[cfg["vehicle_col"]].nunique(), best=best,
        metrics={k: regression_metrics(y, p) for k, p in preds.items()},
        gain_vs_b1={k: bootstrap_mae_gain(y, preds[k], preds[b1], groups, n, seed) for k in [B1_REFIT, *models]},
        gain_vs_refit={k: bootstrap_mae_gain(y, preds[k], preds[B1_REFIT], groups, n, seed) for k in models},
        gap_refs={k: (float(mean_absolute_error(y, p)), bootstrap_mae_gain(y, p, preds[B1_REFIT], groups, n, seed))
                  for k, p in refs.items()},
        gain_vs_explained={k: bootstrap_mae_gain(y, preds[k], explained, groups, n, seed) for k in models},
    )


# ---------------------------------------------------------------------------
# Check behind the top SHAP feature: is n_prior_visits a truck property or a calendar effect?
# ---------------------------------------------------------------------------

def censoring_check(train: pd.DataFrame, gen_cfg: dict, vehicle_col: str) -> dict:
    """Numbers for the report: n_prior_visits vs date and target on TRAIN, and vs the generator's truth.

    Truth = generator clean records (same seed as the file), per vehicle: does the number of
    visits follow the truck's real pace (speed × hours) or lateness? If not, n_prior_visits
    carries calendar/censoring information, not a truck property.
    """
    date_num = train["service_date"].map(pd.Timestamp.toordinal)
    quarter = pd.qcut(date_num, 4, labels=["Q1 (earliest)", "Q2", "Q3", "Q4 (latest)"])
    clean = generate_clean(gen_cfg)
    veh = clean.groupby("vehicle_id").agg(n=("record_id", "size"), speed=("veh_speed_kmh", "first"),
                                          hours=("veh_hours_per_day", "first"), late=("veh_late_prob", "first"))
    return {
        "corr_date": float(train["n_prior_visits"].corr(date_num)),
        "corr_target": float(train["n_prior_visits"].corr(train[TARGET])),
        "median_by_quarter": train.groupby(quarter, observed=True)[TARGET].median().to_dict(),
        "corr_truth_pace": float(veh["n"].corr(veh["speed"] * veh["hours"])),
        "corr_truth_late": float(veh["n"].corr(veh["late"])),
    }


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def plot_variation(runs: list[VariationRun], path: Path) -> None:
    """Test MAE per predictor, variation ON (blue) vs OFF (orange)."""
    names = list(runs[0].metrics)
    y = np.arange(len(names))
    h = 0.38
    fig, ax = plt.subplots(figsize=(9, 4.2), facecolor=SURFACE)
    for k, (run, color) in enumerate(zip(runs, (BLUE, ORANGE))):
        vals = [run.metrics[n]["MAE"] for n in names]
        ax.barh(y + (k - 0.5) * h, vals, height=h - 0.04, color=color, label=f"variation {run.label}")
        for yi, v in zip(y, vals):
            ax.text(v + 0.2, yi + (k - 0.5) * h, f"{v:.1f}", va="center", color=TEXT, fontsize=8)
    ax.set_yticks(y, names)
    ax.invert_yaxis()
    ax.set_xlabel("Test MAE (days, lower is better)", color=TEXT_MUTED, fontsize=9)
    ax.set_title("D-038 check: generator variation ON vs OFF (OFF: ML should ≈ B1)", color=TEXT,
                 fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="lower right")
    X._style(ax)
    fig.tight_layout()
    fig.subplots_adjust(top=0.88)
    X._save(fig, path)


def plot_status(metrics: dict[str, dict[str, float]], path: Path) -> None:
    """Two panels: macro F1 and same-day ROC-AUC (overdue) per predictor, single hue each."""
    names = list(metrics)
    y = np.arange(len(names))
    fig, axes = plt.subplots(1, 2, figsize=(11, 3.6), facecolor=SURFACE)
    for ax, key, title in ((axes[0], "f1_macro", "Macro F1, OK / due soon / overdue (higher is better)"),
                           (axes[1], "auc_overdue_same_day", "ROC-AUC overdue, same check day (0.5 = guessing)")):
        vals = [metrics[n][key] for n in names]
        ax.barh(y, vals, color=BLUE, height=0.5)
        for yi, v in zip(y, vals):
            ax.text(v + 0.01, yi, f"{v:.2f}", va="center", color=TEXT, fontsize=9)
        ax.set_yticks(y, names)
        ax.invert_yaxis()
        ax.set_xlim(0, 1.05)
        ax.set_title(title, color=TEXT, fontsize=10, loc="left")
        X._style(ax)
    fig.tight_layout()
    fig.subplots_adjust(top=0.84)
    X._save(fig, path)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _gain_rows(gains: dict[str, tuple[float, float, float]], ref: str) -> pd.DataFrame:
    """MAE gain table: positive = better than ``ref``."""
    def verdict(lo: float, hi: float) -> str:
        return "better" if lo > 0 else ("worse" if hi < 0 else "≈ (interval includes 0)")
    return pd.DataFrame([{f"vs {ref}": n, "MAE gain (days)": f"{g:+.2f}", "95% interval": f"{lo:+.2f} to {hi:+.2f}",
                          "Result": verdict(lo, hi)} for n, (g, lo, hi) in gains.items()])


def _metric_rows(run: VariationRun) -> pd.DataFrame:
    return pd.DataFrame([{"Predictor": n, "RMSE": f"{m['RMSE']:.1f}", "MAE": f"{m['MAE']:.1f}", "R²": f"{m['R2']:.2f}"}
                         for n, m in run.metrics.items()])


def _status_rows(metrics: dict[str, dict[str, float]]) -> pd.DataFrame:
    return pd.DataFrame([{"Predictor": n, "F1 OK": f"{m['f1_ok']:.2f}", "F1 due soon": f"{m['f1_due_soon']:.2f}",
                          "F1 overdue": f"{m['f1_overdue']:.2f}", "Macro F1": f"{m['f1_macro']:.2f}",
                          "Accuracy": f"{m['accuracy']:.1%}", "ROC-AUC overdue (pooled)": f"{m['auc_overdue']:.3f}",
                          "ROC-AUC overdue (same day)": f"{m['auc_overdue_same_day']:.3f}",
                          "ROC-AUC needs reminder": f"{m['auc_attention']:.3f}"} for n, m in metrics.items()])


def _example_table(row: pd.Series, preds: dict[str, float], actual: float) -> pd.DataFrame:
    vals = [{"Item": f, "Value": (f"{row[f]:.2f}" if isinstance(row[f], float) else str(row[f]))} for f in FEATURE_COLUMNS]
    vals += [{"Item": f"prediction: {n}", "Value": f"{p:.1f} days"} for n, p in preds.items()]
    vals.append({"Item": "actual days to next oil change", "Value": f"{actual:.0f}"})
    return pd.DataFrame(vals)


@dataclass
class MainRun:
    """Everything from the main (cleaned CSV) run needed by the report."""

    cfg: dict
    split: object
    train: pd.DataFrame
    test: pd.DataFrame
    models: dict[str, TrainResult]
    best: str
    buffers: dict[str, int]
    test_scores: dict[str, dict]
    hit_gains: dict[str, tuple[float, float, float]]
    sensitivity: dict[tuple[int, int], tuple[dict[str, int], dict[str, float]]]
    status: dict[str, dict[str, float]]
    shares: dict[str, float]
    n_checks: int
    importance: dict[str, pd.Series]
    additivity: dict[str, float]
    example: tuple
    model_path: Path
    censoring: dict


def build_report(r: MainRun, runs: list[VariationRun]) -> str:
    """Whole Markdown report."""
    cfg, vc = r.cfg, r.cfg["vehicle_col"]
    ev, window = cfg["evaluation"], tuple(cfg["reminder"]["window_days_early"])
    st = ev["status"]
    serving = cfg["models"]["serving_model"]
    order = next(iter(r.importance.values())).index
    imp = pd.DataFrame({n: s.reindex(order).map(lambda v: f"{v:.2f}") for n, s in r.importance.items()})
    imp = imp.reset_index(names="Feature")
    c = r.censoring
    quarters = ", ".join(f"{k} {v:.0f}" for k, v in c["median_by_quarter"].items())
    ex_row, ex_preds, ex_actual, ex_truck = r.example
    on, off = runs
    test_table = results_table(r.test_scores)
    test_table.insert(1, "Buffer (days early)", [r.buffers[n] for n in r.test_scores])
    test_table["Hit rate, no buffer"] = [f"{r.test_scores[n]['hit_rate_no_buffer']:.1%}" for n in r.test_scores]
    hit_rows = pd.DataFrame([{"vs B0": n, "Hit-rate gain": f"{g:+.1%}", "95% interval": f"{lo:+.1%} to {hi:+.1%}"}
                             for n, (g, lo, hi) in r.hit_gains.items()])
    sens_rows = []
    for w, (buf, hit) in r.sensitivity.items():
        sens_rows += [{"Window": f"{w[0]}–{w[1]} days", "Predictor": n, "Buffer": buf[n], "Test hit rate": f"{hit[n]:.1%}"}
                      for n in buf]
    best_off, tol = off.best, ev["d038_tolerance_days"]
    g_off, lo_off, hi_off = off.gain_vs_refit[best_off]
    d038_verdict = (
        f"**Passed (no sign of leakage).** Rule: with variation OFF, the best model on validation must not beat "
        f"the calibrated route formula by more than {tol} days MAE (tolerance in configs/ml.yaml, [ESTIMATE]). "
        f"Result: {best_off} gain = {g_off:+.2f} days (95% interval {lo_off:+.2f} to {hi_off:+.2f}). "
        + ("The interval includes 0: ML ≈ B1." if lo_off <= 0 <= hi_off else
           "The gain is small but real (interval excludes 0) — see reading for what B1 cannot know.")
        if hi_off <= tol else
        f"**Needs a look.** Rule: with variation OFF, the best model must not beat the calibrated route formula by "
        f"more than {tol} days MAE. Result: {best_off} gain = {g_off:+.2f} days (95% interval {lo_off:+.2f} to "
        f"{hi_off:+.2f}) — the upper end is above the tolerance."
    )
    return f"""# ML evaluation + explanation (Task 2.4)

Generated by `python -m src.ml.evaluate` from `configs/ml.yaml` (seed {cfg['seed']}).
**All numbers are on SYNTHETIC data** (generator task 1.3 + cleaning task 1.4), not on
Geo-Expert's customers; every chart says so. Real-record test: later (1.4b intervals, D-050).

Main run = same data and split as docs/ml_results.md (`make_split`: cutoff
{r.split.cutoff:%Y-%m-%d}; train {len(r.train):,} visits / {r.train[vc].nunique()} trucks, test
{len(r.test):,} visits / {r.test[vc].nunique()} trucks; no truck in both). Hyperparameters, best model and
every reminder buffer are chosen on TRAIN out-of-fold predictions (GroupKFold by truck); test is
only scored. Model choice on validation MAE: **{r.best}**. Serving model (PROJECT_STATE v2.1):
**{serving}**.

## 1. SHAP — what the models use (Ridge = linear, XGBoost = tree)

SHAP value = days a feature adds to (or removes from) one prediction, compared with the model's
average prediction. Base value + all SHAP values = the prediction (checked: largest error
Ridge {r.additivity['Ridge']:.1e} days, XGBoost {r.additivity['XGBoost']:.1e} days). Explained rows = the
{len(r.test)} test visits. Ridge: `shap.LinearExplainer`, train rows as background
(SHAP = coefficient × (value − train mean)); XGBoost: `shap.TreeExplainer`.

![SHAP Ridge](figures/{FIG['shap_ridge']})

![SHAP XGBoost](figures/{FIG['shap_xgb']})

Importance per original feature (mean |SHAP|, days; one-hot columns and "was empty" flags summed
into their feature):

![Importance](figures/{FIG['shap_imp']})

{_md_table(imp)}

**Example truck** ({ex_truck}; chosen as the visit, among trucks with ≥
{ev['shap']['example_min_prior_visits']} earlier visits, where Ridge moves furthest from its average — chosen from
predictions only, not from the actual answer):

![Example](figures/{FIG['shap_example']})

{_md_table(_example_table(ex_row, ex_preds, ex_actual))}

**Reading.**
- Both models put most weight on the truck's history (`n_prior_visits`, `km_per_day_hist`,
  `past_late_share`) and on the route (`one_way_km`, `route_km_per_day`, destination). Effects
  are small: the largest feature moves a prediction by ~{r.importance['Ridge'].iloc[0]:.0f} days on average,
  against a test MAE of ~{r.test_scores['Ridge']['MAE']:.0f} days — consistent with ML ≈ B0 (docs/ml_results.md).
- Ridge (linear) uses the pace from the odometer (`km_per_day_hist`) much more than XGBoost; XGBoost
  spreads its weight more over destination and season. Same data, different shapes of model.
- **Warning about the top feature, `n_prior_visits` (more visits → shorter prediction).** On TRAIN it
  correlates {c['corr_date']:+.2f} with the service date and {c['corr_target']:+.2f} with the target. In the generator's
  truth the number of visits is unrelated to a truck's real pace (r = {c['corr_truth_pace']:+.3f}) or lateness
  (r = {c['corr_truth_late']:+.3f}). Median target by service-date quarter of TRAIN: {quarters}.
  So the feature mostly tells the model *how late in the data window* a visit is: visits shortly
  before the split cutoff are only in TRAIN if their next visit came quickly (right-censoring), and
  the same happens near the end of the data for test. This is a property of how the data window is
  cut, not of the truck. **In real use it would shorten predictions for loyal trucks for no reason.**
  Fix proposal for PM (not done here, features.py is outside this brief): drop it or replace it with
  a 0/1 "has history" flag, and retrain.

## 2. D-038 check: generator variation OFF → ML must ≈ B1

Separate run, nothing in configs/generator.yaml changed: the generator's own D-038 switch
`variation.enabled` is set to false on an in-memory copy (V1 speed/hours per truck, V2 trip
noise, V5 per-truck lateness, V6 route switching off). Still on in both runs: on-time km
15k–20k, 40 % late visits, waiting 0–5 days per trip, season factor V3. Both runs use the
generator's clean records (no noise/cleaning step) so ON vs OFF differ ONLY by variation; same
features, split function, search and buffers as the main run.

`{B1_REFIT}` = B1 with a straight line fitted on TRAIN (removes B1's average offset, e.g. from late
visits, which B1 by design does not include). It is the fair "route formula" reference: an ML model
that only learned the route formula should land here.

{d038_verdict}

![D-038](figures/{FIG['d038']})

Variation **ON** (train {on.n_train:,} / test {on.n_test} visits, {on.test_trucks} test trucks; best on validation {on.best}):

{_md_table(_metric_rows(on))}

Variation **OFF** (train {off.n_train:,} / test {off.n_test} visits, {off.test_trucks} test trucks; best on validation {off.best}):

{_md_table(_metric_rows(off))}

MAE gain vs B1, variation OFF (positive = better than B1; 95% interval, whole test trucks resampled):

{_md_table(_gain_rows(off.gain_vs_b1, "B1"))}

MAE gain vs {B1_REFIT}:

| Run | {" | ".join(on.gain_vs_refit)} |
|---|{"---|" * len(on.gain_vs_refit)}
| variation ON | {" | ".join(f"{g:+.2f} ({lo:+.2f} to {hi:+.2f})" for g, lo, hi in on.gain_vs_refit.values())} |
| variation OFF | {" | ".join(f"{g:+.2f} ({lo:+.2f} to {hi:+.2f})" for g, lo, hi in off.gain_vs_refit.values())} |

**What explains the gap?** A model that only knew the route formula should land on `{B1_REFIT}`.
The ML models also see three things B1 does not: the season (V3 stays on in both runs), a
separate average per destination (the late-visit offset is the same number of days for every
route, which a·B1+b cannot fit), and `n_prior_visits` (calendar/censoring proxy, §1). Plain
least-squares fits on TRAIN with only those inputs (nothing tuned):

| Run | {" | ".join(GAP_REFERENCES)} |
|---|{"---|" * len(GAP_REFERENCES)}
| variation ON: test MAE (gain vs B1 refit) | {" | ".join(f"{m:.2f} ({g:+.2f}, {lo:+.2f} to {hi:+.2f})" for m, (g, lo, hi) in on.gap_refs.values())} |
| variation OFF: test MAE (gain vs B1 refit) | {" | ".join(f"{m:.2f} ({g:+.2f}, {lo:+.2f} to {hi:+.2f})" for m, (g, lo, hi) in off.gap_refs.values())} |

ML vs the last of these ("{list(GAP_REFERENCES)[-1]}"), MAE gain with 95% interval:

| Run | {" | ".join(on.gain_vs_explained)} |
|---|{"---|" * len(on.gain_vs_explained)}
| variation ON | {" | ".join(f"{g:+.2f} ({lo:+.2f} to {hi:+.2f})" for g, lo, hi in on.gain_vs_explained.values())} |
| variation OFF | {" | ".join(f"{g:+.2f} ({lo:+.2f} to {hi:+.2f})" for g, lo, hi in off.gain_vs_explained.values())} |

**Reading.** If the ML gain over B1 came from leakage, a three-input linear fit could not
reproduce it. Compare the two tables: the more of the ML gain the simple fit recovers, and the
closer ML is to it (interval including 0), the less room there is for leakage. The
rule above (tolerance set before the final run, not adjusted afterwards) is kept as it came out;
this section only explains it. The visible
items B1 lacks are legitimate inputs (season, destination) plus one that is an artefact of the data
window (`n_prior_visits`, §1) — the latter is the thing to fix.

## 3. Status classes OK / due soon / overdue (D-007)

Status on day t after a service: days left = predicted date − t. **OK** > {st['due_soon_days']} days left,
**due soon** 0–{st['due_soon_days']}, **overdue** < 0 (D-007). True status uses the actual next visit as the
due date (the only due date we observe). Each test visit is checked every {st['check_every_days']} days from
the service until {st['check_after_due_days']} days after its actual next visit → {r.n_checks:,} checks
(true classes: OK {r.shares['ok']:.0%}, due soon {r.shares['due_soon']:.0%}, overdue {r.shares['overdue']:.0%}).
Predicted date = round(prediction), as on the vehicle card (no reminder buffer).
ROC-AUC score = days past the predicted date.

![Status](figures/{FIG['status']})

{_md_table(_status_rows(r.status))}

How to read the three AUCs: **pooled** mixes check days, and elapsed time alone already tells
overdue from not (B0, one number for everyone, scores high too). **Same day** compares trucks on the
same check day only, so it measures what the model knows about each truck (B0 = 0.5 exactly).
**Needs reminder** = due soon or overdue vs OK. The check protocol (every {st['check_every_days']} days, until
+{st['check_after_due_days']}) is an [ESTIMATE] in configs/ml.yaml; it sets the class mix and therefore the F1 values —
compare the predictors with each other, not with numbers from other projects.

## 4. Reminder hit rate, window {window[0]}–{window[1]} days early (D-051)

Window status: PROPOSED in D-051 (PROJECT_STATE v2.2), Ari to confirm.

Hit = reminder arrives {window[0]}–{window[1]} days before the actual visit; sent on predicted day − buffer.
Buffers retuned for this window on TRAIN out-of-fold predictions (range
{cfg['models']['buffer_range_days'][0]}–{cfg['models']['buffer_range_days'][1]} days; ties → fewer late reminders). Window is
configurable: `reminder.window_days_early` in configs/ml.yaml.

![Reminder](figures/{FIG['reminder']})

{_md_table(test_table)}

Hit-rate difference vs B0 on test (95% interval, whole test trucks resampled):

{_md_table(hit_rows)}

Sensitivity: old window (D-049), buffers retuned on validation the same way:

{_md_table(pd.DataFrame(sens_rows))}

## 5. Serving model

`{r.model_path}` (git-ignored) = **{serving}** pipeline + buffer {r.buffers[serving]} days (tuned for the
{window[0]}–{window[1]} day window on validation) + feature list + metadata (`.json` next to it).
The API (task 4.3) loads this file and uses `src/common/features.py` for its inputs.
"""


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main_run(cfg: dict, gen_cfg: dict) -> MainRun:
    """Parts 1, 3, 4, 5 on the cleaned synthetic CSV."""
    ev = cfg["evaluation"]
    figs = Path(cfg["figures_dir"])
    window = tuple(cfg["reminder"]["window_days_early"])
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    train, test = df.loc[split.train], df.loc[split.test]
    print("main run: tuning on TRAIN ...")
    models, _, buffers, best = validate(train, cfg)
    preds = predict_test(train, test, models, cfg)
    y, groups = test[TARGET], test[cfg["vehicle_col"]]
    n, seed = cfg["models"]["bootstrap_resamples"], cfg["seed"]

    # Part 4: reminder window
    test_scores = {k: score(y, p, window, buffers[k]) | {"hit_rate_no_buffer": reminder_outcomes(y, p, window, 0)["hit_rate"]}
                   for k, p in preds.items()}
    b0_hits = hits(y, preds["B0 (median)"], window, buffers["B0 (median)"])
    hit_gains = {k: bootstrap_rate_gain(hits(y, p, window, buffers[k]), b0_hits, groups, n, seed)
                 for k, p in preds.items() if k != "B0 (median)"}
    sensitivity = {}
    for w in map(tuple, cfg["reminder"].get("sensitivity_windows", [])):
        buf = buffers_for_window(train, models, cfg, w)
        sensitivity[w] = (buf, {k: reminder_outcomes(y, p, w, buf[k])["hit_rate"] for k, p in preds.items()})
    plot_baselines(test_scores, window, figs / FIG["reminder"],
                   outcome_title="Reminder outcome on test (buffer tuned on validation)", synthetic_label=True)

    # Part 3: status classes
    st = ev["status"]
    status, checks = {}, None
    for k, p in preds.items():
        checks = status_checks(y, p, st["check_every_days"], st["check_after_due_days"])
        status[k] = status_metrics(checks, st["due_soon_days"])
    plot_status(status, figs / FIG["status"])

    # Part 1: SHAP
    exps, additivity = {}, {}
    for k in ("Ridge", "XGBoost"):
        pipe = models[k].estimator
        exps[k] = X.explain(k, pipe, train[FEATURE_COLUMNS], test[FEATURE_COLUMNS])
        additivity[k] = X.additivity_error(exps[k], pipe, test[FEATURE_COLUMNS])
    sub = f"{len(test)} test visits · one dot = one visit"
    X.plot_beeswarm(exps["Ridge"], figs / FIG["shap_ridge"], ev["shap"]["top_features"], sub)
    X.plot_beeswarm(exps["XGBoost"], figs / FIG["shap_xgb"], ev["shap"]["top_features"], sub)
    importance = {k: X.grouped_importance(e) for k, e in exps.items()}
    X.plot_grouped_importance(importance, figs / FIG["shap_imp"])
    row = X.pick_example_row(exps["Ridge"], test["n_prior_visits"], ev["shap"]["example_min_prior_visits"])
    trucks = sorted(test[cfg["vehicle_col"]].unique())  # neutral label: no plate-like key on a slide
    truck = f"test truck #{trucks.index(test.loc[row, cfg['vehicle_col']]) + 1} of {len(trucks)}"
    contribs = {k: (e.base_value, X.row_contributions(e, row), float(e.frame().loc[row].sum() + e.base_value))
                for k, e in exps.items()}
    X.plot_example(contribs, f"Example: {truck}, actual {y[row]:.0f} days to next oil change", figs / FIG["shap_example"])
    ex_preds = {k: float(preds[k][row]) for k in preds}

    # Part 5: serving model
    path = save_model(models[cfg["models"]["serving_model"]], cfg, split)
    return MainRun(cfg, split, train, test, models, best, buffers, test_scores, hit_gains, sensitivity, status,
                   class_shares(checks, st["due_soon_days"]), len(checks), importance, additivity,
                   (test.loc[row, FEATURE_COLUMNS], ex_preds, float(y[row]), truck), path,
                   censoring_check(train, gen_cfg, cfg["vehicle_col"]))


def main(argv: list[str] | None = None) -> int:
    """Run all parts and write docs/ml_evaluation.md + charts + the serving model."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/ml.yaml"))
    args = parser.parse_args(argv)
    cfg = load_ml_config(args.config)
    gen_cfg = load_generator_config(Path(cfg["generator_config"]))

    r = main_run(cfg, gen_cfg)
    runs = []
    for on in (True, False):
        print(f"D-038 run: variation {'ON' if on else 'OFF'} ...")
        runs.append(run_variation(cfg, gen_cfg, on))
    plot_variation(runs, Path(cfg["figures_dir"]) / FIG["d038"])
    report = Path(cfg["evaluation"]["report_path"])
    report.write_text(build_report(r, runs), encoding="utf-8")
    print(f"report -> {report}; serving model -> {r.model_path} ({MODEL_FILE})")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
