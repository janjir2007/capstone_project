"""Approach B: small custom PyTorch CNN that classifies single characters (Task 3.3, D-008).

Pipeline per plate: crop -> ``char_segment.segment`` (7 character images) ->
CNN gives class probabilities per character -> position rule: positions 1-4
may only be digits, 5-7 only letters (same rule as ``src.common.plates``) ->
text + confidence.

Confidence = product of the 7 chosen probabilities, i.e. the model's own
estimate that ALL 7 characters are right. Comparable in meaning to EasyOCR's
plate-level score, so the same 0.6 threshold is applied to both.

Training data = characters of TRAIN-split plates only. VAL-split plates pick
the best epoch. TEST is never seen here (scored in ``eval_ocr``).

Usage:
    python -m src.cv.char_cnn            # train, save models/plate_ocr/char_cnn.pt, print counts + val scores
"""

from __future__ import annotations

import argparse
import json
import random
import time
from pathlib import Path
from typing import Any

import cv2
import numpy as np
import torch
from torch import nn

from src.common.plates import DIGIT_COUNT, PLATE_LETTERS
from src.cv.char_segment import CHAR_SIZE, PLATE_CHARS, segment

SEED = 42
DIGITS = "0123456789"
CLASSES = DIGITS + "".join(sorted(PLATE_LETTERS))  # 10 digits + 21 letters = 31 classes
DEFAULT_INDEX = Path("data/interim/plate_ocr/index.json")
DEFAULT_WEIGHTS = Path("models/plate_ocr/char_cnn.pt")
EPOCHS = 60
BATCH = 64
LR = 1e-3


def set_seed(seed: int = SEED) -> None:
    """Fix every random source used in training."""
    random.seed(seed)
    np.random.seed(seed)
    torch.manual_seed(seed)


class CharCNN(nn.Module):
    """3 conv blocks (32 -> 64 -> 128 channels) + global average pool + linear. 291 k parameters, 1.1 MB."""

    def __init__(self, n_classes: int = len(CLASSES)) -> None:
        super().__init__()

        def block(c_in: int, c_out: int) -> nn.Sequential:
            return nn.Sequential(nn.Conv2d(c_in, c_out, 3, padding=1), nn.BatchNorm2d(c_out), nn.ReLU(),
                                 nn.Conv2d(c_out, c_out, 3, padding=1), nn.BatchNorm2d(c_out), nn.ReLU(),
                                 nn.MaxPool2d(2))

        self.features = nn.Sequential(block(1, 32), block(32, 64), block(64, 128))  # 32 -> 16 -> 8 -> 4
        self.head = nn.Sequential(nn.AdaptiveAvgPool2d(1), nn.Flatten(), nn.Dropout(0.3), nn.Linear(128, n_classes))

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        """(N, 1, 32, 32) in 0-1 -> (N, n_classes) logits."""
        return self.head(self.features(x))


def position_mask() -> torch.Tensor:
    """(7, n_classes) additive mask: -inf for letters in digit slots and digits in letter slots."""
    mask = torch.full((PLATE_CHARS, len(CLASSES)), float("-inf"))
    mask[:DIGIT_COUNT, : len(DIGITS)] = 0.0
    mask[DIGIT_COUNT:, len(DIGITS) :] = 0.0
    return mask


# ---------------------------------------------------------------- data
def load_crop(crops_dir: Path, stem: str) -> np.ndarray:
    """RGB crop as a numpy array."""
    from PIL import Image

    return np.asarray(Image.open(crops_dir / f"{stem}.png").convert("RGB"))


def char_dataset(rows: list[dict[str, Any]], crops_dir: Path) -> tuple[np.ndarray, np.ndarray, int]:
    """Character images + class ids from plates that segment into 7. Returns (X, y, plates_used)."""
    images, labels, used = [], [], 0
    for row in rows:
        chars = segment(load_crop(crops_dir, row["stem"]))
        if chars is None:
            continue
        used += 1
        images.append(chars)
        labels += [CLASSES.index(c) for c in row["label"]]
    if not images:
        return np.zeros((0, CHAR_SIZE, CHAR_SIZE), np.float32), np.zeros(0, np.int64), 0
    return np.concatenate(images), np.array(labels, dtype=np.int64), used


def augment(img: np.ndarray, rng: np.random.Generator) -> np.ndarray:
    """Random small rotation/scale/shift, contrast/brightness, blur and noise (photos are outdoors)."""
    centre = (CHAR_SIZE / 2, CHAR_SIZE / 2)
    matrix = cv2.getRotationMatrix2D(centre, rng.uniform(-8, 8), rng.uniform(0.85, 1.1))
    matrix[:, 2] += rng.uniform(-2, 2, size=2)
    out = cv2.warpAffine(img, matrix, (CHAR_SIZE, CHAR_SIZE), borderMode=cv2.BORDER_REPLICATE)
    out = (out - 0.5) * rng.uniform(0.6, 1.4) + 0.5 + rng.uniform(-0.15, 0.15)
    if rng.random() < 0.3:
        out = cv2.GaussianBlur(out, (3, 3), 0)
    out = out + rng.normal(0, 0.03, out.shape)
    return np.clip(out, 0, 1).astype(np.float32)


def to_tensor(images: np.ndarray) -> torch.Tensor:
    """(N, 32, 32) -> (N, 1, 32, 32) float tensor."""
    return torch.from_numpy(np.ascontiguousarray(images)).unsqueeze(1).float()


# ---------------------------------------------------------------- train
def train(x_train: np.ndarray, y_train: np.ndarray, x_val: np.ndarray, y_val: np.ndarray,
          epochs: int = EPOCHS, seed: int = SEED) -> tuple[CharCNN, list[dict[str, float]]]:
    """Train on CPU with augmentation; keep the epoch with the best val character accuracy."""
    set_seed(seed)
    rng = np.random.default_rng(seed)
    model = CharCNN()
    optimizer = torch.optim.Adam(model.parameters(), lr=LR)
    scheduler = torch.optim.lr_scheduler.CosineAnnealingLR(optimizer, T_max=epochs)
    loss_fn = nn.CrossEntropyLoss()  # no label smoothing: it caps each probability (~0.95) and so the 7-char product
    best_acc, best_state, history = -1.0, None, []
    for epoch in range(1, epochs + 1):
        model.train()
        order = rng.permutation(len(x_train))
        total = 0.0
        for start in range(0, len(order), BATCH):
            idx = order[start : start + BATCH]
            xb = to_tensor(np.stack([augment(x_train[i], rng) for i in idx]))
            loss = loss_fn(model(xb), torch.from_numpy(y_train[idx]))
            optimizer.zero_grad()
            loss.backward()
            optimizer.step()
            total += loss.item() * len(idx)
        scheduler.step()
        val_acc = char_val_accuracy(model, x_val, y_val)
        history.append({"epoch": epoch, "train_loss": round(total / len(x_train), 4), "val_char_acc": round(val_acc, 4)})
        if val_acc > best_acc:
            best_acc, best_state = val_acc, {k: v.clone() for k, v in model.state_dict().items()}
    if best_state is not None:
        model.load_state_dict(best_state)
    model.eval()
    return model, history


@torch.no_grad()
def char_val_accuracy(model: CharCNN, x: np.ndarray, y: np.ndarray) -> float:
    """Plain per-character accuracy (no position mask) on segmented val characters."""
    if len(x) == 0:
        return 0.0
    model.eval()
    return float((model(to_tensor(x)).argmax(1).numpy() == y).mean())


# ---------------------------------------------------------------- predict
@torch.no_grad()
def predict_chars(model: CharCNN, chars: np.ndarray) -> tuple[str, float]:
    """7 character images (reading order) -> (text, confidence = product of chosen probabilities)."""
    probs = torch.softmax(model(to_tensor(chars)) + position_mask(), dim=1)
    best_p, best_i = probs.max(dim=1)
    return "".join(CLASSES[i] for i in best_i.tolist()), float(best_p.prod())


def recognize_crop(model: CharCNN, crop_rgb: np.ndarray) -> tuple[str, float, float]:
    """Plate crop -> (raw text, confidence, ms). Segmentation failure -> ("", 0.0, ms)."""
    start = time.perf_counter()
    chars = segment(crop_rgb)
    text, conf = ("", 0.0) if chars is None else predict_chars(model, chars)
    return text, conf, (time.perf_counter() - start) * 1000.0


def save(model: CharCNN, path: Path) -> None:
    """Save weights + class list (so a later class change cannot silently mis-map outputs)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    torch.save({"state_dict": model.state_dict(), "classes": CLASSES}, path)


def load(path: Path) -> CharCNN:
    """Load a model saved by ``save``; refuses a file trained with a different class list."""
    ckpt = torch.load(path, map_location="cpu", weights_only=True)
    if ckpt["classes"] != CLASSES:
        raise ValueError(f"{path} was trained with a different class list; retrain")
    model = CharCNN()
    model.load_state_dict(ckpt["state_dict"])
    model.eval()
    return model


def main(argv: list[str] | None = None) -> int:
    """CLI: train on train split, select on val, save weights, print counts + val scores."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--out", type=Path, default=DEFAULT_WEIGHTS)
    parser.add_argument("--epochs", type=int, default=EPOCHS)
    args = parser.parse_args(argv)

    rows = json.loads(args.index.read_text(encoding="utf-8"))
    crops = args.index.parent / "crops"
    by_split = {s: [r for r in rows if r["split"] == s] for s in ("train", "val")}
    x_tr, y_tr, used_tr = char_dataset(by_split["train"], crops)
    x_va, y_va, used_va = char_dataset(by_split["val"], crops)
    start = time.perf_counter()
    model, history = train(x_tr, y_tr, x_va, y_va, epochs=args.epochs)
    save(model, args.out)
    args.out.with_name("char_cnn_history.json").write_text(json.dumps(history, indent=1), encoding="utf-8")
    best = max(history, key=lambda h: h["val_char_acc"])
    print(json.dumps({
        "train_plates_segmented": f"{used_tr}/{len(by_split['train'])}",
        "val_plates_segmented": f"{used_va}/{len(by_split['val'])}",
        "train_chars": len(x_tr),
        "classes_seen_in_train": int(len(set(y_tr.tolist()))),
        "classes_total": len(CLASSES),
        "parameters": sum(p.numel() for p in model.parameters()),
        "best_epoch": best["epoch"],
        "best_val_char_acc_on_segmented": best["val_char_acc"],
        "train_seconds_cpu": round(time.perf_counter() - start, 1),
        "weights_kb": round(args.out.stat().st_size / 1024, 1),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
