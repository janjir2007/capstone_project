"""Tests for src/cv/prelabel.py on synthetic images with a fake detector (no weights, no network)."""

from __future__ import annotations

from pathlib import Path

import numpy as np
from PIL import Image

from src.cv.ls_export import image_path_from_url
from src.cv.prelabel import (
    Detection,
    image_key,
    list_photos,
    load_upright,
    pick_pilot,
    predict_all,
    run_pilot,
    summarize_predictions,
)

EXIF_ORIENTATION_TAG = 0x0112
ROTATE_90_CW = 6  # EXIF value: "rotate 90 degrees clockwise to display"


class FakeDetector:
    """Returns one fixed box so the pipeline can be tested without a model."""

    model_version = "fake-v0"

    def __init__(self) -> None:
        self.seen_shapes: list[tuple[int, ...]] = []

    def detect(self, rgb: np.ndarray) -> list[Detection]:
        self.seen_shapes.append(rgb.shape)
        return [Detection(10, 20, 60, 40, 0.9)]


def _save_jpg(path: Path, size: tuple[int, int] = (200, 100), orientation: int | None = None) -> Path:
    img = Image.new("RGB", size, (128, 128, 128))
    exif = Image.Exif()
    if orientation is not None:
        exif[EXIF_ORIENTATION_TAG] = orientation
    img.save(path, exif=exif)
    return path


def test_load_upright_applies_exif_rotation(tmp_path: Path) -> None:
    path = _save_jpg(tmp_path / "side.jpg", size=(200, 100), orientation=ROTATE_90_CW)
    assert load_upright(path).size == (100, 200)  # width and height swapped, like the browser shows it


def test_load_upright_without_exif_keeps_size(tmp_path: Path) -> None:
    path = _save_jpg(tmp_path / "plain.jpg", size=(200, 100))
    img = load_upright(path)
    assert img.size == (200, 100)
    assert img.mode == "RGB"


def test_list_photos_recursive_jpg_only_sorted(tmp_path: Path) -> None:
    (tmp_path / "sub").mkdir()
    _save_jpg(tmp_path / "b.JPG")
    _save_jpg(tmp_path / "sub" / "a.jpeg")
    (tmp_path / ".DS_Store").write_bytes(b"x")
    (tmp_path / "notes.txt").write_text("x")
    found = list_photos(tmp_path)
    assert [p.name for p in found] == ["b.JPG", "a.jpeg"]  # sorted by full path


def test_pick_pilot_is_reproducible_and_bounded() -> None:
    photos = [Path(f"p{i}.jpg") for i in range(50)]
    first = pick_pilot(photos, 5)
    assert first == pick_pilot(photos, 5)
    assert len(set(first)) == 5
    assert pick_pilot(photos[:3], 5) == photos[:3]


def test_run_pilot_writes_overlays_and_count_only_summary(tmp_path: Path) -> None:
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    photos = [_save_jpg(photo_dir / f"truck_{i}.jpg") for i in range(2)]
    detector = FakeDetector()

    rows = run_pilot(photos, detector, tmp_path / "out")

    assert (tmp_path / "out" / "pilot_1.jpg").is_file()
    assert (tmp_path / "out" / "pilot_2.jpg").is_file()
    assert "truck_0.jpg" in (tmp_path / "out" / "pilot_index.txt").read_text()
    assert rows[0]["boxes"] == 1
    assert rows[0]["conf"] == [0.9]
    assert "truck" not in str(rows)  # summary must not leak file names (RISK-06)
    assert detector.seen_shapes[0] == (100, 200, 3)  # RGB array, H x W x 3


def test_image_key_matches_label_studio_task_path(tmp_path: Path) -> None:
    photo = _save_jpg((tmp_path / "photos").mkdir() or tmp_path / "photos" / "IMG 1.jpg")
    key = image_key(photo, tmp_path)
    assert key == "photos/IMG 1.jpg"
    # Label Studio stores the same file as a URL-encoded "d" parameter.
    assert image_path_from_url("/data/local-files/?d=photos/IMG%201.jpg") == key


def test_predict_all_records_boxes_and_skips_broken_files(tmp_path: Path) -> None:
    photo_dir = tmp_path / "photos"
    photo_dir.mkdir()
    good = _save_jpg(photo_dir / "a.jpg")
    broken = photo_dir / "b.jpg"
    broken.write_bytes(b"not a jpeg")

    pred = predict_all([good, broken], FakeDetector(), tmp_path)

    assert pred["model_version"] == "fake-v0"
    assert pred["failed"] == ["photos/b.jpg"]
    assert len(pred["images"]) == 1
    rec = pred["images"][0]
    assert (rec["image"], rec["width"], rec["height"]) == ("photos/a.jpg", 200, 100)
    assert rec["boxes"] == [{"x1": 10, "y1": 20, "x2": 60, "y2": 40, "confidence": 0.9}]


def _box(conf: float) -> dict:
    return {"x1": 0, "y1": 0, "x2": 1, "y2": 1, "confidence": conf}


def test_summarize_predictions_counts_per_threshold() -> None:
    pred = {
        "model_version": "fake-v0",
        "images": [
            {"image": "photos/secret_a.jpg", "boxes": []},
            {"image": "photos/secret_b.jpg", "boxes": [_box(0.9)]},
            {"image": "photos/secret_c.jpg", "boxes": [_box(0.85), _box(0.3)]},
        ],
        "failed": ["photos/secret_d.jpg"],
        "ms_per_image": [500.0, 40.0, 60.0],
    }
    s = summarize_predictions(pred, thresholds=(0.25, 0.6))

    assert s["photos_processed"] == 3
    assert s["photos_failed"] == 1
    assert s["by_threshold"][">=0.25"] == {
        "photos_0_boxes": 1, "photos_1_box": 1, "photos_2plus_boxes": 1, "boxes_total": 3,
    }
    assert s["by_threshold"][">=0.6"] == {
        "photos_0_boxes": 1, "photos_1_box": 2, "photos_2plus_boxes": 0, "boxes_total": 2,
    }
    assert s["conf_histogram"] == {"0.3-0.4": 1, "0.8-0.9": 1, "0.9-1.0": 1}
    assert s["cpu_ms_per_image_median"] == 50  # warm-up call (500 ms) excluded
    assert "secret" not in str(s)  # no file names in the shareable summary
