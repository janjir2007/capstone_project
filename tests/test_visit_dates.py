"""Tests for src/data/visit_dates.py (Task 1.4b).

Everything here is FAKE: invented plates in a Label Studio-shaped export
and a hand-made "filled" CSV. No real photos or records are read.
"""

import json
from datetime import date
from pathlib import Path

import pandas as pd
import pytest

from src.data import visit_dates as vd

KEY = b"test-key"
TODAY = date(2026, 10, 11)

# photo -> fake plate text as a labeler might type it
FAKE_LABELS = {
    "a1.jpg": "1234УБА",
    "a2.jpg": "1234 уба",   # same truck, different spelling -> must group with a1
    "a3.jpg": "1234-YБA",   # Latin Y and A look-alikes -> still the same truck
    "b1.jpg": "5678УНТ",
    "b2.jpg": "5678УНТ",
    "c1.jpg": "9999ДАР",    # one photo only -> not a repeat truck
    "d1.jpg": "1111УА?",    # unreadable character -> left out
}


def fake_task(tid: int, image: str, text: str, ptype: str = "plate") -> dict:
    """One exported task with one box + type + text (same shape as tests/test_ls_export.py)."""
    geo = {"x": 10, "y": 10, "width": 20, "height": 8, "rotation": 0}
    base = {"id": f"r{tid}", "to_name": "image"}
    result = [
        {**base, "from_name": "bbox", "type": "rectanglelabels", "value": {**geo, "rectanglelabels": ["plate"]}},
        {**base, "from_name": "plate_type", "type": "choices", "value": {**geo, "choices": [ptype]}},
        {**base, "from_name": "plate_text", "type": "textarea", "value": {**geo, "text": [text]}},
    ]
    return {"id": tid, "data": {"image": f"/data/local-files/?d=photos/{image}"},
            "annotations": [{"id": tid, "result": result, "was_cancelled": False, "updated_at": "2026-10-01"}]}


@pytest.fixture()
def tasks() -> list[dict]:
    return [fake_task(i, img, text) for i, (img, text) in enumerate(FAKE_LABELS.items(), start=1)]


@pytest.fixture()
def export_file(tmp_path: Path, tasks: list[dict]) -> Path:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    return path


@pytest.fixture()
def plates(tasks: list[dict]) -> dict[str, str]:
    return vd.photo_plates(tasks)[0]


def filled_frame(dates: dict[str, str]) -> pd.DataFrame:
    """Template for the fake export with the given photo -> typed date."""
    df = pd.DataFrame({
        "photo_file": ["photos/a1.jpg", "photos/a2.jpg", "photos/a3.jpg", "photos/b1.jpg", "photos/b2.jpg"],
        "truck_no": ["1", "1", "1", "2", "2"],
    })
    df["date"] = [dates.get(p.split("/")[1], "") for p in df["photo_file"]]
    return df


# --- photo -> plate --------------------------------------------------------

def test_photo_plates_normalizes_and_drops_unreadable(tasks: list[dict]) -> None:
    plates, left_out = vd.photo_plates(tasks)
    assert plates["photos/a2.jpg"] == plates["photos/a1.jpg"] == plates["photos/a3.jpg"]
    assert "photos/d1.jpg" not in plates
    assert left_out == 1


def test_photo_with_two_different_plates_is_left_out() -> None:
    two = fake_task(1, "x.jpg", "1234УБА")
    two["annotations"][0]["result"] += fake_task(2, "x.jpg", "5678УНТ")["annotations"][0]["result"]
    plates, left_out = vd.photo_plates([two])
    assert plates == {} and left_out == 1


def test_fleet_number_boxes_are_ignored() -> None:
    plates, _ = vd.photo_plates([fake_task(1, "f.jpg", "1234УБА", ptype="fleet_no")])
    assert plates == {}


def test_repeat_trucks_keeps_only_2plus_photos(plates: dict[str, str]) -> None:
    trucks = vd.repeat_trucks(plates)
    assert sorted(len(v) for v in trucks.values()) == [2, 3]


# --- template --------------------------------------------------------------

def test_template_has_no_plates_and_empty_dates(plates: dict[str, str]) -> None:
    template = vd.build_template(vd.repeat_trucks(plates))
    assert list(template.columns) == vd.TEMPLATE_COLUMNS
    assert sorted(template["truck_no"].unique()) == [1, 2]
    assert (template["date"] == "").all()
    assert template["truck_no"].is_monotonic_increasing  # sorted by truck
    text = template.to_csv(index=False)
    assert not any(p in text for p in plates.values())


def test_template_cli_refuses_to_overwrite(export_file: Path, tmp_path: Path) -> None:
    out = tmp_path / "dates_to_fill.csv"
    assert vd.main(["--export", str(export_file), "template", "--output", str(out)]) == 0
    out.write_text("Ari's work", encoding="utf-8")
    assert vd.main(["--export", str(export_file), "template", "--output", str(out)]) == 1
    assert out.read_text(encoding="utf-8") == "Ari's work"


# --- dates -----------------------------------------------------------------

@pytest.mark.parametrize("text", ["2026-09-01", "2026.09.01", "2026/09/01"])
def test_parse_date_allowed_formats(text: str) -> None:
    assert vd.parse_date(text) == date(2026, 9, 1)


@pytest.mark.parametrize("text", ["01/09/2026", "Sept 1", "2026-13-01"])
def test_parse_date_rejects_ambiguous_or_bad(text: str) -> None:
    with pytest.raises(ValueError):
        vd.parse_date(text)


def test_parse_dates_lists_every_bad_row() -> None:
    df = filled_frame({})
    df["date"] = ["2026-09-01", "1/9/2026", "", "2027-01-01", ""]
    with pytest.raises(ValueError, match=r"row 3.*\n.*row 5.*future"):
        vd.parse_dates(df, TODAY)


# --- intervals -------------------------------------------------------------

def test_intervals_merge_same_day_and_count_missing(plates: dict[str, str]) -> None:
    # truck 1: Sep 1, Sep 1 (same visit), Oct 1 -> one gap of 30 days
    # truck 2: one date missing -> no gap
    df = filled_frame({"a1.jpg": "2026-09-01", "a2.jpg": "2026-09-01", "a3.jpg": "2026-10-01", "b1.jpg": "2026-08-01"})
    dates = vd.parse_dates(df, TODAY)
    intervals, counts = vd.compute_intervals(df, dates, plates, KEY)
    assert intervals["days_between_visits"].tolist() == [30]
    assert counts == {"same_day_photos_merged": 1, "trucks_with_intervals": 1}
    s = vd.summary(df, dates, intervals, counts)
    assert s["photos_missing_date"] == 1 and s["intervals"] == 1 and s["repeat_trucks_in_template"] == 2


def test_intervals_sorted_by_date_not_by_photo_order(plates: dict[str, str]) -> None:
    df = filled_frame({"a1.jpg": "2026-10-01", "a2.jpg": "2026-08-01", "a3.jpg": "2026-09-01"})
    intervals, _ = vd.compute_intervals(df, vd.parse_dates(df, TODAY), plates, KEY)
    assert intervals["days_between_visits"].tolist() == [31, 30]


def test_vehicle_key_is_keyed_hash_not_plate(plates: dict[str, str]) -> None:
    plate = plates["photos/a1.jpg"]
    assert vd.plate_key(plate, KEY) == vd.plate_key(plate, KEY)
    assert vd.plate_key(plate, KEY) != vd.plate_key(plate, b"other-key")
    assert plate not in vd.plate_key(plate, KEY) and len(vd.plate_key(plate, KEY)) == vd.KEY_LENGTH


def test_check_trucks_catches_edited_truck_no(plates: dict[str, str]) -> None:
    df = filled_frame({})
    df.loc[3, "truck_no"] = "1"  # b1 moved into truck 1
    with pytest.raises(ValueError, match="truck_no"):
        vd.check_trucks(df, plates)


def test_end_to_end_on_fake_filled_csv(export_file: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
                                       capsys: pytest.CaptureFixture[str]) -> None:
    template = tmp_path / "dates_to_fill.csv"
    out = tmp_path / "real_intervals.csv"
    assert vd.main(["--export", str(export_file), "template", "--output", str(template)]) == 0

    # "Ari" fills the dates (Excel-style BOM included)
    df = pd.read_csv(template, dtype=str, keep_default_na=False)
    df["date"] = ["2026-07-01", "2026-08-15", "2026-09-29", "2026.08.01", ""]
    df.to_csv(template, index=False, encoding="utf-8-sig")

    monkeypatch.setenv(vd.HASH_KEY_ENV, "fixed")
    assert vd.main(["--export", str(export_file), "intervals", "--filled", str(template), "--output", str(out)]) == 0
    result = pd.read_csv(out)
    assert list(result.columns) == vd.INTERVAL_COLUMNS
    assert result["days_between_visits"].tolist() == [45, 45]
    assert result["vehicle_key"].nunique() == 1

    printed = capsys.readouterr().out
    assert "photos_missing_date: 1" in printed and "intervals: 2" in printed
    assert "УБА" not in printed and "a1.jpg" not in printed  # counts only

    # The output is exactly what the synthetic report reads
    from src.data.synthetic_report import load_real_intervals
    assert load_real_intervals(out).tolist() == [45, 45]
