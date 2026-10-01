"""Pre-label plate boxes with a pretrained detector (Task 3.1c).

Detector: open-image-models ``yolo-v9-t-640-license-plate-end2end`` (ONNX
Runtime, CPU). Code is MIT; the weights' license and training data are not
stated by the author (needs verification). Chosen by Ari after a 5-photo pilot
against Hugging Face ``ishaqinu/yolo26n-license-plate-detection`` (oim: same
hits, fewer false boxes).

Everything runs on this Mac. The only network use is the one-time weight
download from the package's GitHub release; photos are never sent anywhere
(RISK-06). Printed output contains counts, confidences and timings only - no
file names or plate text.

Usage (Ari runs these; photos are real data):
    python -m src.cv.prelabel pilot --n 5     # overlays for a quick visual check
    python -m src.cv.prelabel run             # all photos -> data/interim/prelabels/predictions.json
"""

from __future__ import annotations

import argparse
import json
import random
import sys
import time
from collections import Counter
from dataclasses import asdict, dataclass
from importlib.metadata import version
from pathlib import Path
from typing import Any, Protocol

import numpy as np
from PIL import Image, ImageDraw, ImageOps, UnidentifiedImageError

SEED = 42
PHOTO_SUFFIXES = {".jpg", ".jpeg"}
STORE_CONF = 0.10  # keep weak boxes in the JSON; the import threshold (Step 3) filters later
REPORT_THRESHOLDS = (0.25, 0.4, 0.6)
OIM_MODEL = "yolo-v9-t-640-license-plate-end2end"
BOX_COLOR = (229, 57, 53)  # red
DEFAULT_PHOTOS = Path("data/raw/photos")
DEFAULT_ROOT = Path("data/raw")  # = LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT in start_label_studio.sh
DEFAULT_OUT = Path("data/interim/prelabels/predictions.json")


@dataclass(frozen=True)
class Detection:
    """One detected box in pixels of the upright (EXIF-corrected) image."""

    x1: float
    y1: float
    x2: float
    y2: float
    confidence: float


class Detector(Protocol):
    """Anything that finds plate boxes in an RGB image array (H, W, 3, uint8)."""

    model_version: str

    def detect(self, rgb: np.ndarray) -> list[Detection]:
        """Return detected plate boxes."""
        ...


class OimDetector:
    """open-image-models YOLOv9 plate detector, ONNX Runtime on CPU."""

    def __init__(self, conf: float = STORE_CONF) -> None:
        from open_image_models import create_detector  # lazy: heavy import, not needed by tests

        # CPU provider on purpose: timings should match a CPU-only cloud host (RISK-04).
        self._model = create_detector(OIM_MODEL, conf_thresh=conf, providers=["CPUExecutionProvider"])
        self.model_version = f"oim-{version('open-image-models')}-{OIM_MODEL}"

    def detect(self, rgb: np.ndarray) -> list[Detection]:
        """Run the model. It expects BGR (OpenCV order), so flip the channels."""
        bgr = np.ascontiguousarray(rgb[:, :, ::-1])
        return [
            Detection(r.bounding_box.x1, r.bounding_box.y1, r.bounding_box.x2, r.bounding_box.y2, float(r.confidence))
            for r in self._model.predict(bgr)
        ]


def load_upright(path: Path) -> Image.Image:
    """Open a photo and apply its EXIF orientation, as the browser does in Label Studio.

    Without this, a phone photo stored sideways would get boxes in the wrong place.
    """
    with Image.open(path) as img:
        return ImageOps.exif_transpose(img).convert("RGB")


def list_photos(folder: Path) -> list[Path]:
    """All JPG photos below ``folder`` (recursive), sorted so the order is stable."""
    return sorted(p for p in folder.rglob("*") if p.is_file() and p.suffix.lower() in PHOTO_SUFFIXES)


def pick_pilot(photos: list[Path], n: int, seed: int = SEED) -> list[Path]:
    """Pick ``n`` photos reproducibly (same seed + same folder -> same photos)."""
    if n >= len(photos):
        return list(photos)
    return random.Random(seed).sample(photos, n)


def draw_overlay(img: Image.Image, dets: list[Detection]) -> Image.Image:
    """Copy of ``img`` with each box and its confidence drawn on it."""
    out = img.copy()
    draw = ImageDraw.Draw(out)
    line = max(2, round(min(out.size) / 300))
    for d in dets:
        draw.rectangle([d.x1, d.y1, d.x2, d.y2], outline=BOX_COLOR, width=line)
        draw.text((d.x1, max(0.0, d.y1 - 12 * line)), f"{d.confidence:.2f}", fill=BOX_COLOR, font_size=10 * line)
    return out


def _time_detect(detector: Detector, rgb: np.ndarray) -> tuple[list[Detection], float]:
    """Run one detection; return boxes and wall time in milliseconds."""
    start = time.perf_counter()
    dets = detector.detect(rgb)
    return dets, (time.perf_counter() - start) * 1000.0


def run_pilot(photos: list[Path], detector: Detector, out_dir: Path) -> list[dict[str, Any]]:
    """Detect on a few photos, save overlays, return a count-only summary.

    Overlays are ``pilot_<i>.jpg``; ``pilot_index.txt`` maps i -> file name. Both
    stay in ``out_dir`` (under data/, git-ignored) and are NOT printed.
    """
    out_dir.mkdir(parents=True, exist_ok=True)
    if photos:  # warm-up so model start-up is not counted as inference time
        detector.detect(np.asarray(load_upright(photos[0])))

    rows: list[dict[str, Any]] = []
    index_lines: list[str] = []
    for i, path in enumerate(photos, start=1):
        img = load_upright(path)
        dets, ms = _time_detect(detector, np.asarray(img))
        draw_overlay(img, dets).save(out_dir / f"pilot_{i}.jpg", quality=90)
        index_lines.append(f"{i}\t{path}")
        rows.append({
            "photo": i,
            "size": f"{img.width}x{img.height}",
            "boxes": len(dets),
            "conf": sorted((round(d.confidence, 2) for d in dets), reverse=True),
            "ms": round(ms),
        })
    (out_dir / "pilot_index.txt").write_text("\n".join(index_lines) + "\n", encoding="utf-8")
    return rows


def image_key(path: Path, root: Path) -> str:
    """Path relative to the Label Studio local-files root, POSIX style (e.g. "photos/IMG_1.jpg").

    This is the same string ``ls_export.image_path_from_url`` returns for a task,
    so predictions can be matched to Label Studio tasks in Step 3.
    """
    return path.resolve().relative_to(root.resolve()).as_posix()


def predict_all(photos: list[Path], detector: Detector, root: Path) -> dict[str, Any]:
    """Detect plates on every photo. Unreadable files are recorded, not fatal."""
    records: list[dict[str, Any]] = []
    failed: list[str] = []
    times_ms: list[float] = []
    for path in photos:
        key = image_key(path, root)
        try:
            img = load_upright(path)
        except (OSError, UnidentifiedImageError):
            failed.append(key)
            continue
        dets, ms = _time_detect(detector, np.asarray(img))
        times_ms.append(ms)
        records.append({
            "image": key,
            "width": img.width,
            "height": img.height,
            "boxes": [asdict(d) for d in dets],
        })
    return {
        "model_version": detector.model_version,
        "store_conf": STORE_CONF,
        "images": records,
        "failed": failed,
        "ms_per_image": times_ms,
    }


def summarize_predictions(pred: dict[str, Any], thresholds: tuple[float, ...] = REPORT_THRESHOLDS) -> dict[str, Any]:
    """Count-only summary (no file names): photos by number of boxes at each threshold, speed."""
    images = pred["images"]
    by_threshold: dict[str, dict[str, int]] = {}
    for t in thresholds:
        counts = Counter(sum(1 for b in rec["boxes"] if b["confidence"] >= t) for rec in images)
        by_threshold[f">={t}"] = {
            "photos_0_boxes": counts.get(0, 0),
            "photos_1_box": counts.get(1, 0),
            "photos_2plus_boxes": sum(n for k, n in counts.items() if k >= 2),
            "boxes_total": sum(k * n for k, n in counts.items()),
        }
    all_conf = [b["confidence"] for rec in images for b in rec["boxes"]]
    buckets = Counter(min(int(c * 10), 9) / 10 for c in all_conf)
    times = pred["ms_per_image"]
    # Skip the first call (model warm-up) for the speed numbers when possible.
    steady = times[1:] if len(times) > 1 else times
    return {
        "model_version": pred["model_version"],
        "photos_processed": len(images),
        "photos_failed": len(pred["failed"]),
        "by_threshold": by_threshold,
        "conf_histogram": {f"{k:.1f}-{k + 0.1:.1f}": buckets[k] for k in sorted(buckets)},
        "cpu_ms_per_image_median": round(float(np.median(steady))) if steady else None,
        "cpu_ms_per_image_p95": round(float(np.percentile(steady, 95))) if steady else None,
    }


def write_json(data: dict[str, Any], path: Path) -> None:
    """Write JSON (UTF-8, readable) creating parent folders."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=1, ensure_ascii=False), encoding="utf-8")


def _cmd_pilot(args: argparse.Namespace) -> int:
    photos = list_photos(args.photos)
    if not photos:
        print(f"ERROR: no .jpg photos found under {args.photos}", file=sys.stderr)
        return 1
    detector = OimDetector(args.conf)
    rows = run_pilot(pick_pilot(photos, args.n), detector, args.out)
    print(json.dumps({"photos_found": len(photos), "model_version": detector.model_version}))
    for row in rows:
        print(json.dumps(row))
    print(f"Overlays saved in {args.out}/ (open them locally; do not share).")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    photos = list_photos(args.photos)
    if not photos:
        print(f"ERROR: no .jpg photos found under {args.photos}", file=sys.stderr)
        return 1
    pred = predict_all(photos, OimDetector(), args.root)
    write_json(pred, args.out)
    print(json.dumps(summarize_predictions(pred), indent=2))
    print(f"Predictions saved to {args.out} (local only; do not share).")
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)

    pilot = sub.add_parser("pilot", help="draw boxes on a few photos for a visual check")
    pilot.add_argument("--photos", type=Path, default=DEFAULT_PHOTOS)
    pilot.add_argument("--n", type=int, default=5)
    pilot.add_argument("--conf", type=float, default=STORE_CONF)
    pilot.add_argument("--out", type=Path, default=Path("data/interim/prelabel_pilot"))
    pilot.set_defaults(func=_cmd_pilot)

    run = sub.add_parser("run", help="detect on all photos and save predictions JSON")
    run.add_argument("--photos", type=Path, default=DEFAULT_PHOTOS)
    run.add_argument("--root", type=Path, default=DEFAULT_ROOT, help="Label Studio local-files root")
    run.add_argument("--out", type=Path, default=DEFAULT_OUT)
    run.set_defaults(func=_cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
