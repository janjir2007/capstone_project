"""Plate recognition for the API (task 4.3): photo -> plate text, without torch.

Same pipeline as the 3.3 evaluation, but both networks run as ONNX files on
onnxruntime (CPU), so the API image needs neither torch nor ultralytics:

1. Photo bytes (JPEG, PNG, or HEIC/HEIF = iPhone default, via pillow-heif, task 4.4)
   -> upright RGB (EXIF orientation applied, as phones save it).
2. Detector yolo26n (D-028), exported by ``src.cv.export_onnx``: most confident
   box with confidence >= 0.25 (task 3.2 operating threshold), plus the same 5 %
   margin as the 3.3 crops (``src.cv.ocr_data.padded_crop``).
3. ``char_segment.segment`` -> 7 character images (same code as 3.3).
4. Character CNN (recognizer B, chosen in docs/cv_ocr_results.md): softmax +
   position rule (slots 1-4 digits, 5-7 letters); confidence = product of the
   7 chosen probabilities (same as ``char_cnn.predict_chars``).
5. ``src.common.plates.read_plate`` -> normalized plate + needs_manual (D-044),
   at the auto-fill threshold stored WITH the served CNN in
   ``plate_ocr/char_cnn_version.json`` (Task 3.6b): a threshold is chosen on
   val for one model, so it must travel with that model's file.

The detector's ONNX output is (1, 5, N): box centre x, centre y, width, height
(pixels of the 640x640 letterboxed input) and the plate score. Only the single
best box is needed, and the best box always survives NMS, so no NMS is run.
"""

from __future__ import annotations

import hashlib
import io
import json
import time
from dataclasses import dataclass
from pathlib import Path

import cv2
import numpy as np
import onnxruntime as ort
from PIL import Image, ImageOps
from pillow_heif import register_heif_opener

register_heif_opener()  # lets PIL's Image.open read HEIC/HEIF (iPhone photos)

from src.common.plates import DEFAULT_CONFIDENCE_THRESHOLD, DIGIT_COUNT, PlateReading, read_plate
from src.cv.char_segment import segment
from src.cv.ocr_data import DET_CONF, padded_crop

IMGSZ = 640  # detector input size (task 3.2 training/evaluation size)
LETTERBOX_COLOR = 114  # grey padding, as Ultralytics uses
DETECTOR_FILE = "plate_yolo/yolo26n.onnx"
RECOGNIZER_FILE = "plate_ocr/char_cnn.onnx"
VERSION_FILE = "plate_ocr/char_cnn_version.json"  # which CNN is served + its auto-fill threshold
CLASSES_KEY = "classes"  # ONNX metadata key holding the CNN's class list (written by export_onnx)


@dataclass(frozen=True)
class Detection:
    """Best plate box in pixels of the upright photo."""

    xyxy: tuple[float, float, float, float]
    confidence: float


@dataclass(frozen=True)
class Recognition:
    """Everything POST /plates/recognize returns (plus timings for the handoff)."""

    reading: PlateReading
    detection: Detection | None
    ms_detect: float
    ms_read: float


def load_upright_rgb(data: bytes) -> np.ndarray:
    """Image file bytes -> RGB array, EXIF rotation applied. Raises ValueError if not an image."""
    try:
        with Image.open(io.BytesIO(data)) as img:
            return np.asarray(ImageOps.exif_transpose(img).convert("RGB"))
    except (OSError, Image.DecompressionBombError) as exc:  # PIL raises OSError subclasses for bad files
        raise ValueError("file is not a readable image") from exc


def letterbox(rgb: np.ndarray, size: int = IMGSZ) -> tuple[np.ndarray, float, tuple[float, float]]:
    """Resize keeping aspect ratio and pad to size x size (as Ultralytics LetterBox, center=True).

    Returns the padded image, the scale factor and the (left, top) padding, so a
    box can be mapped back to the original photo.
    """
    h, w = rgb.shape[:2]
    scale = min(size / h, size / w)
    new_w, new_h = round(w * scale), round(h * scale)
    resized = cv2.resize(rgb, (new_w, new_h), interpolation=cv2.INTER_LINEAR) if (new_w, new_h) != (w, h) else rgb
    dw, dh = (size - new_w) / 2, (size - new_h) / 2
    top, bottom = round(dh - 0.1), round(dh + 0.1)
    left, right = round(dw - 0.1), round(dw + 0.1)
    padded = cv2.copyMakeBorder(resized, top, bottom, left, right, cv2.BORDER_CONSTANT,
                                value=(LETTERBOX_COLOR,) * 3)
    return padded, scale, (left, top)


def best_box(output: np.ndarray, scale: float, pad: tuple[float, float], shape: tuple[int, int],
             conf: float = DET_CONF) -> Detection | None:
    """Detector output (1, 5, N) -> most confident box in photo pixels, or None below ``conf``."""
    rows = output[0]  # (5, N)
    i = int(np.argmax(rows[4]))
    score = float(rows[4, i])
    if score < conf:
        return None
    cx, cy, bw, bh = (float(v) for v in rows[:4, i])
    h, w = float(shape[0]), float(shape[1])
    x1 = min(max((cx - bw / 2 - pad[0]) / scale, 0.0), w)
    y1 = min(max((cy - bh / 2 - pad[1]) / scale, 0.0), h)
    x2 = min(max((cx + bw / 2 - pad[0]) / scale, 0.0), w)
    y2 = min(max((cy + bh / 2 - pad[1]) / scale, 0.0), h)
    return Detection((x1, y1, x2, y2), score)


def _session(path: Path) -> ort.InferenceSession:
    """CPU-only onnxruntime session (the cloud host has no GPU)."""
    if not path.exists():
        raise FileNotFoundError(f"{path} not found — run `python -m src.cv.export_onnx`")
    return ort.InferenceSession(str(path), providers=["CPUExecutionProvider"])


class OnnxDetector:
    """yolo26n plate detector on onnxruntime."""

    def __init__(self, path: Path) -> None:
        self.session = _session(path)
        self.input_name = self.session.get_inputs()[0].name

    def detect(self, rgb: np.ndarray, conf: float = DET_CONF) -> Detection | None:
        """Most confident plate box (>= conf) or None."""
        padded, scale, pad = letterbox(rgb)
        blob = np.ascontiguousarray(padded.transpose(2, 0, 1)[None], dtype=np.float32) / 255.0
        output = self.session.run(None, {self.input_name: blob})[0]
        return best_box(output, scale, pad, rgb.shape[:2], conf)


def position_mask(classes: str, slots: int = 7, digit_slots: int = DIGIT_COUNT) -> np.ndarray:
    """(slots, n_classes) additive mask: -inf for letters in digit slots and digits in letter slots."""
    is_digit = np.array([c.isdigit() for c in classes])
    mask = np.zeros((slots, len(classes)), dtype=np.float32)
    mask[:digit_slots, ~is_digit] = -np.inf
    mask[digit_slots:, is_digit] = -np.inf
    return mask


def softmax(logits: np.ndarray) -> np.ndarray:
    """Row-wise softmax that tolerates -inf entries."""
    z = logits - logits.max(axis=1, keepdims=True)
    e = np.exp(z)
    return e / e.sum(axis=1, keepdims=True)


class OnnxCharCNN:
    """Character classifier (recognizer B) on onnxruntime; the class list comes from the file itself."""

    def __init__(self, path: Path) -> None:
        self.session = _session(path)
        self.input_name = self.session.get_inputs()[0].name
        classes = self.session.get_modelmeta().custom_metadata_map.get(CLASSES_KEY)
        if not classes:
            raise ValueError(f"{path} has no '{CLASSES_KEY}' metadata — re-export with src.cv.export_onnx")
        self.classes = classes
        self.mask = position_mask(classes)

    def predict_chars(self, chars: np.ndarray) -> tuple[str, float]:
        """7 character images (7, 32, 32) in 0-1 -> (text, confidence = product of chosen probabilities)."""
        logits = self.session.run(None, {self.input_name: chars[:, None].astype(np.float32)})[0]
        probs = softmax(logits + self.mask)
        best = probs.argmax(axis=1)
        return "".join(self.classes[i] for i in best), float(np.prod(probs[np.arange(len(best)), best]))


def sha256_8(path: Path) -> str:
    """First 8 hex characters of a file's SHA-256 (same short id as the version file)."""
    return hashlib.sha256(path.read_bytes()).hexdigest()[:8]


def served_threshold(model_dir: Path) -> float:
    """Auto-fill threshold of the served CNN, from ``VERSION_FILE``.

    No version file, or one without a "threshold" key (written before 3.6b)
    -> the D-044 default. With a threshold, "served_sha256_8" must match the
    ONNX file actually in the folder; otherwise the threshold belongs to a
    different model and ValueError is raised (the API then starts without the
    recognizer and logs why, instead of auto-filling with the wrong cut-off).
    """
    path = model_dir / VERSION_FILE
    if not path.exists():
        return DEFAULT_CONFIDENCE_THRESHOLD
    info = json.loads(path.read_text(encoding="utf-8"))
    if "threshold" not in info:
        return DEFAULT_CONFIDENCE_THRESHOLD
    threshold = float(info["threshold"])
    if not 0.0 <= threshold <= 1.0:
        raise ValueError(f"{path}: threshold must be between 0 and 1, got {threshold}")
    actual = sha256_8(model_dir / RECOGNIZER_FILE)
    if info.get("served_sha256_8") != actual:
        raise ValueError(f"{path}: threshold is for model {info.get('served_sha256_8')}, served file is {actual}")
    return threshold


class PlateRecognizer:
    """Detector + segmentation + CNN + read_plate, loaded once at API startup."""

    def __init__(self, model_dir: Path) -> None:
        self.detector = OnnxDetector(model_dir / DETECTOR_FILE)
        self.reader = OnnxCharCNN(model_dir / RECOGNIZER_FILE)
        self.threshold = served_threshold(model_dir)

    def recognize_rgb(self, rgb: np.ndarray) -> Recognition:
        """Upright RGB photo -> Recognition. No plate found -> needs_manual with reason "no_plate"."""
        start = time.perf_counter()
        det = self.detector.detect(rgb)
        ms_detect = (time.perf_counter() - start) * 1000.0
        start = time.perf_counter()
        if det is None:
            reading = PlateReading("", None, 0.0, needs_manual=True, reason="no_plate")
        else:
            try:
                chars = segment(padded_crop(rgb, list(det.xyxy)))
            except ValueError:  # zero-size box at the photo edge
                chars = None
            text, conf = ("", 0.0) if chars is None else self.reader.predict_chars(chars)
            reading = read_plate(text, min(max(conf, 0.0), 1.0), self.threshold)
        return Recognition(reading, det, ms_detect, (time.perf_counter() - start) * 1000.0)

    def recognize_bytes(self, data: bytes) -> Recognition:
        """Image file bytes -> Recognition (ValueError if not an image)."""
        return self.recognize_rgb(load_upright_rgb(data))
