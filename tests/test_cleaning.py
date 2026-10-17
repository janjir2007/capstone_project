"""Tests for src/data/cleaning.py and src/data/cleaning_report.py (Task 1.4).

All data here is FAKE or synthetic; files go to pytest's tmp_path.
"""

import copy
import inspect
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

import src.data.cleaning as cleaning
from src.data.cleaning import (
    INPUT_COLUMNS,
    alias_table,
    clean_records,
    find_odometer_outliers,
    load_config,
    match_destination,
    text_key,
)
from src.data.cleaning_report import score_rules
from src.data.generator import generate, write_outputs
from src.data.generator import load_config as load_generator_config

CONFIG = Path("configs/cleaning.yaml")


@pytest.fixture(scope="module")
def cfg() -> dict:
    return load_config(CONFIG)


def records(rows: list[dict]) -> pd.DataFrame:
    """Fake dirty table: defaults for every input column, overridden per row."""
    base = {"company_name": "Тест ХХК", "plate": "1234УБА", "service_date": "2025-01-01",
            "created_at": None, "odometer_km": np.nan, "destination_raw": "Beijing", "route": "mn_china",
            "driver_name": "Б. Тест", "driver_phone": "99112233"}
    df = pd.DataFrame([{**base, "record_id": i + 1, **r} for i, r in enumerate(rows)])
    df["created_at"] = df["created_at"].fillna(df["service_date"])
    return df[INPUT_COLUMNS]


def issues_of(issues: pd.DataFrame, record_id: int) -> set[str]:
    return set(issues.loc[issues["record_id"] == record_id, "issue"])


# --- no peeking -------------------------------------------------------------------

def test_cleaning_never_touches_truth() -> None:
    assert list(inspect.signature(clean_records).parameters) == ["dirty", "cfg"]
    source = inspect.getsource(cleaning)
    for forbidden in ("service_records_clean.csv", "NOISE_LOG_FILE", "CLEAN_FILE", "noise_log.csv"):
        assert forbidden not in source


def test_aliases_are_not_copied_from_generator(cfg: dict) -> None:
    gen = load_generator_config(Path("configs/generator.yaml"))["destination_variants"]
    generator_spellings = {v for k, vs in gen.items() if k != "tag" for v in vs}
    own = {a for d in cfg["destinations"] for a in d["aliases"]}
    # Mongolian names and official short names may overlap; Latin noise spellings must not.
    assert not {"zamiin uud", "Zamyn Uud", "Beejin", "Khiagt", "ereen", "beijing", "altanbulag"} & own
    assert generator_spellings  # sanity: the generator list was read


# --- destinations -------------------------------------------------------------------

def test_text_key() -> None:
    assert text_key("Замын-Үүд") == text_key("Zamyn Uud") == "zamynuud"


@pytest.mark.parametrize("raw, expected", [
    ("Замын Үүд", "Zamyn-Uud (MN–CN border)"),
    ("zamiin uud", "Zamyn-Uud (MN–CN border)"),
    ("Khiagt", "Kyakhta (RU side of border)"),
    ("Beejin", "Beijing"),
    ("Эрээн", "Erenhot (CN side of border)"),
    # Task 1.6 destinations: the generator's N5 spellings must still be found.
    ("Ганц мод", "Ganqimaodu (CN side of Gashuunsukhait border)"),
    ("gantsmod", "Ganqimaodu (CN side of Gashuunsukhait border)"),
    ("sehee", "Ceke (CN side of Shiveekhuren border)"),
    ("Улаан Үд", "Ulan-Ude (via Altanbulag–Kyakhta)"),
    ("ulaan ud", "Ulan-Ude (via Altanbulag–Kyakhta)"),
    ("koshagach", "Kosh-Agach (via Tsagaannuur–Tashanta)"),
    ("Кош Агач", "Kosh-Agach (via Tsagaannuur–Tashanta)"),
    ("Moscow", None),
])
def test_match_destination(cfg: dict, raw: str, expected: str | None) -> None:
    assert match_destination(raw, alias_table(cfg), 0.8, 0.05) == expected


def test_route_follows_destination(cfg: dict) -> None:
    cleaned, issues = clean_records(records([{"destination_raw": "Алтанбулаг", "route": "mn_china"}]), cfg)
    assert cleaned.loc[0, "route"] == "mn_russia"  # D-039: destination wins
    assert "destination_variant" in issues_of(issues, 1)


# --- plates, phones, names ---------------------------------------------------------

def test_plate_and_phone(cfg: dict) -> None:
    dirty = records([
        {"plate": "1234 YBA", "driver_phone": "+976 9911 2233"},
        {"plate": "5678УНБ", "driver_phone": "123", "service_date": "2025-02-01"},
        {"plate": "5678УНБ", "driver_phone": None, "driver_name": " ", "service_date": "2025-03-01"},
    ])
    cleaned, issues = clean_records(dirty, cfg)
    row1 = cleaned.set_index("record_id").loc[1]
    assert row1["plate_normalized"] == "1234УВА" and row1["driver_phone"] == "99112233"
    assert {"plate_latin_lookalike", "plate_spacing", "phone_format"} <= issues_of(issues, 1)
    assert "phone_invalid" in issues_of(issues, 2)
    assert {"phone_missing", "driver_name_missing"} <= issues_of(issues, 3)


# --- duplicates, late entry ----------------------------------------------------------

def test_duplicate_keeps_most_complete(cfg: dict) -> None:
    dirty = records([
        {"plate": "1234УБА", "driver_phone": None},
        {"plate": "1234 УБА", "driver_phone": "99112233"},  # same truck, same day, more complete
    ])
    cleaned, issues = clean_records(dirty, cfg)
    assert cleaned["record_id"].tolist() == [2]
    assert issues_of(issues, 1) >= {"duplicate"}


def test_late_entry_flagged_not_changed(cfg: dict) -> None:
    cleaned, issues = clean_records(records([{"created_at": "2025-01-05"}]), cfg)
    assert str(cleaned.loc[0, "service_date"]) == "2025-01-01"
    assert "late_entry" in issues_of(issues, 1)


# --- odometer ------------------------------------------------------------------------

def odometer_case(cfg: dict, kms: list[float]) -> tuple[pd.DataFrame, pd.DataFrame]:
    dates = pd.date_range("2025-01-01", periods=len(kms), freq="60D").strftime("%Y-%m-%d")
    return clean_records(records([{"service_date": d, "odometer_km": k} for d, k in zip(dates, kms)]), cfg)


def test_odometer_clean_sequence_untouched(cfg: dict) -> None:
    cleaned, issues = odometer_case(cfg, [100000, 118000, 135000, 153000])
    assert cleaned["odometer_km"].tolist() == [100000, 118000, 135000, 153000]
    assert issues.empty


def test_odometer_times_ten_fixed(cfg: dict) -> None:
    cleaned, issues = odometer_case(cfg, [100000, 1180000, 135000, 153000])
    assert cleaned["odometer_km"].tolist()[1] == 118000
    assert "odometer_digit_error" in issues_of(issues, 2)


def test_odometer_divided_by_ten_first_reading_fixed(cfg: dict) -> None:
    cleaned, issues = odometer_case(cfg, [10000, 118000, 135000])
    assert cleaned["odometer_km"].tolist()[0] == 100000
    assert "odometer_digit_error" in issues_of(issues, 1)


def test_odometer_lower_than_last_emptied_not_the_true_one(cfg: dict) -> None:
    # Regression: 2nd reading dropped below the 1st; the 1st must NOT be "repaired" ÷10.
    dates = ["2025-01-01", "2025-05-01", "2025-07-01"]
    kms = [145163, 143270, 215000]
    cleaned, issues = clean_records(records([{"service_date": d, "odometer_km": k} for d, k in zip(dates, kms)]), cfg)
    assert cleaned["odometer_km"].iloc[0] == 145163
    assert pd.isna(cleaned["odometer_km"].iloc[1])
    assert "odometer_lower_than_last" in issues_of(issues, 2)


def test_find_outliers_no_readings() -> None:
    assert find_odometer_outliers([], [], 1500, 500, [10, 0.1], 5) == set()


# --- end to end on generated data --------------------------------------------------

@pytest.fixture(scope="module")
def generated(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Small synthetic run (150 vehicles) written to a temp folder."""
    gen_cfg = copy.deepcopy(load_generator_config(Path("configs/generator.yaml")))
    gen_cfg["fleet"]["n_vehicles"]["value"] = 150
    out = tmp_path_factory.mktemp("synthetic")
    write_outputs(*generate(gen_cfg), out)
    return out


def test_scores_on_generated_data(cfg: dict, generated: Path) -> None:
    dirty = pd.read_csv(generated / "service_records_dirty.csv", dtype={"plate": str, "driver_phone": str})
    truth = pd.read_csv(generated / "service_records_clean.csv", dtype={"driver_phone": str})
    noise_log = pd.read_csv(generated / "noise_log.csv")
    cleaned, issues = clean_records(dirty, cfg)
    assert len(cleaned) == len(truth)  # every duplicate removed, nothing else dropped
    scores = score_rules(cleaned, issues, noise_log, truth).set_index("Rule")
    others = scores.drop(index="N8")
    assert (others["Precision"].dropna() >= 0.95).all()
    assert (others["Recall"].dropna() >= 0.95).all()
    # N8: a truck with only 2 readings and a ×10/÷10 error cannot be decided (fixing
    # either reading makes the pair consistent; the tie-break picks the later one).
    # Since task 1.6's destination mix, this seed has one such truck. Every other N8
    # record must be found, and every N8 find must be right.
    found = set(issues.loc[issues["issue"] == "odometer_digit_error", "record_id"])
    logged = set(noise_log.loc[noise_log["noise"] == "N8", "record_id"])
    readings = truth.groupby("vehicle_id")["record_id"].transform("size")
    vehicle_of = truth.set_index("record_id")["vehicle_id"]
    for errors in (found - logged, logged - found):  # wrong finds, missed records
        assert set(readings[truth["record_id"].isin(errors)]) <= {2}
    assert {vehicle_of[r] for r in found ^ logged if r in vehicle_of.index} == \
        {vehicle_of[r] for r in found - logged}  # misses and wrong finds are the same trucks
    assert len(found - logged) <= 1


def test_main_writes_files_and_same_report_twice(generated: Path, tmp_path: Path) -> None:
    args = ["--input", str(generated / "service_records_dirty.csv"), "--output", str(tmp_path / "cleaned.csv"),
            "--report", str(tmp_path / "report.md")]
    assert cleaning.main(args) == 0
    first = (tmp_path / "report.md").read_text(encoding="utf-8")
    assert (tmp_path / "cleaned_issues.csv").exists()
    assert "Precision" in first
    assert cleaning.main(args) == 0
    assert (tmp_path / "report.md").read_text(encoding="utf-8") == first


def test_no_score_mode_needs_no_answer_key(tmp_path: Path) -> None:
    """Real-data mode: only the records file exists, no truth / noise_log next to it."""
    src = tmp_path / "real.csv"
    records([{"plate": "1234 УБА", "odometer_km": 100000}]).to_csv(src, index=False)
    assert cleaning.main(["--input", str(src), "--output", str(tmp_path / "out.csv"), "--no-score",
                          "--report", str(tmp_path / "r.md")]) == 0
    assert (tmp_path / "out.csv").exists() and not (tmp_path / "r.md").exists()


def test_missing_input_column_rejected(tmp_path: Path) -> None:
    src = tmp_path / "bad.csv"
    pd.DataFrame({"plate": ["1234УБА"]}).to_csv(src, index=False)
    with pytest.raises(ValueError, match="missing columns"):
        cleaning.read_records(src)
