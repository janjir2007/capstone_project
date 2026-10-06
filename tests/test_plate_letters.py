"""Tests for src/cv/plate_letters.py (task 3.4). All tasks and plates are FAKE."""

import json
from pathlib import Path

import pytest

from src.cv.plate_letters import letter_report, main, plate_texts


def fake_task(tid: int, boxes: list[tuple[str, str | None]]) -> dict:
    """One exported task with (plate_type, plate_text) boxes, shaped like a Label Studio full JSON export."""
    result = []
    for i, (ptype, text) in enumerate(boxes):
        geo = {"x": 10, "y": 10, "width": 20, "height": 8, "rotation": 0}
        base = {"id": f"r{tid}_{i}", "to_name": "image"}
        result.append({**base, "from_name": "bbox", "value": {**geo, "rectanglelabels": ["plate"]}})
        result.append({**base, "from_name": "plate_type", "value": {**geo, "choices": [ptype]}})
        if text is not None:
            result.append({**base, "from_name": "plate_text", "value": {**geo, "text": [text]}})
    annotation = {"id": tid, "result": result, "was_cancelled": False, "updated_at": "2026-10-01T00:00:00Z"}
    return {"id": tid, "data": {"image": f"/data/local-files/?d=photos/synth_{tid}.jpg"}, "annotations": [annotation]}


@pytest.fixture()
def tasks() -> list[dict]:
    return [
        fake_task(1, [("plate", "1234УБА")]),
        fake_task(2, [("plate", "1234УБА"), ("fleet_no", "HT-27")]),  # repeat truck + fleet number
        fake_task(3, [("plate", "5678 ӨМН")]),
        fake_task(4, [("plate", "9012 ABC")]),  # Latin typed by mistake -> АВС
        fake_task(5, [("plate", None)]),         # box without text
    ]


def test_plate_texts_skips_fleet_numbers_and_empty(tasks: list[dict]) -> None:
    assert plate_texts(tasks) == ["1234УБА", "1234УБА", "5678 ӨМН", "9012 ABC"]


def test_letter_report(tasks: list[dict]) -> None:
    report = letter_report(plate_texts(tasks))
    assert report["plate_texts"] == 4
    assert report["unique_plate_texts"] == 3
    assert report["changed_by_normalization"] == 2  # space removed; Latin mapped
    assert report["wrong_length_or_digits"] == 0
    assert report["letters_outside_mongolian_alphabet"] == []
    assert report["pass_format_with_observed_letters"] == 4
    assert report["letter_counts"] == {"А": 3, "Б": 2, "У": 2, "В": 1, "М": 1, "Н": 1, "С": 1, "Ө": 1}
    assert report["plate_letters_line"] == 'PLATE_LETTERS: frozenset[str] = frozenset("АБВМНСУӨ")'


def test_letter_report_flags_bad_labels() -> None:
    report = letter_report(["123УБА", "1234УБ?"])
    assert report["wrong_length_or_digits"] == 1
    assert report["letters_outside_mongolian_alphabet"] == ["?"]
    assert report["pass_format_with_observed_letters"] == 1  # "?" counts as observed here; the line above flags it


def test_main_prints_no_plate_strings(tmp_path: Path, tasks: list[dict], capsys: pytest.CaptureFixture[str]) -> None:
    export = tmp_path / "export.json"
    export.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    assert main([str(export)]) == 0
    out = capsys.readouterr().out
    assert json.loads(out)["plate_texts"] == 4
    for plate in ("1234УБА", "5678ӨМН", "9012АВС", "1234"):
        assert plate not in out


def test_main_bad_file(tmp_path: Path) -> None:
    assert main([str(tmp_path / "missing.json")]) == 1
