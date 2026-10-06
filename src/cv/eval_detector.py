"""Evaluate plate detectors on the held-out TEST split (Task 3.2).

Compares, on the same test images and with the same metric code
(``src.cv.det_metrics``):
- baseline: pretrained open-image-models YOLOv9-t-640 (the pre-label model, D-025)
- each fine-tuned Ultralytics YOLO run (``best.pt``)

Speed = wall time per image on CPU (image load + preprocessing + model +
postprocessing), median and p95 after warm-up. CPU because the cloud host is
CPU-only (RISK-04); an MPS number is added for the YOLO runs when available.

Outputs:
- ``models/plate_yolo/test_metrics.json`` (local)
- charts in ``docs/figures/`` (numbers only, no photos)
- ``docs/cv_detection_results.md`` (tables + chart links, for slide 6)

Usage (Ari runs it; reads real test photos, prints numbers only):
    python -m src.cv.eval_detector --run models/plate_yolo/yolo11n --run models/plate_yolo/yolo26n
"""

from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from src.cv.det_metrics import DEFAULT_CONF, ImageEval, evaluate, pr_curve

EVAL_CONF = 0.01  # keep low-confidence boxes so the full PR curve (and mAP) can be computed
IMGSZ = 640
WARMUP_RUNS = 2
DEFAULT_DATASET = Path("data/processed/plate_yolo")
DEFAULT_SPLIT = Path("data/interim/plate_split/split.json")
DEFAULT_OUT = Path("models/plate_yolo/test_metrics.json")
DEFAULT_FIGURES = Path("docs/figures")
DEFAULT_MD = Path("docs/cv_detection_results.md")
BASELINE_NAME = "oim yolov9-t (pretrained)"

# Chart style: reference categorical palette, light mode, fixed order per model.
SURFACE = "#fcfcfb"
TEXT = "#0b0b0b"
TEXT_2 = "#52514e"
GRID = "#e6e5e1"
MODEL_COLORS = ["#2a78d6", "#eb6834", "#1baf7a"]  # baseline, 1st run, 2nd run
TRAIN_VAL_COLORS = {"train": "#2a78d6", "val": "#eb6834"}

Detections = tuple[np.ndarray, np.ndarray]  # boxes (M, 4) xyxy pixels, conf (M,)
DetectFn = Callable[[Path], Detections]


# ---------------------------------------------------------------- test data
def yolo_to_xyxy(line: str, width: int, height: int) -> list[float]:
    """``class xc yc w h`` (fractions) -> pixel ``x1, y1, x2, y2``."""
    _, xc, yc, w, h = (float(v) for v in line.split())
    return [(xc - w / 2) * width, (yc - h / 2) * height, (xc + w / 2) * width, (yc + h / 2) * height]


def load_test_set(dataset: Path) -> list[tuple[Path, np.ndarray]]:
    """(image path, ground-truth boxes in pixels) for every test image, sorted by name."""
    from PIL import Image

    items = []
    for img_path in sorted((dataset / "images" / "test").glob("*.jpg")):
        label = dataset / "labels" / "test" / f"{img_path.stem}.txt"
        with Image.open(img_path) as img:
            w, h = img.size
        lines = [ln for ln in label.read_text(encoding="utf-8").splitlines() if ln.strip()] if label.exists() else []
        items.append((img_path, np.array([yolo_to_xyxy(ln, w, h) for ln in lines]).reshape(-1, 4)))
    return items


# ---------------------------------------------------------------- detectors
def oim_detect_fn() -> DetectFn:
    """Baseline detector (ONNX Runtime, CPU), same class as the pre-labeling step."""
    from src.cv.prelabel import OimDetector, load_upright

    detector = OimDetector(conf=EVAL_CONF)

    def detect(path: Path) -> Detections:
        dets = detector.detect(np.asarray(load_upright(path)))
        return (np.array([[d.x1, d.y1, d.x2, d.y2] for d in dets]).reshape(-1, 4),
                np.array([d.confidence for d in dets]))

    return detect


def yolo_detect_fn(weights: Path, device: str) -> DetectFn:
    """Fine-tuned Ultralytics model on ``device`` (``cpu`` or ``mps``)."""
    from ultralytics import YOLO

    model = YOLO(str(weights))

    def detect(path: Path) -> Detections:
        boxes = model.predict(str(path), conf=EVAL_CONF, imgsz=IMGSZ, device=device, verbose=False)[0].boxes
        return boxes.xyxy.cpu().numpy(), boxes.conf.cpu().numpy()

    return detect


def run_detector(detect: DetectFn, paths: list[Path]) -> tuple[list[Detections], list[float]]:
    """Detect on every image; return detections and per-image wall time (ms) after warm-up."""
    for _ in range(WARMUP_RUNS):
        detect(paths[0])
    results, times = [], []
    for path in paths:
        start = time.perf_counter()
        results.append(detect(path))
        times.append((time.perf_counter() - start) * 1000.0)
    return results, times


def timing_stats(times_ms: list[float]) -> dict[str, float]:
    """Median and p95 milliseconds per image."""
    return {"ms_median": round(float(np.median(times_ms)), 1), "ms_p95": round(float(np.percentile(times_ms, 95)), 1)}


def ultralytics_val(weights: Path, data_yaml: Path, project: Path) -> dict[str, float]:
    """Cross-check with Ultralytics' own evaluator on the test split (CPU)."""
    from ultralytics import YOLO

    metrics = YOLO(str(weights)).val(data=str(data_yaml), split="test", imgsz=IMGSZ, device="cpu",
                                     plots=False, verbose=False, project=str(project.resolve()),
                                     name="val_check", exist_ok=True)
    return {"map50": float(metrics.box.map50), "map50_95": float(metrics.box.map),
            "precision": float(metrics.box.mp), "recall": float(metrics.box.mr)}


def evaluate_model(name: str, detect: DetectFn, test_set: list[tuple[Path, np.ndarray]]) -> tuple[dict[str, Any], list[ImageEval]]:
    """Run one detector on the test set and compute all metrics."""
    detections, times = run_detector(detect, [p for p, _ in test_set])
    images = [ImageEval(gt, boxes, conf) for (_, gt), (boxes, conf) in zip(test_set, detections)]
    return {"model": name, **evaluate(images, DEFAULT_CONF), **timing_stats(times)}, images


# ---------------------------------------------------------------- charts
def _style(ax: Any) -> None:
    """Recessive axes: light grid, no top/right spines, secondary ink."""
    ax.set_facecolor(SURFACE)
    ax.grid(True, color=GRID, linewidth=0.8)
    ax.set_axisbelow(True)
    for side in ("top", "right"):
        ax.spines[side].set_visible(False)
    for side in ("left", "bottom"):
        ax.spines[side].set_color(GRID)
    ax.tick_params(colors=TEXT_2, labelsize=9)
    ax.xaxis.label.set_color(TEXT_2)
    ax.yaxis.label.set_color(TEXT_2)
    ax.title.set_color(TEXT)


def _figure(nrows: int, ncols: int, size: tuple[float, float]) -> tuple[Any, np.ndarray]:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(nrows, ncols, figsize=size, squeeze=False, facecolor=SURFACE)
    for ax in axes.flat:
        _style(ax)
    return fig, axes


def _save(fig: Any, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fig.tight_layout()
    fig.savefig(path, dpi=160, facecolor=SURFACE)
    import matplotlib.pyplot as plt

    plt.close(fig)


def read_results_csv(run_dir: Path) -> Any:
    """Ultralytics per-epoch log; column names stripped (some versions pad them with spaces)."""
    import pandas as pd

    df = pd.read_csv(run_dir / "results.csv")
    df.columns = [c.strip() for c in df.columns]
    return df


def plot_loss_curves(runs: dict[str, Any], path: Path) -> None:
    """One row per run, one column per loss component; train vs val lines.

    Each run gets its own components: YOLO11 logs box/cls/dfl, YOLO26 logs box/cls/l1.
    """
    components = {name: [c.split("/", 1)[1] for c in df.columns
                         if c.startswith("train/") and f"val/{c.split('/', 1)[1]}" in df.columns]
                  for name, df in runs.items()}
    ncols = max(len(comps) for comps in components.values())
    fig, axes = _figure(len(runs), ncols, (3.6 * ncols, 2.8 * len(runs)))
    for r, (name, df) in enumerate(runs.items()):
        for c in range(len(components[name]), ncols):
            axes[r, c].set_visible(False)
        for c, comp in enumerate(components[name]):
            ax = axes[r, c]
            for part in ("train", "val"):
                col = f"{part}/{comp}"
                if col in df.columns:
                    ax.plot(df["epoch"], df[col], color=TRAIN_VAL_COLORS[part], linewidth=2, label=part)
            ax.set_title(f"{name} - {comp}", fontsize=10)
            ax.set_xlabel("epoch")
            if c == 0:
                ax.set_ylabel("loss")
            ax.legend(frameon=False, fontsize=8, labelcolor=TEXT_2)
    _save(fig, path)


def plot_val_metrics(runs: dict[str, Any], path: Path) -> None:
    """Validation precision, recall, mAP50, mAP50-95 by epoch; one line per run."""
    metrics = [("metrics/precision(B)", "precision"), ("metrics/recall(B)", "recall"),
               ("metrics/mAP50(B)", "mAP50"), ("metrics/mAP50-95(B)", "mAP50-95")]
    fig, axes = _figure(1, len(metrics), (3.4 * len(metrics), 3.0))
    for c, (col, label) in enumerate(metrics):
        ax = axes[0, c]
        for i, (name, df) in enumerate(runs.items()):
            if col in df.columns:
                ax.plot(df["epoch"], df[col], color=MODEL_COLORS[i + 1], linewidth=2, label=name)
        ax.set_title(f"val {label}", fontsize=10)
        ax.set_xlabel("epoch")
        ax.set_ylim(0, 1.02)
        ax.legend(frameon=False, fontsize=8, labelcolor=TEXT_2)
    _save(fig, path)


def plot_comparison(rows: list[dict[str, Any]], path: Path) -> None:
    """Grouped bars: test metrics per model, value labels above each bar."""
    metrics = [("map50", "mAP50"), ("map50_95", "mAP50-95"), ("precision", "precision"),
               ("recall", "recall"), ("mean_iou_matched", "mean IoU")]
    fig, axes = _figure(1, 1, (9.0, 3.8))
    ax = axes[0, 0]
    width = 0.8 / len(rows)
    x = np.arange(len(metrics))
    for i, row in enumerate(rows):
        values = [row[key] for key, _ in metrics]
        pos = x - 0.4 + width * (i + 0.5)
        ax.bar(pos, values, width=width * 0.92, color=MODEL_COLORS[i], label=row["model"])
        for px, v in zip(pos, values):
            ax.text(px, v + 0.015, f"{v:.2f}", ha="center", va="bottom", fontsize=7.5, color=TEXT_2)
    ax.set_xticks(x, [label for _, label in metrics])
    ax.set_ylim(0, 1.1)
    ax.set_title(f"Plate detection on held-out test trucks (n = {rows[0]['images']} images)", fontsize=11)
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXT_2, loc="upper center", ncol=len(rows),
              bbox_to_anchor=(0.5, -0.1))
    _save(fig, path)


def plot_pr_curves(curves: dict[str, list[ImageEval]], path: Path) -> None:
    """Test precision-recall curve at IoU 0.5, one line per model."""
    fig, axes = _figure(1, 1, (5.0, 4.0))
    ax = axes[0, 0]
    for i, (name, images) in enumerate(curves.items()):
        recall, precision, _ = pr_curve(images, 0.5)
        # real points only (no artificial start at recall 0, precision 1), drawn as steps
        ax.plot(recall, precision, color=MODEL_COLORS[i], linewidth=2, label=name, drawstyle="steps-post")
    ax.set_xlabel("recall")
    ax.set_ylabel("precision")
    ax.set_xlim(0, 1.02)
    ax.set_ylim(0, 1.02)
    ax.set_title("Test precision-recall (IoU 0.5)", fontsize=11)
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXT_2, loc="lower left")
    _save(fig, path)


# ---------------------------------------------------------------- report
def results_markdown(report: dict[str, Any], figures: dict[str, str]) -> str:
    """Slide-ready markdown: dataset, metrics table, speed, cross-check, caveats, charts."""
    split = report["split"]
    lines = [
        "# Plate detection results (Task 3.2)",
        "",
        f"Generated by `python -m src.cv.eval_detector` on {report['date']}. Numbers only, no photos.",
        "",
        "## Data",
        "",
        "Split by truck (plate text), seed 42. No truck is in more than one split.",
        "",
        "| split | images | trucks |",
        "|---|---|---|",
        *[f"| {k} | {v['images']} | {v['trucks']} |" for k, v in split.items()],
        "",
        f"## Test results (operating threshold conf >= {DEFAULT_CONF}, IoU 0.5)",
        "",
        "| model | mAP50 | mAP50-95 | precision | recall | mean IoU | missed / false pos. | CPU ms/img (median / p95) | MPS ms/img |",
        "|---|---|---|---|---|---|---|---|---|",
    ]
    for r in report["models"]:
        mps = f"{r['mps_ms_median']}" if "mps_ms_median" in r else "-"
        lines.append(
            f"| {r['model']} | {r['map50']:.3f} | {r['map50_95']:.3f} | {r['precision']:.3f} | {r['recall']:.3f} "
            f"| {r['mean_iou_matched']:.3f} | {r['missed']} / {r['false_positives']} "
            f"| {r['ms_median']} / {r['ms_p95']} | {mps} |"
        )
    lines += [
        "",
        "- **mean IoU** = average IoU of correct detections. `mean_best_iou` in the JSON also counts misses as 0.",
        "- **ms/img** = image load + preprocessing + model + postprocessing, after warm-up, on: "
        f"{report['machine']}.",
        "",
        "## Cross-check with Ultralytics `model.val(split='test')`",
        "",
        "| model | mAP50 | mAP50-95 | precision | recall |",
        "|---|---|---|---|---|",
        *[f"| {name} | {v['map50']:.3f} | {v['map50_95']:.3f} | {v['precision']:.3f} | {v['recall']:.3f} |"
          for name, v in report["ultralytics_val"].items()],
        "",
        "Small differences from the table above are expected: Ultralytics picks its own precision/recall "
        "operating point and uses its own matching details.",
        "",
        "## Caveats (say these on the slide)",
        "",
        f"- Small test set: {split['test']['images']} images of {split['test']['trucks']} trucks. "
        "One image changes recall by several points.",
        "- The baseline is favored: ground-truth boxes started as this model's pre-labels (D-025) "
        "and were corrected by hand, so its IoU / mAP50-95 are likely optimistic.",
        "- Every labeled photo has exactly one plate; multi-truck scenes are not tested.",
        "- Not yet tested on the unseen `photos_new` set (D-027).",
        "",
        "## Charts",
        "",
        *[f"![{title}]({rel})" for title, rel in figures.items()],
        "",
    ]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--run", type=Path, action="append", required=True,
                        help="training run folder (contains weights/best.pt); repeat for several")
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--figures", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD)
    parser.add_argument("--no-baseline", action="store_true", help="skip the pretrained oim baseline")
    args = parser.parse_args(argv)

    test_set = load_test_set(args.dataset)
    if not test_set:
        print(f"ERROR: no test images in {args.dataset}/images/test. Run src.cv.plate_split first.", file=sys.stderr)
        return 1
    missing = [r for r in args.run if not (r / "weights" / "best.pt").exists()]
    if missing:
        print(f"ERROR: no weights/best.pt in {', '.join(map(str, missing))}", file=sys.stderr)
        return 1

    from src.cv.plate_split import split_counts

    import torch

    rows: list[dict[str, Any]] = []
    curves: dict[str, list[ImageEval]] = {}
    if not args.no_baseline:
        row, images = evaluate_model(BASELINE_NAME, oim_detect_fn(), test_set)
        rows.append({**row, "framework": f"open-image-models {version('open-image-models')} (ONNX Runtime CPU)"})
        curves[BASELINE_NAME] = images

    histories: dict[str, Any] = {}
    cross_check: dict[str, dict[str, float]] = {}
    for run in args.run:
        name = f"{run.name} (fine-tuned)"
        weights = run / "weights" / "best.pt"
        row, images = evaluate_model(name, yolo_detect_fn(weights, "cpu"), test_set)
        row.update({"framework": f"ultralytics {version('ultralytics')} (PyTorch CPU)",
                    "weights_mb": round(weights.stat().st_size / 1e6, 1)})
        if torch.backends.mps.is_available():
            _, mps_times = run_detector(yolo_detect_fn(weights, "mps"), [p for p, _ in test_set])
            row["mps_ms_median"] = timing_stats(mps_times)["ms_median"]
        rows.append(row)
        curves[name] = images
        histories[run.name] = read_results_csv(run)
        cross_check[name] = ultralytics_val(weights, args.dataset / "data.yaml", args.out.parent)

    figures = {
        "Training and validation loss": "det_loss_curves.png",
        "Validation metrics by epoch": "det_val_metrics.png",
        "Baseline vs fine-tuned (test)": "det_baseline_vs_finetuned.png",
        "Test precision-recall": "det_pr_curve_test.png",
    }
    plot_loss_curves(histories, args.figures / figures["Training and validation loss"])
    plot_val_metrics(histories, args.figures / figures["Validation metrics by epoch"])
    plot_comparison(rows, args.figures / figures["Baseline vs fine-tuned (test)"])
    plot_pr_curves(curves, args.figures / figures["Test precision-recall"])

    report = {
        "date": time.strftime("%Y-%m-%d"),
        "machine": f"{platform.platform()}, torch {torch.__version__}",
        "split": split_counts(json.loads(args.split.read_text(encoding="utf-8"))),
        "eval_conf": EVAL_CONF,
        "models": rows,
        "ultralytics_val": cross_check,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1), encoding="utf-8")
    rel = Path("figures") if args.md.parent.resolve() == args.figures.parent.resolve() else args.figures
    args.md.write_text(results_markdown(report, {t: (rel / f).as_posix() for t, f in figures.items()}), encoding="utf-8")

    print(json.dumps(report, indent=2))
    print(f"Saved {args.out}, {args.md} and charts in {args.figures}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
