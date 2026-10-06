"""Tests for src/cv/det_metrics.py (Task 3.2). All boxes are made up; values checked by hand."""

import numpy as np
import pytest

from src.cv.det_metrics import (
    ImageEval,
    average_precision,
    evaluate,
    iou_matrix,
    match_image,
    operating_point,
    pr_curve,
)

GT = [0, 0, 10, 10]  # area 100


def test_iou_identical_disjoint_and_half_overlap() -> None:
    ious = iou_matrix([GT], [[0, 0, 10, 10], [20, 20, 30, 30], [5, 0, 15, 10]])
    # half overlap: inter 50, union 150 -> 1/3
    assert ious.shape == (1, 3)
    assert ious[0].tolist() == pytest.approx([1.0, 0.0, 1 / 3])


def test_iou_handles_empty_inputs() -> None:
    assert iou_matrix(np.zeros((0, 4)), [GT]).shape == (0, 1)


def test_match_highest_confidence_wins_the_ground_truth() -> None:
    img = ImageEval([GT], [[0, 0, 10, 10], [0, 0, 10, 9]], [0.3, 0.9])
    tp, iou = match_image(img, 0.5)
    # the 0.9 box (IoU 0.9) takes the only ground truth; the 0.3 duplicate is a false positive
    assert tp.tolist() == [False, True]
    assert iou.tolist() == pytest.approx([0.0, 0.9])


def test_match_respects_iou_threshold() -> None:
    img = ImageEval([GT], [[5, 0, 15, 10]], [0.9])  # IoU 1/3
    assert match_image(img, 0.5)[0].tolist() == [False]
    assert match_image(img, 0.3)[0].tolist() == [True]


def test_perfect_detector_has_ap_one() -> None:
    images = [ImageEval([GT], [GT], [0.9]), ImageEval([[5, 5, 20, 20]], [[5, 5, 20, 20]], [0.8])]
    result = evaluate(images)
    assert result["map50"] == pytest.approx(1.0)
    assert result["map50_95"] == pytest.approx(1.0)
    assert result["precision"] == 1.0 and result["recall"] == 1.0
    assert result["mean_iou_matched"] == pytest.approx(1.0)


def test_ap_with_one_miss_out_of_two() -> None:
    # Only one of two plates is found -> recall stops at 0.5.
    # 101-point AP: precision 1 at recall 0.00..0.50 (51 points), 0 after -> 51/101.
    images = [ImageEval([GT], [GT], [0.9]), ImageEval([[50, 50, 60, 60]])]
    recall, precision, _ = pr_curve(images, 0.5)
    assert average_precision(recall, precision) == pytest.approx(51 / 101)


def test_ap_ranked_false_positive_first() -> None:
    # Ranking: FP (0.9), TP (0.8). Recall 1.0 reached at precision 0.5 -> envelope 0.5 everywhere.
    images = [ImageEval([GT], [[0, 0, 10, 10], [40, 40, 50, 50]], [0.8, 0.9])]
    recall, precision, _ = pr_curve(images, 0.5)
    assert average_precision(recall, precision) == pytest.approx(0.5)


def test_no_predictions_gives_zero() -> None:
    result = evaluate([ImageEval([GT])])
    assert result["map50"] == 0.0 and result["recall"] == 0.0 and result["missed"] == 1


def test_operating_point_ignores_boxes_below_threshold() -> None:
    images = [ImageEval([GT], [[0, 0, 10, 10], [40, 40, 50, 50]], [0.9, 0.1])]
    op = operating_point(images, conf_thr=0.25)
    assert op["precision"] == 1.0 and op["false_positives"] == 0
    op_low = operating_point(images, conf_thr=0.05)
    assert op_low["precision"] == 0.5 and op_low["false_positives"] == 1


def test_mean_best_iou_counts_misses_as_zero() -> None:
    images = [ImageEval([GT], [GT], [0.9]), ImageEval([[50, 50, 60, 60]])]
    op = operating_point(images)
    assert op["mean_iou_matched"] == pytest.approx(1.0)
    assert op["mean_best_iou"] == pytest.approx(0.5)


def test_mismatched_lengths_raise() -> None:
    with pytest.raises(ValueError):
        ImageEval([GT], [GT, GT], [0.9])
