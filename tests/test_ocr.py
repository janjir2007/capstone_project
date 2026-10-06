"""Tests for task 3.3 plate recognition. All plates and images are FAKE (drawn in the test).

No EasyOCR model is loaded (CI would have to download ~100 MB); only its pure
helper ``join_pieces`` is tested.
"""

from pathlib import Path

import cv2
import numpy as np
import pytest
import torch

from src.cv.char_cnn import (
    CLASSES,
    DIGITS,
    CharCNN,
    augment,
    load,
    position_mask,
    predict_chars,
    save,
    set_seed,
)
from src.cv.char_segment import CHAR_SIZE, Blob, keep_consistent, reading_order, segment
from src.cv.ocr_data import labels_by_image, padded_crop
from src.cv.ocr_easyocr import ALLOWLIST, join_pieces
from src.cv.ocr_metrics import (
    Prediction,
    char_accuracy,
    confusion_pairs,
    edit_distance,
    evaluate_predictions,
    mcnemar_exact_p,
    paired_comparison,
    threshold_sweep,
)
from tests.test_plate_letters import fake_task


# ---------------------------------------------------------------- ocr_metrics
def test_edit_distance() -> None:
    assert edit_distance("1234УБА", "1234УБА") == 0
    assert edit_distance("1234УБА", "1234УБ") == 1  # one missing
    assert edit_distance("1234УБА", "1234УБАА") == 1  # one extra
    assert edit_distance("1234УБА", "1239УБА") == 1  # one substituted
    assert edit_distance("", "abc") == 3


def test_char_accuracy_counts_a_dropped_char_as_one_error() -> None:
    assert char_accuracy("1234УБА", "234УБА") == pytest.approx(6 / 7)
    assert char_accuracy("1234УБА", "") == 0.0
    assert char_accuracy("1234УБА", "x" * 20) == 0.0  # floored at 0


def test_confusion_pairs_only_for_same_length() -> None:
    assert confusion_pairs("1234УБА", "1284УБН") == [("3", "8"), ("А", "Н")]
    assert confusion_pairs("1234УБА", "1234УБ") == []


def p(label: str, raw: str, conf: float, ms: float = 1.0) -> Prediction:
    return Prediction(label=label, raw_text=raw, confidence=conf, ms=ms)


def test_evaluate_uses_read_plate_rules() -> None:
    preds = [
        p("1234УВА", "1234 YBA", 0.9),  # Latin Y->У, B->В (not Б) + space -> correct, auto
        p("5678ӨМН", "5678ӨМН", 0.3),  # correct but low confidence -> manual
        p("1111ААА", "1111ААВ", 0.95),  # confident and wrong -> the costly case
        p("2222ВВВ", "", 0.0),  # nothing read -> manual "empty"
    ]
    m = evaluate_predictions(preds, threshold=0.6)
    assert m["plates"] == 4
    assert m["exact_match"] == pytest.approx(0.5)
    assert m["auto_correct"] == 1
    assert m["wrong_auto_fill"] == 1
    assert m["manual"] == 2
    assert m["manual_reasons"] == {"low_confidence": 1, "empty": 1}
    assert m["length_errors"] == 1
    assert m["top_confusions"] == [{"true": "А", "pred": "В", "count": 1}]


def test_evaluate_rejects_empty_list() -> None:
    with pytest.raises(ValueError):
        evaluate_predictions([])


def test_threshold_sweep_manual_rate_never_drops() -> None:
    preds = [p("1234УБА", "1234УБА", c) for c in (0.1, 0.4, 0.7, 0.95)]
    rows = threshold_sweep(preds, [0.0, 0.5, 0.8, 1.0])
    manual = [r["manual_rate"] for r in rows]
    assert manual == sorted(manual)
    assert manual[0] == 0.0 and manual[-1] == 1.0


def test_mcnemar_exact_p() -> None:
    # 3 vs 13 discordant: 2 * (C(16,0)+C(16,1)+C(16,2)+C(16,3)) / 2**16 = 2 * 697 / 65536
    assert mcnemar_exact_p(3, 13) == pytest.approx(2 * 697 / 65536)
    assert mcnemar_exact_p(5, 5) == 1.0
    assert mcnemar_exact_p(0, 0) == 1.0


def test_paired_comparison() -> None:
    a = [p("1234УБА", "1234УБА", 0.1), p("5678ӨМН", "5678ӨМ", 0.9)]
    b = [p("1234УБА", "1234УБН", 0.9), p("5678ӨМН", "5678ӨМН", 0.2)]
    out = paired_comparison(a, b)  # confidence is ignored: only "is the text right"
    assert (out["both_right"], out["a_only"], out["b_only"], out["both_wrong"]) == (0, 1, 1, 0)
    with pytest.raises(ValueError):
        paired_comparison(a, b[::-1])


# ---------------------------------------------------------------- EasyOCR helper
def box(x1: float, y1: float, x2: float, y2: float) -> list[list[float]]:
    return [[x1, y1], [x2, y1], [x2, y2], [x1, y2]]


def test_join_pieces_one_row_left_to_right() -> None:
    text, conf = join_pieces([(box(60, 0, 100, 20), "УБА", 0.8), (box(0, 1, 55, 21), "1234", 0.5)])
    assert text == "1234УБА"
    assert conf == pytest.approx(0.4)


def test_join_pieces_two_rows_top_first() -> None:
    text, _ = join_pieces([(box(5, 40, 60, 70), "УБА", 0.9), (box(0, 0, 70, 30), "1234", 0.9)])
    assert text == "1234УБА"


def test_join_pieces_empty() -> None:
    assert join_pieces([]) == ("", 0.0)


def test_allowlist_has_mongolian_letters() -> None:
    assert "Ө" in ALLOWLIST and "Ү" in ALLOWLIST and "0" in ALLOWLIST


# ---------------------------------------------------------------- segmentation
def draw_plate(rows: list[str], dark_text: bool = True) -> np.ndarray:
    """Fake plate: Hershey font text (digits/Latin are enough: segmentation ignores the class)."""
    height = 70 if len(rows) == 1 else 130
    bg, fg = (255, 0) if dark_text else (0, 255)
    img = np.full((height, 330), bg, np.uint8)
    for i, text in enumerate(rows):
        cv2.putText(img, "  ".join(text), (12, 52 + 60 * i), cv2.FONT_HERSHEY_SIMPLEX, 1.4, fg, 4)
    return cv2.cvtColor(img, cv2.COLOR_GRAY2RGB)


def test_segment_one_row_plate() -> None:
    chars = segment(draw_plate(["1234ABK"]))
    assert chars is not None
    assert chars.shape == (7, CHAR_SIZE, CHAR_SIZE)
    assert 0.0 <= chars.min() and chars.max() <= 1.0


def test_segment_two_row_plate() -> None:
    assert segment(draw_plate(["1234", "ABK"])) is not None


def test_segment_light_text_on_dark_is_inverted_to_dark_text() -> None:
    chars = segment(draw_plate(["1234ABK"], dark_text=False))
    assert chars is not None
    assert chars[:, 0, 0].mean() > 0.5  # corners = background = light


def test_segment_blank_plate_fails() -> None:
    assert segment(np.full((60, 300, 3), 255, np.uint8)) is None


def test_keep_consistent_drops_odd_heights() -> None:
    blobs = [Blob(i * 10, 0, 8, 40) for i in range(7)] + [Blob(80, 0, 8, 12), Blob(90, 0, 8, 90)]
    kept = keep_consistent(blobs)
    assert len(kept) == 7 and all(b.h == 40 for b in kept)


def test_reading_order_two_rows_needs_4_plus_3() -> None:
    top = [Blob(x, 0, 8, 30) for x in (40, 0, 20, 60)]
    bottom = [Blob(x, 50, 8, 30) for x in (30, 10, 50)]
    ordered = reading_order(top + bottom)
    assert ordered is not None
    assert [b.y for b in ordered] == [0] * 4 + [50] * 3
    assert [b.x for b in ordered] == [0, 20, 40, 60, 10, 30, 50]
    assert reading_order([Blob(x, 0, 8, 30) for x in (0, 20, 40)] + [Blob(x, 50, 8, 30) for x in (0, 20, 40, 60)]) is None
    assert reading_order(top) is None  # not 7


# ---------------------------------------------------------------- CNN
def test_classes() -> None:
    assert CLASSES.startswith(DIGITS) and len(CLASSES) == 31 and len(set(CLASSES)) == 31


def test_position_mask_digits_then_letters() -> None:
    mask = position_mask()
    assert mask.shape == (7, len(CLASSES))
    assert torch.isinf(mask[:4, 10:]).all() and (mask[:4, :10] == 0).all()
    assert torch.isinf(mask[4:, :10]).all() and (mask[4:, 10:] == 0).all()


def test_cnn_forward_and_prediction_obey_positions() -> None:
    set_seed()
    model = CharCNN().eval()
    chars = np.random.default_rng(0).random((7, CHAR_SIZE, CHAR_SIZE), dtype=np.float32)
    assert model(torch.from_numpy(chars).unsqueeze(1)).shape == (7, len(CLASSES))
    text, conf = predict_chars(model, chars)
    assert len(text) == 7
    assert text[:4].isdigit() and not any(c in DIGITS for c in text[4:])
    assert 0.0 < conf <= 1.0


def test_save_load_roundtrip_and_class_check(tmp_path: Path) -> None:
    set_seed()
    model = CharCNN().eval()
    path = tmp_path / "cnn.pt"
    save(model, path)
    x = torch.rand(2, 1, CHAR_SIZE, CHAR_SIZE)
    assert torch.allclose(load(path)(x), model(x))
    torch.save({"state_dict": model.state_dict(), "classes": "0123"}, path)
    with pytest.raises(ValueError):
        load(path)


def test_augment_keeps_shape_and_range() -> None:
    img = np.full((CHAR_SIZE, CHAR_SIZE), 0.5, np.float32)
    out = augment(img, np.random.default_rng(1))
    assert out.shape == img.shape and out.dtype == np.float32
    assert 0.0 <= out.min() and out.max() <= 1.0


# ---------------------------------------------------------------- ocr_data
def test_padded_crop_clips_to_image() -> None:
    image = np.zeros((100, 200, 3), np.uint8)
    assert padded_crop(image, [10, 10, 50, 30], pad=0.0).shape == (20, 40, 3)
    assert padded_crop(image, [0, 0, 200, 100], pad=0.1).shape == (100, 200, 3)
    with pytest.raises(ValueError):
        padded_crop(image, [50, 50, 50, 60])


def test_labels_by_image_normalizes_and_skips_empty() -> None:
    tasks = [fake_task(1, [("plate", "1234 yba")]), fake_task(2, [("plate", None)]),
             fake_task(3, [("fleet_no", "HT-27")])]
    assert labels_by_image(tasks) == {"photos/synth_1.jpg": "1234УВА"}
