"""Baselines B0 and B1 on the test split + docs/ml_baselines.md (Task 2.3a).

B0 (D-035): every prediction = median days_to_next_change of the TRAIN rows.
B1 (D-035): days = interval_km ÷ route km/day of the stated destination.
            Unknown destination -> B0 (same fallback the app uses, D-047).
The ML model (task 2.3b) must beat both on the same test split.

Metrics: RMSE, MAE, R² (course) and the reminder hit rate (D-036, business).

Usage:
    python -m src.ml.baselines            # writes docs/ml_baselines.md + chart
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window; write files only
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from sklearn.metrics import mean_absolute_error, mean_squared_error, r2_score  # noqa: E402

from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split  # noqa: E402

CHART = "ml_baselines.png"

# Reference palette (dataviz skill, light surface), same as src/data/synthetic_report.py.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
GRID = "#e4e3df"
BLUE = "#2a78d6"     # slot 1
ORANGE = "#eb6834"   # slot 2
AQUA = "#1baf7a"     # slot 3


# ---------------------------------------------------------------------------
# Predictions
# ---------------------------------------------------------------------------

def predict_b0(train_target: pd.Series, index: pd.Index) -> pd.Series:
    """Fixed interval: the median train interval for every row."""
    return pd.Series(float(train_target.median()), index=index, name="B0")


def predict_b1(route_km_per_day: pd.Series, interval_km: float, fallback: pd.Series) -> pd.Series:
    """interval_km ÷ route km/day; rows without a known route take ``fallback`` (B0)."""
    days = interval_km / route_km_per_day
    return days.where(route_km_per_day.notna() & (route_km_per_day > 0), fallback).rename("B1")


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

def regression_metrics(y: pd.Series, pred: pd.Series) -> dict[str, float]:
    """RMSE, MAE (days) and R²."""
    return {
        "RMSE": float(np.sqrt(mean_squared_error(y, pred))),
        "MAE": float(mean_absolute_error(y, pred)),
        "R2": float(r2_score(y, pred)),
    }


def reminder_outcomes(y: pd.Series, pred: pd.Series, window: tuple[int, int], buffer_days: int = 0
                      ) -> dict[str, float]:
    """Shares of reminders that are a hit, too early, or too late (D-036).

    The reminder goes out ``round(pred) - buffer_days`` days after the service.
    lead = actual days to the next visit - reminder day.
    hit: window[0] <= lead <= window[1]; too early: lead > window[1];
    too late: lead < window[0] (the worse miss: the truck may already be due).
    """
    lo, hi = window
    lead = np.asarray(y, dtype=float) - (np.round(np.asarray(pred, dtype=float)) - buffer_days)
    return {
        "hit_rate": float(np.mean((lead >= lo) & (lead <= hi))),
        "too_early": float(np.mean(lead > hi)),
        "too_late": float(np.mean(lead < lo)),
    }


def score(y: pd.Series, pred: pd.Series, window: tuple[int, int], buffer_days: int) -> dict[str, float]:
    """All metrics for one prediction column."""
    return regression_metrics(y, pred) | reminder_outcomes(y, pred, window, buffer_days)


# ---------------------------------------------------------------------------
# Report
# ---------------------------------------------------------------------------

def _md_table(df: pd.DataFrame) -> str:
    """Small DataFrame -> Markdown table (no extra dependency)."""
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(map(str, row)) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def results_table(results: dict[str, dict[str, float]]) -> pd.DataFrame:
    """Metrics per baseline, formatted for Markdown."""
    rows = []
    for name, m in results.items():
        rows.append({"Baseline": name, "RMSE (days)": f"{m['RMSE']:.1f}", "MAE (days)": f"{m['MAE']:.1f}",
                     "R²": f"{m['R2']:.2f}", "Reminder hit rate": f"{m['hit_rate']:.1%}",
                     "Too early": f"{m['too_early']:.1%}", "Too late": f"{m['too_late']:.1%}"})
    return pd.DataFrame(rows)


def plot_baselines(results: dict[str, dict[str, float]], window: tuple[int, int], path: Path) -> None:
    """Two panels on separate axes (never a dual axis): MAE, and reminder outcome shares."""
    names = list(results)
    fig, (ax1, ax2) = plt.subplots(1, 2, figsize=(11, 3.6), facecolor=SURFACE,
                                   gridspec_kw={"width_ratios": [1, 1.6]})
    y = np.arange(len(names))
    mae = [results[n]["MAE"] for n in names]
    ax1.barh(y, mae, color=BLUE, height=0.5)
    for yi, v in zip(y, mae):
        ax1.text(v + 0.2, yi, f"{v:.1f}", va="center", color=TEXT, fontsize=9)
    ax1.set_yticks(y, names)
    ax1.invert_yaxis()
    ax1.set_title("Mean absolute error (days, lower is better)", color=TEXT, fontsize=10, loc="left")

    left = np.zeros(len(names))
    for key, label, color in (("hit_rate", f"Hit ({window[0]}–{window[1]} days early)", BLUE), ("too_early", "Too early", AQUA),
                              ("too_late", "Too late", ORANGE)):
        vals = np.array([results[n][key] for n in names]) * 100
        ax2.barh(y, vals, left=left, color=color, height=0.5, label=label, edgecolor=SURFACE, linewidth=2)
        for yi, l, v in zip(y, left, vals):
            if v >= 8:
                ax2.text(l + v / 2, yi, f"{v:.0f}%", va="center", ha="center", color="white", fontsize=9)
        left += vals
    ax2.set_yticks(y, names)
    ax2.invert_yaxis()
    ax2.set_xlim(0, 100)
    ax2.set_title("Reminder outcome (% of test visits)", color=TEXT, fontsize=10, loc="left")
    ax2.legend(frameon=False, fontsize=8, labelcolor=TEXT, ncol=3, loc="upper left", bbox_to_anchor=(0, -0.12))
    for ax in (ax1, ax2):
        ax.set_facecolor(SURFACE)
        for side in ("top", "right"):
            ax.spines[side].set_visible(False)
        for side in ("left", "bottom"):
            ax.spines[side].set_color(TEXT_MUTED)
        ax.tick_params(colors=TEXT_MUTED, labelsize=9)
        ax.grid(axis="x", color=GRID, linewidth=0.8)
        ax.set_axisbelow(True)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def build_report(cfg: dict, df: pd.DataFrame, split, results: dict[str, dict[str, float]],
                 b0_value: float, b1_fallbacks: int, routes: dict) -> str:
    """Whole Markdown report as one string (no timestamps -> same input, same report)."""
    vc = cfg["vehicle_col"]
    train, test = df.loc[split.train], df.loc[split.test]
    window = cfg["reminder"]["window_days_early"]
    km = cfg["baselines"]["b1_interval_km"]
    test_median = test.groupby("destination_name")[TARGET].median()
    route_rows = pd.DataFrame([
        {"Destination": name, "Route": r.route, "One-way km": f"{r.one_way_km:,.0f}",
         "km/day (all ranges at middle)": f"{r.km_per_day:.0f}", f"B1 days at {km:,} km": f"{km / r.km_per_day:.0f}",
         "Test: actual median days": f"{test_median.get(name, float('nan')):.0f}"}
        for name, r in routes.items()
    ])
    split_rows = pd.DataFrame([
        {"Set": "Train", "Trucks": train[vc].nunique(), "Visits": len(train),
         "Dates": f"{train['service_date'].min():%Y-%m-%d} – {train['service_date'].max():%Y-%m-%d}",
         "Median days": f"{train[TARGET].median():.0f}"},
        {"Set": "Test", "Trucks": test[vc].nunique(), "Visits": len(test),
         "Dates": f"{test['service_date'].min():%Y-%m-%d} – {test['service_date'].max():%Y-%m-%d}",
         "Median days": f"{test[TARGET].median():.0f}"},
    ])
    n_target = int(df[TARGET].notna().sum())
    return f"""# ML baselines (Tasks 2.1–2.3a)

Generated by `python -m src.ml.baselines` from `configs/ml.yaml` (seed {cfg['seed']}).
Data: `{cfg['input']}` — **SYNTHETIC** (task 1.3 generator + 1.4 cleaning), not
Geo-Expert's customers. Same config + data → same report.

## 1. Target and split

- Target `days_to_next_change` (D-006) = days from a visit to the same truck's next
  visit. {len(df):,} visits, {n_target:,} with a target; the other {len(df) - n_target:,}
  are each truck's last visit (never returned, or next visit after the data ends).
  On this synthetic file the derived target equals the generator's truth on every
  returned visit (checked in task 2.1).
- Split (D-009): {len(split.test_vehicles)} of {df[vc].nunique()} trucks held out
  ({cfg['split']['test_vehicle_share']:.0%}, seed {cfg['seed']}); cutoff
  **{split.cutoff:%Y-%m-%d}** ({cfg['split']['cutoff_quantile']:.0%} quantile of service dates).
  Train = train trucks' visits whose next visit is before the cutoff; test = test
  trucks' visits on/after it. No truck is in both; nothing after the cutoff is trained on.

{_md_table(split_rows)}

## 2. Baselines

- **B0** = median train interval = **{b0_value:.0f} days** for every truck.
- **B1** = {km:,} km (D-030 recommended interval) ÷ route km/day. km/day = round-trip km ÷
  (driving days + waiting) with speed, hours and waiting at the middle of their
  [ESTIMATE] ranges (configs/generator.yaml). {b1_fallbacks} of {len(test)} test visits
  have no destination → B0 fallback.

{_md_table(route_rows)}

## 3. Results on the test split ({len(test)} visits, {test[vc].nunique()} trucks)

![Baselines](figures/{CHART})

{_md_table(results_table(results))}

Reminder: sent on the predicted day − {cfg['reminder']['buffer_days']} buffer days. **Hit** =
it arrives {window[0]}–{window[1]} days before the actual visit (D-036; window [ESTIMATE],
Ari to confirm). **Too late** is the worse miss (truck may already be overdue).

The `B1 @ … km` rows are a sensitivity check only (middle of the actual 15k–20k km,
D-030), not the official B1, and were not chosen by looking at the test scores.

## 4. Reading

- Both baselines predict one number per truck type at best, so they cannot follow a
  truck's own pace or lateness. Their hit rate is the bar the ML model (2.3b) must clear.
- **B1 is worse than B0.** The table in §2 shows why: B1's days differ a lot by
  destination (e.g. Beijing vs the Russian border), but the actual medians barely do.
  A truck's stated destination fixes only its next trip; it often changes route
  before the next oil change (V6), and waiting days matter as much as distance
  (D-047, docs/synthetic_report.md §3). B1 at 15,000 km also predicts the
  *recommended* day, while trucks come at 15k–20k km and ~40 % late (D-030, D-031),
  so it is too early on average. This is a finding about the SYNTHETIC rules; real
  routes may behave differently.
- Test has {len(test)} visits: differences of about 1 day MAE or a few % hit rate
  are within noise. Only {test[vc].nunique()} of the {len(split.test_vehicles)} held-out trucks have a visit
  after the cutoff: the rest stopped coming earlier (the generator's "never returns",
  D-031). All test trucks already have history (first services are in the
  first year), so the first-visit fallback is not exercised by this split.
- Visits near the end of the data only have a target if the truck came back soon,
  so long intervals are slightly under-represented in test (same for every model).
"""


def main(argv: list[str] | None = None) -> int:
    """Score B0 and B1 on the test split and write the report + chart."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/ml.yaml"))
    args = parser.parse_args(argv)

    cfg = load_ml_config(args.config)
    df, routes = build_dataset(cfg)
    split = make_split(df, cfg)
    train, test = df.loc[split.train], df.loc[split.test]
    y = test[TARGET]
    window = tuple(cfg["reminder"]["window_days_early"])
    buffer_days = cfg["reminder"]["buffer_days"]

    b0 = predict_b0(train[TARGET], test.index)
    preds = {"B0 (median)": b0,
             f"B1 ({cfg['baselines']['b1_interval_km']:,} km)":
                 predict_b1(test["route_km_per_day"], cfg["baselines"]["b1_interval_km"], b0)}
    for km in cfg["baselines"]["b1_sensitivity_km"]:
        preds[f"B1 @ {km:,} km (sensitivity)"] = predict_b1(test["route_km_per_day"], km, b0)
    results = {name: score(y, p, window, buffer_days) for name, p in preds.items()}

    figures_dir = Path(cfg["figures_dir"])
    plot_baselines(results, window, figures_dir / CHART)
    fallbacks = int(test["route_km_per_day"].isna().sum())
    text = build_report(cfg, df, split, results, float(b0.iloc[0]), fallbacks, routes)
    Path(cfg["report_path"]).write_text(text, encoding="utf-8")
    print(results_table(results).to_string(index=False))
    print(f"report -> {cfg['report_path']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
