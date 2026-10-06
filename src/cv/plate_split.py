"""Truck-grouped train/val/test split + YOLO dataset build (Task 3.2).

Why group by truck: the same truck photographed twice looks almost the same.
If one photo is in train and the other in test, the test score measures
memory, not generalization (D-009). So every photo of one plate text goes to
the same split. Photos that share any plate text (e.g. two trucks in one
photo) are merged into one group too (union-find).

Outputs (all git-ignored, local only - real photos, RISK-06):
- ``data/interim/plate_split/split.json``: image -> group id + split. Group ids
  are ``g000``, ``g001``, ... (no plate strings in the file).
- ``data/processed/plate_yolo/``: ``images/{train,val,test}``,
  ``labels/{train,val,test}`` and ``data.yaml`` for Ultralytics. Images are
  re-saved upright (EXIF orientation applied, EXIF metadata dropped) because
  Label Studio box coordinates refer to the upright image.

Printed output is counts only.

Usage (Ari runs it):
    python -m src.cv.plate_split data/interim/labelstudio_export/<newest>.json
"""

from __future__ import annotations

import argparse
import json
import random
import shutil
import sys
from collections import Counter, defaultdict
from pathlib import Path, PurePosixPath
from typing import Any

from src.cv.ls_export import PlateBox, boxes_from_task, load_export

SEED = 42
FRACTIONS = {"train": 0.70, "val": 0.15, "test": 0.15}
SPLITS = ("train", "val", "test")
CLASS_NAMES = {0: "plate"}  # one class: fleet_no boxes are also "a plate-like sign" for the detector
DEFAULT_ROOT = Path("data/raw")  # Label Studio local-files root (same as prelabel.py)
DEFAULT_SPLIT = Path("data/interim/plate_split/split.json")
DEFAULT_DATASET = Path("data/processed/plate_yolo")
JPEG_QUALITY = 95


def boxes_by_image(tasks: list[dict[str, Any]]) -> dict[str, list[PlateBox]]:
    """All labeled boxes grouped by image path. Skipped tasks have no boxes and drop out."""
    out: dict[str, list[PlateBox]] = defaultdict(list)
    for task in tasks:
        for box in boxes_from_task(task):
            out[box.image].append(box)
    return dict(out)


def group_images(texts_by_image: dict[str, list[str]]) -> dict[str, str]:
    """Assign each image a truck group id; images sharing any plate text share a group.

    Images without any text get their own group (cannot be linked to a truck).
    Group ids are ``g000``... numbered by the group's first image path, so they
    are stable for the same export and contain no plate text.
    """
    parent = {img: img for img in texts_by_image}

    def find(x: str) -> str:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    first_image_of_text: dict[str, str] = {}
    for img in sorted(texts_by_image):
        for text in texts_by_image[img]:
            if text in first_image_of_text:
                parent[find(img)] = find(first_image_of_text[text])
            else:
                first_image_of_text[text] = img

    members: dict[str, list[str]] = defaultdict(list)
    for img in texts_by_image:
        members[find(img)].append(img)
    ordered = sorted(members.values(), key=min)
    return {img: f"g{i:03d}" for i, imgs in enumerate(ordered) for img in imgs}


def split_groups(
    group_sizes: dict[str, int], fractions: dict[str, float] = FRACTIONS, seed: int = SEED
) -> dict[str, str]:
    """Assign whole groups to train/val/test so image counts are close to ``fractions``.

    Groups are shuffled with a fixed seed. Test is filled first, then val, each
    up to its target image count without overshooting; everything else is train.
    """
    total = sum(group_sizes.values())
    targets = {name: round(fractions[name] * total) for name in ("test", "val")}
    filled = {"test": 0, "val": 0}
    gids = sorted(group_sizes)
    random.Random(seed).shuffle(gids)
    assignment: dict[str, str] = {}
    for gid in gids:
        size = group_sizes[gid]
        for name in ("test", "val"):
            if filled[name] + size <= targets[name]:
                assignment[gid] = name
                filled[name] += size
                break
        else:
            assignment[gid] = "train"
    return assignment


def make_split(tasks: list[dict[str, Any]], seed: int = SEED) -> dict[str, Any]:
    """Full split record: one row per labeled image with its group and split."""
    by_image = boxes_by_image(tasks)
    texts = {img: [b.plate_text for b in boxes if b.plate_text] for img, boxes in by_image.items()}
    group_of = group_images(texts)
    split_of_group = split_groups(Counter(group_of.values()), seed=seed)
    rows = [
        {"image": img, "group": group_of[img], "split": split_of_group[group_of[img]]}
        for img in sorted(by_image)
    ]
    return {"seed": seed, "fractions": FRACTIONS, "images": rows}


def split_counts(split: dict[str, Any]) -> dict[str, dict[str, int]]:
    """Images and groups per split (count-only, safe to share)."""
    out: dict[str, dict[str, int]] = {}
    for name in SPLITS:
        rows = [r for r in split["images"] if r["split"] == name]
        out[name] = {"images": len(rows), "trucks": len({r["group"] for r in rows})}
    return out


def check_no_leak(split: dict[str, Any]) -> None:
    """Raise if any truck group appears in more than one split."""
    splits_per_group: dict[str, set[str]] = defaultdict(set)
    for row in split["images"]:
        splits_per_group[row["group"]].add(row["split"])
    leaked = [g for g, s in splits_per_group.items() if len(s) > 1]
    if leaked:
        raise ValueError(f"{len(leaked)} truck groups appear in more than one split")


def yolo_label_lines(boxes: list[PlateBox]) -> list[str]:
    """One ``class x_center y_center width height`` line per box (fractions, 6 decimals)."""
    return [f"0 {b.x_center:.6f} {b.y_center:.6f} {b.width:.6f} {b.height:.6f}" for b in boxes]


def dataset_file_stem(image: str) -> str:
    """Flatten ``photos/sub/IMG_1.jpg`` to ``photos__sub__IMG_1`` so names never collide."""
    path = PurePosixPath(image)
    return "__".join([*path.parent.parts, path.stem])


def write_data_yaml(dataset: Path) -> Path:
    """Ultralytics dataset file. Absolute ``path`` so training works from any folder."""
    lines = [
        f"path: {dataset.resolve()}",
        "train: images/train",
        "val: images/val",
        "test: images/test",
        "names:",
        *[f"  {k}: {v}" for k, v in CLASS_NAMES.items()],
    ]
    yaml_path = dataset / "data.yaml"
    yaml_path.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return yaml_path


def build_dataset(tasks: list[dict[str, Any]], split: dict[str, Any], root: Path, dataset: Path) -> int:
    """Write upright images + YOLO labels for every image in ``split``. Returns images written."""
    from src.cv.prelabel import load_upright  # lazy: pulls in PIL + numpy only when building

    by_image = boxes_by_image(tasks)
    for sub in ("images", "labels"):  # start clean: a re-run must not keep photos from an old split
        shutil.rmtree(dataset / sub, ignore_errors=True)
    for name in SPLITS:
        (dataset / "images" / name).mkdir(parents=True, exist_ok=True)
        (dataset / "labels" / name).mkdir(parents=True, exist_ok=True)
    written = 0
    for row in split["images"]:
        stem = dataset_file_stem(row["image"])
        img = load_upright(root / row["image"])
        img.save(dataset / "images" / row["split"] / f"{stem}.jpg", quality=JPEG_QUALITY)
        label = "\n".join(yolo_label_lines(by_image[row["image"]])) + "\n"
        (dataset / "labels" / row["split"] / f"{stem}.txt").write_text(label, encoding="utf-8")
        written += 1
    write_data_yaml(dataset)
    return written


def main(argv: list[str] | None = None) -> int:
    """CLI: make the split, save it, build the YOLO dataset, print counts."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export_json", type=Path, help="Label Studio full JSON export")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Label Studio local-files root")
    parser.add_argument("--split-out", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--seed", type=int, default=SEED)
    args = parser.parse_args(argv)

    try:
        tasks = load_export(args.export_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    split = make_split(tasks, seed=args.seed)
    split["export"] = args.export_json.name
    check_no_leak(split)
    args.split_out.parent.mkdir(parents=True, exist_ok=True)
    args.split_out.write_text(json.dumps(split, indent=1, ensure_ascii=False), encoding="utf-8")

    written = build_dataset(tasks, split, args.root, args.dataset)
    print(json.dumps({"images_written": written, "per_split": split_counts(split)}, indent=2))
    print(f"Split saved to {args.split_out}; dataset in {args.dataset} (local only; do not share).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
