"""Tests for src/cv/ls_export.py (Task 3.1).

All tasks here are FAKE, shaped like a real Label Studio 1.23.2 full JSON
export (captured from a smoke test with synthetic images).
"""

import json
from pathlib import Path

import pytest

from src.cv.ls_export import (
    boxes_from_task,
    image_path_from_url,
    load_export,
    main,
    summarize,
)

FAKE_TEXTS = ["1234УБА", "HT-27", "5678УН?"]


def region(rid: str, x: float, y: float, w: float, h: float, text: str | None, ptype: str | None) -> list[dict]:
    """Build the 1-3 result entries Label Studio saves for one box."""
    geo = {"x": x, "y": y, "width": w, "height": h, "rotation": 0}
    base = {"id": rid, "to_name": "image", "original_width": 640, "original_height": 480}
    results = [{**base, "from_name": "bbox", "type": "rectanglelabels", "value": {**geo, "rectanglelabels": ["plate"]}}]
    if ptype is not None:
        results.append({**base, "from_name": "plate_type", "type": "choices", "value": {**geo, "choices": [ptype]}})
    if text is not None:
        results.append({**base, "from_name": "plate_text", "type": "textarea", "value": {**geo, "text": [text]}})
    return results


def task(tid: int, image: str, annotations: list[dict]) -> dict:
    """Build one exported task."""
    return {"id": tid, "data": {"image": f"/data/local-files/?d=photos/{image}"}, "annotations": annotations}


def annotation(aid: int, result: list[dict], cancelled: bool = False, updated: str = "2026-09-30T00:00:00Z") -> dict:
    """Build one annotation."""
    return {"id": aid, "result": result, "was_cancelled": cancelled, "updated_at": updated}


@pytest.fixture()
def tasks() -> list[dict]:
    """Four fake tasks: plate, fleet_no, two boxes, skipped."""
    return [
        task(1, "synth_00.jpg", [annotation(1, region("r1", 31.25, 62.5, 31.25, 10.4, FAKE_TEXTS[0], "plate"))]),
        task(2, "synth_01.jpg", [annotation(2, region("r2", 34.4, 62.5, 31.25, 10.4, FAKE_TEXTS[1], "fleet_no"))]),
        task(
            3,
            "synth_02.JPG",
            [annotation(3, region("r3", 37.5, 62.5, 31.25, 10.4, FAKE_TEXTS[2], "plate") + region("r4", 5, 10, 20, 8, "", None))],
        ),
        task(4, "synth_03.jpg", [annotation(4, [], cancelled=True)]),
    ]


def test_image_path_from_local_files_url() -> None:
    assert image_path_from_url("/data/local-files/?d=photos/IMG%200001.jpg") == "photos/IMG 0001.jpg"


def test_image_path_other_url_unchanged() -> None:
    assert image_path_from_url("/data/upload/1/abc.jpg") == "/data/upload/1/abc.jpg"


def test_box_converted_to_yolo_fractions(tasks: list[dict]) -> None:
    (box,) = boxes_from_task(tasks[0])
    assert box.image == "photos/synth_00.jpg"
    # Same numbers Label Studio's own YOLO export produced in the smoke test.
    assert box.x_center == pytest.approx(0.46875)
    assert box.y_center == pytest.approx(0.677)
    assert box.width == pytest.approx(0.3125)
    assert box.height == pytest.approx(0.104)
    assert box.plate_type == "plate"
    assert box.plate_text == "1234УБА"


def test_text_and_type_stay_with_their_own_box(tasks: list[dict]) -> None:
    boxes = {b.region_id: b for b in boxes_from_task(tasks[2])}
    assert boxes["r3"].plate_text == "5678УН?"
    assert boxes["r4"].plate_text is None  # empty string -> None
    assert boxes["r4"].plate_type == "plate"  # missing choice -> default


def test_skipped_task_gives_no_boxes(tasks: list[dict]) -> None:
    assert boxes_from_task(tasks[3]) == []


def test_newest_annotation_wins() -> None:
    old = annotation(1, region("a", 0, 0, 10, 10, "OLD", "plate"), updated="2026-09-01T00:00:00Z")
    new = annotation(2, region("b", 0, 0, 10, 10, "NEW", "plate"), updated="2026-09-02T00:00:00Z")
    (box,) = boxes_from_task(task(1, "x.jpg", [old, new]))
    assert box.plate_text == "NEW"


def test_summary_counts(tasks: list[dict]) -> None:
    s = summarize(tasks)
    assert s["tasks_total"] == 4
    assert s["tasks_labeled"] == 3
    assert s["tasks_skipped"] == 1
    assert s["tasks_unlabeled"] == 0
    assert s["boxes_total"] == 4
    assert s["boxes_by_type"] == {"plate": 3, "fleet_no": 1}
    assert s["boxes_missing_text"] == 1
    assert s["boxes_with_unreadable_char"] == 1
    assert s["boxes_out_of_bounds"] == 0
    assert s["images_with_multiple_boxes"] == 1
    assert s["image_extensions"] == {".jpg": 3}  # ".JPG" is lower-cased


def test_summary_never_contains_plate_strings_or_file_names(tasks: list[dict]) -> None:
    dumped = json.dumps(summarize(tasks), ensure_ascii=False)
    for secret in FAKE_TEXTS + ["synth_00", "synth_01", "synth_02"]:
        assert secret not in dumped


def test_json_min_export_is_rejected(tmp_path: Path) -> None:
    path = tmp_path / "min.json"
    path.write_text(json.dumps([{"image": "x", "plate_text": "1234УБА"}]), encoding="utf-8")
    with pytest.raises(ValueError, match="JSON-MIN"):
        load_export(path)


def test_cli_prints_summary(tmp_path: Path, tasks: list[dict], capsys: pytest.CaptureFixture[str]) -> None:
    path = tmp_path / "export.json"
    path.write_text(json.dumps(tasks, ensure_ascii=False), encoding="utf-8")
    assert main([str(path)]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["boxes_total"] == 4
    assert "1234УБА" not in json.dumps(out, ensure_ascii=False)
