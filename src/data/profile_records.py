"""Profile a service-records Excel file WITHOUT exposing personal data (Task 1.4a).

Ari runs this on the real Excel himself; Claude Code never sees data/raw/.
The report is printed and saved to data/interim/ (git-ignored, never committed):
business totals and fleet mix are commercially sensitive.

Privacy rules built into the report:
- Columns that look personal (names, phones, plates, companies, staff) are
  masked: only dtype / missing % / unique count are shown, never values.
- Value counts are shown only for low-cardinality, non-personal columns, and
  every category with fewer than MIN_GROUP_SIZE rows is merged into "other".
- Per-vehicle statistics are aggregated; the vehicle column is never printed.

Usage:
    python -m src.data.profile_records data/raw/records/<file>.xlsx
"""

from __future__ import annotations

import argparse
import re
from collections.abc import Iterable
from pathlib import Path

import pandas as pd

DEFAULT_OUT = Path("data/interim/records_profile.md")
MIN_GROUP_SIZE = 3  # smaller categories are merged into "other"
MAX_CATEGORIES = 30  # more unique values than this -> no value counts
TOP_N = 10  # categories listed per column before "other"
VALUE_MATCH_SHARE = 0.3  # share of cells matching a pattern -> column is personal

# Substrings of column names (case-insensitive) that mark a column as personal.
PERSONAL_KEYWORDS: tuple[str, ...] = (
    # people
    "name", "нэр", "driver", "жолооч", "owner", "эзэмшигч", "эзэн",
    "customer", "client", "харилцагч", "үйлчлүүлэгч",
    "changer", "employee", "staff", "mechanic", "ажилтан", "механик",
    # contact
    "phone", "утас", "тел", "email", "и-мэйл", "address", "хаяг",
    # identifiers
    "plate", "улсын", "дугаар", "register", "регистр", "fleet", "парк",
    # companies
    "company", "компани", "байгууллага",
)
DATE_KEYWORDS = ("date", "огноо", "өдөр")
VEHICLE_KEYWORDS = ("plate", "улсын", "машины дугаар", "fleet", "парк", "identifier")
ODOMETER_KEYWORDS = ("odometer", "mileage", "km", "км", "гүйлт")
HOURS_KEYWORDS = ("engine_hours", "engine hours", "hours", "моточас", "мото цаг")

PHONE_RE = re.compile(r"(?:\+?976[\s-]?)?\d{4}[\s-]?\d{4}")
PLATE_RE = re.compile(r"\d{4}[\s-]?[A-ZА-ЯЁӨҮ]{2,3}", re.IGNORECASE)
COMPANY_RE = re.compile(r".*\b(?:ХХК|ХК|LLC)\b.*", re.IGNORECASE)
VALUE_PATTERNS: dict[str, re.Pattern[str]] = {
    "phone numbers": PHONE_RE,
    "plates": PLATE_RE,
    "company names": COMPANY_RE,
}


# --------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------
def _text(value: object) -> str | None:
    """Return a cell as stripped text, or None for an empty cell.

    Excel often stores phone numbers as floats (99112233.0); whole floats are
    turned into int text ("99112233") so the phone pattern still matches.
    """
    if value is None or (not isinstance(value, str) and pd.isna(value)):
        return None
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    text = str(value).strip()
    return text or None


def _fmt(value: float | int | None) -> str:
    """Format a number for the report: integers plainly, others to 1 decimal."""
    if value is None or pd.isna(value):
        return "n/a"
    if float(value).is_integer():
        return str(int(value))
    return f"{value:.1f}"


def _md_table(headers: list[str], rows: list[list[str]]) -> list[str]:
    """Render a simple Markdown table (no extra dependency like tabulate)."""
    def clean(cell: str) -> str:
        return str(cell).replace("|", "\\|").replace("\n", " ")

    lines = ["| " + " | ".join(clean(h) for h in headers) + " |"]
    lines.append("|" + "---|" * len(headers))
    lines += ["| " + " | ".join(clean(c) for c in row) + " |" for row in rows]
    return lines


def pick_column(columns: Iterable[str], keywords: Iterable[str]) -> str | None:
    """Return the first column whose name contains any keyword (case-insensitive)."""
    keywords = tuple(k.casefold() for k in keywords)
    for col in columns:
        name = str(col).casefold()
        if any(k in name for k in keywords):
            return col
    return None


# --------------------------------------------------------------------------
# Personal-data detection
# --------------------------------------------------------------------------
def pattern_share(series: pd.Series, pattern: re.Pattern[str]) -> float:
    """Share of non-empty cells whose full text matches `pattern` (0.0–1.0)."""
    texts = [t for t in (_text(v) for v in series) if t is not None]
    if not texts:
        return 0.0
    return sum(bool(pattern.fullmatch(t)) for t in texts) / len(texts)


def personal_reason(name: str, series: pd.Series) -> str | None:
    """Explain why a column looks personal, or return None if it does not.

    Checks the column name first, then the cell values.
    """
    lowered = str(name).casefold()
    for keyword in PERSONAL_KEYWORDS:
        if keyword in lowered:
            return f"name contains '{keyword}'"
    for label, pattern in VALUE_PATTERNS.items():
        share = pattern_share(series, pattern)
        if share >= VALUE_MATCH_SHARE:
            return f"{share:.0%} of values look like {label}"
    return None


def find_personal_columns(df: pd.DataFrame) -> dict[str, str]:
    """Map every personal-looking column to the reason it was masked."""
    found = {}
    for col in df.columns:
        reason = personal_reason(col, df[col])
        if reason:
            found[col] = reason
    return found


def guess_vehicle_column(df: pd.DataFrame, personal: dict[str, str]) -> str | None:
    """Guess which (personal) column identifies the vehicle.

    Prefers a column named like a plate/fleet number; otherwise the column
    whose values look most like plates.
    """
    by_name = pick_column(personal, VEHICLE_KEYWORDS)
    if by_name:
        return by_name
    shares = {col: pattern_share(df[col], PLATE_RE) for col in personal}
    best = max(shares, key=lambda c: shares[c], default=None)
    return best if best is not None and shares[best] >= VALUE_MATCH_SHARE else None


def guess_date_column(df: pd.DataFrame, exclude: Iterable[str]) -> str | None:
    """First real datetime column, else the first column named like a date."""
    candidates = [c for c in df.columns if c not in set(exclude)]
    for col in candidates:
        if pd.api.types.is_datetime64_any_dtype(df[col]):
            return col
    return pick_column(candidates, DATE_KEYWORDS)


# --------------------------------------------------------------------------
# Statistics
# --------------------------------------------------------------------------
def parse_dates(series: pd.Series) -> pd.Series:
    """Parse a column to datetimes; unreadable cells become NaT.

    Plain numbers are NOT parsed (pandas would read them as nanoseconds since
    1970), so Excel serial numbers stored as numbers count as unparseable.
    """
    if pd.api.types.is_datetime64_any_dtype(series):
        return series
    no_numbers = series.map(
        lambda v: None if isinstance(v, (int, float)) and not isinstance(v, bool) else v
    )
    return pd.to_datetime(no_numbers, errors="coerce", format="mixed")


def safe_value_counts(series: pd.Series) -> list[tuple[str, int]]:
    """Value counts where categories with < MIN_GROUP_SIZE rows become "other".

    Shows at most TOP_N named categories; everything else is summed into one
    "other" row so small groups cannot identify a customer.
    """
    texts = series.map(_text)
    counts = texts.dropna().value_counts()
    shown = counts[counts >= MIN_GROUP_SIZE].head(TOP_N)
    rows = [(str(value), int(n)) for value, n in shown.items()]
    hidden = counts.drop(shown.index)
    if len(hidden):
        rows.append((f"other ({len(hidden)} categories)", int(hidden.sum())))
    missing = int(texts.isna().sum())
    if missing:
        rows.append(("(missing)", missing))
    return rows


def visit_gaps(dates: pd.Series, vehicles: pd.Series) -> dict[str, float | int | None]:
    """Days between consecutive visits of the same vehicle, aggregated.

    Rows with no date or no vehicle are dropped (and counted).
    """
    frame = pd.DataFrame({"vehicle": vehicles.map(_text), "date": dates}).dropna()
    frame = frame.sort_values(["vehicle", "date"], kind="stable")
    gaps = frame.groupby("vehicle")["date"].diff().dt.days.dropna()
    visits = frame.groupby("vehicle").size()
    return {
        "rows_used": len(frame),
        "rows_dropped": len(dates) - len(frame),
        "vehicles": len(visits),
        "vehicles_2plus": int((visits >= 2).sum()),
        "gaps": len(gaps),
        "min": gaps.min() if len(gaps) else None,
        "median": gaps.median() if len(gaps) else None,
        "max": gaps.max() if len(gaps) else None,
        "same_day": int((gaps == 0).sum()),
    }


def reading_checks(
    values: pd.Series,
    dates: pd.Series | None,
    vehicles: pd.Series | None,
) -> dict[str, float | int | None]:
    """Min/median/max of an odometer or engine-hours column + impossible values.

    Impossible = negative, zero, or lower than the same vehicle's previous
    reading (by date). The decreasing check uses only positive readings so a
    zero or negative value is not counted twice; it needs date + vehicle.
    """
    texts = values.map(_text)
    numbers = pd.to_numeric(texts, errors="coerce")
    valid = numbers.dropna()
    result: dict[str, float | int | None] = {
        "numeric": len(valid),
        "missing": int(texts.isna().sum()),
        "non_numeric": int((texts.notna() & numbers.isna()).sum()),
        "min": valid.min() if len(valid) else None,
        "median": valid.median() if len(valid) else None,
        "max": valid.max() if len(valid) else None,
        "negative": int((valid < 0).sum()),
        "zero": int((valid == 0).sum()),
        "decreasing": None,
    }
    if dates is not None and vehicles is not None:
        frame = pd.DataFrame(
            {"vehicle": vehicles.map(_text), "date": dates, "value": numbers}
        ).dropna()
        frame = frame[frame["value"] > 0].sort_values(["vehicle", "date"], kind="stable")
        result["decreasing"] = int((frame.groupby("vehicle")["value"].diff() < 0).sum())
    return result


# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------
def _check_columns(df: pd.DataFrame, names: Iterable[str | None]) -> None:
    """Raise a clear error if a column given on the command line does not exist."""
    missing = [n for n in names if n is not None and n not in df.columns]
    if missing:
        raise ValueError(f"Column(s) not found: {missing}. Available: {list(df.columns)}")


def _columns_section(df: pd.DataFrame, masked: dict[str, str]) -> list[str]:
    """Table of every column: dtype, missing %, unique count, masked or not."""
    rows = []
    for col in df.columns:
        texts = df[col].map(_text)
        missing_pct = 100 * texts.isna().mean() if len(df) else 0.0
        rows.append([
            col,
            str(df[col].dtype),
            f"{missing_pct:.1f}%",
            str(texts.nunique()),
            f"MASKED ({masked[col]})" if col in masked else "",
        ])
    return ["## Columns", ""] + _md_table(
        ["column", "dtype", "missing", "unique", "privacy"], rows
    )


def _dates_section(df: pd.DataFrame, date_col: str | None) -> tuple[list[str], pd.Series | None]:
    """Date range + unparseable count. Also returns the parsed dates for reuse."""
    lines = ["## Date range", ""]
    if date_col is None:
        return lines + ["No date column found (use --date-col)."], None
    dates = parse_dates(df[date_col])
    filled = df[date_col].map(_text).notna()
    lines += [
        f"- Date column: `{date_col}`",
        f"- Earliest: {dates.min().date() if dates.notna().any() else 'n/a'}",
        f"- Latest: {dates.max().date() if dates.notna().any() else 'n/a'}",
        f"- Missing: {int((~filled).sum())}",
        f"- Filled but unparseable: {int((filled & dates.isna()).sum())}",
    ]
    return lines, dates


def _value_counts_section(df: pd.DataFrame, skip: set[str]) -> list[str]:
    """Value counts for non-personal, low-cardinality columns."""
    lines = [
        "## Value counts (non-personal columns)",
        "",
        f"Categories with fewer than {MIN_GROUP_SIZE} rows are merged into \"other\".",
    ]
    for col in df.columns:
        if col in skip:
            continue
        unique = df[col].map(_text).nunique()
        lines += ["", f"### {col}", ""]
        if unique > MAX_CATEGORIES:
            lines.append(f"Skipped: {unique} unique values (more than {MAX_CATEGORIES}).")
            continue
        lines += _md_table(["value", "rows"], [[v, str(n)] for v, n in safe_value_counts(df[col])])
    return lines


def _gaps_section(dates: pd.Series | None, vehicles: pd.Series | None) -> list[str]:
    """Days between visits per vehicle (aggregated only)."""
    lines = ["## Days between visits (same vehicle)", ""]
    if dates is None or vehicles is None:
        return lines + ["Needs both a date and a vehicle column (use --date-col / --vehicle-col)."]
    g = visit_gaps(dates, vehicles)
    return lines + [
        f"- Rows used: {g['rows_used']} (dropped for missing date/vehicle: {g['rows_dropped']})",
        f"- Vehicles: {g['vehicles']} (with 2+ visits: {g['vehicles_2plus']})",
        f"- Gaps measured: {g['gaps']}",
        f"- Min / median / max days: {_fmt(g['min'])} / {_fmt(g['median'])} / {_fmt(g['max'])}",
        f"- Same-day repeat visits (gap = 0, possible duplicates): {g['same_day']}",
        "- Note: vehicles are grouped by the raw identifier text (no plate "
        "normalization yet), so typos split one truck into two.",
    ]


def _readings_section(
    title: str,
    col: str | None,
    df: pd.DataFrame,
    dates: pd.Series | None,
    vehicles: pd.Series | None,
) -> list[str]:
    """Odometer / engine-hours statistics and impossible-value counts."""
    lines = [f"## {title}", ""]
    if col is None:
        return lines + ["No column found."]
    r = reading_checks(df[col], dates, vehicles)
    decreasing = "n/a (needs date + vehicle)" if r["decreasing"] is None else str(r["decreasing"])
    return lines + [
        f"- Column: `{col}`",
        f"- Numeric: {r['numeric']}, missing: {r['missing']}, non-numeric text: {r['non_numeric']}",
        f"- Min / median / max: {_fmt(r['min'])} / {_fmt(r['median'])} / {_fmt(r['max'])}",
        f"- Impossible: negative {r['negative']}, zero {r['zero']}, "
        f"decreasing per vehicle {decreasing}",
    ]


def build_report(
    df: pd.DataFrame,
    source_name: str,
    sheet_label: str,
    date_col: str | None = None,
    vehicle_col: str | None = None,
    odometer_col: str | None = None,
    hours_col: str | None = None,
) -> str:
    """Build the full Markdown profile. Columns not given are guessed."""
    _check_columns(df, [date_col, vehicle_col, odometer_col, hours_col])
    masked = find_personal_columns(df)
    vehicle_col = vehicle_col or guess_vehicle_column(df, masked)
    if vehicle_col is not None and vehicle_col not in masked:
        masked[vehicle_col] = "vehicle identifier"
    date_col = date_col or guess_date_column(df, exclude=masked)
    measured = set(masked) | {date_col}
    odometer_col = odometer_col or pick_column([c for c in df.columns if c not in measured], ODOMETER_KEYWORDS)
    measured.add(odometer_col)
    hours_col = hours_col or pick_column([c for c in df.columns if c not in measured], HOURS_KEYWORDS)

    empty_rows = int(df.map(_text).isna().all(axis=1).sum()) if len(df.columns) else len(df)
    date_lines, dates = _dates_section(df, date_col)
    vehicles = df[vehicle_col] if vehicle_col is not None else None
    skip = set(masked) | {c for c in (date_col, odometer_col, hours_col) if c is not None}

    lines = [
        "# Records profile (PRIVATE — do not commit)",
        "",
        f"- File: `{source_name}`, sheet: {sheet_label}",
        f"- Rows: {len(df)} (completely empty: {empty_rows})",
        f"- Columns: {len(df.columns)} (masked as personal: {len(masked)})",
        "",
    ]
    lines += _columns_section(df, masked) + [""]
    lines += date_lines + [""]
    lines += _value_counts_section(df, skip) + [""]
    lines += _gaps_section(dates, vehicles) + [""]
    lines += _readings_section("Odometer (km)", odometer_col, df, dates, vehicles) + [""]
    lines += _readings_section("Engine hours", hours_col, df, dates, vehicles)
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------
# Command line
# --------------------------------------------------------------------------
def load_sheet(path: Path, sheet: str | None) -> tuple[pd.DataFrame, str]:
    """Read one sheet. Returns the data and a label that avoids the sheet name
    (sheet names can be customer names)."""
    with pd.ExcelFile(path) as book:
        names = book.sheet_names
        if sheet is None:
            index = 0
        elif sheet.isdigit():
            index = int(sheet)
        elif sheet in names:
            index = names.index(sheet)
        else:
            raise ValueError(f"Sheet not found: {sheet!r}")
        df = book.parse(index)
    df.columns = [str(c).strip() for c in df.columns]
    return df, f"#{index} of {len(names)}"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    """Command-line options."""
    p = argparse.ArgumentParser(description="Privacy-safe profile of a records Excel file.")
    p.add_argument("path", type=Path, help="Excel file (.xlsx)")
    p.add_argument("--sheet", help="sheet name or 0-based index (default: first)")
    p.add_argument("--date-col", help="service date column (default: guessed)")
    p.add_argument("--vehicle-col", help="plate / fleet number column (default: guessed)")
    p.add_argument("--odometer-col", help="odometer km column (default: guessed)")
    p.add_argument("--hours-col", help="engine hours column (default: guessed)")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT, help=f"report path (default: {DEFAULT_OUT})")
    return p.parse_args(argv)


def main(argv: list[str] | None = None) -> None:
    """Profile the file, print the report, and save it as Markdown."""
    args = parse_args(argv)
    df, sheet_label = load_sheet(args.path, args.sheet)
    report = build_report(
        df,
        source_name=args.path.name,
        sheet_label=sheet_label,
        date_col=args.date_col,
        vehicle_col=args.vehicle_col,
        odometer_col=args.odometer_col,
        hours_col=args.hours_col,
    )
    print(report)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(report, encoding="utf-8")
    print(f"Saved to {args.out}")


if __name__ == "__main__":
    main()
