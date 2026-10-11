"""Score cleaning against the generator's answer key -> docs/cleaning_report.md (Task 1.4).

The ONLY place that reads the synthetic truth (service_records_clean.csv) and
noise_log.csv. src/data/cleaning.py never imports this for its own work, so
cleaning cannot peek at the answer.

Per noise rule:
  logged     records the generator changed (noise_log)
  masked     changed, but a later rule erased the evidence (e.g. a phone that was
             reformatted N10 and then deleted N1) -> cannot be found, left out of recall
  found      records cleaning flagged with an issue of that rule
  precision  found AND logged / found        (how many flags are right)
  recall     found AND logged / detectable   (how many changes were caught)
  fixed ok   for rules cleaning repairs: share of caught records whose value now equals the truth
"""

from __future__ import annotations

from pathlib import Path

import pandas as pd

from src.data.cleaning import ISSUE_TO_NOISE
from src.data.generator import CLEAN_FILE, NOISE_LOG_FILE

# Rule -> (short description, rule that can erase its evidence later)
NOISE_RULES = {
    "N1": ("missing phone", None),
    "N2": ("missing driver name", None),
    "N3": ("missing destination", None),
    "N4": ("missing odometer", None),
    "N5": ("destination spelled differently", "N3"),
    "N6": ("plate Latin look-alike", None),
    "N7": ("plate spacing", None),
    "N8": ("odometer ×10 / ÷10", None),
    "N9": ("odometer lower than last", None),
    "N10": ("phone format", "N1"),
    "N11": ("duplicate record", None),
    "N12": ("late entry", None),
}


def _ids(df: pd.DataFrame, mask: pd.Series) -> set[int]:
    return set(df.loc[mask, "record_id"].astype(int))


def after_missing_odometer(noise_log: pd.DataFrame, truth: pd.DataFrame) -> set[int]:
    """Records whose PREVIOUS service (same vehicle) lost its odometer (N4).

    An N9 reading is 'lower than the last service' — if that last reading is
    gone, nothing in the data shows the drop, so it is masked.
    """
    ordered = truth.sort_values(["vehicle_id", "service_date", "record_id"])
    previous = ordered.groupby("vehicle_id")["record_id"].shift(1)
    lost = _ids(noise_log, noise_log["noise"] == "N4")
    return set(ordered.loc[previous.isin(lost), "record_id"].astype(int))


def fixed_correctly(code: str, caught: set[int], cleaned: pd.DataFrame, truth: pd.DataFrame) -> float | None:
    """Share of caught records whose cleaned value equals the truth (None if the rule is not repaired)."""
    if code == "N11":
        kept = set(cleaned["record_id"].astype(int))
        return sum(r not in kept for r in caught) / len(caught) if caught else None
    column = {"N5": "destination_name", "N6": "plate_normalized", "N7": "plate_normalized",
              "N8": "odometer_km", "N10": "driver_phone"}.get(code)
    if column is None or not caught:
        return None
    both = cleaned[cleaned["record_id"].isin(caught)].merge(
        truth[["record_id", column]], on="record_id", suffixes=("", "_true"))
    if code == "N8":  # ÷10 loses the last digit -> within 10 km counts as fixed
        ok = (both[column].astype(float) - both[f"{column}_true"].astype(float)).abs() <= 10
    else:
        ok = both[column].astype(str) == both[f"{column}_true"].astype(str)
    return float(ok.mean()) if len(both) else None


def score_rules(cleaned: pd.DataFrame, issues: pd.DataFrame, noise_log: pd.DataFrame,
                truth: pd.DataFrame) -> pd.DataFrame:
    """One row per noise rule: logged, found, precision, recall, actions, fixed ok."""
    issue_rule = issues["issue"].map(ISSUE_TO_NOISE)
    # A duplicate (N11) is a copy of an already-noisy row, but noise_log lists it only
    # as N11. Its other issues are the original's, so they are not scored again.
    duplicates = _ids(noise_log, noise_log["noise"] == "N11")
    rows = []
    for code, (desc, masked_by) in NOISE_RULES.items():
        logged = _ids(noise_log, noise_log["noise"] == code)
        masked = logged & _ids(noise_log, noise_log["noise"] == masked_by) if masked_by else set()
        if code == "N9":
            masked |= logged & after_missing_odometer(noise_log, truth)
        detectable = logged - masked
        found = _ids(issues, issue_rule == code)
        if code != "N11":
            found -= duplicates
        caught = found & detectable
        scored = (issue_rule == code) & (code == "N11" or ~issues["record_id"].isin(duplicates))
        actions = issues.loc[scored, "action"].value_counts()
        rows.append({
            "Rule": code, "Noise": desc, "Logged": len(logged), "Masked": len(masked), "Found": len(found),
            "Precision": len(found & logged) / len(found) if found else float("nan"),
            "Recall": len(caught) / len(detectable) if detectable else float("nan"),
            "Actions": ", ".join(f"{a} {n}" for a, n in sorted(actions.items())),
            "Fixed ok": fixed_correctly(code, caught, cleaned, truth),
        })
    return pd.DataFrame(rows)


def value_accuracy(cleaned: pd.DataFrame, truth: pd.DataFrame) -> pd.DataFrame:
    """After cleaning: how often each field equals the truth (non-empty cleaned values only)."""
    both = cleaned.merge(truth, on="record_id", suffixes=("", "_true"))
    rows = []
    for col in ("plate_normalized", "destination_name", "route", "driver_phone", "odometer_km"):
        filled = both[col].notna()
        if col == "odometer_km":  # ÷10 repair loses the last digit -> within 10 km
            equal = (both.loc[filled, col].astype(float) - both.loc[filled, f"{col}_true"]).abs() <= 10
        else:
            equal = both.loc[filled, col].astype(str) == both.loc[filled, f"{col}_true"].astype(str)
        rows.append({"Field": col, "Filled": int(filled.sum()), "Empty": int((~filled).sum()),
                     "Equal to truth": float(equal.mean())})
    return pd.DataFrame(rows)


def vehicle_identity(cleaned: pd.DataFrame, truth: pd.DataFrame) -> dict[str, int]:
    """Does one cleaned vehicle_key = one true vehicle?"""
    both = cleaned.merge(truth[["record_id", "vehicle_id"]], on="record_id")
    return {
        "true vehicles": int(truth["vehicle_id"].nunique()),
        "cleaned vehicle keys": int(cleaned["vehicle_key"].nunique()),
        "keys holding >1 true vehicle": int((both.groupby("vehicle_key")["vehicle_id"].nunique() > 1).sum()),
        "true vehicles split over >1 key": int((both.groupby("vehicle_id")["vehicle_key"].nunique() > 1).sum()),
    }


def _md_table(df: pd.DataFrame) -> str:
    def fmt(x: object) -> str:
        if x is None or (isinstance(x, float) and pd.isna(x)):
            return "–"
        if isinstance(x, float):
            return f"{x:.1%}"
        return str(x)
    lines = ["| " + " | ".join(df.columns) + " |", "|" + "---|" * len(df.columns)]
    lines += ["| " + " | ".join(fmt(x) for x in row) + " |" for row in df.itertuples(index=False)]
    return "\n".join(lines)


def build_report(dirty: pd.DataFrame, cleaned: pd.DataFrame, issues: pd.DataFrame,
                 noise_log: pd.DataFrame, truth: pd.DataFrame) -> str:
    """Whole Markdown report (no timestamps -> reproducible)."""
    dropped = issues.loc[issues["action"] == "dropped", "record_id"].nunique()
    counts = pd.DataFrame([
        ("Dirty rows in", f"{len(dirty):,}"),
        ("Rows dropped (duplicates / bad date)", f"{dropped:,}"),
        ("Cleaned rows out", f"{len(cleaned):,}"),
        ("True records (generator truth)", f"{len(truth):,}"),
        ("Issues logged", f"{len(issues):,}"),
    ], columns=["What", "Count"])
    identity = pd.DataFrame(list(vehicle_identity(cleaned, truth).items()), columns=["Vehicle identity", "Count"])
    return "\n\n".join([
        "# Cleaning report (Task 1.4)",
        "Generated by `python -m src.data.cleaning` on the synthetic dirty file "
        "(`data/synthetic/service_records_dirty.csv`, seed 42). Cleaning sees only the dirty file; "
        "this report then compares its result with the generator's answer key (`noise_log.csv`, "
        "`service_records_clean.csv`). Same input → same report.",
        "## 1. Rows before / after\n\n" + _md_table(counts),
        "## 2. Per noise rule\n\n" + _md_table(score_rules(cleaned, issues, noise_log, truth)) +
        "\n\n*Masked* = changed by the rule but erased by a later one (N10 phone then deleted by N1; "
        "N5 spelling then deleted by N3; N9 drop when the previous service's odometer was deleted by N4), "
        "so no cleaner could find it; left out of recall. "
        "*Fixed ok* = caught records whose value now equals the truth (N8: within 10 km, because ÷10 "
        "loses the last digit; N11: the duplicate copy was the row dropped). Missing values (N1–N4) are "
        "found but cannot be repaired; they stay empty. N12 is flagged only.",
        "## 3. Field accuracy after cleaning\n\n" + _md_table(value_accuracy(cleaned, truth)) +
        "\n\nShare of non-empty cleaned values equal to the truth (odometer: within 10 km).",
        "## 4. Vehicle identity (plate → vehicle_key)\n\n" + _md_table(identity),
        "## 5. Limits\n\n"
        "- The noise is the generator's own (synthetic_rules §7). Real records will have problems "
        "it did not simulate (e.g. a wrong digit in a plate splits one truck into two; 1.4a saw this). "
        "Ari runs `python -m src.data.cleaning --input <real.csv> --output data/processed/<name>.csv "
        "--no-score` and shares the issue counts only.\n"
        "- Destination aliases (`configs/cleaning.yaml`) were written separately from the generator's "
        "spellings, but by the same team; real spellings may be harder.\n"
        "- Odometer checks need ≥ 2 readings of the same truck. A replaced dashboard (all later readings "
        "lower) would be flagged reading by reading, not as one reset.\n",
    ])


def write_report(dirty: pd.DataFrame, cleaned: pd.DataFrame, issues: pd.DataFrame,
                 synthetic_dir: Path, report_path: Path) -> None:
    """Read the answer key from synthetic_dir and write the report."""
    truth = pd.read_csv(synthetic_dir / CLEAN_FILE, dtype={"driver_phone": str}, encoding="utf-8")
    noise_log = pd.read_csv(synthetic_dir / NOISE_LOG_FILE, encoding="utf-8")
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(build_report(dirty, cleaned, issues, noise_log, truth), encoding="utf-8")
