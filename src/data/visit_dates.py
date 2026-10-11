"""Real days between visits for repeat trucks (Task 1.4b, D-046).

Messenger photos carry no date (no EXIF, no date in the file name), so Ari
reads each date from the Messenger chat. Two steps:

1. ``template``: from the Label Studio export (plate per photo), write
   data/interim/dates_to_fill.csv with one row per photo of a REPEAT truck
   (2+ photos): ``photo_file, truck_no, date`` (date empty). Trucks are numbered
   1, 2, 3, ... so the file shows no plates (RISK-06).
2. ``intervals``: after Ari fills the dates, write
   data/interim/real_intervals.csv (``vehicle_key, days_between_visits``, one row
   per gap, the format src/data/synthetic_report.py reads) and print a
   counts-only summary Ari can share.

Rules (D-046 / D-043):
- Missing dates are counted, never guessed.
- Photos of the same truck on the same date are ONE visit (same plate + date =
  duplicate, D-043), so they never make a 0-day gap.
- A date that cannot be read is an error (row numbers shown), not skipped.

Usage:
    python -m src.data.visit_dates template
    python -m src.data.visit_dates intervals
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import os
import secrets
import sys
from collections import defaultdict
from datetime import date, datetime
from pathlib import Path

import pandas as pd

from src.common.plates import fix_by_position, is_valid_plate, normalize_plate
from src.cv.ls_export import DEFAULT_TYPE, boxes_from_task, load_export

EXPORT_DIR = Path("data/interim/labelstudio_export")
DEFAULT_TEMPLATE = Path("data/interim/dates_to_fill.csv")
DEFAULT_INTERVALS = Path("data/interim/real_intervals.csv")

TEMPLATE_COLUMNS = ["photo_file", "truck_no", "date"]
INTERVAL_COLUMNS = ["vehicle_key", "days_between_visits"]  # REAL_COLUMN in synthetic_report.py

# Formats Ari may type. Day/month order is never guessed: "05/10/2026" is
# rejected because it could be 5 Oct or 10 May.
DATE_FORMATS = ("%Y-%m-%d", "%Y.%m.%d", "%Y/%m/%d")

# Env var with a secret key for vehicle_key. Without it a random key is used,
# so keys are consistent inside one output file but differ between runs.
HASH_KEY_ENV = "PLATE_HASH_KEY"
KEY_LENGTH = 12  # hex characters kept from the HMAC


# ---------------------------------------------------------------------------
# Photo -> plate (from the Label Studio export)
# ---------------------------------------------------------------------------

def latest_export(folder: Path = EXPORT_DIR) -> Path:
    """Newest export file. Label Studio names them project-1-at-<date-time>-..., so name order = time order."""
    files = sorted(folder.glob("*.json"))
    if not files:
        raise FileNotFoundError(f"no Label Studio export (*.json) in {folder}")
    return files[-1]


def photo_plates(tasks: list[dict]) -> tuple[dict[str, str], int]:
    """Map photo path -> normalized plate. Also return how many photos were left out.

    A photo is left out if it has no readable valid plate, or two different
    plates (we cannot tell which truck it belongs to).
    """
    plates: dict[str, set[str]] = defaultdict(set)
    seen: set[str] = set()
    for task in tasks:
        for box in boxes_from_task(task):
            seen.add(box.image)
            if box.plate_type != DEFAULT_TYPE or not box.plate_text or "?" in box.plate_text:
                continue
            plate = fix_by_position(normalize_plate(box.plate_text))
            if is_valid_plate(plate):
                plates[box.image].add(plate)
    result = {image: next(iter(p)) for image, p in plates.items() if len(p) == 1}
    return result, len(seen) - len(result)


def repeat_trucks(plates: dict[str, str], min_photos: int = 2) -> dict[str, list[str]]:
    """Plate -> sorted photo list, only plates with ``min_photos`` or more photos."""
    by_plate: dict[str, list[str]] = defaultdict(list)
    for image, plate in plates.items():
        by_plate[plate].append(image)
    return {plate: sorted(images) for plate, images in sorted(by_plate.items()) if len(images) >= min_photos}


# ---------------------------------------------------------------------------
# Step 1: fill-in template
# ---------------------------------------------------------------------------

def build_template(trucks: dict[str, list[str]]) -> pd.DataFrame:
    """One row per photo, trucks numbered 1..n (no plate in the output), date empty."""
    rows = [
        {"photo_file": image, "truck_no": truck_no, "date": ""}
        for truck_no, images in enumerate(trucks.values(), start=1)
        for image in images
    ]
    return pd.DataFrame(rows, columns=TEMPLATE_COLUMNS)


# ---------------------------------------------------------------------------
# Step 2: filled template -> intervals
# ---------------------------------------------------------------------------

def parse_date(text: str) -> date:
    """Read one typed date in an allowed format, or raise ValueError."""
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise ValueError(text)


def read_filled(path: Path) -> pd.DataFrame:
    """Read Ari's filled CSV (as text; utf-8-sig drops the BOM Excel may add)."""
    df = pd.read_csv(path, dtype=str, keep_default_na=False, encoding="utf-8-sig")
    missing = [c for c in TEMPLATE_COLUMNS if c not in df.columns]
    if missing:
        raise ValueError(f"{path} is missing column(s): {', '.join(missing)}")
    return df.apply(lambda col: col.str.strip())


def parse_dates(df: pd.DataFrame, today: date) -> pd.Series:
    """Column of dates (None where empty). Bad or future dates raise one error listing every bad row."""
    parsed: list[date | None] = []
    bad: list[str] = []
    for i, text in enumerate(df["date"]):
        row = i + 2  # row number as a spreadsheet shows it (header is row 1)
        if text == "":
            parsed.append(None)
            continue
        try:
            d = parse_date(text)
        except ValueError:
            bad.append(f"row {row}: '{text}' (use YYYY-MM-DD)")
            parsed.append(None)
            continue
        if d > today:
            bad.append(f"row {row}: '{text}' is in the future")
        parsed.append(d)
    if bad:
        raise ValueError("dates that could not be used:\n  " + "\n  ".join(bad))
    return pd.Series(parsed, index=df.index, dtype=object)


def check_trucks(df: pd.DataFrame, plates: dict[str, str]) -> None:
    """Each photo must be in the export, and each truck_no must be exactly one plate (and back)."""
    unknown = sorted(set(df["photo_file"]) - set(plates))
    if unknown:
        raise ValueError(f"{len(unknown)} photo_file value(s) not in the export, e.g. row with '{unknown[0]}'")
    pairs = pd.DataFrame({"truck_no": df["truck_no"], "plate": df["photo_file"].map(plates)}).drop_duplicates()
    if pairs["truck_no"].duplicated().any() or pairs["plate"].duplicated().any():
        raise ValueError("truck_no does not match the photos' plates (was a truck_no edited?); "
                         "make a fresh template with `template --force`")


def plate_key(plate: str, key: bytes) -> str:
    """Keyed hash of a plate. A plain SHA-256 is not enough: there are only ~92 million plates,
    so anyone could hash them all and look a plate up; without the key they cannot."""
    return hmac.new(key, plate.encode("utf-8"), hashlib.sha256).hexdigest()[:KEY_LENGTH]


def compute_intervals(df: pd.DataFrame, dates: pd.Series, plates: dict[str, str], key: bytes
                      ) -> tuple[pd.DataFrame, dict[str, int]]:
    """Gaps between consecutive distinct visit dates per truck, plus counts for the summary."""
    visits = pd.DataFrame({"plate": df["photo_file"].map(plates), "date": dates}).dropna(subset=["date"])
    unique_visits = visits.drop_duplicates()
    rows = []
    for plate, group in unique_visits.groupby("plate", sort=True):
        days = sorted(group["date"])
        vehicle_key = plate_key(plate, key)
        rows += [{"vehicle_key": vehicle_key, "days_between_visits": (b - a).days} for a, b in zip(days, days[1:])]
    counts = {
        "same_day_photos_merged": len(visits) - len(unique_visits),
        "trucks_with_intervals": int((unique_visits.groupby("plate").size() >= 2).sum()),
    }
    return pd.DataFrame(rows, columns=INTERVAL_COLUMNS), counts


def summary(df: pd.DataFrame, dates: pd.Series, intervals: pd.DataFrame, counts: dict[str, int]) -> dict[str, object]:
    """Counts only (no plates, no file names, no dates) — safe to share (RISK-06)."""
    days = intervals["days_between_visits"]
    return {
        "repeat_trucks_in_template": df["truck_no"].nunique(),
        "photos_in_template": len(df),
        "photos_missing_date": int(dates.isna().sum()),
        "same_day_photos_merged": counts["same_day_photos_merged"],
        "trucks_with_2plus_dated_visits": counts["trucks_with_intervals"],
        "intervals": len(intervals),
        "days_min": int(days.min()) if len(days) else None,
        "days_median": float(days.median()) if len(days) else None,
        "days_max": int(days.max()) if len(days) else None,
    }


def hash_key() -> tuple[bytes, bool]:
    """Key from PLATE_HASH_KEY, or a random one. Second value: True if it came from the env var."""
    env = os.environ.get(HASH_KEY_ENV, "")
    if env:
        return env.encode("utf-8"), True
    return secrets.token_bytes(32), False


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def run_template(export: Path, output: Path, force: bool) -> int:
    """Write the fill-in CSV. Refuses to overwrite, so a filled file is never lost by accident."""
    if output.exists() and not force:
        print(f"ERROR: {output} exists (it may already hold Ari's dates). Use --force to overwrite.", file=sys.stderr)
        return 1
    plates, left_out = photo_plates(load_export(export))
    trucks = repeat_trucks(plates)
    template = build_template(trucks)
    output.parent.mkdir(parents=True, exist_ok=True)
    template.to_csv(output, index=False, encoding="utf-8")
    print(f"photos with one plate: {len(plates)} (left out: {left_out}), trucks: {len(set(plates.values()))}")
    print(f"repeat trucks (2+ photos): {len(trucks)}, photos to date: {len(template)} -> {output}")
    return 0


def run_intervals(export: Path, filled: Path, output: Path, today: date) -> int:
    """Read the filled CSV, write real_intervals.csv, print the shareable summary."""
    plates, _ = photo_plates(load_export(export))
    df = read_filled(filled)
    check_trucks(df, plates)
    dates = parse_dates(df, today)
    key, from_env = hash_key()
    intervals, counts = compute_intervals(df, dates, plates, key)
    output.parent.mkdir(parents=True, exist_ok=True)
    intervals.to_csv(output, index=False, encoding="utf-8")
    print(f"-> {output}")
    if not from_env:
        print(f"note: {HASH_KEY_ENV} not set, vehicle_key uses a random key (differs between runs)")
    print("SUMMARY (counts only, safe to share)")
    for name, value in summary(df, dates, intervals, counts).items():
        print(f"  {name}: {value}")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI with two commands: ``template`` and ``intervals``."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--export", type=Path, default=None, help="Label Studio JSON export (default: newest)")
    sub = parser.add_subparsers(dest="command", required=True)
    t = sub.add_parser("template", help="write the fill-in CSV")
    t.add_argument("--output", type=Path, default=DEFAULT_TEMPLATE)
    t.add_argument("--force", action="store_true", help="overwrite an existing template")
    i = sub.add_parser("intervals", help="filled CSV -> real_intervals.csv + summary")
    i.add_argument("--filled", type=Path, default=DEFAULT_TEMPLATE)
    i.add_argument("--output", type=Path, default=DEFAULT_INTERVALS)
    args = parser.parse_args(argv)

    try:
        export = args.export or latest_export()
        if args.command == "template":
            return run_template(export, args.output, args.force)
        return run_intervals(export, args.filled, args.output, date.today())
    except (OSError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
