"""Tests for src/data/generator.py and src/data/synthetic_report.py (Task 1.3).

All data here is SYNTHETIC. Outputs go to pytest's tmp_path, never data/ or docs/.
"""

import copy
from pathlib import Path

import numpy as np
import pandas as pd
import pytest
import yaml

from src.common.plates import normalize_plate
from src.data.generator import (
    driving_days,
    generate,
    load_config,
    main,
    plate_lookalike,
    season_of,
    untagged_params,
    validate_config,
)
from src.data.synthetic_report import closeness_label, ks_statistic

CONFIG = Path("configs/generator.yaml")
TRUTH_COLUMNS = {"vehicle_id", "next_outcome", "days_to_next_change", "km_to_next_change",
                 "veh_speed_kmh", "veh_hours_per_day", "veh_late_prob"}


@pytest.fixture(scope="module")
def base_cfg() -> dict:
    """The real config (parameters as committed)."""
    return load_config(CONFIG)


@pytest.fixture(scope="module")
def data(base_cfg: dict) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    """One full-size run (500 vehicles, < 1 s), shared by the statistical tests."""
    return generate(base_cfg)


def small_cfg(base: dict, tmp_path: Path, n: int = 40) -> dict:
    """Config copy with few vehicles and every output inside tmp_path."""
    cfg = copy.deepcopy(base)
    cfg["fleet"]["n_vehicles"]["value"] = n
    cfg["output_dir"] = str(tmp_path / "synthetic")
    cfg["report_path"] = str(tmp_path / "report.md")
    cfg["figures_dir"] = str(tmp_path / "figures")
    cfg["real_intervals_path"] = str(tmp_path / "real_intervals.csv")
    return cfg


# --- config -----------------------------------------------------------------

def test_every_parameter_is_tagged(base_cfg: dict) -> None:
    assert untagged_params(base_cfg) == []
    tags = [n["tag"] for n in base_cfg["trip"].values()]
    assert all(t.startswith("[ESTIMATE]") or t.startswith("[SOURCE") for t in tags)


def test_brief_ranges_are_in_config(base_cfg: dict) -> None:
    trip = base_cfg["trip"]
    assert (trip["speed_kmh"]["min"], trip["speed_kmh"]["max"]) == (90, 110)
    assert (trip["driving_hours_per_day"]["min"], trip["driving_hours_per_day"]["max"]) == (8, 11)
    assert (trip["waiting_days_per_trip"]["min"], trip["waiting_days_per_trip"]["max"]) == (0, 5)
    assert base_cfg["interval"]["min_km"]["value"] == 15000
    assert base_cfg["interval"]["max_km"]["value"] == 20000


def test_untagged_parameter_is_rejected(base_cfg: dict) -> None:
    cfg = copy.deepcopy(base_cfg)
    del cfg["trip"]["speed_kmh"]["tag"]
    with pytest.raises(ValueError, match="trip.speed_kmh"):
        validate_config(cfg)


def test_return_shares_must_sum_to_one(base_cfg: dict) -> None:
    cfg = copy.deepcopy(base_cfg)
    cfg["return_behavior"]["never_share"]["value"] = 0.3
    with pytest.raises(ValueError, match="sum to 1"):
        validate_config(cfg)


# --- formulas ---------------------------------------------------------------

def test_driving_days_formula() -> None:
    # Zamyn-Uud round trip 1,312 km at 100 km/h × 10 h/day = 1.312 days.
    assert driving_days(1312, 100, 10) == pytest.approx(1.312)


@pytest.mark.parametrize("month, season", [(1, "winter"), (12, "winter"), (4, "spring"), (7, "summer"), (10, "autumn")])
def test_season_of(month: int, season: str) -> None:
    assert season_of(pd.Timestamp(2025, month, 15).date()) == season


def test_ks_statistic() -> None:
    a = pd.Series([1, 2, 3, 4])
    assert ks_statistic(a, a) == 0.0
    assert ks_statistic(a, a + 100) == 1.0
    assert closeness_label(0.05) == "close"
    assert closeness_label(0.5) == "far apart"


# --- reproducibility ----------------------------------------------------------

def test_same_seed_same_data(base_cfg: dict, tmp_path: Path) -> None:
    cfg = small_cfg(base_cfg, tmp_path)
    for a, b in zip(generate(cfg), generate(cfg)):
        pd.testing.assert_frame_equal(a, b)


def test_other_seed_other_data(base_cfg: dict, tmp_path: Path) -> None:
    cfg = small_cfg(base_cfg, tmp_path)
    other = copy.deepcopy(cfg)
    other["seed"] = cfg["seed"] + 1
    assert not generate(cfg)[0].equals(generate(other)[0])


# --- clean data rules -----------------------------------------------------------

def test_no_vehicle_model_or_oil_grade(data: tuple) -> None:
    for df in data[:2]:
        assert not {"vehicle_model", "oil_grade"} & set(df.columns)


def test_on_time_inside_interval_and_late_beyond(data: tuple, base_cfg: dict) -> None:
    clean = data[0]
    on_time = clean.loc[clean["next_outcome"] == "on_time", "km_to_next_change"]
    late = clean.loc[clean["next_outcome"] == "late", "km_to_next_change"]
    assert on_time.between(15000, 20000).all()
    assert (late >= 20000).all()
    assert (clean["days_to_next_change"].dropna() > 0).all()


def test_target_only_when_next_visit_observed(data: tuple) -> None:
    clean = data[0]
    observed = clean["next_outcome"].isin(["on_time", "late"])
    assert clean.loc[observed, "days_to_next_change"].notna().all()
    assert clean.loc[~observed, "days_to_next_change"].isna().all()


def test_history_is_consistent_per_vehicle(data: tuple) -> None:
    clean = data[0].sort_values(["vehicle_id", "service_date"])
    for _, g in clean.groupby("vehicle_id"):
        dates = pd.to_datetime(g["service_date"])
        assert (dates.diff().dt.days.iloc[1:].to_numpy() == g["days_to_next_change"].iloc[:-1].to_numpy()).all()
        assert (g["odometer_km"].diff().iloc[1:].to_numpy() == g["km_to_next_change"].iloc[:-1].to_numpy()).all()
        # Only the last record can end the history (never / censored).
        assert g["next_outcome"].iloc[:-1].isin(["on_time", "late"]).all()
        assert g["next_outcome"].iloc[-1] in {"never", "censored"}


def test_return_shares_near_d031(data: tuple) -> None:
    decided = data[0].query("next_outcome != 'censored'")
    share = decided["next_outcome"].value_counts(normalize=True)
    assert share["on_time"] == pytest.approx(0.50, abs=0.04)
    assert share["late"] == pytest.approx(0.40, abs=0.04)
    assert share["never"] == pytest.approx(0.10, abs=0.03)


def test_equal_destination_mix(data: tuple) -> None:
    # Home destinations are drawn equally -> first records spread over all 5.
    first = data[0].sort_values("service_date").groupby("vehicle_id").first()
    share = first["destination_name"].value_counts(normalize=True)
    assert len(share) == 5
    assert share.max() - share.min() < 0.08


def test_variation_off_gives_identical_vehicles(base_cfg: dict, tmp_path: Path) -> None:
    cfg = small_cfg(base_cfg, tmp_path)
    cfg["variation"]["enabled"]["value"] = False
    clean = generate(cfg)[0]
    assert clean["veh_speed_kmh"].nunique() == 1
    assert clean["veh_late_prob"].nunique() == 1
    # No destination changes (V6 off): one destination per vehicle.
    assert (clean.groupby("vehicle_id")["destination_name"].nunique() == 1).all()


# --- dirty data -----------------------------------------------------------------

def test_dirty_has_no_truth(data: tuple) -> None:
    assert not TRUTH_COLUMNS & set(data[1].columns)


def test_noise_rates_near_config(data: tuple, base_cfg: dict) -> None:
    clean, _, log = data
    applied = log["noise"].value_counts() / len(clean)
    assert applied["N5"] == pytest.approx(base_cfg["noise"]["destination_variant"]["value"], abs=0.02)
    assert applied["N2"] == pytest.approx(base_cfg["noise"]["missing_driver_name"]["value"], abs=0.02)
    assert applied["N11"] == pytest.approx(base_cfg["noise"]["duplicate_record"]["value"], abs=0.01)


def test_noisy_plates_normalize_back(data: tuple) -> None:
    """N6/N7 are typing noise: plates.py must undo them (cleaning relies on this)."""
    clean, dirty, log = data
    touched = log.loc[log["noise"].isin(["N6", "N7"]), "record_id"].unique()
    merged = dirty[dirty["record_id"].isin(touched)].merge(clean[["record_id", "plate_normalized"]], on="record_id")
    assert len(merged) > 0
    assert (merged["plate"].map(normalize_plate) == merged["plate_normalized"]).all()


def test_plate_lookalike() -> None:
    rng = np.random.default_rng(0)
    changed = plate_lookalike("1234АБВ", rng)
    assert changed is not None and changed != "1234АБВ" and normalize_plate(changed) == "1234АБВ"
    assert plate_lookalike("1234БГД", rng) is None  # no Latin look-alike letters


# --- command + report -------------------------------------------------------------

def run_main(cfg: dict, tmp_path: Path) -> str:
    path = tmp_path / "generator.yaml"
    path.write_text(yaml.safe_dump(cfg, allow_unicode=True), encoding="utf-8")
    assert main(["--config", str(path)]) == 0
    return Path(cfg["report_path"]).read_text(encoding="utf-8")


def test_main_writes_files_and_same_report_twice(base_cfg: dict, tmp_path: Path) -> None:
    cfg = small_cfg(base_cfg, tmp_path)
    first = run_main(cfg, tmp_path)
    out = Path(cfg["output_dir"])
    for name in ("service_records_clean.csv", "service_records_dirty.csv", "noise_log.csv"):
        assert (out / name).exists()
    assert (Path(cfg["figures_dir"]) / "synthetic_interval_distribution.png").exists()
    assert "was not found" in first
    assert run_main(cfg, tmp_path) == first


def test_report_compares_with_real_when_present(base_cfg: dict, tmp_path: Path) -> None:
    cfg = small_cfg(base_cfg, tmp_path)
    # FAKE "real" gaps, only to exercise the comparison code.
    pd.DataFrame({"days_between_visits": [30, 45, 60, 75, 90, 120]}).to_csv(cfg["real_intervals_path"], index=False)
    report = run_main(cfg, tmp_path)
    assert "KS statistic" in report
    assert (Path(cfg["figures_dir"]) / "synthetic_vs_real_days.png").exists()


def test_real_file_without_column_fails(base_cfg: dict, tmp_path: Path) -> None:
    cfg = small_cfg(base_cfg, tmp_path)
    pd.DataFrame({"gap": [30]}).to_csv(cfg["real_intervals_path"], index=False)
    with pytest.raises(ValueError, match="days_between_visits"):
        run_main(cfg, tmp_path)
