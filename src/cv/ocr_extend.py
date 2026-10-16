"""Add the newly labeled photos (Label Studio project ``plates_new``) to the char CNN data (Task 3.6).

The detector is NOT retrained (YOLO unchanged). Three steps, each a sub-command:

1. ``split``: SHA-256 dedupe of the new photos against the old photos and
   against each other (byte-identical copies only), then extend the 3.2/3.3
   split WITHOUT moving any old photo:
   - new photo of a truck already in the old split -> that truck's old split
     (old test truck -> test; old train/val truck -> same split), so no truck
     is ever in two sets;
   - new truck -> train or val (seeded, whole trucks, ~15 % val);
   - a photo linking trucks from two different old splits -> dropped (counted).
   New crops come from the same detector (yolo26n, best box). The crop's label
   is the text of the labeled plate box that overlaps the detector box best
   (IoU >= 0.5); if none does, the hand-drawn box is cropped (``source = gt``).
   Writes ``split_v2.json`` (old split.json is kept unchanged) and
   ``index_v2.json`` = old index rows + new rows.
2. Train with the unchanged trainer: ``python -m src.cv.char_cnn --index
   data/interim/plate_ocr/index_v2.json --out models/plate_ocr/char_cnn_v2.pt``.
3. ``compare``: old model vs new model on the OLD test plates and on the new
   test photos (old test trucks seen again), threshold 0.6, then the keep rule
   below. Writes a "Task 3.6" section into docs/cv_ocr_results.md.
   ``promote`` then makes the new ONNX file the served one, only if the rule
   said so (old files are kept as ``char_cnn_v1.*``).

Keep rule (fixed before any result was seen): keep the new model only if
(a) it makes 0 wrong auto-fills on every test set, (b) it reads at least
``MIN_EXTRA_EXACT`` more test plates exactly than the old model (1-2 plates is
noise on a test set this small, docs/cv_ocr_results.md), and (c) it auto-fills
correctly at least as many plates. Otherwise the old model stays.

Printed output and the markdown contain counts only (RISK-06).

Usage:
    python -m src.cv.ocr_extend split data/interim/labelstudio_export/<plates_new export>.json
    python -m src.cv.char_cnn --index data/interim/plate_ocr/index_v2.json --out models/plate_ocr/char_cnn_v2.pt
    python -m src.cv.ocr_extend compare
    python -m src.cv.ocr_extend promote
"""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sys
import time
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

from src.common.plates import DEFAULT_CONFIDENCE_THRESHOLD, is_valid_plate, normalize_plate
from src.cv.ls_export import PlateBox, boxes_from_task, load_export, summarize
from src.cv.plate_split import SEED, boxes_by_image, dataset_file_stem, group_images, split_groups

DEFAULT_ROOT = Path("data/raw")
DEFAULT_OLD_PHOTOS = Path("data/raw/photos")
DEFAULT_EXPORT_DIR = Path("data/interim/labelstudio_export")
DEFAULT_SPLIT = Path("data/interim/plate_split/split.json")
DEFAULT_SPLIT_V2 = Path("data/interim/plate_split/split_v2.json")
DEFAULT_OCR = Path("data/interim/plate_ocr")
DEFAULT_WEIGHTS = Path("models/plate_yolo/yolo26n/weights/best.pt")
OLD_CNN = Path("models/plate_ocr/char_cnn.pt")
NEW_CNN = Path("models/plate_ocr/char_cnn_v2.pt")
DEFAULT_MD = Path("docs/cv_ocr_results.md")
NEW_VAL_FRACTION = 0.15 / 0.85  # same train:val ratio as the 3.2 split (70:15)
MATCH_IOU = 0.5
MIN_EXTRA_EXACT = 3
MD_MARKER = "## Task 3.6"
JPEG_QUALITY = 95  # same re-save as plate_split.build_dataset, so new crops look like old ones


# ---------------------------------------------------------------- dedupe
def sha256_file(path: Path) -> str:
    """Hex SHA-256 of a file's bytes."""
    digest = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            digest.update(chunk)
    return digest.hexdigest()


def dedupe(new_hashes: dict[str, str], old_hashes: set[str]) -> tuple[list[str], dict[str, int]]:
    """Keep new images whose bytes are not an old photo and not an earlier new photo (sorted order)."""
    kept, seen = [], set()
    counts = {"duplicate_of_old": 0, "duplicate_within_new": 0}
    for image in sorted(new_hashes):
        h = new_hashes[image]
        if h in old_hashes:
            counts["duplicate_of_old"] += 1
        elif h in seen:
            counts["duplicate_within_new"] += 1
        else:
            seen.add(h)
            kept.append(image)
    return kept, counts


# ---------------------------------------------------------------- split
def safe_normalize(text: str) -> str | None:
    """normalize_plate, or None for a blank text."""
    try:
        return normalize_plate(text)
    except ValueError:
        return None


def texts_by_image(by_image: dict[str, list[PlateBox]]) -> dict[str, list[str]]:
    """Normalized texts of every box (plate and fleet_no), the truck identity used for grouping."""
    out = {}
    for image, boxes in by_image.items():
        texts = (safe_normalize(b.plate_text) for b in boxes if b.plate_text)
        out[image] = sorted({t for t in texts if t})
    return out


def extend_split(old_rows: list[dict[str, Any]], old_texts: dict[str, list[str]],
                 new_texts: dict[str, list[str]], seed: int = SEED) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Rows for the new images: inherit an old truck's split, or split new trucks into train/val.

    ``old_rows`` are split.json rows (image, group, split); old rows are never changed.
    """
    old_by_image = {r["image"]: r for r in old_rows}
    old_of_text: dict[str, tuple[str, str]] = {}  # text -> (old group, old split)
    for image, texts in old_texts.items():
        if image in old_by_image:
            for t in texts:
                old_of_text[t] = (old_by_image[image]["group"], old_by_image[image]["split"])

    local = group_images(new_texts)  # union-find among the new photos only
    members: dict[str, list[str]] = defaultdict(list)
    for image, gid in local.items():
        members[gid].append(image)

    next_id = 1 + max((int(r["group"][1:]) for r in old_rows), default=-1)
    rows, stats = [], Counter()
    new_truck_groups: dict[str, list[str]] = {}
    for gid in sorted(members):
        links = sorted({old_of_text[t] for img in members[gid] for t in new_texts[img] if t in old_of_text})
        splits = {s for _, s in links}
        if len(splits) > 1:
            stats["dropped_links_two_old_splits"] += len(members[gid])
            continue
        if links:
            group, split = links[0]
            stats[f"known_truck_to_{split}"] += len(members[gid])
            rows += [{"image": img, "group": group, "split": split, "source": "new"} for img in members[gid]]
        else:
            new_gid = f"g{next_id:03d}"
            next_id += 1
            new_truck_groups[new_gid] = members[gid]

    sizes = {g: len(imgs) for g, imgs in new_truck_groups.items()}
    assignment = split_groups(sizes, {"test": 0.0, "val": NEW_VAL_FRACTION, "train": 1 - NEW_VAL_FRACTION}, seed)
    for g, imgs in new_truck_groups.items():
        stats[f"new_truck_to_{assignment[g]}"] += len(imgs)
        rows += [{"image": img, "group": g, "split": assignment[g], "source": "new"} for img in imgs]
    stats["new_trucks"] = len(new_truck_groups)
    return sorted(rows, key=lambda r: r["image"]), dict(stats)


def check_no_truck_in_two_splits(rows: list[dict[str, Any]], texts: dict[str, list[str]]) -> None:
    """Raise if one group, or one plate text, appears in more than one split."""
    by_group: dict[str, set[str]] = defaultdict(set)
    by_text: dict[str, set[str]] = defaultdict(set)
    for r in rows:
        by_group[r["group"]].add(r["split"])
        for t in texts.get(r["image"], []):
            by_text[t].add(r["split"])
    bad_groups = sum(len(s) > 1 for s in by_group.values())
    bad_texts = sum(len(s) > 1 for s in by_text.values())
    if bad_groups or bad_texts:
        raise ValueError(f"leak: {bad_groups} groups and {bad_texts} plate texts in more than one split")


# ---------------------------------------------------------------- labels for crops
def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """IoU of two x1y1x2y2 boxes."""
    w = max(0.0, min(a[2], b[2]) - max(a[0], b[0]))
    h = max(0.0, min(a[3], b[3]) - max(a[1], b[1]))
    inter = w * h
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return inter / union if union > 0 else 0.0


def box_pixels(box: PlateBox, width: int, height: int) -> tuple[float, float, float, float]:
    """Label Studio fractions -> pixel x1y1x2y2 of the upright image."""
    return ((box.x_center - box.width / 2) * width, (box.y_center - box.height / 2) * height,
            (box.x_center + box.width / 2) * width, (box.y_center + box.height / 2) * height)


def plate_boxes(boxes: list[PlateBox]) -> list[PlateBox]:
    """Registration-plate boxes that have text."""
    return [b for b in boxes if b.plate_type == "plate" and b.plate_text]


def match_label(det_xyxy: tuple[float, float, float, float] | None, boxes: list[PlateBox],
                width: int, height: int) -> tuple[PlateBox, str] | None:
    """Labeled plate box for the crop: best IoU with the detector box, else the first plate box (gt crop)."""
    candidates = plate_boxes(boxes)
    if not candidates:
        return None
    if det_xyxy is not None:
        best = max(candidates, key=lambda b: iou(det_xyxy, box_pixels(b, width, height)))
        if iou(det_xyxy, box_pixels(best, width, height)) >= MATCH_IOU:
            return best, "yolo26n"
    return candidates[0], "gt"


def build_new_crops(rows: list[dict[str, Any]], by_image: dict[str, list[PlateBox]], root: Path,
                    weights: Path, ocr_dir: Path) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Crop each new image (detector best box or hand box) and return index rows + counts."""
    import io

    import numpy as np
    from PIL import Image
    from ultralytics import YOLO

    from src.cv.ocr_data import best_box, padded_crop
    from src.cv.prelabel import load_upright

    model = YOLO(str(weights))
    upright_dir, crops_dir = ocr_dir / "upright_new", ocr_dir / "crops"
    upright_dir.mkdir(parents=True, exist_ok=True)
    crops_dir.mkdir(parents=True, exist_ok=True)
    out, counts = [], Counter()
    for row in rows:
        stem = dataset_file_stem(row["image"])
        buffer = io.BytesIO()  # JPEG round trip like the old dataset images
        load_upright(root / row["image"]).save(buffer, format="JPEG", quality=JPEG_QUALITY)
        path = upright_dir / f"{stem}.jpg"
        path.write_bytes(buffer.getvalue())
        image = np.asarray(Image.open(path).convert("RGB"))
        h, w = image.shape[:2]
        found = best_box(model, path)
        matched = match_label(tuple(found[0]) if found else None, by_image[row["image"]], w, h)
        if matched is None:
            counts["no_plate_text"] += 1
            continue
        box, source = matched
        label = safe_normalize(box.plate_text or "")
        if not label or not is_valid_plate(label):
            counts["label_fails_format"] += 1
            continue
        xyxy = list(found[0]) if source == "yolo26n" else list(box_pixels(box, w, h))
        Image.fromarray(padded_crop(image, xyxy)).save(crops_dir / f"{stem}.png")
        counts[f"crop_{source}"] += 1
        out.append({"stem": stem, "split": row["split"], "group": row["group"], "label": label,
                    "det_conf": round(found[1], 4) if found and source == "yolo26n" else 0.0,
                    "source": source, "origin": "new"})
    return out, dict(counts)


def format_pass(tasks: list[dict[str, Any]]) -> dict[str, int]:
    """How many plate-type texts pass the app's format check (4 digits + 3 known letters)."""
    texts = [b.plate_text for t in tasks for b in boxes_from_task(t) if b.plate_type == "plate" and b.plate_text]
    normalized = [safe_normalize(t) for t in texts]
    passed = sum(1 for t in normalized if t and is_valid_plate(t))
    unseen = Counter(c for t in normalized if t and len(t) == 7 for c in t[4:]
                     if c.isalpha() and not is_valid_plate("0000" + c * 3))
    return {"plate_texts": len(texts), "format_pass": passed, "format_fail": len(texts) - passed,
            "texts_with_question_mark": sum("?" in t for t in texts),
            "letters_not_in_alphabet": sum(unseen.values())}  # count only: which letters is plate data


def cmd_split(args: argparse.Namespace) -> int:
    """Export counts, dedupe, extend the split, build new crops, write split_v2 + index_v2."""
    new_tasks = load_export(args.export_json)
    old_split = json.loads(args.split.read_text(encoding="utf-8"))
    old_tasks = load_export(args.export_dir / old_split["export"])
    report: dict[str, Any] = {"export": {**summarize(new_tasks), **format_pass(new_tasks)}}

    new_by_image = boxes_by_image(new_tasks)
    old_hashes = {sha256_file(p) for p in sorted(args.old_photos.iterdir()) if p.is_file()}
    kept, dup = dedupe({img: sha256_file(args.root / img) for img in new_by_image}, old_hashes)
    report["dedupe"] = {"labeled_new_images": len(new_by_image), **dup, "kept": len(kept)}
    new_by_image = {img: new_by_image[img] for img in kept}

    old_texts = texts_by_image(boxes_by_image(old_tasks))
    new_texts = texts_by_image(new_by_image)
    new_rows, stats = extend_split(old_split["images"], old_texts, new_texts, args.seed)
    all_rows = [{**r, "source": "old"} for r in old_split["images"]] + new_rows
    check_no_truck_in_two_splits(all_rows, {**old_texts, **new_texts})
    report["split_new_images"] = stats

    split_v2 = {**old_split, "images": all_rows, "export_new": args.export_json.name, "task": "3.6"}
    args.split_out.write_text(json.dumps(split_v2, indent=1, ensure_ascii=False), encoding="utf-8")

    index_rows, crop_counts = build_new_crops(new_rows, new_by_image, args.root, args.weights, args.ocr_dir)
    old_index = [{**r, "origin": "old"} for r in json.loads((args.ocr_dir / "index.json").read_text(encoding="utf-8"))]
    (args.ocr_dir / "index_v2.json").write_text(json.dumps(old_index + index_rows, indent=1, ensure_ascii=False),
                                                encoding="utf-8")
    report["new_crops"] = {**crop_counts, "per_split": dict(Counter(r["split"] for r in index_rows))}
    print(json.dumps(report, indent=2))
    print(f"Saved {args.split_out} and {args.ocr_dir / 'index_v2.json'} (local only; do not share).")
    return 0


# ---------------------------------------------------------------- compare
def eval_sets(index_rows: list[dict[str, Any]]) -> dict[str, list[dict[str, Any]]]:
    """Test plates by origin: the 27 old test plates, and new photos of old test trucks."""
    return {"old_test": [r for r in index_rows if r["split"] == "test" and r.get("origin") == "old"],
            "new_test": [r for r in index_rows if r["split"] == "test" and r.get("origin") == "new"]}


def keep_new(old: dict[str, dict[str, Any]], new: dict[str, dict[str, Any]]) -> tuple[bool, list[str]]:
    """The fixed keep rule. ``old``/``new`` map eval-set name -> evaluate_predictions output."""
    def total(m: dict[str, dict[str, Any]], key: str) -> int:
        return sum(round(v["exact_match"] * v["plates"]) if key == "exact" else v[key] for v in m.values())

    checks = [
        (total(new, "wrong_auto_fill") == 0, f"new wrong auto-fills = {total(new, 'wrong_auto_fill')} (must be 0)"),
        (total(new, "exact") - total(old, "exact") >= MIN_EXTRA_EXACT,
         f"exact reads {total(old, 'exact')} -> {total(new, 'exact')} (need +{MIN_EXTRA_EXACT})"),
        (total(new, "auto_correct") >= total(old, "auto_correct"),
         f"auto-filled & correct {total(old, 'auto_correct')} -> {total(new, 'auto_correct')} (must not drop)"),
    ]
    return all(ok for ok, _ in checks), [f"{'PASS' if ok else 'FAIL'}: {text}" for ok, text in checks]


def results_section(report: dict[str, Any]) -> str:
    """Markdown section for docs/cv_ocr_results.md (counts and rates only)."""
    lines = [
        f"{MD_MARKER} — retrain char CNN on old + new labeled photos",
        "",
        f"Generated by `python -m src.cv.ocr_extend compare` on {report['date']}. Detector unchanged (yolo26n). "
        f"Threshold {DEFAULT_CONFIDENCE_THRESHOLD} unchanged. Same trainer, same settings, seed {SEED}.",
        "",
        "### Data",
        "",
        f"- Character samples for training (train split, plates that segment into 7): "
        f"old {report['train_chars']['old']} → new {report['train_chars']['new']} "
        f"(+{report['train_chars']['new'] - report['train_chars']['old']}).",
        "- Field tests: **not run** — no field-test photos exist yet (Ari, 2026-10-16).",
        "",
        "### Old model vs new model (test only, run once)",
        "",
        "| test set | plates | model | exact read | auto-filled | auto-filled & correct | wrong auto-fills |",
        "|---|---|---|---|---|---|---|",
    ]
    for name, by_model in report["sets"].items():
        for model in ("old", "new"):
            m = by_model[model]
            n = m["plates"]
            auto = n - m["manual"]
            lines.append(f"| {name} | {n} | {model} | {m['exact_match']:.1%} ({round(m['exact_match'] * n)}/{n}) "
                         f"| {auto / n:.1%} ({auto}/{n}) | {m['auto_correct']}/{n} | {m['wrong_auto_fill']} |")
    lines += ["", "Paired exact reads (old vs new, same plates): "
              + "; ".join(f"{k}: only old {p['a_only']}, only new {p['b_only']}, McNemar p = {p['mcnemar_p']:.3f}"
                          for k, p in report["paired"].items()), "",
              "- `old_test` = the same 27 test plates as Task 3.3. `new_test` = new photos of trucks already in the "
              "old test set (they stay in test; no truck is in two sets).",
              "- auto-filled = plate filled without the oil changer typing (confidence ≥ 0.6 and valid format).",
              "", "### Decision", "",
              f"Rule D-085, fixed before the run: keep the new model only if 0 wrong auto-fills, ≥ +{MIN_EXTRA_EXACT} exact "
              "reads on all test plates, and no fewer correct auto-fills.", "",
              *[f"- {c}" for c in report["checks"]], "",
              f"**{'New model kept (char_cnn_v2 served).' if report['keep_new'] else 'Old model kept; new model NOT served.'}**",
              ""]
    return "\n".join(lines)


def write_section(md: Path, section: str) -> None:
    """Replace the Task 3.6 section of the results file, or append it."""
    text = md.read_text(encoding="utf-8") if md.exists() else ""
    head = text.split(MD_MARKER)[0].rstrip() + "\n\n" if MD_MARKER in text else text.rstrip() + "\n\n"
    md.write_text(head + section, encoding="utf-8")


def cmd_compare(args: argparse.Namespace) -> int:
    """Score old and new CNN on the test sets, apply the keep rule, write the report."""
    import numpy as np
    from PIL import Image

    from src.cv.char_cnn import char_dataset, load, recognize_crop
    from src.cv.eval_ocr import run_recognizer
    from src.cv.ocr_metrics import evaluate_predictions, paired_comparison

    index = json.loads((args.ocr_dir / "index_v2.json").read_text(encoding="utf-8"))
    crops_dir = args.ocr_dir / "crops"
    models = {"old": load(args.old), "new": load(args.new)}
    report: dict[str, Any] = {"date": time.strftime("%Y-%m-%d"), "sets": {}, "paired": {}}
    train_old = [r for r in index if r["split"] == "train" and r.get("origin") == "old"]
    train_all = [r for r in index if r["split"] == "train"]
    report["train_chars"] = {"old": len(char_dataset(train_old, crops_dir)[1]),
                             "new": len(char_dataset(train_all, crops_dir)[1])}
    for name, rows in eval_sets(index).items():
        if not rows:
            continue
        crops = [np.asarray(Image.open(crops_dir / f"{r['stem']}.png").convert("RGB")) for r in rows]
        labels = [r["label"] for r in rows]
        preds = {k: run_recognizer(lambda c, m=m: recognize_crop(m, c), crops, labels) for k, m in models.items()}
        report["sets"][name] = {k: evaluate_predictions(p) for k, p in preds.items()}
        report["sets"][name]["trucks"] = len({r["group"] for r in rows})
        report["paired"][name] = paired_comparison(preds["old"], preds["new"])
    metrics = {model: {s: v[model] for s, v in report["sets"].items()} for model in ("old", "new")}
    report["keep_new"], report["checks"] = keep_new(metrics["old"], metrics["new"])
    for v in report["sets"].values():
        v.pop("trucks")
    Path(args.out).write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
    write_section(args.md, results_section(report))
    print(json.dumps(report, indent=2, ensure_ascii=False))
    return 0


# ---------------------------------------------------------------- promote
def cmd_promote(args: argparse.Namespace) -> int:
    """Export the new CNN to ONNX; serve it only if ``compare`` said keep_new."""
    from src.cv.export_onnx import check_char_cnn, export_char_cnn

    report = json.loads(Path(args.report).read_text(encoding="utf-8"))
    folder = args.new.parent
    v2_onnx = export_char_cnn(args.new, folder / "char_cnn_v2.onnx")
    info: dict[str, Any] = {"onnx_v2": str(v2_onnx), "check": check_char_cnn(args.new, v2_onnx),
                            "sha256_8": {}, "served": "v1"}
    if report["keep_new"]:
        for ext in ("pt", "onnx"):
            served, v1 = folder / f"char_cnn.{ext}", folder / f"char_cnn_v1.{ext}"
            if not v1.exists():
                shutil.copy2(served, v1)  # keep the 3.3 model for rollback
            shutil.copy2(folder / f"char_cnn_v2.{ext}", served)
        info["served"] = "v2"
    for name in ("char_cnn.onnx", "char_cnn_v1.onnx", "char_cnn_v2.onnx"):
        if (folder / name).exists():
            info["sha256_8"][name] = sha256_file(folder / name)[:8]
    (folder / "char_cnn_version.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=2))
    return 0


def main(argv: list[str] | None = None) -> int:
    """CLI with sub-commands split / compare / promote."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = parser.add_subparsers(dest="cmd", required=True)
    sp = sub.add_parser("split", help="dedupe + extend split + new crops")
    sp.add_argument("export_json", type=Path, help="full JSON export of plates_new")
    sp.add_argument("--split", type=Path, default=DEFAULT_SPLIT)
    sp.add_argument("--split-out", type=Path, default=DEFAULT_SPLIT_V2)
    sp.add_argument("--export-dir", type=Path, default=DEFAULT_EXPORT_DIR, help="where the old export lives")
    sp.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    sp.add_argument("--old-photos", type=Path, default=DEFAULT_OLD_PHOTOS)
    sp.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR)
    sp.add_argument("--weights", type=Path, default=DEFAULT_WEIGHTS)
    sp.add_argument("--seed", type=int, default=SEED)
    sp.set_defaults(func=cmd_split)
    cp = sub.add_parser("compare", help="old vs new CNN on test + keep rule")
    cp.add_argument("--ocr-dir", type=Path, default=DEFAULT_OCR)
    cp.add_argument("--old", type=Path, default=OLD_CNN)
    cp.add_argument("--new", type=Path, default=NEW_CNN)
    cp.add_argument("--out", type=Path, default=Path("models/plate_ocr/compare_3_6.json"))
    cp.add_argument("--md", type=Path, default=DEFAULT_MD)
    cp.set_defaults(func=cmd_compare)
    pp = sub.add_parser("promote", help="export ONNX v2; serve it only if compare said keep")
    pp.add_argument("--new", type=Path, default=NEW_CNN)
    pp.add_argument("--report", type=Path, default=Path("models/plate_ocr/compare_3_6.json"))
    pp.set_defaults(func=cmd_promote)
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except (OSError, ValueError, KeyError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
