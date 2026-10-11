"""Report for the synthetic dataset (Task 1.3): docs/synthetic_report.md + charts.

Called by src/data/generator.py. The text has no timestamps, so the same
config + seed always writes the same report (reproducibility check).

If data/interim/real_intervals.csv exists (made by Ari from real records,
private), the report compares synthetic vs real days between visits.
Only quantiles and one chart are written, never real rows.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # no window; write files only
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from src.data.generator import driving_days, midpoint, value  # noqa: E402

INTERVAL_CHART = "synthetic_interval_distribution.png"
REAL_CHART = "synthetic_vs_real_days.png"
REAL_COLUMN = "days_between_visits"
QUANTILES = (0.05, 0.25, 0.5, 0.75, 0.95)

# Reference palette (dataviz skill, light surface): slot 1 blue, slot 2 orange.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_MUTED = "#52514e"
BLUE = "#2a78d6"
ORANGE = "#eb6834"

NOISE_NAMES = {
    "N1": "missing_phone", "N2": "missing_driver_name", "N3": "missing_destination", "N4": "missing_odometer",
    "N5": "destination_variant", "N6": "plate_latin_lookalike", "N7": "plate_spacing",
    "N8": "odometer_digit_error", "N9": "odometer_lower_than_last", "N10": "phone_format",
    "N11": "duplicate_record", "N12": "late_entry",
}


# ---------------------------------------------------------------------------
# Numbers
# ---------------------------------------------------------------------------

def returned_intervals(clean: pd.DataFrame) -> pd.DataFrame:
    """Rows whose next visit was observed (on time or late) — the ML training rows."""
    return clean[clean["next_outcome"].isin(["on_time", "late"])]


def quantile_table(values: pd.Series) -> dict[str, float]:
    """Count, mean and the report quantiles of a numeric series."""
    v = pd.Series(values, dtype=float).dropna()
    out = {"n": float(len(v)), "mean": float(v.mean())}
    out.update({f"p{int(q * 100)}": float(v.quantile(q)) for q in QUANTILES})
    return out


def ks_statistic(a: pd.Series, b: pd.Series) -> float:
    """Two-sample Kolmogorov–Smirnov statistic: largest gap between the two ECDFs (0 = same, 1 = no overlap)."""
    a = np.sort(np.asarray(a, dtype=float))
    b = np.sort(np.asarray(b, dtype=float))
    grid = np.concatenate([a, b])
    cdf_a = np.searchsorted(a, grid, side="right") / len(a)
    cdf_b = np.searchsorted(b, grid, side="right") / len(b)
    return float(np.max(np.abs(cdf_a - cdf_b)))


def closeness_label(ks: float) -> str:
    """Plain-words reading of the KS statistic. Thresholds are a rule of thumb [ESTIMATE], not a test."""
    if ks < 0.1:
        return "close"
    if ks < 0.25:
        return "moderately different"
    return "far apart"


def formula_days_at_midpoints(cfg: dict) -> pd.DataFrame:
    """Per destination: days for 15,000 km with every range at its middle (B1-style sanity check)."""
    trip = cfg["trip"]
    rows = []
    for d in cfg["destinations"]:
        km = value(trip["round_trip_factor"]) * d["one_way_km"]
        days = driving_days(km, midpoint(trip["speed_kmh"]), midpoint(trip["driving_hours_per_day"]))
        days += midpoint(trip["waiting_days_per_trip"])
        km_per_day = km / days
        rows.append({"destination_name": d["name"], "round_trip_km": km, "trip_days_mid": days,
                     "km_per_day_mid": km_per_day,
                     "days_for_15000_mid": value(cfg["interval"]["min_km"]) / km_per_day})
    return pd.DataFrame(rows)


def load_real_intervals(path: Path) -> pd.Series | None:
    """Real days between visits, or None if the file does not exist."""
    if not path.exists():
        return None
    real = pd.read_csv(path)
    if REAL_COLUMN not in real.columns:
        raise ValueError(f"{path} needs a column '{REAL_COLUMN}'")
    return pd.to_numeric(real[REAL_COLUMN], errors="coerce").dropna()


# ---------------------------------------------------------------------------
# Charts
# ---------------------------------------------------------------------------

def _style(ax: plt.Axes) -> None:
    """Recessive axes: no top/right spines, light grid behind the bars."""
    ax.set_facecolor(SURFACE)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(TEXT_MUTED)
    ax.tick_params(colors=TEXT_MUTED, labelsize=9)
    ax.grid(axis="y", color="#e4e3df", linewidth=0.8)
    ax.set_axisbelow(True)


def plot_intervals(clean: pd.DataFrame, path: Path) -> None:
    """Two panels: days to next change and km to next change, stacked on time vs late."""
    ret = returned_intervals(clean)
    fig, axes = plt.subplots(1, 2, figsize=(11, 4), facecolor=SURFACE)
    panels = (("days_to_next_change", "Days to next oil change", 2),
              ("km_to_next_change", "Km to next oil change", 500))
    for ax, (col, title, width) in zip(axes, panels):
        lo, hi = ret[col].min(), ret[col].max()
        bins = np.arange(np.floor(lo / width) * width, hi + width, width)
        data = [ret.loc[ret["next_outcome"] == o, col] for o in ("on_time", "late")]
        ax.hist(data, bins=bins, stacked=True, color=[BLUE, ORANGE], label=["On time", "Late"],
                edgecolor=SURFACE, linewidth=1)
        ax.set_title(title, color=TEXT, fontsize=11, loc="left")
        ax.set_ylabel("Service records", color=TEXT_MUTED, fontsize=9)
        _style(ax)
    axes[1].xaxis.set_major_formatter(matplotlib.ticker.StrMethodFormatter("{x:,.0f}"))
    axes[0].legend(frameon=False, fontsize=9, labelcolor=TEXT)
    fig.suptitle(f"Synthetic intervals (n = {len(ret):,} returned visits)", color=TEXT, fontsize=12, x=0.01, ha="left")
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


def plot_real_vs_synthetic(synthetic: pd.Series, real: pd.Series, path: Path) -> None:
    """Empirical CDFs of days between visits (fair even if the two counts differ a lot)."""
    fig, ax = plt.subplots(figsize=(7, 4), facecolor=SURFACE)
    for values, color, label in ((synthetic, BLUE, "Synthetic"), (real, ORANGE, "Real")):
        v = np.sort(np.asarray(values, dtype=float))
        ax.step(v, np.arange(1, len(v) + 1) / len(v), where="post", color=color, linewidth=2,
                label=f"{label} (n = {len(v):,})")
    ax.set_xlabel("Days between visits", color=TEXT_MUTED, fontsize=9)
    ax.set_ylabel("Share of visits ≤ x", color=TEXT_MUTED, fontsize=9)
    ax.set_title("Days between visits: synthetic vs real", color=TEXT, fontsize=11, loc="left")
    ax.legend(frameon=False, fontsize=9, labelcolor=TEXT)
    _style(ax)
    fig.tight_layout()
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.savefig(path, dpi=150, facecolor=SURFACE, metadata={"Software": None})
    plt.close(fig)


# ---------------------------------------------------------------------------
# Markdown
# ---------------------------------------------------------------------------

def _md_table(df: pd.DataFrame, floatfmt: str = "{:,.1f}") -> str:
    """Small DataFrame -> Markdown table (no extra dependency)."""
    def fmt(x: object) -> str:
        return floatfmt.format(x) if isinstance(x, (float, np.floating)) else str(x)
    lines = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(fmt(x) for x in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def _counts_section(clean: pd.DataFrame, dirty: pd.DataFrame) -> str:
    per_vehicle = clean.groupby("vehicle_id").size()
    rows = pd.DataFrame([
        ("Service records (clean)", f"{len(clean):,}"),
        ("Service records (dirty, incl. duplicates)", f"{len(dirty):,}"),
        ("Vehicles", f"{clean['vehicle_id'].nunique():,}"),
        ("Companies", f"{clean['company_name'].nunique():,}"),
        ("Records per vehicle (min / median / max)",
         f"{per_vehicle.min()} / {per_vehicle.median():.0f} / {per_vehicle.max()}"),
        ("Service dates", f"{clean['service_date'].min()} – {clean['service_date'].max()}"),
        ("Training rows (next visit observed)", f"{len(returned_intervals(clean)):,}"),
    ], columns=["What", "Count"])
    return "## 1. Rows and vehicles\n\n" + _md_table(rows)


def _outcome_section(clean: pd.DataFrame, cfg: dict) -> str:
    rb = cfg["return_behavior"]
    target = {"on_time": value(rb["on_time_share"]), "late": value(rb["late_share"]), "never": value(rb["never_share"])}
    decided = clean[clean["next_outcome"] != "censored"]
    share = decided["next_outcome"].value_counts(normalize=True)
    rows = pd.DataFrame([(o, f"{target[o]:.0%}", f"{share.get(o, 0):.1%}") for o in target],
                        columns=["Outcome", "Target (D-031)", "Generated"])
    censored = (clean["next_outcome"] == "censored").sum()
    return ("## 2. Return behavior\n\n" + _md_table(rows) +
            f"\n\nShares are over records whose next step is known. {censored:,} more records are "
            "**censored** (the next visit would fall after `end_date`); they have no target, like "
            "the newest real records. `never` includes late visits beyond the 60-day maximum (§4).")


def _interval_section(clean: pd.DataFrame, cfg: dict) -> str:
    ret = returned_intervals(clean)
    q = pd.DataFrame({
        "All returned": quantile_table(ret["days_to_next_change"]),
        "On time": quantile_table(ret.loc[ret["next_outcome"] == "on_time", "days_to_next_change"]),
        "Late": quantile_table(ret.loc[ret["next_outcome"] == "late", "days_to_next_change"]),
        "Km (all returned)": quantile_table(ret["km_to_next_change"]),
    }).T.reset_index(names="Series")
    by_dest = (ret.groupby("destination_name")["days_to_next_change"]
               .agg(n="size", median="median", p25=lambda s: s.quantile(0.25), p75=lambda s: s.quantile(0.75))
               .reset_index())
    by_dest = by_dest.merge(formula_days_at_midpoints(cfg)[["destination_name", "days_for_15000_mid"]],
                            on="destination_name")
    by_dest = by_dest.rename(columns={"destination_name": "Stated destination",
                                      "days_for_15000_mid": "Formula days for 15,000 km (all ranges at middle)"})
    by_season = ret.groupby("season")["days_to_next_change"].median().reindex(["winter", "spring", "summer", "autumn"])
    season_line = ", ".join(f"{s} {v:.0f}" for s, v in by_season.items())
    return (
        "## 3. Interval distribution\n\n"
        f"![Synthetic interval distribution](figures/{INTERVAL_CHART})\n\n"
        "Days and km from one service to the next, for visits that came back.\n\n"
        + _md_table(q) +
        "\n\n**By stated destination** (destination said at the service; the truck may change "
        "route afterwards, V6):\n\n" + _md_table(by_dest) +
        f"\n\n**Median days by season of the service:** {season_line}.\n\n"
        "Reading: on the short Russian-border routes (~700 km round trip) the 0–5 waiting days per "
        "trip take more time than the driving, so the destinations differ less than their km "
        "suggest. If real waiting is shorter or longer, this changes a lot (see open items).\n\n"
        "Why the formula column is lower than the medians, most of all for long routes: (1) the "
        "stated destination fixes only the FIRST trip; with V6 (same destination again with "
        "probability 0.7 per trip) a truck usually changes route several times before its next "
        "oil change, so every destination's median moves toward the fleet average; (2) the "
        "formula uses 15,000 km, while trucks actually drive 15k–20k km and ~40% come late (D-030, "
        "D-031). This is the gap between B1 and reality that the ML should learn from history."
    )


def _noise_section(clean: pd.DataFrame, noise_log: pd.DataFrame, cfg: dict) -> str:
    counts = noise_log["noise"].value_counts()
    rows = []
    for code, name in NOISE_NAMES.items():
        target = value(cfg["noise"][name])
        rows.append((code, name, f"{target:.0%}", f"{counts.get(code, 0) / len(clean):.1%}"))
    table = pd.DataFrame(rows, columns=["Rule", "Config key", "Target", "Applied (share of clean records)"])
    return ("## 4. Noise in the dirty file (synthetic_rules §7)\n\n" + _md_table(table) +
            "\n\nN6 is skipped when a plate has no letter with a Latin look-alike, so it lands a "
            "little under target. N13 (haul trucks) is not used: road trucks only (D-037 fallback).")


def _real_section(clean: pd.DataFrame, real: pd.Series | None, cfg: dict, figures_dir: Path) -> str:
    path = cfg["real_intervals_path"]
    if real is None:
        return ("## 5. Synthetic vs real\n\n"
                f"`{path}` was not found, so there is no comparison yet. To add it: put one "
                f"row per real visit gap in that file with a column `{REAL_COLUMN}` (private, git-ignored) "
                "and rerun the generator.")
    synthetic = returned_intervals(clean)["days_to_next_change"]
    plot_real_vs_synthetic(synthetic, real, figures_dir / REAL_CHART)
    table = pd.DataFrame({"Synthetic": quantile_table(synthetic), "Real": quantile_table(real)}).T
    table = table.reset_index(names="Days between visits")
    ks = ks_statistic(synthetic, real)
    med_s, med_r = synthetic.median(), real.median()
    gap = (med_s - med_r) / med_r if med_r else float("nan")
    return (
        "## 5. Synthetic vs real (days between visits)\n\n"
        f"![Synthetic vs real](figures/{REAL_CHART})\n\n" + _md_table(table) +
        f"\n\n**How close:** synthetic median {med_s:.0f} days vs real {med_r:.0f} days "
        f"({gap:+.0%}). KS statistic {ks:.2f} (largest gap between the two curves) → "
        f"**{closeness_label(ks)}** (rule of thumb: < 0.10 close, < 0.25 moderate). "
        "Ranges were NOT tuned to match (task 1.3); this only shows the gap."
    )


def build_report(clean: pd.DataFrame, dirty: pd.DataFrame, noise_log: pd.DataFrame, cfg: dict,
                 real: pd.Series | None, figures_dir: Path) -> str:
    """Whole Markdown report as one string."""
    header = (
        "# Synthetic data report (Task 1.3)\n\n"
        "Generated by `python -m src.data.generator` from `configs/generator.yaml` "
        f"(seed {cfg['seed']}). Same config + seed → same data and same report.\n"
        "All numbers below describe SYNTHETIC data built from [ESTIMATE] ranges "
        "(docs/synthetic_rules.md); they are not facts about Geo-Expert's customers.\n\n"
        "Files (git-ignored): `data/synthetic/service_records_clean.csv` (truth + target), "
        "`service_records_dirty.csv` (noise, no truth), `noise_log.csv`."
    )
    sections = [
        header,
        _counts_section(clean, dirty),
        _outcome_section(clean, cfg),
        _interval_section(clean, cfg),
        _noise_section(clean, noise_log, cfg),
        _real_section(clean, real, cfg, figures_dir),
    ]
    return "\n\n".join(sections) + "\n"


def write_report(clean: pd.DataFrame, dirty: pd.DataFrame, noise_log: pd.DataFrame, cfg: dict) -> None:
    """Write charts + docs/synthetic_report.md (paths from the config)."""
    figures_dir = Path(cfg["figures_dir"])
    plot_intervals(clean, figures_dir / INTERVAL_CHART)
    real = load_real_intervals(Path(cfg["real_intervals_path"]))
    text = build_report(clean, dirty, noise_log, cfg, real, figures_dir)
    Path(cfg["report_path"]).write_text(text, encoding="utf-8")
