"""Plate crops + text labels for recognition (Task 3.3).

For every labeled image in ``split.json`` (same truck-grouped split as the
detector, D-009), run the production detector yolo26n (D-028) and save the crop
of its most confident box. Recognition is then evaluated on what the detector
really gives it, not on hand-drawn boxes. If the detector finds nothing, the
hand-drawn box is used and ``source`` says so (counted in the summary).

Outputs (git-ignored, local only - real plates, RISK-06):
- ``data/interim/plate_ocr/crops/<stem>.png``
- ``data/interim/plate_ocr/index.json``: one row per crop with split, truck
  group, normalized label, detector confidence, crop source.

Printed output is counts only.

Usage:
    python -m src.cv.ocr_data
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

import numpy as np

from src.common.plates import normalize_plate
from src.cv.ls_export import boxes_from_task, load_export
from src.cv.plate_split import DEFAULT_DATASET, DEFAULT_SPLIT, dataset_file_stem

DEFAULT_EXPORT_DIR = Path("data/interim/labelstudio_export")
DEFAULT_WEIGHTS = Path("models/plate_yolo/yolo26n/weights/best.pt")
DEFAULT_OUT = Path("data/interim/plate_ocr")
DET_CONF = 0.25  # detector operating threshold used in task 3.2
PAD = 0.05  # extra margin around the box, as a fraction of box width/height


def labels_by_image(tasks: list[dict[str, Any]]) -> dict[str, str]:
    """Image path -> normalized plate text. Images whose only box has no text are skipped."""
    out: dict[str, str] = {}
    for task in tasks:
        for box in boxes_from_task(task):
            if box.plate_type == "plate" and box.plate_text:
                out.setdefault(box.image, normalize_plate(box.plate_text))
    return out


def padded_crop(image: np.ndarray, xyxy: list[float], pad: float = PAD) -> np.ndarray:
    """Crop ``x1, y1, x2, y2`` (pixels) plus ``pad`` margin, clipped to the image."""
    x1, y1, x2, y2 = xyxy
    dx, dy = (x2 - x1) * pad, (y2 - y1) * pad
    h, w = image.shape[:2]
    left, top = max(0, int(round(x1 - dx))), max(0, int(round(y1 - dy)))
    right, bottom = min(w, int(round(x2 + dx))), min(h, int(round(y2 + dy)))
    if right <= left or bottom <= top:
        raise ValueError(f"empty crop for box {xyxy}")
    return image[top:bottom, left:right]


def gt_box(label_file: Path, width: int, height: int) -> list[float]:
    """First YOLO label line of an image -> pixel ``x1, y1, x2, y2``."""
    from src.cv.eval_detector import yolo_to_xyxy

    first = next(ln for ln in label_file.read_text(encoding="utf-8").splitlines() if ln.strip())
    return yolo_to_xyxy(first, width, height)


def best_box(model: Any, image_path: Path) -> tuple[list[float], float] | None:
    """Most confident detector box (pixels) and its confidence, or None."""
    boxes = model.predict(str(image_path), conf=DET_CONF, imgsz=640, device="cpu", verbose=False)[0].boxes
    if len(boxes) == 0:
        return None
    i = int(boxes.conf.argmax())
    return boxes.xyxy[i].tolist(), float(boxes.conf[i])


def build(split: dict[str, Any], labels: dict[str, str], dataset: Path, weights: Path, out: Path) -> list[dict[str, Any]]:
    """Write one crop per labeled image and return the index rows."""
    from PIL import Image
    from ultralytics import YOLO

    model = YOLO(str(weights))
    crops = out / "crops"
    crops.mkdir(parents=True, exist_ok=True)
    rows = []
    for row in split["images"]:
        if row["image"] not in labels:
            continue
        stem = dataset_file_stem(row["image"])
        img_path = dataset / "images" / row["split"] / f"{stem}.jpg"
        image = np.asarray(Image.open(img_path).convert("RGB"))
        found = best_box(model, img_path)
        if found is None:
            h, w = image.shape[:2]
            xyxy, det_conf, source = gt_box(dataset / "labels" / row["split"] / f"{stem}.txt", w, h), 0.0, "gt"
        else:
            (xyxy, det_conf), source = found, "yolo26n"
        Image.fromarray(padded_crop(image, xyxy)).save(crops / f"{stem}.png")
        rows.append({"stem": stem, "split": row["split"], "group": row["group"], "label": labels[row["image"]],
                     "det_conf": round(det_conf, 4), "source": source})
    return rows


def summary(rows: list[dict[str, Any]]) -> dict[str, Any]:
    """Count-only summary."""
    return {
        "crops": len(rows),
        "per_split": dict(Counter(r["split"] for r in rows)),
        "trucks_per_split": {s: len({r["group"] for r in rows if r["split"] == s}) for s in ("train", "val", "test")},
        "crop_source": dict(Counter(r["source"] for r in rows)),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: build crops + index, print counts."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--export", type=Path, help="Label Studio export (default: the one named in split.json)")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = parser.parse_args(argv)

    split = json.loads(args.split.read_text(encoding="utf-8"))
    export = args.export or DEFAULT_EXPORT_DIR / split["export"]
    try:
        tasks = load_export(export)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    rows = build(split, labels_by_image(tasks), args.dataset, args.weights, args.out)
    (args.out / "index.json").write_text(json.dumps(rows, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary(rows), indent=2))
    print(f"Crops + index in {args.out} (local only; do not share).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
