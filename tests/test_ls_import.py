"""Tests for src/cv/ls_import.py. FAKE tasks and detections only; no Label Studio server needed."""

from __future__ import annotations

import pytest

from src.cv.ls_export import boxes_from_task
from src.cv.ls_import import LabelStudio, build_result, is_untouched, plan_import, to_percent_box

MODEL = "oim-test"


def _rec(image: str, *confs: float) -> dict:
    """Fake detection record for a 1000x500 photo; each box is 200x50 px at (100, 300)."""
    return {
        "image": image,
        "width": 1000,
        "height": 500,
        "boxes": [{"x1": 100.0, "y1": 300.0, "x2": 300.0, "y2": 350.0, "confidence": c} for c in confs],
    }


def _task(tid: int, image: str, **extra) -> dict:
    return {"id": tid, "project": 7, "data": {"image": f"/data/local-files/?d={image}"}, **extra}


def test_to_percent_box_converts_and_clamps() -> None:
    assert to_percent_box({"x1": 100, "y1": 300, "x2": 300, "y2": 350}, 1000, 500) == {
        "x": 10.0, "y": 60.0, "width": 20.0, "height": 10.0, "rotation": 0,
    }
    clamped = to_percent_box({"x1": -5, "y1": 480, "x2": 50, "y2": 520}, 1000, 500)
    assert clamped["x"] == 0.0
    assert clamped["y"] + clamped["height"] == pytest.approx(100.0)


def test_build_result_filters_by_conf_and_pairs_box_with_choice() -> None:
    result = build_result(_rec("photos/a.jpg", 0.9, 0.3), conf=0.6)
    assert [r["from_name"] for r in result] == ["bbox", "plate_type"]
    assert result[0]["id"] == result[1]["id"]
    assert result[0]["value"]["rectanglelabels"] == ["plate"]
    assert result[1]["value"]["choices"] == ["plate"]
    assert all(r["to_name"] == "image" for r in result)
    assert not any(r["from_name"] == "plate_text" for r in result)  # Ari types the text


def test_prediction_round_trips_through_ls_export() -> None:
    """A prediction accepted as-is by Ari must export to the right YOLO box (ls_export reads it)."""
    result = build_result(_rec("photos/a.jpg", 0.9), conf=0.6)
    task = {**_task(1, "photos/a.jpg"), "annotations": [{"id": 1, "result": result, "was_cancelled": False}]}
    (box,) = boxes_from_task(task)
    assert box.image == "photos/a.jpg"
    assert box.plate_type == "plate"
    assert (box.x_center, box.y_center, box.width, box.height) == pytest.approx((0.2, 0.65, 0.2, 0.1))


@pytest.mark.parametrize(
    "extra",
    [
        {"annotations": [{"id": 1, "result": []}]},  # submitted without a box
        {"total_annotations": 1},
        {"cancelled_annotations": 1},  # skipped
        {"drafts": [{"id": 3}]},
    ],
)
def test_is_untouched_false_for_any_work(extra: dict) -> None:
    assert not is_untouched(_task(1, "photos/a.jpg", **extra))


def test_is_untouched_true_for_fresh_task() -> None:
    assert is_untouched(_task(1, "photos/a.jpg", annotations=[], drafts=[], total_annotations=0))


def test_plan_import_skips_and_counts() -> None:
    tasks = [
        _task(1, "photos/a.jpg"),  # -> create (1 box)
        _task(2, "photos/b.jpg", total_annotations=1),  # annotated -> skip
        _task(3, "photos/c.jpg"),  # already predicted -> skip
        _task(4, "photos/d.jpg"),  # only weak box -> skip
        _task(5, "photos/e.jpg"),  # not in predictions.json -> skip
    ]
    pred = {
        "model_version": MODEL,
        "images": [
            _rec("photos/a.jpg", 0.95),
            _rec("photos/b.jpg", 0.9),
            _rec("photos/c.jpg", 0.9),
            _rec("photos/d.jpg", 0.2),
            _rec("photos/zzz.jpg", 0.9),  # photo with no task
        ],
    }
    payloads, report = plan_import(tasks, pred, already_predicted={3}, conf=0.6)

    assert [p["task"] for p in payloads] == [1]
    assert payloads[0]["model_version"] == MODEL
    assert payloads[0]["project"] == 7
    assert payloads[0]["score"] == 0.95
    assert report == {
        "tasks_total": 5,
        "to_create": 1,
        "boxes_to_create": 1,
        "skip_annotated": 1,
        "skip_already_predicted": 1,
        "skip_no_box_above_threshold": 1,
        "skip_no_detection_record": 1,
        "detection_records_without_task": 1,
    }


@pytest.mark.parametrize("url", ["https://app.heartex.com", "http://192.168.1.5:8080"])
def test_client_refuses_non_local_url(url: str) -> None:
    with pytest.raises(ValueError, match="non-local"):
        LabelStudio(url, "token")


def test_client_accepts_localhost() -> None:
    assert LabelStudio("http://localhost:8080/", "token").base_url == "http://localhost:8080"
