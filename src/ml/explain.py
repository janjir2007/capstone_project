"""SHAP explanations for Ridge (linear) and XGBoost (tree) (Task 2.4, R7 "XAI").

SHAP value of a feature = how many days it moves THIS prediction away from the
model's average prediction (the "base value"). For every row:
    base value + sum of SHAP values = model prediction   (additivity, checked below)

- Ridge  -> ``shap.LinearExplainer`` with the TRAIN rows as background:
            SHAP = coefficient × (value − train mean of that column). Exact.
- XGBoost -> ``shap.TreeExplainer`` (tree_path_dependent, no background needed). Exact.

Both explain the model in its own input space, i.e. AFTER the pipeline's
preprocessing (one-hot columns, median-filled numbers, "was empty" flags,
scaling for Ridge). ``group_feature`` maps those columns back to the 10
features of src/common/features.py; summing SHAP values inside a group is
allowed because SHAP values add up.

Imports of shap / xgboost are inside the functions: on macOS xgboost and
torch must not share a process (see src/ml/train.py ``model_specs``).
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402
from sklearn.pipeline import Pipeline  # noqa: E402

from src.common.features import FEATURE_COLUMNS  # noqa: E402
from src.ml.baselines import BLUE, GRID, ORANGE, SURFACE, TEXT, TEXT_MUTED, mark_synthetic  # noqa: E402

# Feature value low -> high on ONE hue (dataviz: magnitude = sequential), blue steps 250 -> 700
# (step 250 is the lightest that still shows on the light surface).
VALUE_CMAP = LinearSegmentedColormap.from_list("blue_seq", ["#86b6ef", "#2a78d6", "#0d366b"])


@dataclass
class Explanation:
    """SHAP result of one model on a set of rows."""

    model: str
    values: np.ndarray          # rows × transformed columns, in days
    base_value: float           # average prediction (days)
    data: np.ndarray            # transformed input values (for colour in the beeswarm)
    columns: list[str]          # readable column names
    index: pd.Index             # row labels of the explained rows

    def frame(self) -> pd.DataFrame:
        """SHAP values as a DataFrame (rows × readable columns)."""
        return pd.DataFrame(self.values, index=self.index, columns=self.columns)

    def predictions(self) -> np.ndarray:
        """Base value + sum of SHAP values = the model's prediction."""
        return self.base_value + self.values.sum(axis=1)


# ---------------------------------------------------------------------------
# Column names
# ---------------------------------------------------------------------------

def pretty_column(name: str) -> str:
    """ColumnTransformer name -> readable label.

    'cat__destination_name_Beijing' -> 'destination_name = Beijing'
    'num__missingindicator_km_per_day_hist' -> 'km_per_day_hist (empty)'
    'num__one_way_km' -> 'one_way_km'
    """
    if name.startswith("cat__"):
        rest = name.removeprefix("cat__")
        for feat in FEATURE_COLUMNS:
            if rest.startswith(feat + "_"):
                return f"{feat} = {rest.removeprefix(feat + '_')}"
        return rest
    rest = name.removeprefix("num__")
    if rest.startswith("missingindicator_"):
        return f"{rest.removeprefix('missingindicator_')} (empty)"
    return rest


def group_feature(label: str) -> str:
    """Readable column -> one of the 10 original features (one-hot + 'empty' flag fold back)."""
    base = re.split(r" = | \(empty\)", label)[0]
    if base not in FEATURE_COLUMNS:
        raise ValueError(f"unknown feature column: {label}")
    return base


# ---------------------------------------------------------------------------
# SHAP
# ---------------------------------------------------------------------------

def _transformed(pipe: Pipeline, X: pd.DataFrame) -> tuple[np.ndarray, list[str]]:
    """Rows after the pipeline's preprocessing step + readable column names."""
    prep = pipe.named_steps["prep"]
    names = [pretty_column(n) for n in prep.get_feature_names_out()]
    return np.asarray(prep.transform(X), dtype=float), names


def explain(name: str, pipe: Pipeline, X_background: pd.DataFrame, X_explain: pd.DataFrame) -> Explanation:
    """SHAP values of a fitted Ridge or XGBoost pipeline on ``X_explain``.

    ``X_background`` (TRAIN rows) is only used by the linear explainer, for the column means.
    """
    import shap

    model = pipe.named_steps["model"]
    Z, names = _transformed(pipe, X_explain)
    if type(model).__name__ == "Ridge":
        Zb, _ = _transformed(pipe, X_background)
        sv = shap.LinearExplainer(model, Zb)(Z)
    elif type(model).__name__ == "XGBRegressor":
        sv = shap.TreeExplainer(model)(Z)
    else:
        raise ValueError(f"no SHAP explainer set up for {type(model).__name__}")
    base = float(np.ravel(sv.base_values)[0])
    return Explanation(name, np.asarray(sv.values, dtype=float), base, Z, names, X_explain.index)


def additivity_error(exp: Explanation, pipe: Pipeline, X: pd.DataFrame) -> float:
    """Largest |base + sum(SHAP) − pipeline prediction| in days (should be ~0)."""
    return float(np.max(np.abs(exp.predictions() - pipe.predict(X))))


def grouped_importance(exp: Explanation) -> pd.Series:
    """Mean |SHAP| (days) per original feature, columns of one feature summed per row first."""
    by_feature = exp.frame().T.groupby(group_feature).sum().T
    return by_feature.abs().mean().reindex(FEATURE_COLUMNS).fillna(0.0).sort_values(ascending=False)


def row_contributions(exp: Explanation, row) -> pd.Series:
    """SHAP values of one row, grouped by original feature (days, signed)."""
    return exp.frame().loc[row].groupby(group_feature).sum().reindex(FEATURE_COLUMNS).fillna(0.0)


def pick_example_row(exp: Explanation, n_prior_visits: pd.Series, min_prior: int) -> object:
    """The visit whose prediction moves furthest from the average, among trucks with history.

    Uses predictions only (never the target), so picking it does not look at test answers.
    """
    shift = pd.Series(np.abs(exp.values.sum(axis=1)), index=exp.index)
    eligible = shift[n_prior_visits.reindex(exp.index) >= min_prior]
    return (eligible if len(eligible) else shift).idxmax()


# ---------------------------------------------------------------------------
# Charts (every one stamped SYNTHETIC)
# ---------------------------------------------------------------------------

def _style(ax: plt.Axes, grid_axis: str = "x") -> None:
    """Recessive axes and grid, same look as src/ml/baselines.py charts."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9)
    ax.grid(axis=grid_axis, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)


def _save(fig: plt.Figure, path: Path) -> None:
    """Stamp SYNTHETIC, write PNG without timestamps."""
    mark_synthetic(fig)
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def plot_beeswarm(exp: Explanation, path: Path, top: int, subtitle: str) -> None:
    """SHAP summary (beeswarm) of the ``top`` columns with the largest mean |SHAP|."""
    import shap

    sv = shap.Explanation(values=exp.values, base_values=np.full(len(exp.values), exp.base_value),
                          data=exp.data, feature_names=exp.columns)
    fig, ax = plt.subplots(figsize=(9, 0.42 * top + 1.8), facecolor=SURFACE)
    shap.plots.beeswarm(sv, max_display=top, show=False, color=VALUE_CMAP, plot_size=None, ax=ax,
                        axis_color=TEXT_MUTED, color_bar_label="Feature value (low → high)")
    ax.set_facecolor(SURFACE)
    ax.set_xlabel("SHAP value = days added to the prediction (negative = earlier oil change)",
                  color=TEXT_MUTED, fontsize=9)
    ax.set_title(f"{exp.model}: what moves the predicted days to next oil change\n{subtitle}",
                 color=TEXT, fontsize=10, loc="left")
    fig.tight_layout()
    fig.subplots_adjust(top=0.88)
    _save(fig, path)


def plot_grouped_importance(importances: dict[str, pd.Series], path: Path) -> None:
    """Mean |SHAP| per original feature, one bar per model (two series: blue, orange)."""
    order = list(next(iter(importances.values())).index)
    y = np.arange(len(order))
    h = 0.38
    fig, ax = plt.subplots(figsize=(9, 4.6), facecolor=SURFACE)
    for k, ((name, imp), color) in enumerate(zip(importances.items(), (BLUE, ORANGE))):
        vals = imp.reindex(order).to_numpy()
        ax.barh(y + (k - 0.5) * h, vals, height=h - 0.04, color=color, label=name)
        for yi, v in zip(y, vals):
            if v >= 0.05:
                ax.text(v + 0.03, yi + (k - 0.5) * h, f"{v:.2f}", va="center", color=TEXT, fontsize=8)
    ax.set_yticks(y, order)
    ax.invert_yaxis()
    ax.set_xlabel("Mean |SHAP| on test visits (days)", color=TEXT_MUTED, fontsize=9)
    ax.set_title("Feature importance: average size of each feature's effect", color=TEXT, fontsize=10, loc="left")
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT, loc="lower right")
    _style(ax)
    fig.tight_layout()
    fig.subplots_adjust(top=0.9)
    _save(fig, path)


def plot_example(contribs: dict[str, tuple[float, pd.Series, float]], title: str, path: Path) -> None:
    """One truck, one panel per model: average -> each feature's push (days) -> prediction.

    ``contribs[name] = (base_value, contributions by feature, prediction)``.
    Blue = pushes the date later (more days), orange = earlier. Features with |effect| < 0.05 days hidden.
    """
    fig, axes = plt.subplots(1, len(contribs), figsize=(6 * len(contribs), 4.4), facecolor=SURFACE)
    for ax, (name, (base, c, pred)) in zip(np.atleast_1d(axes), contribs.items()):
        c = c[c.abs() >= 0.05].sort_values(key=np.abs, ascending=False)
        labels = ["average prediction", *c.index, "this prediction"]
        y = np.arange(len(labels))
        ax.barh(y[0], base, color=TEXT_MUTED, height=0.55)
        running = base
        for yi, v in zip(y[1:-1], c.to_numpy()):
            ax.barh(yi, v, left=running, color=BLUE if v > 0 else ORANGE, height=0.55)
            ax.text(max(running, running + v) + 0.3, yi, f"{v:+.1f}", va="center", color=TEXT, fontsize=8)
            running += v
        ax.barh(y[-1], pred, color=TEXT, height=0.55)
        ax.text(base + 0.3, y[0], f"{base:.1f}", va="center", color=TEXT, fontsize=8)
        ax.text(pred + 0.3, y[-1], f"{pred:.1f} days", va="center", color=TEXT, fontsize=8)
        ax.set_yticks(y, labels)
        ax.invert_yaxis()
        lo = min(base, pred, *(base + c.cumsum()))
        ax.set_xlim(max(0, lo - 10), max(base, pred, *(base + c.cumsum())) + 6)
        ax.set_title(name, color=TEXT, fontsize=10, loc="left")
        ax.set_xlabel("days to next oil change (blue = later, orange = earlier)", color=TEXT_MUTED, fontsize=9)
        _style(ax)
    fig.suptitle(title, color=TEXT, fontsize=10, x=0.01, ha="left")
    fig.tight_layout()
    fig.subplots_adjust(top=0.84)
    _save(fig, path)
