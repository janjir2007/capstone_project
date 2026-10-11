"""Tests for src/common/features.py (Task 2.2). Small hand-made visits, no data files."""

import numpy as np
import pandas as pd
import pytest

from src.common import features as F
from src.data.generator import SEASON_BY_MONTH as GENERATOR_SEASONS

ROUTES = {
    "Beijing": F.Route(route="mn_china", one_way_km=1330, km_per_day=500.0),
    "Kyakhta": F.Route(route="mn_russia", one_way_km=351, km_per_day=200.0),
}


def visits(rows: list[tuple]) -> pd.DataFrame:
    """rows: (vehicle, date, odometer, destination)."""
    df = pd.DataFrame(rows, columns=["vehicle_key", "service_date", "odometer_km", "destination_name"])
    df["service_date"] = pd.to_datetime(df["service_date"])
    df["route"] = df["destination_name"].map(lambda d: ROUTES[d].route if d in ROUTES else None)
    return df


@pytest.fixture()
def truck_a() -> pd.DataFrame:
    # 3 visits, 50 and 60 days apart; 18,000 km then 21,000 km (late)
    return visits([
        ("A", "2025-01-01", 100_000, "Beijing"),
        ("A", "2025-02-20", 118_000, "Kyakhta"),
        ("A", "2025-04-21", 139_000, "Beijing"),
    ])


def test_first_visit_has_empty_history(truck_a: pd.DataFrame) -> None:
    f = F.build_features(truck_a, ROUTES).iloc[0]
    assert f["n_prior_visits"] == 0
    for col in ("days_since_prev_visit", "past_interval_mean_days", "km_per_day_hist", "past_late_share"):
        assert np.isnan(f[col]), col


def test_history_uses_only_earlier_visits(truck_a: pd.DataFrame) -> None:
    f = F.build_features(truck_a, ROUTES)
    assert f["n_prior_visits"].tolist() == [0, 1, 2]
    assert f.loc[1, "days_since_prev_visit"] == 50
    assert f.loc[2, "past_interval_mean_days"] == 55
    assert f.loc[1, "km_per_day_hist"] == pytest.approx(18_000 / 50)
    assert f.loc[2, "km_per_day_hist"] == pytest.approx(39_000 / 110)
    assert f.loc[1, "past_late_share"] == 0.0
    assert f.loc[2, "past_late_share"] == 0.5


def test_future_visit_does_not_change_past_features(truck_a: pd.DataFrame) -> None:
    """No leakage: adding a later visit leaves earlier rows' features identical."""
    before = F.build_features(truck_a.iloc[:2], ROUTES)
    after = F.build_features(truck_a, ROUTES).iloc[:2]
    pd.testing.assert_frame_equal(before, after)


def test_api_style_last_row_equals_batch_row(truck_a: pd.DataFrame) -> None:
    """The API passes history + new visit and takes the last row: same as training's row (R8)."""
    other = visits([("B", "2025-01-10", 5_000, "Kyakhta"), ("B", "2025-03-01", 20_000, "Kyakhta")])
    batch = F.build_features(pd.concat([other, truck_a], ignore_index=True), ROUTES)
    single = F.build_features(truck_a, ROUTES)
    pd.testing.assert_series_equal(batch.iloc[-1], single.iloc[-1], check_names=False)


def test_unsorted_input_keeps_index_and_order(truck_a: pd.DataFrame) -> None:
    shuffled = truck_a.iloc[[2, 0, 1]]
    f = F.build_features(shuffled, ROUTES)
    assert list(f.index) == [2, 0, 1]
    assert f.loc[2, "n_prior_visits"] == 2


def test_route_columns_and_unknown_destination() -> None:
    df = visits([("C", "2025-07-01", 1_000, "Beijing"), ("C", "2025-12-05", 2_000, None)])
    f = F.build_features(df, ROUTES)
    assert f.loc[0, "route"] == "mn_china" and f.loc[0, "route_km_per_day"] == 500.0
    assert f.loc[0, "season"] == "summer" and f.loc[1, "season"] == "winter"
    assert f.loc[1, "destination_name"] == F.UNKNOWN and f.loc[1, "route"] == F.UNKNOWN
    assert np.isnan(f.loc[1, "one_way_km"])


def test_missing_odometer_is_skipped_not_guessed() -> None:
    df = visits([("D", "2025-01-01", 10_000, "Kyakhta"), ("D", "2025-02-01", np.nan, "Kyakhta"),
                 ("D", "2025-03-02", 30_000, "Kyakhta")])
    f = F.build_features(df, ROUTES)
    assert np.isnan(f.loc[1, "km_per_day_hist"])          # only one reading so far
    assert f.loc[2, "km_per_day_hist"] == pytest.approx(20_000 / 60)
    assert np.isnan(f.loc[2, "past_late_share"])          # no interval with both readings


def test_late_km_is_a_parameter(truck_a: pd.DataFrame) -> None:
    f = F.build_features(truck_a, ROUTES, late_km=17_000)
    assert f.loc[2, "past_late_share"] == 1.0


def test_columns_and_missing_input() -> None:
    assert F.FEATURE_COLUMNS == F.CATEGORICAL_FEATURES + F.NUMERIC_FEATURES
    with pytest.raises(ValueError, match="odometer_km"):
        F.build_features(pd.DataFrame({"vehicle_key": [], "service_date": [], "destination_name": [], "route": []}),
                         ROUTES)


def test_empty_input_gives_empty_table() -> None:
    empty = visits([]).astype({"service_date": "datetime64[ns]"})
    assert list(F.build_features(empty, ROUTES).columns) == F.FEATURE_COLUMNS


def test_seasons_match_generator() -> None:
    assert F.SEASON_BY_MONTH == GENERATOR_SEASONS
