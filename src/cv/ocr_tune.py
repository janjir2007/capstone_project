"""Char CNN v3: field-style augmentation + validation-only tuning (Task 3.6b, D-087).

Product target D-087 (set before this run): on the 27 old test plates,
>= 18 (2/3) auto-filled correctly AND 0 wrong auto-fills.

Two sub-commands:

1. ``tune`` (VAL ONLY, test is never loaded). For every config in the grid
   (augmentation strength x epochs) train a CNN on the train split, then pick
   its auto-fill threshold on val with the rule: most correct auto-fills with
   0 wrong auto-fills (ties -> the HIGHER threshold, more safety margin at no
   val cost). The config with the most val correct auto-fills wins (ties ->
   the higher val threshold = safer, then fewer epochs). It is
   saved as ``char_cnn_v3.pt``. v1 and v2 get a val threshold by the same
   rule, so the final table can separate "new threshold" from "new model".
2. ``final`` (TEST, ONCE). Refuses to run if its result file already exists.
   Scores v1 / v2 / v3 on the test plates at the served 0.6 and at each
   model's val threshold, applies the D-087 rule to v3 at its val threshold,
   writes the "Task 3.6b" section of docs/cv_ocr_results.md.
3. ``promote`` (only if ``final`` said PASS). Exports v3 to ONNX, keeps v1 as
   ``char_cnn_v1.*`` for rollback, makes v3 the served ``char_cnn.*`` and
   writes its val threshold + the served file's SHA-256 into
   ``char_cnn_version.json``; the API reads the threshold from there
   (``plate_reader.served_threshold``), so 0.6 is no longer hard-wired.

Field augmentation mimics the failures seen in the field test (D-077) and is
applied to the WHOLE plate crop before segmentation, so the CNN also learns
from the slightly broken characters that segmentation produces on bad photos:
harsh sun (brighter, flatter contrast), blur, small rotation, and a
downscale-then-upscale (plate far from the camera). The trainer's own
per-character augmentation (``char_cnn.augment``) still runs on top.

Printed output and the markdown contain counts only (RISK-06).

Usage:
    python -m src.cv.ocr_tune tune
    python -m src.cv.ocr_tune final
    python -m src.cv.ocr_tune promote
"""

from __future__ import annotations

import argparse
import json
import math
import shutil
import sys
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np

from src.common.plates import DEFAULT_CONFIDENCE_THRESHOLD
from src.cv.ocr_metrics import Prediction, evaluate_predictions

SEED = 42
DEFAULT_OCR = Path("data/interim/plate_ocr")
MODELS = Path("models/plate_ocr")
V1, V2, V3 = MODELS / "char_cnn.pt", MODELS / "char_cnn_v2.pt", MODELS / "char_cnn_v3.pt"
TUNE_OUT = MODELS / "tune_3_6b.json"
FINAL_OUT = MODELS / "final_3_6b.json"
DEFAULT_MD = Path("docs/cv_ocr_results.md")
MD_MARKER = "## Task 3.6b"

STRENGTHS = (0.0, 0.5, 1.0)  # 0 = no field augmentation (the v2 recipe)
EPOCH_GRID = (40, 60, 90)
COPIES = 4  # augmented copies of each train plate (strength > 0 only)
THRESHOLDS = tuple(round(0.30 + 0.05 * i, 2) for i in range(14))  # 0.30 ... 0.95
TARGET_FRACTION = 2 / 3  # D-087


# ---------------------------------------------------------------- augmentation
def field_augment(crop_rgb: np.ndarray, rng: np.random.Generator, strength: float) -> np.ndarray:
    """One randomly degraded copy of a plate crop (uint8 RGB in, uint8 RGB out).

    ``strength`` 0 returns the crop unchanged; 1 = strongest setting:
    contrast x0.5-1.3 and brightness -40..+80 (sun), Gaussian blur sigma up to
    1.5 px, rotation up to +-5 deg, and with probability 0.5 a downscale to
    30-100 % of the size and back up (far plate).
    """
    if strength <= 0:
        return crop_rgb.copy()
    h, w = crop_rgb.shape[:2]
    out = crop_rgb.astype(np.float32)
    out = out * rng.uniform(1 - 0.5 * strength, 1 + 0.3 * strength) + rng.uniform(-40, 80) * strength
    out = np.clip(out, 0, 255).astype(np.uint8)
    angle = rng.uniform(-5, 5) * strength
    matrix = cv2.getRotationMatrix2D((w / 2, h / 2), angle, 1.0)
    out = cv2.warpAffine(out, matrix, (w, h), borderMode=cv2.BORDER_REPLICATE)
    if rng.random() < 0.5:
        factor = rng.uniform(1 - 0.7 * strength, 1.0)
        small = cv2.resize(out, (max(1, round(w * factor)), max(1, round(h * factor))), interpolation=cv2.INTER_AREA)
        out = cv2.resize(small, (w, h), interpolation=cv2.INTER_LINEAR)
    sigma = rng.uniform(0, 1.5 * strength)
    if sigma > 0.3:
        out = cv2.GaussianBlur(out, (0, 0), sigma)
    return out


def augmented_chars(rows: list[dict[str, Any]], crops_dir: Path, strength: float, copies: int,
                    seed: int = SEED) -> tuple[np.ndarray, np.ndarray, dict[str, int]]:
    """Characters of ``copies`` field-augmented versions of each plate (only those that still segment into 7)."""
    from src.cv.char_cnn import CLASSES, load_crop
    from src.cv.char_segment import CHAR_SIZE, segment

    rng = np.random.default_rng(seed)
    images, labels, tried, kept = [], [], 0, 0
    if strength > 0:
        for row in rows:
            crop = load_crop(crops_dir, row["stem"])
            for _ in range(copies):
                tried += 1
                chars = segment(field_augment(crop, rng, strength))
                if chars is None:
                    continue
                kept += 1
                images.append(chars)
                labels += [CLASSES.index(c) for c in row["label"]]
    x = np.concatenate(images) if images else np.zeros((0, CHAR_SIZE, CHAR_SIZE), np.float32)
    return x, np.array(labels, dtype=np.int64), {"aug_plates_tried": tried, "aug_plates_segmented": kept}


# ---------------------------------------------------------------- selection rules (pure)
def choose_threshold(preds: list[Prediction], grid: tuple[float, ...] = THRESHOLDS) -> dict[str, Any]:
    """Val rule: the threshold with the most correct auto-fills among those with 0 wrong; ties -> higher.

    If every threshold makes a wrong auto-fill, the highest one is returned with ``safe = False``.
    """
    rows = []
    for t in grid:
        m = evaluate_predictions(preds, t)
        rows.append({"threshold": t, "auto_correct": m["auto_correct"], "wrong": m["wrong_auto_fill"]})
    safe = [r for r in rows if r["wrong"] == 0]
    if not safe:
        return {**rows[-1], "safe": False}
    best = max(safe, key=lambda r: (r["auto_correct"], r["threshold"]))
    return {**best, "safe": True}


def config_rank(result: dict[str, Any]) -> tuple[Any, ...]:
    """Sort key (bigger = better): val correct auto-fills, then HIGHER val threshold (safer), then fewer epochs.

    Later ties (rare): more val exact reads, then weaker augmentation.
    """
    return (result["val_safe"], result["val_auto_correct"], result["val_threshold"], -result["epochs"],
            result["val_exact"], -result["strength"])


def target_count(plates: int, fraction: float = TARGET_FRACTION) -> int:
    """Smallest whole number of plates that is >= fraction of ``plates`` (27 -> 18)."""
    return math.ceil(plates * fraction - 1e-9)


def promote_v3(old_test: dict[str, Any]) -> tuple[bool, list[str]]:
    """D-087 rule on the 27 old test plates (``evaluate_predictions`` output at v3's val threshold)."""
    need = target_count(old_test["plates"])
    checks = [(old_test["wrong_auto_fill"] == 0, f"wrong auto-fills = {old_test['wrong_auto_fill']} (must be 0)"),
              (old_test["auto_correct"] >= need,
               f"correct auto-fills = {old_test['auto_correct']}/{old_test['plates']} (need >= {need})")]
    return all(ok for ok, _ in checks), [f"{'PASS' if ok else 'FAIL'}: {text}" for ok, text in checks]


# ---------------------------------------------------------------- model helpers
def read_rows(model: Any, rows: list[dict[str, Any]], crops_dir: Path) -> list[Prediction]:
    """One Prediction per plate (segmentation failures included, as in the app)."""
    from src.cv.char_cnn import load_crop, recognize_crop

    out = []
    for r in rows:
        text, conf, ms = recognize_crop(model, load_crop(crops_dir, r["stem"]))
        out.append(Prediction(label=r["label"], raw_text=text, confidence=conf, ms=ms))
    return out


def val_summary(preds: list[Prediction]) -> dict[str, Any]:
    """Val exact reads + the threshold chosen by the val rule."""
    exact = round(evaluate_predictions(preds, 0.0)["exact_match"] * len(preds))
    choice = choose_threshold(preds)
    return {"val_exact": exact, "val_threshold": choice["threshold"], "val_auto_correct": choice["auto_correct"],
            "val_wrong": choice["wrong"], "val_safe": choice["safe"],
            "val_at_0_6": {k: evaluate_predictions(preds, DEFAULT_CONFIDENCE_THRESHOLD)[k]
                           for k in ("auto_correct", "wrong_auto_fill")}}


# ---------------------------------------------------------------- tune
def cmd_tune(args: argparse.Namespace) -> int:
    """Grid on train/val only; save the winner as v3 and every val number to tune_3_6b.json."""
    from src.cv.char_cnn import char_dataset, load, save, train

    index = json.loads((args.ocr_dir / "index_v2.json").read_text(encoding="utf-8"))
    crops = args.ocr_dir / "crops"
    tr = [r for r in index if r["split"] == "train"]
    va = [r for r in index if r["split"] == "val"]  # test rows are never touched here
    x_tr, y_tr, used_tr = char_dataset(tr, crops)
    x_va, y_va, used_va = char_dataset(va, crops)
    report: dict[str, Any] = {
        "date": time.strftime("%Y-%m-%d"), "seed": SEED, "copies": COPIES, "thresholds": list(THRESHOLDS),
        "val": {"plates": len(va), "trucks": len({r["group"] for r in va}), "segmented": used_va},
        "train": {"plates": len(tr), "segmented": used_tr, "chars": len(x_tr)},
        "baselines": {}, "grid": []}
    for name, path in (("v1", V1), ("v2", V2)):
        report["baselines"][name] = val_summary(read_rows(load(path), va, crops))

    best_state, best_result = None, None
    for strength in args.strengths:
        x_aug, y_aug, aug_stats = augmented_chars(tr, crops, strength, COPIES)
        x_all, y_all = np.concatenate([x_tr, x_aug]), np.concatenate([y_tr, y_aug])
        for epochs in args.epochs:
            start = time.perf_counter()
            model, history = train(x_all, y_all, x_va, y_va, epochs=epochs, seed=SEED)
            result = {"strength": strength, "epochs": epochs, "train_chars": len(x_all), **aug_stats,
                      "best_epoch": max(history, key=lambda h: h["val_char_acc"])["epoch"],
                      "val_char_acc": max(h["val_char_acc"] for h in history),
                      **val_summary(read_rows(model, va, crops)),
                      "seconds": round(time.perf_counter() - start, 1)}
            report["grid"].append(result)
            print(json.dumps(result), flush=True)
            if best_result is None or config_rank(result) > config_rank(best_result):
                best_result, best_state = result, {k: v.clone() for k, v in model.state_dict().items()}
    model.load_state_dict(best_state)
    model.eval()
    save(model, args.out)
    report["chosen"] = best_result
    report["chosen_weights"] = str(args.out)
    TUNE_OUT.write_text(json.dumps(report, indent=1), encoding="utf-8")
    print(json.dumps({"chosen": best_result, "baselines": report["baselines"]}, indent=2))
    return 0


# ---------------------------------------------------------------- final (test, once)
def same_weights(a: Any, b: Any) -> bool:
    """True if two CharCNNs have bit-identical weights (v3 = re-run of the v2 recipe)."""
    import torch

    sa, sb = a.state_dict(), b.state_dict()
    return sa.keys() == sb.keys() and all(torch.equal(sa[k], sb[k]) for k in sa)


def results_section(final: dict[str, Any], tune: dict[str, Any]) -> str:
    """Markdown for docs/cv_ocr_results.md (counts and rates only)."""
    c = tune["chosen"]
    lines = [
        f"{MD_MARKER} — augmentation + validation-only tuning (char CNN v3)", "",
        f"Generated by `python -m src.cv.ocr_tune tune` (val only) and `python -m src.cv.ocr_tune final` "
        f"(test, run once) on {final['date']}. Detector unchanged (yolo26n). Seed {SEED}.", "",
        "### Target (D-087, set before this run)", "",
        "On the 27 old test plates: ≥ 18/27 (2/3) auto-filled correctly AND 0 wrong auto-fills. "
        "Only v3 can be promoted; otherwise v1 stays served (D-086).", "",
        "### What was tuned, on validation only", "",
        f"- Validation set = **{tune['val']['plates']} plates of {tune['val']['trucks']} trucks** "
        f"({tune['val']['segmented']} segment into 7). One val plate = {100 / tune['val']['plates']:.1f} points; "
        "a threshold chosen on so few plates can easily be too low for new photos.",
        "- Field augmentation on whole train crops before segmentation: brightness/contrast (sun), blur, "
        f"rotation, downscale→upscale (far plate); {tune['copies']} copies per train plate.",
        f"- Grid: strength {sorted({g['strength'] for g in tune['grid']})} × epochs "
        f"{sorted({g['epochs'] for g in tune['grid']})}; threshold grid 0.30–0.95.",
        "- Rule: per model, threshold = most val correct auto-fills with 0 val wrong (tie → higher threshold); "
        "best config = most val correct auto-fills (tie → higher threshold, then fewer epochs).", "",
        "| config | train chars | val exact | val threshold | val correct auto | val wrong auto |",
        "|---|---|---|---|---|---|",
    ]
    for g in tune["grid"]:
        lines.append(f"| strength {g['strength']}, {g['epochs']} ep | {g['train_chars']} | {g['val_exact']}/"
                     f"{tune['val']['plates']} | {g['val_threshold']:.2f} | {g['val_auto_correct']} | {g['val_wrong']} |")
    for name, b in tune["baselines"].items():
        lines.append(f"| {name} (existing) | — | {b['val_exact']}/{tune['val']['plates']} | {b['val_threshold']:.2f} "
                     f"| {b['val_auto_correct']} | {b['val_wrong']} |")
    lines += ["", f"**Chosen v3: strength {c['strength']}, {c['epochs']} epochs, threshold {c['val_threshold']:.2f}.**",
              "", "### Test (run once)", "",
              "| test set | model | threshold | exact read | correct auto-fills | wrong auto-fills | sent to manual |",
              "|---|---|---|---|---|---|---|"]
    for set_name, by_model in final["sets"].items():
        for row in by_model:
            m = row["metrics"]
            n = m["plates"]
            lines.append(f"| {set_name} | {row['model']} | {row['threshold']:.2f} | {round(m['exact_match'] * n)}/{n} "
                         f"| {m['auto_correct']}/{n} | {m['wrong_auto_fill']} | {m['manual']}/{n} |")
    lines += ["", "- `old_test` = the same 27 plates as Tasks 3.3 / 3.6 (the D-087 target is on these). "
              "`new_test` = 1 new photo of an old test truck.",
              "- Segmentation failures (`empty`) go to manual for every CNN; they cap what any retrain can reach.", "",
              "Paired exact reads on old_test: " + "; ".join(
                  f"{k}: only first {p['a_only']}, only second {p['b_only']}, McNemar p = {p['mcnemar_p']:.3f}"
                  for k, p in final["paired"].items()), "",
              *(["**The val winner is the v2 recipe (strength 0, 60 epochs) and its weights are identical to v2: "
                 "the v3 rows reproduce v2's known Task 3.6 test result (same weights; compare the threshold column).**", ""]
                if final.get("v3_same_weights_as_v2") else []),
              "### Decision", "", *[f"- {c}" for c in final["checks"]], "",
              f"**{final['decision']}**", ""]
    return "\n".join(lines)


def write_section(md: Path, section: str) -> None:
    """Replace the Task 3.6b section of the results file, or append it."""
    text = md.read_text(encoding="utf-8") if md.exists() else ""
    head = text.split(MD_MARKER)[0].rstrip() + "\n\n" if MD_MARKER in text else text.rstrip() + "\n\n"
    md.write_text(head + section, encoding="utf-8")


def cmd_final(args: argparse.Namespace) -> int:
    """The single test run: v1 / v2 / v3 at 0.6 and at their val thresholds, then the D-087 rule."""
    from src.cv.char_cnn import load
    from src.cv.ocr_extend import eval_sets
    from src.cv.ocr_metrics import paired_comparison

    if FINAL_OUT.exists():
        raise ValueError(f"{FINAL_OUT} exists: the test set was already used once (no second final run)")
    tune = json.loads(TUNE_OUT.read_text(encoding="utf-8"))
    thresholds = {"v1": tune["baselines"]["v1"]["val_threshold"], "v2": tune["baselines"]["v2"]["val_threshold"],
                  "v3": tune["chosen"]["val_threshold"]}
    models = {"v1": load(V1), "v2": load(V2), "v3": load(V3)}
    index = json.loads((args.ocr_dir / "index_v2.json").read_text(encoding="utf-8"))
    crops = args.ocr_dir / "crops"
    final: dict[str, Any] = {"date": time.strftime("%Y-%m-%d"), "thresholds": thresholds, "sets": {}, "paired": {}}
    preds_old: dict[str, list[Prediction]] = {}
    for set_name, rows in eval_sets(index).items():
        if not rows:
            continue
        out = []
        for name, model in models.items():
            preds = read_rows(model, rows, crops)
            if set_name == "old_test":
                preds_old[name] = preds
            for t in sorted({DEFAULT_CONFIDENCE_THRESHOLD, thresholds[name]}):
                m = evaluate_predictions(preds, t)
                m.pop("top_confusions")  # single characters only, but not needed here
                out.append({"model": name, "threshold": t, "metrics": m})
        final["sets"][set_name] = out
    final["paired"] = {"v1 vs v3": paired_comparison(preds_old["v1"], preds_old["v3"]),
                       "v2 vs v3": paired_comparison(preds_old["v2"], preds_old["v3"])}
    v3_old = evaluate_predictions(preds_old["v3"], thresholds["v3"])
    final["promote_v3"], final["checks"] = promote_v3(v3_old)
    final["v3_same_weights_as_v2"] = same_weights(models["v2"], models["v3"])
    final["decision"] = (f"v3 meets D-087 → promote v3 with threshold {thresholds['v3']:.2f}."
                         if final["promote_v3"] else
                         "v3 does not meet D-087 → v1 stays served (D-086 unchanged); v2 and v3 saved for later.")
    FINAL_OUT.write_text(json.dumps(final, indent=1), encoding="utf-8")
    write_section(args.md, results_section(final, tune))
    print(json.dumps({k: final[k] for k in ("thresholds", "checks", "decision")}, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- promote
def cmd_promote(args: argparse.Namespace) -> int:
    """Serve v3 with its val threshold, only if the single final run passed D-087."""
    from src.cv.export_onnx import check_char_cnn, export_char_cnn
    from src.cv.plate_reader import RECOGNIZER_FILE, VERSION_FILE, sha256_8

    final = json.loads(FINAL_OUT.read_text(encoding="utf-8"))
    if not final["promote_v3"]:
        raise ValueError("final run did not pass D-087: v3 is not promoted (v1 stays served)")
    folder = MODELS
    v3_onnx = export_char_cnn(V3, folder / "char_cnn_v3.onnx")
    check = check_char_cnn(V3, v3_onnx)
    if check["same_text"] != check["plates"]:
        raise ValueError(f"ONNX v3 disagrees with PyTorch v3: {check}")
    for ext in ("pt", "onnx"):
        served, v1 = folder / f"char_cnn.{ext}", folder / f"char_cnn_v1.{ext}"
        if not v1.exists():
            shutil.copy2(served, v1)  # keep the 3.3 model for rollback
        shutil.copy2(folder / f"char_cnn_v3.{ext}", served)
    served_onnx = MODELS.parent / RECOGNIZER_FILE
    info = {"served": "v3", "threshold": final["thresholds"]["v3"], "served_sha256_8": sha256_8(served_onnx),
            "threshold_source": "val rule, Task 3.6b (tune_3_6b.json)", "check": check,
            "sha256_8": {p.name: sha256_8(p) for p in sorted(folder.glob("char_cnn*.onnx"))}}
    (MODELS.parent / VERSION_FILE).write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI with sub-commands tune / final / promote."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    tp = sub.add_parser("tune", help="grid on train/val only; saves char_cnn_v3.pt")
    tp.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR)
    tp.add_argument("--out", type=Path, default=V3)
    tp.add_argument("--strengths", type=float, nargs="+", default=list(STRENGTHS))
    tp.add_argument("--epochs", type=int, nargs="+", default=list(EPOCH_GRID))
    tp.set_defaults(func=cmd_tune)
    fp = sub.add_parser("final", help="the single test run + D-087 rule")
    fp.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR)
    fp.add_argument("--md", type=Path, default=DEFAULT_MD)
    fp.set_defaults(func=cmd_final)
    pp = sub.add_parser("promote", help="serve v3 + its threshold, only if final passed")
    pp.set_defaults(func=cmd_promote)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
