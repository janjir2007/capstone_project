"""Tests for src/cv/ocr_extend.py (Task 3.6). All plates and files are FAKE."""

from pathlib import Path

import pytest

from src.cv.ls_export import PlateBox
from src.cv.ocr_extend import (
    MIN_EXTRA_EXACT,
    check_no_truck_in_two_splits,
    dedupe,
    eval_sets,
    extend_split,
    iou,
    keep_new,
    match_label,
    sha256_file,
    write_section,
)

OLD_ROWS = [
    {"image": "photos/a.jpg", "group": "g000", "split": "train"},
    {"image": "photos/b.jpg", "group": "g001", "split": "val"},
    {"image": "photos/c.jpg", "group": "g002", "split": "test"},
]
OLD_TEXTS = {"photos/a.jpg": ["1111АБВ"], "photos/b.jpg": ["2222АБВ"], "photos/c.jpg": ["3333АБВ"]}


def box(text: str | None, x: float = 0.5, kind: str = "plate") -> PlateBox:
    return PlateBox("img", 1, "r", x, 0.5, 0.2, 0.1, kind, text, 0.0)


def test_sha256_and_dedupe(tmp_path: Path) -> None:
    (tmp_path / "x").write_bytes(b"same")
    (tmp_path / "y").write_bytes(b"same")
    assert sha256_file(tmp_path / "x") == sha256_file(tmp_path / "y")
    kept, counts = dedupe({"n/1": "h_old", "n/2": "h1", "n/3": "h1", "n/4": "h2"}, {"h_old"})
    assert kept == ["n/2", "n/4"]
    assert counts == {"duplicate_of_old": 1, "duplicate_within_new": 1}


def test_known_trucks_keep_their_split_and_group() -> None:
    new = {"photos_new/1.jpg": ["3333АБВ"], "photos_new/2.jpg": ["1111АБВ"], "photos_new/3.jpg": ["2222АБВ"]}
    rows, stats = extend_split(OLD_ROWS, OLD_TEXTS, new)
    by = {r["image"]: r for r in rows}
    assert (by["photos_new/1.jpg"]["split"], by["photos_new/1.jpg"]["group"]) == ("test", "g002")
    assert by["photos_new/2.jpg"]["split"] == "train"
    assert by["photos_new/3.jpg"]["split"] == "val"
    assert stats["new_trucks"] == 0


def test_new_trucks_never_go_to_test_and_get_fresh_ids() -> None:
    new = {f"photos_new/{i}.jpg": [f"{i:04d}ГДЕ"] for i in range(40)}
    new["photos_new/dup.jpg"] = ["0001ГДЕ"]  # second photo of a new truck -> same group
    rows, stats = extend_split(OLD_ROWS, OLD_TEXTS, new)
    assert {r["split"] for r in rows} <= {"train", "val"}
    assert "val" in {r["split"] for r in rows}
    assert min(int(r["group"][1:]) for r in rows) >= 3
    by = {r["image"]: r for r in rows}
    assert by["photos_new/dup.jpg"]["group"] == by["photos_new/1.jpg"]["group"]
    assert stats["new_trucks"] == 40


def test_photo_linking_two_old_splits_is_dropped() -> None:
    rows, stats = extend_split(OLD_ROWS, OLD_TEXTS, {"photos_new/x.jpg": ["1111АБВ", "3333АБВ"]})
    assert rows == []
    assert stats["dropped_links_two_old_splits"] == 1


def test_extend_split_is_deterministic() -> None:
    new = {f"photos_new/{i}.jpg": [f"{i:04d}ГДЕ"] for i in range(20)}
    assert extend_split(OLD_ROWS, OLD_TEXTS, new) == extend_split(OLD_ROWS, OLD_TEXTS, new)


def test_leak_check() -> None:
    rows = [*OLD_ROWS, {"image": "photos_new/1.jpg", "group": "g009", "split": "train"}]
    with pytest.raises(ValueError, match="leak"):
        check_no_truck_in_two_splits(rows, {**OLD_TEXTS, "photos_new/1.jpg": ["3333АБВ"]})
    check_no_truck_in_two_splits(rows, {**OLD_TEXTS, "photos_new/1.jpg": ["9999АБВ"]})


def test_iou_and_match_label() -> None:
    assert iou((0, 0, 10, 10), (0, 0, 10, 10)) == 1.0
    assert iou((0, 0, 10, 10), (20, 20, 30, 30)) == 0.0
    left, right = box("1111АБВ", x=0.2), box("2222АБВ", x=0.7)
    # image 100x100: right box = x 60..80, y 45..55
    assert match_label((60, 45, 80, 55), [left, right], 100, 100) == (right, "yolo26n")
    assert match_label((0, 90, 5, 95), [left, right], 100, 100) == (left, "gt")
    assert match_label(None, [left], 100, 100) == (left, "gt")
    assert match_label((60, 45, 80, 55), [box("1", kind="fleet_no"), box(None)], 100, 100) is None


def metrics(exact: int, auto_correct: int, wrong: int, n: int = 27) -> dict:
    return {"plates": n, "exact_match": exact / n, "auto_correct": auto_correct, "wrong_auto_fill": wrong,
            "manual": n - auto_correct - wrong}


def test_keep_rule() -> None:
    old = {"old_test": metrics(19, 9, 0)}
    assert keep_new(old, {"old_test": metrics(19 + MIN_EXTRA_EXACT, 9, 0)})[0]
    assert not keep_new(old, {"old_test": metrics(19 + MIN_EXTRA_EXACT - 1, 12, 0)})[0]  # too small a gain
    assert not keep_new(old, {"old_test": metrics(25, 15, 1)})[0]  # any wrong auto-fill
    assert not keep_new(old, {"old_test": metrics(25, 8, 0)})[0]  # fewer correct auto-fills
    two = {"old_test": metrics(19, 9, 0), "new_test": metrics(1, 1, 0, 5)}
    assert keep_new(two, {"old_test": metrics(20, 9, 0), "new_test": metrics(3, 1, 0, 5)})[0]  # summed over sets


def test_eval_sets_split_by_origin() -> None:
    rows = [{"split": "test", "origin": "old"}, {"split": "test", "origin": "new"}, {"split": "train", "origin": "new"}]
    sets = eval_sets(rows)
    assert len(sets["old_test"]) == 1 and len(sets["new_test"]) == 1


def test_write_section_replaces_only_its_own_part(tmp_path: Path) -> None:
    md = tmp_path / "r.md"
    md.write_text("# 3.3 results\n\nkeep me\n", encoding="utf-8")
    write_section(md, "## Task 3.6 — v1\n")
    write_section(md, "## Task 3.6 — v2\n")
    text = md.read_text(encoding="utf-8")
    assert "keep me" in text and "v2" in text and "v1" not in text
