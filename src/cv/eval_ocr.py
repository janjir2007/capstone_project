"""Compare plate recognizers on the held-out TEST trucks (Task 3.3).

A = pretrained EasyOCR ("mn" model), B = custom character CNN. Both read the
SAME test crops (yolo26n detections from ``src.cv.ocr_data``) and are scored by
the SAME code (``src.cv.ocr_metrics`` -> ``src.common.plates.read_plate``).

Speed = CPU wall time per plate, crop in -> text out (B includes
segmentation), median and p95 after warm-up. Detector time is not included
(same for both; see docs/cv_detection_results.md).

Outputs:
- ``models/plate_ocr/test_metrics.json`` (local)
- ``docs/figures/ocr_comparison.png``, ``docs/figures/ocr_threshold_tradeoff.png`` (numbers only)
- ``docs/cv_ocr_results.md`` (slide material)

Printed output: counts, rates and single-character confusions only (RISK-06).

Usage:
    python -m src.cv.eval_ocr
"""

from __future__ import annotations

import argparse
import json
import platform
import time
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import Any

import numpy as np

from src.common.plates import DEFAULT_CONFIDENCE_THRESHOLD
from src.cv.ocr_metrics import Prediction, evaluate_predictions, paired_comparison, threshold_sweep

DEFAULT_INDEX = Path("data/interim/plate_ocr/index.json")
DEFAULT_CNN = Path("models/plate_ocr/char_cnn.pt")
DEFAULT_OUT = Path("models/plate_ocr/test_metrics.json")
DEFAULT_FIGURES = Path("docs/figures")
DEFAULT_MD = Path("docs/cv_ocr_results.md")
WARMUP_RUNS = 2
SWEEP = [round(t, 2) for t in np.arange(0.0, 1.0001, 0.05)]
NAME_A = "A: EasyOCR mn (pretrained)"
NAME_B = "B: custom char CNN"

RecognizeFn = Callable[[np.ndarray], tuple[str, float, float]]


def run_recognizer(recognize: RecognizeFn, crops: list[np.ndarray], labels: list[str]) -> list[Prediction]:
    """Read every crop after warm-up; one Prediction per plate."""
    for _ in range(WARMUP_RUNS):
        recognize(crops[0])
    out = []
    for crop, label in zip(crops, labels):
        text, conf, ms = recognize(crop)
        out.append(Prediction(label=label, raw_text=text, confidence=conf, ms=ms))
    return out


def easyocr_fn() -> RecognizeFn:
    """Approach A on CPU."""
    from src.cv.ocr_easyocr import load_reader, recognize_crop

    reader = load_reader(gpu=False)
    return lambda crop: recognize_crop(reader, crop)


def cnn_fn(weights: Path) -> RecognizeFn:
    """Approach B on CPU."""
    from src.cv.char_cnn import load, recognize_crop

    model = load(weights)
    return lambda crop: recognize_crop(model, crop)


def easyocr_model_mb() -> float | None:
    """Size of EasyOCR's downloaded detection + recognition weights, if found."""
    folder = Path.home() / ".EasyOCR" / "model"
    files = [folder / "craft_mlt_25k.pth", folder / "cyrillic_g2.pth"]
    if not all(f.exists() for f in files):
        return None
    return round(sum(f.stat().st_size for f in files) / 1e6, 1)


# ---------------------------------------------------------------- charts
def plot_comparison(rows: list[dict[str, Any]], path: Path) -> None:
    """Grouped bars: accuracy and outcome rates at the 0.6 threshold, one colour per approach."""
    from src.cv.eval_detector import MODEL_COLORS, TEXT_2, _figure, _save

    metrics = [("exact_match", "exact plate\nmatch"), ("char_accuracy", "character\naccuracy"),
               ("auto_correct_rate", "auto-filled\n& correct"), ("manual_rate", "sent to\nmanual input"),
               ("wrong_auto_rate", "auto-filled\nbut WRONG")]
    fig, axes = _figure(1, 1, (9.0, 3.9))
    ax = axes[0, 0]
    width = 0.8 / len(rows)
    x = np.arange(len(metrics))
    for i, row in enumerate(rows):
        values = [row[key] for key, _ in metrics]
        pos = x - 0.4 + width * (i + 0.5)
        ax.bar(pos, values, width=width - 0.02, color=MODEL_COLORS[i], label=row["model"])
        for px, v in zip(pos, values):
            ax.text(px, v + 0.015, f"{v:.0%}", ha="center", va="bottom", fontsize=8, color=TEXT_2)
    ax.set_xticks(x, [label for _, label in metrics])
    ax.set_ylim(0, 1.12)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title(f"Plate reading on held-out test trucks (n = {rows[0]['plates']} plates, "
                 f"threshold {rows[0]['threshold']})", fontsize=11)
    ax.legend(frameon=False, fontsize=8, labelcolor=TEXT_2, loc="upper center", ncol=len(rows),
              bbox_to_anchor=(0.5, -0.2))
    _save(fig, path)


def plot_tradeoff(sweeps: dict[str, list[dict[str, float]]], path: Path) -> None:
    """Manual-input rate (solid) and wrong auto-fill rate (dashed) vs confidence threshold."""
    from src.cv.eval_detector import GRID, MODEL_COLORS, TEXT_2, _figure, _save

    fig, axes = _figure(1, 1, (6.8, 4.8))
    ax = axes[0, 0]
    for i, (name, rows) in enumerate(sweeps.items()):
        t = [r["threshold"] for r in rows]
        ax.plot(t, [r["manual_rate"] for r in rows], color=MODEL_COLORS[i], linewidth=2,
                label=f"{name} - manual input")
        ax.plot(t, [r["wrong_auto_rate"] for r in rows], color=MODEL_COLORS[i], linewidth=2, linestyle="--",
                label=f"{name} - wrong auto-fill")
    ax.axvline(DEFAULT_CONFIDENCE_THRESHOLD, color=GRID, linewidth=1.5, zorder=0)
    ax.text(DEFAULT_CONFIDENCE_THRESHOLD + 0.01, 1.0, f"current {DEFAULT_CONFIDENCE_THRESHOLD}",
            fontsize=8, color=TEXT_2, va="top")
    ax.set_xlabel("confidence threshold (below -> oil changer types the plate)")
    ax.set_ylabel("share of test plates")
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1.02)
    ax.yaxis.set_major_formatter(lambda v, _: f"{v:.0%}")
    ax.set_title("Threshold trade-off: typing more vs saving under the wrong truck", fontsize=10)
    ax.legend(frameon=False, fontsize=7.5, labelcolor=TEXT_2, loc="upper center", ncol=2, bbox_to_anchor=(0.5, -0.16))
    _save(fig, path)


# ---------------------------------------------------------------- report
def _confusions(row: dict[str, Any]) -> str:
    pairs = row["top_confusions"][:5]
    return ", ".join(f"{p['true']}->{p['pred']} x{p['count']}" for p in pairs) or "none"


def decision_lines(report: dict[str, Any]) -> list[str]:
    """'Chosen approach' section, built from the numbers (winner = higher exact match on test)."""
    a, b = report["models"]
    win, lose = (b, a) if b["exact_match"] >= a["exact_match"] else (a, b)
    n, p = win["plates"], report["paired"]["mcnemar_p"]
    return [
        "## Decision",
        "",
        f"**Chosen: {win['model']}.** Reasons:",
        "",
        f"1. Exact plate match {win['exact_match']:.0%} vs {lose['exact_match']:.0%} on the same {n} plates "
        f"(paired exact McNemar p = {p:.3f}{'; unlikely to be chance' if p < 0.05 else '; could still be chance'}).",
        f"2. Speed {win['ms_median']} vs {lose['ms_median']} ms/plate on CPU (cloud host is CPU-only).",
        f"3. Wrong auto-fills at threshold {win['threshold']}: {win['wrong_auto_fill']} vs {lose['wrong_auto_fill']}.",
        f"4. Both still send most plates to manual input at {win['threshold']} "
        f"({win['manual']}/{n} vs {lose['manual']}/{n}): recognition HELPS the oil changer but does not replace typing yet.",
        "",
        f"Threshold: keep {DEFAULT_CONFIDENCE_THRESHOLD} for now. Lower values look better on test, "
        "but picking the threshold on the test set would be cheating, and on val the CNN gave confidences up to "
        "~0.5 to wrong plates. Re-choose on a larger val set (photos_new).",
        "",
    ]


def results_markdown(report: dict[str, Any], figures: dict[str, str]) -> str:
    """Slide-ready markdown: data, metrics table, threshold, confusions, caveats, charts."""
    rows = report["models"]
    n = rows[0]["plates"]
    lines = [
        "# Plate recognition results (Task 3.3)",
        "",
        f"Generated by `python -m src.cv.eval_ocr` on {report['date']}. Numbers and single characters only, no photos or plates.",
        "",
        "## Setup",
        "",
        f"- Test = {n} plates of {report['test_trucks']} held-out trucks (same truck-grouped split as detection, D-009). "
        "Crops come from the production detector yolo26n (D-028), not from hand-drawn boxes.",
        "- **A** = EasyOCR " + report["easyocr_version"] + ", language `mn` (loads the `cyrillic_g2` model; its "
        "alphabet contains Ө and Ү — checked in the package's `config.py`, not assumed). No training on our data. "
        "Allowlist = digits + the 21 letters seen on our plates.",
        "- **B** = our CNN: connected-component segmentation into 7 characters (handles 1-row and 2-row plates) "
        f"→ 32×32 character classifier ({report['cnn']['parameters']:,} parameters, {report['cnn']['weights_kb']} KB), "
        "trained from scratch on train-split characters only, best epoch picked on val. "
        "Position rule: slots 1–4 digits, 5–7 letters.",
        "- Both outputs go through the app's own `read_plate()` (normalize → format check → confidence threshold).",
        "",
        f"## Test results (threshold {rows[0]['threshold']})",
        "",
        "| approach | exact plate match | character accuracy | auto-filled & correct | sent to manual | auto-filled but WRONG | CPU ms/plate (median / p95) |",
        "|---|---|---|---|---|---|---|",
    ]
    for r in rows:
        lines.append(
            f"| {r['model']} | {r['exact_match']:.1%} ({round(r['exact_match'] * n)}/{n}) | {r['char_accuracy']:.1%} "
            f"| {r['auto_correct']}/{n} | {r['manual']}/{n} | {r['wrong_auto_fill']}/{n} "
            f"| {r['ms_median']} / {r['ms_p95']} |"
        )
    lines += [
        "",
        "Paired on the same plates (exact match): "
        f"both right {report['paired']['both_right']}, only A {report['paired']['a_only']}, "
        f"only B {report['paired']['b_only']}, both wrong {report['paired']['both_wrong']}; "
        f"exact McNemar p = {report['paired']['mcnemar_p']:.3f}.",
        "",
        "- **exact plate match** = all 7 characters right, whatever the confidence.",
        "- **character accuracy** = 1 − edit distance / 7 (a dropped character costs 1, not 7).",
        "- **auto-filled but WRONG** = confident but wrong: the costly case (service saved under another truck).",
        f"- ms/plate = crop → text on {report['machine']}; detector time not included.",
        "",
        "Why sent to manual:",
        "",
        *[f"- {r['model']}: {r['manual_reasons'] or 'none'}" for r in rows],
        "",
        "(`empty` = nothing read; for B this means segmentation did not find exactly 7 characters.)",
        "",
        "## Top character confusions (true → predicted, same-length readings only)",
        "",
        *[f"- {r['model']}: {_confusions(r)}; wrong-length readings: {r['length_errors']}" for r in rows],
        "",
        "## Threshold trade-off",
        "",
        "| threshold | " + " | ".join(f"{r['model']} manual / wrong auto" for r in rows) + " |",
        "|---|" + "---|" * len(rows),
    ]
    sweeps = report["threshold_sweep"]
    for i, t in enumerate(SWEEP):
        if t in (0.0, 0.2, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9):
            cells = [f"{sweeps[r['model']][i]['manual_rate']:.0%} / {sweeps[r['model']][i]['wrong_auto_rate']:.0%}" for r in rows]
            lines.append(f"| {t} | " + " | ".join(cells) + " |")
    lines += [
        "",
        *decision_lines(report),
        "## Size / deployability",
        "",
        f"- A: EasyOCR weights on disk (text detector + cyrillic recognizer) = {report['easyocr_model_mb']} MB, plus the easyocr package and its dependencies (scipy, scikit-image, shapely ...).",
        f"- B: {report['cnn']['weights_kb']} KB weights, only torch + opencv (already needed by the detector).",
        "",
        "## Caveats (say these on the slide)",
        "",
        f"- Tiny test set: {n} plates. One plate = {100 / n:.1f} percentage points. Differences of 1–2 plates are noise.",
        "- The 21-letter alphabet (allowlist for A, classes for B) was taken from all 183 labels, test included; "
        "a letter that never appears on our plates would be impossible for both.",
        "- B's segmentation filters were tuned on train/val crops only; test was run once.",
        "- Lighting/dirt conditions of the test photos were not audited (photos are not opened by Claude, RISK-06); "
        "an error gallery by condition needs Ari's eyes.",
        "",
        "## Charts",
        "",
        *[f"![{title}]({rel})" for title, rel in figures.items()],
        "",
    ]
    return "\n".join(lines)


def load_split(index: Path, split: str) -> tuple[list[np.ndarray], list[str], int]:
    """Crops, labels and number of trucks of one split."""
    from PIL import Image

    rows = [r for r in json.loads(index.read_text(encoding="utf-8")) if r["split"] == split]
    crops = [np.asarray(Image.open(index.parent / "crops" / f"{r['stem']}.png").convert("RGB")) for r in rows]
    return crops, [r["label"] for r in rows], len({r["group"] for r in rows})


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--cnn", type=Path, default=DEFAULT_CNN)
    parser.add_argument("--split", default="test", help="split to score (test for the report; val for debugging)")
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--figures", type=Path, default=DEFAULT_FIGURES)
    parser.add_argument("--md", type=Path, default=DEFAULT_MD)
    args = parser.parse_args(argv)

    import torch

    crops, labels, trucks = load_split(args.index, args.split)
    rows, sweeps, all_preds = [], {}, []
    for name, fn in ((NAME_A, easyocr_fn()), (NAME_B, cnn_fn(args.cnn))):
        preds = run_recognizer(fn, crops, labels)
        all_preds.append(preds)
        metrics = evaluate_predictions(preds)
        metrics["auto_correct_rate"] = metrics["auto_correct"] / metrics["plates"]
        metrics["wrong_auto_rate"] = metrics["wrong_auto_fill"] / metrics["plates"]
        rows.append({"model": name, **metrics})
        sweeps[name] = threshold_sweep(preds, SWEEP)

    from src.cv.char_cnn import load

    report = {
        "date": time.strftime("%Y-%m-%d"),
        "split": args.split,
        "test_trucks": trucks,
        "machine": f"{platform.platform()}, torch {torch.__version__}",
        "easyocr_version": version("easyocr"),
        "easyocr_model_mb": easyocr_model_mb(),
        "cnn": {"parameters": sum(p.numel() for p in load(args.cnn).parameters()),
                "weights_kb": round(args.cnn.stat().st_size / 1024, 1)},
        "models": rows,
        "paired": paired_comparison(*all_preds),
        "threshold_sweep": sweeps,
    }
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    print(json.dumps({k: v for k, v in report.items() if k != "threshold_sweep"}, indent=2, ensure_ascii=False))
    if args.split != "test":
        print("Not the test split: report and charts NOT written.")
        return 0

    figures = {"A vs B on test trucks": "ocr_comparison.png",
               "Confidence threshold trade-off": "ocr_threshold_tradeoff.png"}
    plot_comparison(rows, args.figures / figures["A vs B on test trucks"])
    plot_tradeoff(sweeps, args.figures / figures["Confidence threshold trade-off"])
    rel = Path("figures") if args.md.parent.resolve() == args.figures.parent.resolve() else args.figures
    args.md.write_text(results_markdown(report, {t: (rel / f).as_posix() for t, f in figures.items()}), encoding="utf-8")
    print(f"Saved {args.out}, {args.md} and charts in {args.figures}/")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
