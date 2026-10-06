"""Detection metrics for one class (``plate``) - Task 3.2.

One evaluator for every model (pretrained oim baseline AND our fine-tuned
YOLO), so the comparison table is computed by the same code on the same
boxes. Ultralytics' own ``model.val()`` is only used as a cross-check.

Definitions (all boxes are pixel ``x1, y1, x2, y2``):
- IoU: intersection area / union area of two boxes.
- Matching: predictions are processed from highest to lowest confidence;
  each one takes the unmatched ground-truth box it overlaps most, if that
  IoU >= the threshold (COCO-style greedy matching).
- AP: area under the precision-recall curve with COCO 101-point
  interpolation. mAP50 = AP at IoU 0.5; mAP50-95 = mean AP over IoU
  0.50, 0.55, ..., 0.95. With one class, "mean over classes" is that class.
- Precision / recall / mean IoU: at one operating confidence (default 0.25)
  and IoU 0.5, i.e. what the app would actually use.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

IOU_THRESHOLDS = np.round(np.arange(0.5, 0.96, 0.05), 2)  # 0.50 ... 0.95 (10 values)
RECALL_POINTS = np.linspace(0.0, 1.0, 101)  # COCO 101-point interpolation
DEFAULT_CONF = 0.25


@dataclass
class ImageEval:
    """Ground truth and predictions for one image."""

    gt: np.ndarray  # (N, 4) x1, y1, x2, y2
    boxes: np.ndarray = field(default_factory=lambda: np.zeros((0, 4)))  # (M, 4) predictions
    conf: np.ndarray = field(default_factory=lambda: np.zeros(0))  # (M,) confidences

    def __post_init__(self) -> None:
        self.gt = np.asarray(self.gt, dtype=float).reshape(-1, 4)
        self.boxes = np.asarray(self.boxes, dtype=float).reshape(-1, 4)
        self.conf = np.asarray(self.conf, dtype=float).reshape(-1)
        if len(self.boxes) != len(self.conf):
            raise ValueError("boxes and conf must have the same length")


def iou_matrix(a: np.ndarray, b: np.ndarray) -> np.ndarray:
    """IoU of every box in ``a`` (N, 4) with every box in ``b`` (M, 4) -> (N, M)."""
    a = np.asarray(a, dtype=float).reshape(-1, 4)
    b = np.asarray(b, dtype=float).reshape(-1, 4)
    ix1 = np.maximum(a[:, None, 0], b[None, :, 0])
    iy1 = np.maximum(a[:, None, 1], b[None, :, 1])
    ix2 = np.minimum(a[:, None, 2], b[None, :, 2])
    iy2 = np.minimum(a[:, None, 3], b[None, :, 3])
    inter = np.clip(ix2 - ix1, 0, None) * np.clip(iy2 - iy1, 0, None)
    area_a = (a[:, 2] - a[:, 0]) * (a[:, 3] - a[:, 1])
    area_b = (b[:, 2] - b[:, 0]) * (b[:, 3] - b[:, 1])
    union = area_a[:, None] + area_b[None, :] - inter
    return np.divide(inter, union, out=np.zeros_like(inter), where=union > 0)


def match_image(img: ImageEval, iou_thr: float) -> tuple[np.ndarray, np.ndarray]:
    """Greedy match of one image's predictions to its ground truth.

    Returns ``(tp, iou)`` aligned with the predictions in their ORIGINAL order:
    ``tp[i]`` is True if prediction i matched a ground-truth box, ``iou[i]`` is
    the IoU of that match (0 for false positives).
    """
    tp = np.zeros(len(img.boxes), dtype=bool)
    matched_iou = np.zeros(len(img.boxes))
    if len(img.boxes) == 0 or len(img.gt) == 0:
        return tp, matched_iou
    ious = iou_matrix(img.boxes, img.gt)
    taken = np.zeros(len(img.gt), dtype=bool)
    for i in np.argsort(-img.conf, kind="stable"):
        candidates = np.where(taken, -1.0, ious[i])
        j = int(np.argmax(candidates))
        if candidates[j] >= iou_thr:
            taken[j] = True
            tp[i] = True
            matched_iou[i] = ious[i, j]
    return tp, matched_iou


def pr_curve(images: list[ImageEval], iou_thr: float) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Precision and recall after each prediction, all images pooled, sorted by confidence.

    Returns ``(recall, precision, conf)``; empty arrays if there are no predictions.
    """
    n_gt = sum(len(img.gt) for img in images)
    tps, confs = [], []
    for img in images:
        tp, _ = match_image(img, iou_thr)
        tps.append(tp)
        confs.append(img.conf)
    tp_all = np.concatenate(tps) if tps else np.zeros(0, dtype=bool)
    conf_all = np.concatenate(confs) if confs else np.zeros(0)
    order = np.argsort(-conf_all, kind="stable")
    tp_sorted = tp_all[order]
    cum_tp = np.cumsum(tp_sorted)
    cum_fp = np.cumsum(~tp_sorted)
    recall = cum_tp / n_gt if n_gt else np.zeros_like(cum_tp, dtype=float)
    precision = cum_tp / np.maximum(cum_tp + cum_fp, 1)
    return recall, precision, conf_all[order]


def average_precision(recall: np.ndarray, precision: np.ndarray) -> float:
    """AP with COCO 101-point interpolation.

    The precision "envelope" (best precision at this recall or higher) is
    sampled at recall 0.00, 0.01, ..., 1.00; recall levels never reached count 0.
    """
    if len(recall) == 0:
        return 0.0
    envelope = np.maximum.accumulate(precision[::-1])[::-1]
    idx = np.searchsorted(recall, RECALL_POINTS, side="left")
    sampled = np.array([envelope[i] if i < len(envelope) else 0.0 for i in idx])
    return float(sampled.mean())


def operating_point(images: list[ImageEval], conf_thr: float = DEFAULT_CONF, iou_thr: float = 0.5) -> dict[str, float]:
    """Precision, recall and IoU at one confidence threshold (the app's setting).

    ``mean_iou_matched``: average IoU of correct detections (localization quality).
    ``mean_best_iou``: for every ground-truth box, its best IoU with any kept
    prediction (0 if nothing overlaps), so missed plates pull it down.
    """
    tp_n = fp_n = 0
    matched: list[float] = []
    best: list[float] = []
    for img in images:
        keep = img.conf >= conf_thr
        kept = ImageEval(img.gt, img.boxes[keep], img.conf[keep])
        tp, iou = match_image(kept, iou_thr)
        tp_n += int(tp.sum())
        fp_n += int((~tp).sum())
        matched.extend(iou[tp].tolist())
        if len(kept.gt):
            ious = iou_matrix(kept.gt, kept.boxes)
            best.extend(ious.max(axis=1).tolist() if ious.size else [0.0] * len(kept.gt))
    n_gt = sum(len(img.gt) for img in images)
    return {
        "conf_threshold": conf_thr,
        "precision": tp_n / (tp_n + fp_n) if tp_n + fp_n else 0.0,
        "recall": tp_n / n_gt if n_gt else 0.0,
        "mean_iou_matched": float(np.mean(matched)) if matched else 0.0,
        "mean_best_iou": float(np.mean(best)) if best else 0.0,
        "true_positives": tp_n,
        "false_positives": fp_n,
        "missed": n_gt - tp_n,
    }


def evaluate(images: list[ImageEval], conf_thr: float = DEFAULT_CONF) -> dict[str, float]:
    """All test metrics for one model: mAP50, mAP50-95 and the operating point."""
    aps = [average_precision(*pr_curve(images, float(t))[:2]) for t in IOU_THRESHOLDS]
    return {
        "images": len(images),
        "gt_boxes": sum(len(img.gt) for img in images),
        "map50": aps[0],
        "map50_95": float(np.mean(aps)),
        **operating_point(images, conf_thr),
    }
