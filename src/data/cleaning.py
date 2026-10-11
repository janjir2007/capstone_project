"""Cleaning: dirty service records -> clean training data (Task 1.4).

Works on any table with these columns (synthetic dirty file now, real
records later):
    record_id, company_name, plate, service_date, created_at, odometer_km,
    destination_raw, route, driver_name, driver_phone

It never sees the truth: scoring against the generator's answer key lives in
src/data/cleaning_report.py and only runs after cleaning is finished.

Steps (each writes rows to the issue log: record_id, issue, action):
1. Plate  -> plates.normalize_plate (the ONLY plate normalizer). Latin
   look-alikes (N6) and spacing (N7) are fixed; the plate is the vehicle key.
2. Phone  -> api.schemas.normalize_phone (same rule as the API, D-019).
   Formatting (N10) fixed; impossible numbers set to empty; missing (N1) kept empty.
3. Driver name missing (N2): kept empty (not a model input).
4. Destination text -> one row of the destination list (N5), via exact
   alias, transliteration to Latin, then fuzzy match. Route follows the
   destination (D-039). Missing (N3): kept empty.
5. Duplicates (N11): same vehicle + same service_date -> keep one (D-043 rule).
6. Late entry (N12): created_at after service_date -> flagged only;
   service_date stays the service day.
7. Odometer per vehicle (N4, N8, N9): readings must grow, but not faster
   than max_km_per_day. Readings that break this are repaired (×10 / ÷10)
   or set to empty. The row is kept: its date is still a real service.

Run:  python -m src.data.cleaning   (synthetic files + report)
      python -m src.data.cleaning --input X.csv --output Y.csv --no-score   (real data)
"""

from __future__ import annotations

import argparse
import difflib
import re
from dataclasses import dataclass, field
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from src.api.schemas import normalize_phone
from src.common.plates import LATIN_TO_CYRILLIC, is_valid_plate, normalize_plate
from src.data.generator import untagged_params, value

DEFAULT_CONFIG = Path("configs/cleaning.yaml")
DEFAULT_INPUT = Path("data/synthetic/service_records_dirty.csv")
DEFAULT_OUTPUT = Path("data/synthetic/service_records_cleaned.csv")
ISSUES_SUFFIX = "_issues.csv"

INPUT_COLUMNS = ["record_id", "company_name", "plate", "service_date", "created_at", "odometer_km",
                 "destination_raw", "route", "driver_name", "driver_phone"]

# Issue code -> the generator noise rule it corresponds to (for scoring only).
ISSUE_TO_NOISE = {
    "phone_missing": "N1", "driver_name_missing": "N2", "destination_missing": "N3",
    "odometer_missing": "N4", "destination_variant": "N5", "destination_unmatched": "N5",
    "plate_latin_lookalike": "N6", "plate_spacing": "N7", "odometer_digit_error": "N8",
    "odometer_lower_than_last": "N9", "odometer_implausible": "N9", "phone_format": "N10",
    "phone_invalid": "N10", "duplicate": "N11", "late_entry": "N12",
}

# Mongolian Cyrillic -> Latin, simple one-way scheme used ONLY to compare
# spellings (never stored). Ө/Ү fold to o/u like common Latin typing.
_TRANSLIT = str.maketrans({
    "а": "a", "б": "b", "в": "v", "г": "g", "д": "d", "е": "e", "ё": "yo", "ж": "j", "з": "z",
    "и": "i", "й": "i", "к": "k", "л": "l", "м": "m", "н": "n", "о": "o", "ө": "o", "п": "p",
    "р": "r", "с": "s", "т": "t", "у": "u", "ү": "u", "ф": "f", "х": "kh", "ц": "ts", "ч": "ch",
    "ш": "sh", "щ": "sh", "ъ": "", "ы": "y", "ь": "i", "э": "e", "ю": "yu", "я": "ya",
})
_NOT_ALNUM = re.compile(r"[^a-z0-9]")
_PARENTHESIS = re.compile(r"\s*\(.*?\)")
_LATIN_LOOKALIKES = frozenset(LATIN_TO_CYRILLIC)


@dataclass
class IssueLog:
    """Collects (record_id, issue, action) rows while cleaning."""

    rows: list[tuple[int, str, str]] = field(default_factory=list)

    def add(self, record_ids: object, issue: str, action: str) -> None:
        """Log one issue for each record id given."""
        self.rows.extend((int(r), issue, action) for r in np.atleast_1d(record_ids))

    def frame(self) -> pd.DataFrame:
        """Issue log as a sorted DataFrame."""
        df = pd.DataFrame(self.rows, columns=["record_id", "issue", "action"])
        return df.sort_values(["record_id", "issue"], kind="stable").reset_index(drop=True)


# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

def load_config(path: Path) -> dict:
    """Read configs/cleaning.yaml; every parameter must carry a tag."""
    with open(path, encoding="utf-8") as f:
        cfg = yaml.safe_load(f)
    missing = untagged_params(cfg) + [d["name"] for d in cfg["destinations"] if "tag" not in d]
    if missing:
        raise ValueError(f"parameters without [SOURCE]/[ESTIMATE] tag: {missing}")
    return cfg


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _blank(x: object) -> bool:
    """True for NaN / None / empty or spaces-only text."""
    return x is None or (isinstance(x, float) and np.isnan(x)) or (isinstance(x, str) and not x.strip())


def text_key(text: str) -> str:
    """Spelling-insensitive key: lower case, Cyrillic -> Latin, letters and digits only.

    'Замын-Үүд' -> 'zamynuud', 'Zamyn Uud' -> 'zamynuud'.
    """
    return _NOT_ALNUM.sub("", text.casefold().translate(_TRANSLIT))


# ---------------------------------------------------------------------------
# 1. Plates
# ---------------------------------------------------------------------------

def clean_plates(df: pd.DataFrame, log: IssueLog) -> pd.DataFrame:
    """Normalize plates (plates.py) and log what was wrong with the raw text."""
    raw = df["plate"].fillna("").astype(str)
    df["plate_normalized"] = [normalize_plate(p) if p.strip() else None for p in raw]
    latin = raw.map(lambda p: any(ch in _LATIN_LOOKALIKES for ch in p.upper()))
    spacing = raw.str.contains(r"\s", regex=True)
    log.add(df.loc[latin, "record_id"], "plate_latin_lookalike", "fixed")
    log.add(df.loc[spacing, "record_id"], "plate_spacing", "fixed")
    invalid = df["plate_normalized"].map(lambda p: p is None or not is_valid_plate(p))
    log.add(df.loc[invalid, "record_id"], "plate_invalid", "kept")
    df["vehicle_key"] = df["plate_normalized"]
    return df


# ---------------------------------------------------------------------------
# 2–3. Phone, driver name
# ---------------------------------------------------------------------------

def _phone_or_none(raw: object) -> str | None:
    """8-digit phone, or None if missing / not a valid Mongolian number."""
    if _blank(raw):
        return None
    try:
        return normalize_phone(str(raw))
    except ValueError:
        return None


def clean_phones(df: pd.DataFrame, log: IssueLog) -> pd.DataFrame:
    """Phone -> 8 digits (D-019). Log formatting fixes, invalid and missing phones."""
    raw = df["driver_phone"]
    missing = raw.map(_blank)
    phone = raw.map(_phone_or_none)
    invalid = ~missing & phone.isna()
    reformatted = ~missing & phone.notna() & (raw.astype(str) != phone)
    log.add(df.loc[missing, "record_id"], "phone_missing", "kept_empty")
    log.add(df.loc[invalid, "record_id"], "phone_invalid", "set_empty")
    log.add(df.loc[reformatted, "record_id"], "phone_format", "fixed")
    df["driver_phone"] = phone
    return df


def clean_driver_names(df: pd.DataFrame, log: IssueLog) -> pd.DataFrame:
    """Strip names; log missing ones (kept empty)."""
    missing = df["driver_name"].map(_blank)
    log.add(df.loc[missing, "record_id"], "driver_name_missing", "kept_empty")
    df["driver_name"] = [None if m else str(n).strip() for n, m in zip(df["driver_name"], missing)]
    return df


# ---------------------------------------------------------------------------
# 4. Destinations
# ---------------------------------------------------------------------------

def alias_table(cfg: dict) -> dict[str, str]:
    """Latin key -> official destination name, from names (with and without brackets) + aliases."""
    table: dict[str, str] = {}
    for d in cfg["destinations"]:
        for text in [d["name"], _PARENTHESIS.sub("", d["name"]), *d.get("aliases", [])]:
            table[text_key(text)] = d["name"]
    return table


def match_destination(raw: str, aliases: dict[str, str], min_similarity: float, min_margin: float) -> str | None:
    """Official destination name for a free-text answer, or None if unsure.

    Exact key first; else the most similar key if it is similar enough AND
    clearly better than the best key of a DIFFERENT destination.
    """
    key = text_key(raw)
    if not key:
        return None
    if key in aliases:
        return aliases[key]
    best: dict[str, float] = {}
    for alias_key, name in aliases.items():
        score = difflib.SequenceMatcher(None, key, alias_key).ratio()
        best[name] = max(best.get(name, 0.0), score)
    ranked = sorted(best.items(), key=lambda kv: kv[1], reverse=True)
    top_name, top = ranked[0]
    second = ranked[1][1] if len(ranked) > 1 else 0.0
    return top_name if top >= min_similarity and top - second >= min_margin else None


def clean_destinations(df: pd.DataFrame, cfg: dict, log: IssueLog) -> pd.DataFrame:
    """Map destination text to the official list; route follows the destination (D-039)."""
    aliases = alias_table(cfg)
    route_of = {d["name"]: d["route_category"] for d in cfg["destinations"]}
    m = cfg["destination_match"]
    names: list[str | None] = []
    for rid, raw in zip(df["record_id"], df["destination_raw"]):
        if _blank(raw):
            log.add(rid, "destination_missing", "kept_empty")
            names.append(None)
            continue
        name = match_destination(str(raw), aliases, value(m["min_similarity"]), value(m["min_margin"]))
        if name is None:
            log.add(rid, "destination_unmatched", "kept_raw")
        elif str(raw) != name:
            log.add(rid, "destination_variant", "fixed")
        names.append(name)
    df["destination_name"] = names
    mapped = df["destination_name"].notna()
    df.loc[mapped, "route"] = df.loc[mapped, "destination_name"].map(route_of)
    return df


# ---------------------------------------------------------------------------
# 5–6. Duplicates, late entry
# ---------------------------------------------------------------------------

def drop_duplicates(df: pd.DataFrame, log: IssueLog) -> pd.DataFrame:
    """Same vehicle + same service_date = duplicate (D-043). Keep the most complete row, then the oldest id."""
    filled = df[INPUT_COLUMNS].notna().sum(axis=1)
    order = df.assign(_filled=filled).sort_values(["vehicle_key", "service_date", "_filled", "record_id"],
                                                  ascending=[True, True, False, True], kind="stable")
    dupes = order.duplicated(["vehicle_key", "service_date"], keep="first") & order["vehicle_key"].notna()
    log.add(order.loc[dupes, "record_id"], "duplicate", "dropped")
    return df.drop(index=order.index[dupes])


def flag_late_entries(df: pd.DataFrame, log: IssueLog) -> pd.DataFrame:
    """created_at after service_date -> flag only (service_date is the service day)."""
    late = df["created_at"].notna() & (df["created_at"] > df["service_date"])
    log.add(df.loc[late, "record_id"], "late_entry", "kept")
    return df


# ---------------------------------------------------------------------------
# 7. Odometer
# ---------------------------------------------------------------------------

def consistent(km_a: float, day_a: pd.Timestamp, km_b: float, day_b: pd.Timestamp,
               max_km_per_day: float, slack_km: float) -> bool:
    """Can a truck go from reading a (earlier) to reading b (later)?"""
    gain = km_b - km_a
    return 0 <= gain <= max_km_per_day * (day_b - day_a).days + slack_km


def _fits_all(km: float, i: int, keep: list[int], days: list[pd.Timestamp], kms: list[float],
              max_rate: float, slack: float) -> bool:
    """Is reading `km` at position i consistent with every kept reading?"""
    for j in keep:
        if j == i:
            continue
        a, b = (j, i) if j < i else (i, j)
        km_a, km_b = (kms[j], km) if j < i else (km, kms[j])
        if not consistent(km_a, days[a], km_b, days[b], max_rate, slack):
            return False
    return True


def _out_of_scale(i: int, keep: list[int], kms: list[float], max_ratio: float) -> bool:
    """Is reading i about ×10 / ÷10 off its nearest kept reading? (a true or N9 reading is ~×1)"""
    others = [j for j in keep if j != i]
    if not others or kms[i] <= 0:
        return False
    nearest = kms[min(others, key=lambda j: abs(j - i))]
    ratio = kms[i] / nearest if nearest > 0 else float("inf")
    return ratio > max_ratio or ratio < 1 / max_ratio


def _digit_fix(i: int, keep: list[int], days: list, kms: list, factors: list[float],
               max_rate: float, slack: float, max_ratio: float) -> float | None:
    """×10 / ÷10 version of reading i that fits every kept reading, if any (N8).

    Only tried when the reading is out of scale: otherwise a correct reading next
    to a long gap could be 'repaired' into a wrong one.
    """
    if not _out_of_scale(i, keep, kms, max_ratio):
        return None
    for f in factors:
        candidate = round(kms[i] * f)
        if _fits_all(candidate, i, keep, days, kms, max_rate, slack):
            return float(candidate)
    return None


def find_odometer_outliers(days: list[pd.Timestamp], kms: list[float], max_rate: float, slack: float,
                           factors: list[float], max_ratio: float) -> set[int]:
    """Positions of readings to distrust, for ONE vehicle sorted by date.

    Greedy: count, for every reading, how many other readings it is
    inconsistent with; remove the worst one; repeat until all agree.
    Ties: prefer a reading that a ×10 / ÷10 fix would repair, then the later one
    (a reading lower than the last service is the newer one).
    """
    keep = [i for i, km in enumerate(kms) if not np.isnan(km)]
    bad: set[int] = set()
    while True:
        conflicts = {i: 0 for i in keep}
        for a, b in combinations(keep, 2):
            if not consistent(kms[a], days[a], kms[b], days[b], max_rate, slack):
                conflicts[a] += 1
                conflicts[b] += 1
        worst = max(conflicts.values(), default=0)
        if worst == 0:
            return bad
        tied = [i for i, c in conflicts.items() if c == worst]
        others = lambda i: [j for j in keep if j != i]  # noqa: E731
        fixable = [i for i in tied if _digit_fix(i, others(i), days, kms, factors, max_rate, slack, max_ratio) is not None]
        pick = max(fixable or tied)
        keep.remove(pick)
        bad.add(pick)


def clean_odometers(df: pd.DataFrame, cfg: dict, log: IssueLog) -> pd.DataFrame:
    """Repair or empty odometer readings that do not fit the vehicle's other readings."""
    o = cfg["odometer"]
    max_rate, slack, factors = value(o["max_km_per_day"]), value(o["slack_km"]), value(o["digit_fix_factors"])
    max_ratio = value(o["digit_error_min_ratio"])
    df["odometer_km"] = pd.to_numeric(df["odometer_km"], errors="coerce").astype(float)
    log.add(df.loc[df["odometer_km"].isna(), "record_id"], "odometer_missing", "kept_empty")

    for _, g in df.sort_values(["service_date", "record_id"]).groupby("vehicle_key", sort=False):
        idx, days, kms = list(g.index), list(g["service_date"]), list(g["odometer_km"])
        bad = find_odometer_outliers(days, kms, max_rate, slack, factors, max_ratio)
        keep = [i for i, km in enumerate(kms) if not np.isnan(km) and i not in bad]
        for i in sorted(bad):
            rid = df.at[idx[i], "record_id"]
            fixed = _digit_fix(i, keep, days, kms, factors, max_rate, slack, max_ratio)
            if fixed is not None:
                df.at[idx[i], "odometer_km"] = fixed
                log.add(rid, "odometer_digit_error", "fixed")
                continue
            earlier = [kms[j] for j in keep if j < i]
            issue = "odometer_lower_than_last" if earlier and kms[i] < earlier[-1] else "odometer_implausible"
            df.at[idx[i], "odometer_km"] = np.nan
            log.add(rid, issue, "set_empty")
    df["odometer_km"] = df["odometer_km"].round().astype("Int64")
    return df


# ---------------------------------------------------------------------------
# Whole pipeline
# ---------------------------------------------------------------------------

OUTPUT_COLUMNS = ["record_id", "vehicle_key", "plate_normalized", "company_name", "service_date", "created_at",
                  "odometer_km", "destination_name", "destination_raw", "route", "driver_name", "driver_phone"]


def read_records(path: Path) -> pd.DataFrame:
    """Read a records CSV with the input columns; dates parsed, text kept as text."""
    df = pd.read_csv(path, dtype={"plate": str, "driver_phone": str}, encoding="utf-8")
    missing = [c for c in INPUT_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing columns: {missing}")
    return df


def clean_records(dirty: pd.DataFrame, cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Run every cleaning step. Input: the dirty table only. Returns (cleaned, issue_log)."""
    log = IssueLog()
    df = dirty[INPUT_COLUMNS].copy().reset_index(drop=True)
    df["service_date"] = pd.to_datetime(df["service_date"], errors="coerce")
    df["created_at"] = pd.to_datetime(df["created_at"], errors="coerce")
    bad_date = df["service_date"].isna()
    log.add(df.loc[bad_date, "record_id"], "service_date_invalid", "dropped")
    df = df[~bad_date].copy()

    df = clean_plates(df, log)
    df = clean_phones(df, log)
    df = clean_driver_names(df, log)
    df = clean_destinations(df, cfg, log)
    df = drop_duplicates(df, log)
    df = flag_late_entries(df, log)
    df = clean_odometers(df, cfg, log)

    df = df.sort_values(["service_date", "record_id"], kind="stable").reset_index(drop=True)
    for col in ("service_date", "created_at"):
        df[col] = df[col].dt.date
    return df[OUTPUT_COLUMNS], log.frame()


def issues_path(output: Path) -> Path:
    """Issue log file next to the cleaned file."""
    return output.with_name(output.stem + ISSUES_SUFFIX)


def main(argv: list[str] | None = None) -> int:
    """Clean a records file; for synthetic data also score against the answer key."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--input", type=Path, default=DEFAULT_INPUT)
    parser.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    parser.add_argument("--no-score", action="store_true", help="real data: no answer key, no report")
    parser.add_argument("--report", type=Path, default=Path("docs/cleaning_report.md"))
    args = parser.parse_args(argv)

    cfg = load_config(args.config)
    dirty = read_records(args.input)
    cleaned, issues = clean_records(dirty, cfg)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    cleaned.to_csv(args.output, index=False, encoding="utf-8")
    issues.to_csv(issues_path(args.output), index=False, encoding="utf-8")
    print(f"{len(dirty)} rows in -> {len(cleaned)} rows out, {len(issues)} issues -> {args.output}")

    if not args.no_score:
        # Scoring is a separate step: only here are truth + noise_log opened.
        from src.data.cleaning_report import write_report
        write_report(dirty, cleaned, issues, args.input.parent, args.report)
        print(f"report -> {args.report}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
