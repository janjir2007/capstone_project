"""Export the plate detector and the character CNN to ONNX for the API (task 4.3).

Run once on the development Mac (needs torch + ultralytics + onnx, which the
API image does NOT have):

    python -m src.cv.export_onnx

Writes (git-ignored, D-015):
- models/plate_yolo/yolo26n.onnx   from models/plate_yolo/yolo26n/weights/best.pt
- models/plate_ocr/char_cnn.onnx   from models/plate_ocr/char_cnn.pt, class list in its metadata

Then checks that each ONNX file gives the same answer as the PyTorch model on
synthetic inputs (no photos) and prints the differences and file sizes.
"""

from __future__ import annotations

import argparse
import json
import shutil
import tempfile
from pathlib import Path

import numpy as np

from src.cv.plate_reader import CLASSES_KEY, DETECTOR_FILE, IMGSZ, RECOGNIZER_FILE, OnnxCharCNN, OnnxDetector

DEFAULT_DET_WEIGHTS = Path("models/plate_yolo/yolo26n/weights/best.pt")
DEFAULT_CNN_WEIGHTS = Path("models/plate_ocr/char_cnn.pt")
OPSET = 18  # what ultralytics 8.4.170 picks for the detector; same for the CNN
SEED = 42


def export_detector(weights: Path, out: Path) -> Path:
    """Ultralytics export (static 640x640 input, no simplify: needs only the onnx package)."""
    from ultralytics import YOLO

    with tempfile.TemporaryDirectory() as tmp:  # ultralytics writes next to the .pt; keep models/ tidy
        copy = Path(tmp) / weights.name
        shutil.copy(weights, copy)
        exported = Path(YOLO(str(copy)).export(format="onnx", imgsz=IMGSZ, simplify=False, dynamic=False,
                                               opset=OPSET, device="cpu"))
        out.parent.mkdir(parents=True, exist_ok=True)
        shutil.move(exported, out)
    return out


def export_char_cnn(weights: Path, out: Path) -> Path:
    """torch.onnx.export of CharCNN with a variable batch size; class list stored as metadata."""
    import onnx
    import torch

    from src.cv.char_cnn import CLASSES, load

    model = load(weights)
    dummy = torch.zeros(7, 1, 32, 32)
    out.parent.mkdir(parents=True, exist_ok=True)
    torch.onnx.export(model, dummy, str(out), input_names=["chars"], output_names=["logits"],
                      dynamic_axes={"chars": {0: "n"}, "logits": {0: "n"}}, opset_version=OPSET, dynamo=False)
    proto = onnx.load(str(out))
    proto.metadata_props.add(key=CLASSES_KEY, value=CLASSES)
    onnx.save(proto, str(out))
    return out


def check_char_cnn(weights: Path, onnx_path: Path, n_plates: int = 50) -> dict[str, float]:
    """Same text and ~same confidence as PyTorch on random character images."""
    import torch

    from src.cv.char_cnn import load, predict_chars

    model, onnx_model = load(weights), OnnxCharCNN(onnx_path)
    rng = np.random.default_rng(SEED)
    same_text, max_conf_diff = 0, 0.0
    for _ in range(n_plates):
        chars = rng.random((7, 32, 32), dtype=np.float32)
        with torch.no_grad():
            t_text, t_conf = predict_chars(model, chars)
        o_text, o_conf = onnx_model.predict_chars(chars)
        same_text += t_text == o_text
        max_conf_diff = max(max_conf_diff, abs(t_conf - o_conf))
    return {"plates": n_plates, "same_text": same_text, "max_confidence_diff": max_conf_diff}


def synthetic_photo() -> np.ndarray:
    """Grey noise with a white plate-like rectangle and dark text (no real photo)."""
    import cv2

    rng = np.random.default_rng(SEED)
    img = rng.normal(110, 25, (720, 1280, 3)).clip(0, 255).astype(np.uint8)
    cv2.rectangle(img, (520, 420), (760, 480), (240, 240, 240), -1)
    cv2.rectangle(img, (520, 420), (760, 480), (20, 20, 20), 3)
    cv2.putText(img, "1234 ABC", (532, 466), cv2.FONT_HERSHEY_SIMPLEX, 1.3, (10, 10, 10), 3)
    return img


def check_detector(weights: Path, onnx_path: Path) -> dict[str, float | None]:
    """Our ONNX decoding vs Ultralytics .pt on one synthetic photo: IoU of the best boxes."""
    from ultralytics import YOLO

    from src.cv.det_metrics import iou_matrix

    rgb = synthetic_photo()
    ours = OnnxDetector(onnx_path).detect(rgb, conf=0.01)
    boxes = YOLO(str(weights)).predict(rgb[..., ::-1], conf=0.01, imgsz=IMGSZ, device="cpu", verbose=False)[0].boxes
    if ours is None or len(boxes) == 0:
        return {"iou": None, "conf_onnx": None if ours is None else ours.confidence, "conf_pt": None}
    i = int(boxes.conf.argmax())
    return {"iou": float(iou_matrix(np.array(ours.xyxy), boxes.xyxy[i].numpy())[0, 0]),
            "conf_onnx": ours.confidence, "conf_pt": float(boxes.conf[i])}


def main(argv: list[str] | None = None) -> int:
    """CLI: export both models, check them, print sizes (numbers only)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--model-dir", type=Path, default=Path("models"))
    parser.add_argument("--det-weights", type=Path, default=DEFAULT_DET_WEIGHTS)
    parser.add_argument("--cnn-weights", type=Path, default=DEFAULT_CNN_WEIGHTS)
    args = parser.parse_args(argv)

    det = export_detector(args.det_weights, args.model_dir / DETECTOR_FILE)
    cnn = export_char_cnn(args.cnn_weights, args.model_dir / RECOGNIZER_FILE)
    print(json.dumps({
        "detector": str(det), "detector_mb": round(det.stat().st_size / 1e6, 2),
        "recognizer": str(cnn), "recognizer_mb": round(cnn.stat().st_size / 1e6, 2),
        "check_detector_synthetic": check_detector(args.det_weights, det),
        "check_char_cnn_random": check_char_cnn(args.cnn_weights, cnn),
    }, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
