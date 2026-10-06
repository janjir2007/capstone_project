"""Fine-tune a small Ultralytics YOLO plate detector (Task 3.2).

Transfer learning: start from COCO-pretrained nano weights (``yolo11n.pt``
main, ``yolo26n.pt`` comparison) and train one class, ``plate``, on the
truck-grouped split made by ``src.cv.plate_split``.

- The val split is used by Ultralytics for early stopping and to pick
  ``best.pt``. The test split is NOT touched here (see ``eval_detector``).
- Runs locally. Device: Apple MPS if available, else CPU; if training on MPS
  fails, it is retried once on CPU.
- Output goes to ``models/plate_yolo/<run name>/`` (git-ignored). Ultralytics
  also saves batch preview images there - they show real photos, keep local.

Usage (Ari runs it; reads real photos):
    python -m src.cv.train_detector --model yolo11n.pt
    python -m src.cv.train_detector --model yolo26n.pt
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from importlib.metadata import version
from pathlib import Path
from typing import Any

SEED = 42
DEFAULT_DATA = Path("data/processed/plate_yolo/data.yaml")
DEFAULT_PROJECT = Path("models/plate_yolo")
DEFAULT_EPOCHS = 100
DEFAULT_PATIENCE = 20  # stop if val fitness has not improved for 20 epochs
DEFAULT_IMGSZ = 640  # same input size as the oim baseline (yolo-v9-t-640)
DEFAULT_BATCH = 16


def pick_device(requested: str = "auto") -> str:
    """``auto`` -> ``mps`` on Apple Silicon if PyTorch supports it, else ``cpu``."""
    if requested != "auto":
        return requested
    import torch

    return "mps" if torch.backends.mps.is_available() else "cpu"


def run_name(model: str) -> str:
    """Folder name for a run, e.g. ``yolo11n.pt`` -> ``yolo11n``."""
    return Path(model).stem


def train_args(data: Path, project: Path, name: str, device: str, epochs: int, patience: int,
               imgsz: int, batch: int, seed: int = SEED) -> dict[str, Any]:
    """Keyword arguments for ``YOLO.train``. Everything not listed stays at Ultralytics defaults."""
    return {
        "data": str(data.resolve()),
        "epochs": epochs,
        "patience": patience,
        "imgsz": imgsz,
        "batch": batch,
        "device": device,
        "seed": seed,
        "deterministic": True,
        "project": str(project.resolve()),  # absolute: otherwise Ultralytics puts it under ./runs
        "name": name,
        "exist_ok": True,  # re-running overwrites this run's folder instead of making name2, name3...
        "plots": True,
        "verbose": True,
    }


def train(model: str, args: dict[str, Any]) -> tuple[Path, str]:
    """Train; on an MPS failure retry once on CPU. Returns (run folder, device used)."""
    from ultralytics import YOLO  # lazy: heavy import, not needed by tests

    try:
        result = YOLO(model).train(**args)
    except Exception as exc:  # noqa: BLE001 - any MPS backend error should fall back, not crash
        if args["device"] != "mps":
            raise
        print(f"WARNING: training on MPS failed ({type(exc).__name__}: {exc}); retrying on CPU.", file=sys.stderr)
        args = {**args, "device": "cpu"}
        result = YOLO(model).train(**args)
    save_dir = Path(result.save_dir) if result is not None and hasattr(result, "save_dir") else \
        Path(args["project"]) / args["name"]
    return save_dir, args["device"]


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model", default="yolo11n.pt", help="pretrained weights, e.g. yolo11n.pt or yolo26n.pt")
    parser.add_argument("--data", type=Path, default=DEFAULT_DATA)
    parser.add_argument("--project", type=Path, default=DEFAULT_PROJECT)
    parser.add_argument("--device", default="auto", help="auto, mps or cpu")
    parser.add_argument("--epochs", type=int, default=DEFAULT_EPOCHS)
    parser.add_argument("--patience", type=int, default=DEFAULT_PATIENCE)
    parser.add_argument("--imgsz", type=int, default=DEFAULT_IMGSZ)
    parser.add_argument("--batch", type=int, default=DEFAULT_BATCH)
    args = parser.parse_args(argv)

    if not args.data.exists():
        print(f"ERROR: {args.data} not found. Run python -m src.cv.plate_split first.", file=sys.stderr)
        return 1

    name = run_name(args.model)
    kwargs = train_args(args.data, args.project, name, pick_device(args.device), args.epochs,
                        args.patience, args.imgsz, args.batch)
    start = time.perf_counter()
    save_dir, device = train(args.model, kwargs)
    info = {
        "model": args.model,
        "ultralytics": version("ultralytics"),
        "device": device,
        "train_minutes": round((time.perf_counter() - start) / 60, 1),
        "args": {k: v for k, v in kwargs.items() if k not in ("data", "project")},
        "best_weights": str(save_dir / "weights" / "best.pt"),
    }
    (save_dir / "train_info.json").write_text(json.dumps(info, indent=1), encoding="utf-8")
    print(json.dumps(info, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
