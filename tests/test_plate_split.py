"""Tests for src/cv/plate_split.py and the pure helpers of the 3.2 train/eval scripts.

All plate texts and images are FAKE; real photos are never used in tests.
"""

import json
from pathlib import Path

import pytest
from PIL import Image

from src.cv.eval_detector import yolo_to_xyxy
from src.cv.ls_export import PlateBox
from src.cv.plate_split import (
    build_dataset,
    check_no_leak,
    dataset_file_stem,
    group_images,
    make_split,
    split_counts,
    split_groups,
    yolo_label_lines,
)
from src.cv.train_detector import run_name, train_args


def fake_task(tid: int, image: str, texts: list[str], skipped: bool = False) -> dict:
    """Minimal Label Studio task with one box per text (same shape as the real export)."""
    result = []
    for i, text in enumerate(texts):
        rid = f"r{tid}_{i}"
        geo = {"x": 10.0 + i * 30, "y": 50.0, "width": 20.0, "height": 10.0, "rotation": 0}
        result.append({"id": rid, "from_name": "bbox", "to_name": "image", "type": "rectanglelabels",
                       "value": {**geo, "rectanglelabels": ["plate"]}})
        result.append({"id": rid, "from_name": "plate_text", "to_name": "image", "type": "textarea",
                       "value": {**geo, "text": [text]}})
    return {"id": tid, "data": {"image": f"/data/local-files/?d=photos/{image}"},
            "annotations": [{"id": tid, "result": [] if skipped else result, "was_cancelled": skipped}]}


def fake_tasks(n_trucks: int = 40) -> list[dict]:
    """n_trucks fake trucks; every 3rd truck has 3 photos, others 1; plus one skipped task."""
    tasks, tid = [], 0
    for t in range(n_trucks):
        for _ in range(3 if t % 3 == 0 else 1):
            tasks.append(fake_task(tid, f"img_{tid:03d}.jpg", [f"{1000 + t}АБВ"]))
            tid += 1
    tasks.append(fake_task(tid, "skipped.jpg", [], skipped=True))
    return tasks


def test_group_images_merges_images_sharing_a_text() -> None:
    groups = group_images({"a.jpg": ["1111АА"], "b.jpg": ["1111АА", "2222ББ"], "c.jpg": ["2222ББ"], "d.jpg": ["3333ВВ"]})
    assert groups["a.jpg"] == groups["b.jpg"] == groups["c.jpg"]
    assert groups["d.jpg"] != groups["a.jpg"]
    assert set(groups.values()) == {"g000", "g001"}


def test_group_images_without_text_are_their_own_group() -> None:
    groups = group_images({"a.jpg": [], "b.jpg": []})
    assert groups["a.jpg"] != groups["b.jpg"]


def test_split_groups_hits_targets_without_overshoot() -> None:
    sizes = {f"g{i:03d}": (3 if i % 3 == 0 else 1) for i in range(40)}  # 14 x 3 + 26 x 1 = 68 images
    total = sum(sizes.values())
    target = round(0.15 * total)
    assignment = split_groups(sizes, seed=42)
    per_split = {s: sum(sizes[g] for g, a in assignment.items() if a == s) for s in ("train", "val", "test")}
    assert target - 2 <= per_split["test"] <= target and target - 2 <= per_split["val"] <= target
    assert sum(per_split.values()) == total


def test_split_is_reproducible_and_leak_free() -> None:
    tasks = fake_tasks()
    first, second = make_split(tasks, seed=42), make_split(tasks, seed=42)
    assert first == second
    check_no_leak(first)
    assert make_split(tasks, seed=7) != first  # seed actually matters


def test_split_excludes_skipped_tasks_and_has_no_plate_text() -> None:
    split = make_split(fake_tasks())
    assert all(row["image"] != "photos/skipped.jpg" for row in split["images"])
    assert "АБВ" not in json.dumps(split, ensure_ascii=False)
    counts = split_counts(split)
    assert sum(c["trucks"] for c in counts.values()) == 40


def test_check_no_leak_raises_on_shared_group() -> None:
    bad = {"images": [{"image": "a", "group": "g000", "split": "train"},
                      {"image": "b", "group": "g000", "split": "test"}]}
    with pytest.raises(ValueError):
        check_no_leak(bad)


def test_yolo_label_round_trip() -> None:
    box = PlateBox("photos/a.jpg", 1, "r", 0.5, 0.25, 0.2, 0.1, "plate", "1234АБВ", 0.0)
    (line,) = yolo_label_lines([box])
    assert line == "0 0.500000 0.250000 0.200000 0.100000"
    assert yolo_to_xyxy(line, 200, 100) == pytest.approx([80.0, 20.0, 120.0, 30.0])


def test_dataset_file_stem_flattens_folders() -> None:
    assert dataset_file_stem("photos/sub/IMG_1.jpg") == "photos__sub__IMG_1"


def test_build_dataset_writes_images_labels_and_yaml(tmp_path: Path) -> None:
    tasks = fake_tasks(10)
    photos = tmp_path / "raw" / "photos"
    photos.mkdir(parents=True)
    for task in tasks:
        name = task["data"]["image"].split("photos/")[1]
        Image.new("RGB", (64, 48), (120, 120, 120)).save(photos / name)  # synthetic grey image
    split = make_split(tasks)
    out = tmp_path / "yolo"
    (out / "images" / "train").mkdir(parents=True)
    (out / "images" / "train" / "stale.jpg").write_bytes(b"old")  # must be removed by a rebuild

    written = build_dataset(tasks, split, tmp_path / "raw", out)

    assert written == len(split["images"])
    assert not (out / "images" / "train" / "stale.jpg").exists()
    for row in split["images"]:
        stem = dataset_file_stem(row["image"])
        assert (out / "images" / row["split"] / f"{stem}.jpg").exists()
        assert (out / "labels" / row["split"] / f"{stem}.txt").read_text().startswith("0 ")
    assert "test: images/test" in (out / "data.yaml").read_text()


def test_train_args_use_seed_absolute_project_and_run_name(tmp_path: Path) -> None:
    args = train_args(tmp_path / "data.yaml", tmp_path / "proj", run_name("yolo11n.pt"), "cpu", 5, 2, 640, 8)
    assert args["name"] == "yolo11n" and args["seed"] == 42 and args["deterministic"] is True
    assert Path(args["project"]).is_absolute()
