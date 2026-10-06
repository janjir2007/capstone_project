"""Cut a plate crop into its 7 character images (Task 3.3, approach B).

Why not 7 fixed slots (the brief's first idea): some trucks have two-row plates
(digits on top, letters below, Ari 2026-10-06), some one-row plates have a
blue MNG strip on the left, and detector boxes have uneven margins. Fixed
slots would cut through characters. Instead:

1. Grey, resize to a fixed height, boost contrast (CLAHE), threshold (Otsu).
   Both polarities are tried (dark text on light plate, and the reverse).
2. Connected components = blobs. Keep character-shaped blobs (height, width,
   fill limits below); split over-wide blobs (touching characters). Chosen on
   train+val crops: 82.7% -> 87.8% of plates give exactly 7 blobs (erosion or
   opening helped less).
3. If more than 7, drop the blob whose height is furthest from the median
   until 7 remain (removes MNG letters, bolts, flag symbol).
4. Rows: sort by vertical centre; a big jump (> half a character height)
   starts the second row. Two rows must be 4 on top + 3 below.
5. Order: top row first, each row left to right = label order.

Returns None when it cannot find exactly 7 characters; the app then asks the
oil changer to type the plate (counted as "manual" in the evaluation).
"""

from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

PLATE_CHARS = 7
WORK_HEIGHT = 96  # crop is resized to this height before thresholding (pixels)
CHAR_SIZE = 32  # CNN input is CHAR_SIZE x CHAR_SIZE

# Blob filters, as fractions of the work image height (tuned on train/val crops only).
MIN_CHAR_H = 0.18
MAX_CHAR_H = 0.95
MIN_ASPECT = 0.10  # width / height; "1" is narrow
MAX_ASPECT = 1.2  # wider blobs are treated as touching characters and split
TYPICAL_ASPECT = 0.6  # used to guess how many characters a wide blob holds
MAX_MERGED = 3
MIN_FILL = 0.12  # blob pixels / bounding-box area
MAX_FILL = 0.95


@dataclass(frozen=True)
class Blob:
    """Bounding box of one connected component, in work-image pixels."""

    x: int
    y: int
    w: int
    h: int

    @property
    def cy(self) -> float:
        """Vertical centre."""
        return self.y + self.h / 2


def to_work_gray(crop_rgb: np.ndarray) -> np.ndarray:
    """RGB crop -> contrast-boosted grey image of height WORK_HEIGHT."""
    gray = cv2.cvtColor(crop_rgb, cv2.COLOR_RGB2GRAY)
    scale = WORK_HEIGHT / gray.shape[0]
    gray = cv2.resize(gray, (max(1, round(gray.shape[1] * scale)), WORK_HEIGHT), interpolation=cv2.INTER_CUBIC)
    return cv2.createCLAHE(clipLimit=2.0, tileGridSize=(4, 4)).apply(gray)


def binarize(gray: np.ndarray, dark_text: bool) -> np.ndarray:
    """Otsu threshold; foreground (text) = 255 for the chosen polarity."""
    blurred = cv2.GaussianBlur(gray, (3, 3), 0)
    mode = cv2.THRESH_BINARY_INV if dark_text else cv2.THRESH_BINARY
    return cv2.threshold(blurred, 0, 255, mode + cv2.THRESH_OTSU)[1]


def char_blobs(binary: np.ndarray) -> list[Blob]:
    """Connected components that look like characters; touching characters are split.

    A blob wider than MAX_ASPECT is usually 2-3 characters touching (dirt, low
    resolution). It is cut into ``round(width / (TYPICAL_ASPECT * height))``
    equal parts; more than MAX_MERGED parts is treated as not text.
    """
    height = binary.shape[0]
    n, _, stats, _ = cv2.connectedComponentsWithStats(binary, connectivity=8)
    blobs = []
    for x, y, w, h, area in stats[1:n]:  # row 0 is the background
        if not MIN_CHAR_H * height <= h <= MAX_CHAR_H * height:
            continue
        if not MIN_FILL <= area / (w * h) <= MAX_FILL:
            continue
        if w / h < MIN_ASPECT:
            continue
        parts = 1 if w / h <= MAX_ASPECT else max(2, round(w / (TYPICAL_ASPECT * h)))
        if parts > MAX_MERGED:
            continue
        blobs += [Blob(int(x + i * w / parts), int(y), int(w / parts), int(h)) for i in range(parts)]
    return blobs


def keep_consistent(blobs: list[Blob], k: int = PLATE_CHARS) -> list[Blob]:
    """Drop the blob whose height is furthest from the median until ``k`` remain."""
    blobs = list(blobs)
    while len(blobs) > k:
        median = float(np.median([b.h for b in blobs]))
        blobs.remove(max(blobs, key=lambda b: abs(b.h - median)))
    return blobs


def reading_order(blobs: list[Blob]) -> list[Blob] | None:
    """Top row then bottom row, each left to right. None if rows are not 7 or 4+3."""
    if len(blobs) != PLATE_CHARS:
        return None
    by_y = sorted(blobs, key=lambda b: b.cy)
    gaps = [b.cy - a.cy for a, b in zip(by_y, by_y[1:])]
    split_at = int(np.argmax(gaps))
    if gaps[split_at] <= 0.5 * float(np.median([b.h for b in blobs])):
        return sorted(blobs, key=lambda b: b.x)  # one row
    top, bottom = by_y[: split_at + 1], by_y[split_at + 1 :]
    if (len(top), len(bottom)) != (4, 3):
        return None
    return sorted(top, key=lambda b: b.x) + sorted(bottom, key=lambda b: b.x)


def char_image(gray: np.ndarray, blob: Blob, dark_text: bool) -> np.ndarray:
    """Square CHAR_SIZE x CHAR_SIZE float image (0-1), dark character on light background."""
    m = max(1, blob.h // 10)
    y1, y2 = max(0, blob.y - m), min(gray.shape[0], blob.y + blob.h + m)
    x1, x2 = max(0, blob.x - m), min(gray.shape[1], blob.x + blob.w + m)
    patch = gray[y1:y2, x1:x2]
    if not dark_text:
        patch = 255 - patch
    side = max(patch.shape)
    top, left = (side - patch.shape[0]) // 2, (side - patch.shape[1]) // 2
    square = cv2.copyMakeBorder(patch, top, side - patch.shape[0] - top, left, side - patch.shape[1] - left,
                                cv2.BORDER_REPLICATE)
    return cv2.resize(square, (CHAR_SIZE, CHAR_SIZE), interpolation=cv2.INTER_AREA).astype(np.float32) / 255.0


def segment(crop_rgb: np.ndarray) -> np.ndarray | None:
    """Plate crop -> array (7, CHAR_SIZE, CHAR_SIZE) in reading order, or None.

    Tries dark text first (normal plates); if both polarities work, the one
    with the most uniform character heights wins.
    """
    gray = to_work_gray(crop_rgb)
    best: tuple[float, list[Blob], bool] | None = None
    for dark_text in (True, False):
        ordered = reading_order(keep_consistent(char_blobs(binarize(gray, dark_text))))
        if ordered is None:
            continue
        spread = float(np.std([b.h for b in ordered]))
        if best is None or spread < best[0]:
            best = (spread, ordered, dark_text)
    if best is None:
        return None
    _, ordered, dark_text = best
    return np.stack([char_image(gray, b, dark_text) for b in ordered])
