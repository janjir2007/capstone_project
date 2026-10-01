"""Read a Label Studio JSON export of plate labels (Task 3.1).

Why the full "JSON" export and not "YOLO" or "JSON-MIN" (checked on
Label Studio 1.23.2 with synthetic images):
- YOLO export lists the per-box Choices values as extra classes
  (classes.txt = fleet_no, plate), so "plate" gets class id 1, and the
  plate text is dropped.
- JSON-MIN turns multi-box fields into parallel lists and loses which text
  belongs to which box.
- Full JSON keeps a shared region "id" on the box, its choice and its text.

This module turns that export into one flat record per box. The summary
printed by ``main`` contains only counts, never plate strings, so Ari can
share it (RISK-06).

Usage:
    python -m src.cv.ls_export data/interim/labelstudio_export/export.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from typing import Any
from urllib.parse import parse_qs, unquote, urlparse

# Tag names from docs/labeling/label_config.xml.
BOX_TAG = "bbox"
TYPE_TAG = "plate_type"
TEXT_TAG = "plate_text"
DEFAULT_TYPE = "plate"


@dataclass(frozen=True)
class PlateBox:
    """One labeled box. Coordinates are YOLO-style fractions of the image (0-1)."""

    image: str  # path relative to the Local files root, e.g. "photos/IMG_0001.jpg"
    task_id: int
    region_id: str
    x_center: float
    y_center: float
    width: float
    height: float
    plate_type: str  # "plate" or "fleet_no"
    plate_text: str | None  # None if the labeler left it empty
    rotation: float


def image_path_from_url(url: str) -> str:
    """Turn Label Studio's task image URL into a relative file path.

    Local files storage stores ``/data/local-files/?d=photos/IMG_1.jpg``;
    ``d`` is relative to LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT (data/raw).
    Any other URL is returned unchanged (only its file part if it has a path).
    """
    parsed = urlparse(url)
    if parsed.path.rstrip("/").endswith("/data/local-files"):
        d_values = parse_qs(parsed.query).get("d")
        if d_values:
            return unquote(d_values[0])
    return unquote(parsed.path) or url


def _percent_box_to_yolo(value: dict[str, Any]) -> tuple[float, float, float, float]:
    """Convert Label Studio box (top-left x/y, width, height in %) to YOLO fractions."""
    width = value["width"] / 100.0
    height = value["height"] / 100.0
    x_center = value["x"] / 100.0 + width / 2.0
    y_center = value["y"] / 100.0 + height / 2.0
    return x_center, y_center, width, height


def _clean_text(value: dict[str, Any]) -> str | None:
    """Return the first non-empty TextArea entry, stripped, or None."""
    for text in value.get("text", []):
        if text and text.strip():
            return text.strip()
    return None


def _pick_annotation(task: dict[str, Any]) -> dict[str, Any] | None:
    """Pick the newest non-cancelled (not skipped) annotation of a task."""
    valid = [a for a in task.get("annotations", []) if not a.get("was_cancelled")]
    if not valid:
        return None
    return max(valid, key=lambda a: (a.get("updated_at") or "", a.get("id") or 0))


def boxes_from_task(task: dict[str, Any]) -> list[PlateBox]:
    """Group one task's annotation results by region id into PlateBox records."""
    annotation = _pick_annotation(task)
    if annotation is None:
        return []

    regions: dict[str, dict[str, Any]] = {}
    for result in annotation.get("result", []):
        region = regions.setdefault(result["id"], {})
        region[result["from_name"]] = result["value"]

    image = image_path_from_url(task["data"]["image"])
    boxes: list[PlateBox] = []
    for region_id, parts in regions.items():
        if BOX_TAG not in parts:
            continue  # a choice/text without a box cannot be used
        box_value = parts[BOX_TAG]
        choices = parts.get(TYPE_TAG, {}).get("choices") or [DEFAULT_TYPE]
        x_c, y_c, w, h = _percent_box_to_yolo(box_value)
        boxes.append(
            PlateBox(
                image=image,
                task_id=int(task["id"]),
                region_id=str(region_id),
                x_center=x_c,
                y_center=y_c,
                width=w,
                height=h,
                plate_type=choices[0],
                plate_text=_clean_text(parts.get(TEXT_TAG, {})),
                rotation=float(box_value.get("rotation", 0) or 0),
            )
        )
    return boxes


def load_export(path: Path) -> list[dict[str, Any]]:
    """Load a Label Studio full JSON export (a list of tasks)."""
    with path.open(encoding="utf-8") as f:
        data = json.load(f)
    if not isinstance(data, list) or (data and "annotations" not in data[0]):
        raise ValueError(
            f"{path} is not a full Label Studio JSON export "
            "(expected a list of tasks with 'annotations'). Use Export -> JSON, not JSON-MIN."
        )
    return data


def summarize(tasks: list[dict[str, Any]]) -> dict[str, Any]:
    """Count-only summary of an export. Contains no plate strings or file names."""
    boxes = [box for task in tasks for box in boxes_from_task(task)]
    per_image = Counter(box.image for box in boxes)
    labeled_tasks = sum(1 for task in tasks if _pick_annotation(task) is not None)
    skipped_tasks = sum(
        1
        for task in tasks
        if task.get("annotations") and all(a.get("was_cancelled") for a in task["annotations"])
    )
    return {
        "tasks_total": len(tasks),
        "tasks_labeled": labeled_tasks,
        "tasks_skipped": skipped_tasks,
        "tasks_unlabeled": len(tasks) - labeled_tasks - skipped_tasks,
        "boxes_total": len(boxes),
        "boxes_by_type": dict(Counter(box.plate_type for box in boxes)),
        "boxes_missing_text": sum(1 for box in boxes if box.plate_text is None),
        "boxes_with_unreadable_char": sum(1 for box in boxes if box.plate_text and "?" in box.plate_text),
        "boxes_rotated": sum(1 for box in boxes if box.rotation != 0),
        "boxes_out_of_bounds": sum(1 for box in boxes if not _inside_image(box)),
        "images_with_multiple_boxes": sum(1 for n in per_image.values() if n > 1),
        "image_extensions": dict(Counter(PurePosixPath(img).suffix.lower() for img in per_image)),
    }


def _inside_image(box: PlateBox) -> bool:
    """True if the box lies within the image (small float tolerance)."""
    eps = 1e-6
    return (
        box.x_center - box.width / 2 >= -eps
        and box.y_center - box.height / 2 >= -eps
        and box.x_center + box.width / 2 <= 1 + eps
        and box.y_center + box.height / 2 <= 1 + eps
    )


def main(argv: list[str] | None = None) -> int:
    """CLI: print a shareable, count-only summary of a Label Studio export."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export_json", type=Path, help="Label Studio full JSON export file")
    args = parser.parse_args(argv)
    try:
        tasks = load_export(args.export_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(summarize(tasks), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
