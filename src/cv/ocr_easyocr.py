"""Approach A: pretrained OCR = EasyOCR with the Mongolian model (Task 3.3, D-012).

Cyrillic support was checked in the package itself (easyocr 1.7.2), not assumed:
- ``easyocr/config.py``: "mn" is in ``cyrillic_lang_list``, so it loads the
  ``cyrillic_g2`` recognition model.
- that model's ``characters`` string contains the Mongolian-only letters Ө and Ү
  (a Russian-only model would not have them); ``mn_char.txt`` contains them too.
- EasyOCR's site lists "Mongolian (mn)" and "Russian (ru)" as supported.
Weights (~detection + recognition model) download once to ``~/.EasyOCR/``.

EasyOCR finds text lines itself, so a two-row plate comes back as two pieces.
They are joined top row first, then left to right, matching how the label is
written (digits on top, letters below).

``allowlist`` limits the alphabet to digits + the letters seen on real plates
(``PLATE_LETTERS``), so EasyOCR cannot answer with, e.g., Ж or punctuation.
"""

from __future__ import annotations

import time
from typing import Any

import numpy as np

from src.common.plates import PLATE_LETTERS

LANGS = ["mn"]
ALLOWLIST = "0123456789" + "".join(sorted(PLATE_LETTERS))


def load_reader(gpu: bool = False) -> Any:
    """Create the EasyOCR reader (CPU by default: the cloud host has no GPU)."""
    import easyocr

    return easyocr.Reader(LANGS, gpu=gpu, verbose=False)


def join_pieces(pieces: list[tuple[list[list[float]], str, float]]) -> tuple[str, float]:
    """Join EasyOCR ``(box, text, conf)`` pieces in reading order.

    Rows: a piece starts a new row when its top is below the previous piece's
    vertical centre. Confidence = product of piece confidences (all pieces must
    be right for the plate to be right). No pieces -> ("", 0.0).
    """
    if not pieces:
        return "", 0.0
    items = []
    for box, text, conf in pieces:
        ys = [p[1] for p in box]
        xs = [p[0] for p in box]
        items.append((min(ys), (min(ys) + max(ys)) / 2, min(xs), text, float(conf)))
    items.sort(key=lambda it: it[0])
    rows: list[list[tuple[float, float, float, str, float]]] = [[items[0]]]
    for it in items[1:]:
        if it[0] > rows[-1][-1][1]:
            rows.append([it])
        else:
            rows[-1].append(it)
    text = "".join(it[3] for row in rows for it in sorted(row, key=lambda it: it[2]))
    return text, float(np.prod([it[4] for it in items]))


def recognize_crop(reader: Any, crop_rgb: np.ndarray) -> tuple[str, float, float]:
    """Read one plate crop -> (raw text, confidence 0-1, milliseconds)."""
    start = time.perf_counter()
    pieces = reader.readtext(crop_rgb, detail=1, allowlist=ALLOWLIST)
    text, conf = join_pieces(pieces)
    return text, conf, (time.perf_counter() - start) * 1000.0
