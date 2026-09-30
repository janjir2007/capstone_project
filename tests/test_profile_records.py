"""Tests for src/data/profile_records.py (Task 1.4a).

All data here is FAKE. The Excel file is written to pytest's tmp_path, so no
spreadsheet ever lands in the repo (D-015).
"""

from datetime import datetime
from pathlib import Path

import pandas as pd
import pytest

from src.data.profile_records import (
    find_personal_columns,
    main,
    parse_dates,
    personal_reason,
    reading_checks,
    safe_value_counts,
    visit_gaps,
)

# Fake personal values that must NEVER appear in any output.
FAKE_PLATES = ["1234УБА", "5678УНБ", "9012ДАР"]
FAKE_NAMES = ["Бат Тестов", "Дорж Жишээ", "Сараа Хуурамч"]
FAKE_PHONES = ["99112233", "88112233", "95556677", "99887766"]
FAKE_COMPANY = "Тест Тээвэр ХХК"


def fake_records() -> pd.DataFrame:
    """10 fake service rows for 3 trucks, with known quirks.

    Truck A: 4 visits 30 days apart, odometer drops once (105000 < 110000).
    Truck B: two visits on the same day, then 60 + 60 days; one zero reading.
    Truck C: one valid visit (negative odometer) + one row with a bad date.
    """
    a, b, c = FAKE_PLATES
    rows = [
        # plate, date, odometer, oil, route
        (a, datetime(2025, 1, 10), 100000, "15W-40", "UB city"),
        (a, datetime(2025, 2, 9), 110000, "15W-40", "UB city"),
        (a, datetime(2025, 3, 11), 105000, "15W-40", "UB city"),
        (a, datetime(2025, 4, 10), 115000, "15W-40", "UB city"),
        (b, datetime(2025, 1, 15), 50000, "10W-40", "MN–China"),
        (b, datetime(2025, 1, 15), 50000, "10W-40", "MN–China"),
        (b, datetime(2025, 3, 16), 0, "10W-40", "MN–China"),
        (b, datetime(2025, 5, 15), 70000, "10W-40", "MN–China"),
        (c, datetime(2025, 2, 1), -5, "15W-40", "UB city"),
        (c, "not a date", 20000, "5W-30", "UB city"),
    ]
    df = pd.DataFrame(rows, columns=["Улсын дугаар", "Огноо", "Гүйлт км", "Тосны төрөл", "Маршрут"])
    df["Жолоочийн нэр"] = [FAKE_NAMES[i % 3] for i in range(10)]
    df["Утас"] = [int(FAKE_PHONES[i % 3]) for i in range(10)]  # stored as numbers, like Excel
    df["Холбоо барих"] = [FAKE_PHONES[(i + 1) % 3] for i in range(10)]  # neutral name, phone values
    df["Компани"] = FAKE_COMPANY
    df["Моточас"] = [None] * 8 + [1200, 1300]
    df["Тэмдэглэл"] = [f"тэмдэглэл {i}" for i in range(9)] + [f"залгах {FAKE_PHONES[3]}"]
    return df


@pytest.fixture
def fake_excel(tmp_path: Path) -> Path:
    """Write the fake records to a temporary .xlsx file."""
    path = tmp_path / "fake_records.xlsx"
    fake_records().to_excel(path, index=False)
    return path


# ---------------------------------------------------------------- detection
@pytest.mark.parametrize(
    "column",
    ["Жолоочийн нэр", "Driver name", "Утасны дугаар", "phone", "Улсын дугаар",
     "Компанийн нэр", "Company", "Харилцагч", "oil_changer"],
)
def test_personal_column_names(column: str) -> None:
    """Columns named like people/contacts/plates/companies are masked."""
    assert personal_reason(column, pd.Series(["x"])) is not None


def test_phone_values_detected_even_as_floats() -> None:
    """Excel floats like 99112233.0 are still recognized as phones."""
    reason = personal_reason("contact", pd.Series([99112233.0, 88112233.0, None]))
    assert reason is not None and "phone" in reason


def test_plate_and_company_values_detected() -> None:
    """Value patterns catch plates and company names under neutral headers."""
    assert "plates" in personal_reason("col_a", pd.Series(["1234 УБА", "5678УНБ"]))
    assert "company" in personal_reason("col_b", pd.Series(["Тест Тээвэр ХХК", "Өөр ХХК"]))


def test_non_personal_columns_not_masked() -> None:
    """Oil grade, route, odometer, engine hours, notes stay unmasked."""
    masked = find_personal_columns(fake_records())
    assert set(masked) == {"Улсын дугаар", "Жолоочийн нэр", "Утас", "Холбоо барих", "Компани"}


# ---------------------------------------------------------------- statistics
def test_safe_value_counts_merges_small_groups() -> None:
    """Categories with < 3 rows go to "other"; missing is counted separately."""
    series = pd.Series(["15W-40"] * 5 + ["10W-40"] * 3 + ["5W-30", "0W-20", None])
    assert safe_value_counts(series) == [
        ("15W-40", 5),
        ("10W-40", 3),
        ("other (2 categories)", 2),
        ("(missing)", 1),
    ]


def test_parse_dates_rejects_text_and_plain_numbers() -> None:
    """Bad text and bare numbers become NaT instead of wrong 1970 dates."""
    parsed = parse_dates(pd.Series([datetime(2025, 1, 1), "2025-02-03", "not a date", 45000]))
    assert parsed.notna().tolist() == [True, True, False, False]


def test_visit_gaps() -> None:
    """Gaps A: 30,30,30; B: 0,60,60 -> min 0, median 30, max 60."""
    df = fake_records()
    gaps = visit_gaps(parse_dates(df["Огноо"]), df["Улсын дугаар"])
    assert gaps["rows_dropped"] == 1
    assert gaps["vehicles"] == 3 and gaps["vehicles_2plus"] == 2
    assert gaps["gaps"] == 6
    assert (gaps["min"], gaps["median"], gaps["max"]) == (0, 30, 60)
    assert gaps["same_day"] == 1


def test_reading_checks_counts_impossible_values() -> None:
    """One negative, one zero, one decrease (truck A 110000 -> 105000)."""
    df = fake_records()
    r = reading_checks(df["Гүйлт км"], parse_dates(df["Огноо"]), df["Улсын дугаар"])
    assert (r["negative"], r["zero"], r["decreasing"]) == (1, 1, 1)
    assert (r["min"], r["max"]) == (-5, 115000)


def test_reading_checks_without_vehicle() -> None:
    """Without date/vehicle the decreasing check is reported as not available."""
    r = reading_checks(pd.Series(["100", "abc", None]), None, None)
    assert r["decreasing"] is None
    assert (r["numeric"], r["non_numeric"], r["missing"]) == (1, 1, 1)


# ---------------------------------------------------------------- end to end
def test_report_never_leaks_personal_values(
    fake_excel: Path, tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Full run on the fake Excel: report saved, no personal value anywhere."""
    out = tmp_path / "interim" / "records_profile.md"
    main([str(fake_excel), "--out", str(out)])
    printed = capsys.readouterr().out
    saved = out.read_text(encoding="utf-8")

    for text in (printed, saved):
        for secret in FAKE_PLATES + FAKE_NAMES + FAKE_PHONES + [FAKE_COMPANY]:
            assert secret not in text
        assert "Rows: 10" in text
        assert "Earliest: 2025-01-10" in text and "Latest: 2025-05-15" in text
        assert "Min / median / max days: 0 / 30 / 60" in text
        assert "negative 1, zero 1, decreasing per vehicle 1" in text
        assert "| 15W-40 | 5 |" in text
        assert "other (1 categories)" in text  # 5W-30 has only 1 row


def test_unknown_column_raises(fake_excel: Path, tmp_path: Path) -> None:
    """A typo in --date-col gives a clear error instead of a silent guess."""
    with pytest.raises(ValueError, match="not found"):
        main([str(fake_excel), "--date-col", "nope", "--out", str(tmp_path / "x.md")])
