"""Tests for src/cv/ocr_tune.py (Task 3.6b). All plates and images are FAKE."""

from pathlib import Path

import numpy as np
import pytest

from src.cv.ocr_metrics import Prediction
from src.cv.ocr_tune import (
    MD_MARKER,
    choose_threshold,
    config_rank,
    field_augment,
    promote_v3,
    target_count,
    write_section,
)

RIGHT, WRONG = "1234УБА", "1234УБВ"


def pred(read: str, conf: float, label: str = RIGHT) -> Prediction:
    return Prediction(label=label, raw_text=read, confidence=conf, ms=1.0)


def fake_crop() -> np.ndarray:
    rng = np.random.default_rng(0)
    return rng.integers(0, 256, size=(40, 120, 3), dtype=np.uint8)


def test_field_augment_strength_zero_is_identity() -> None:
    crop = fake_crop()
    out = field_augment(crop, np.random.default_rng(1), 0.0)
    assert np.array_equal(out, crop)
    assert out is not crop  # a copy, so callers can change it safely


def test_field_augment_keeps_shape_dtype_and_is_seeded() -> None:
    crop = fake_crop()
    a = field_augment(crop, np.random.default_rng(7), 1.0)
    b = field_augment(crop, np.random.default_rng(7), 1.0)
    assert a.shape == crop.shape and a.dtype == np.uint8
    assert np.array_equal(a, b)  # same seed -> same picture
    assert not np.array_equal(a, crop)


def test_choose_threshold_takes_most_correct_with_zero_wrong() -> None:
    preds = [pred(RIGHT, 0.9), pred(RIGHT, 0.5), pred(WRONG, 0.45), pred(RIGHT, 0.35)]
    choice = choose_threshold(preds, (0.3, 0.4, 0.5, 0.6))
    # 0.3 and 0.4 auto-fill the wrong 0.45 plate; 0.5 gives 2 correct, 0 wrong; 0.6 gives only 1
    assert choice == {"threshold": 0.5, "auto_correct": 2, "wrong": 0, "safe": True}


def test_choose_threshold_ties_go_to_higher_threshold() -> None:
    preds = [pred(RIGHT, 0.9), pred(WRONG, 0.2)]
    assert choose_threshold(preds, (0.3, 0.5, 0.7))["threshold"] == 0.7


def test_choose_threshold_unsafe_when_every_threshold_has_a_wrong() -> None:
    choice = choose_threshold([pred(WRONG, 0.99)], (0.3, 0.6))
    assert choice["safe"] is False and choice["threshold"] == 0.6


def test_config_rank_prefers_correct_then_higher_threshold_then_fewer_epochs() -> None:
    base = {"val_safe": True, "val_auto_correct": 10, "val_threshold": 0.6, "val_exact": 20,
            "strength": 0.5, "epochs": 60}
    assert config_rank({**base, "val_auto_correct": 11, "val_threshold": 0.3}) > config_rank(base)
    assert config_rank({**base, "val_threshold": 0.7, "epochs": 90}) > config_rank(base)  # threshold before epochs
    assert config_rank({**base, "epochs": 40, "val_exact": 10}) > config_rank(base)  # epochs before exact
    assert config_rank({**base, "val_exact": 21}) > config_rank(base)
    assert config_rank({**base, "strength": 0.0}) > config_rank(base)
    assert config_rank({**base, "val_safe": False, "val_auto_correct": 30}) < config_rank(base)


def test_target_count_is_two_thirds_rounded_up() -> None:
    assert target_count(27) == 18
    assert target_count(28) == 19
    assert target_count(3) == 2


@pytest.mark.parametrize(("correct", "wrong", "ok"), [(18, 0, True), (17, 0, False), (20, 1, False)])
def test_promote_v3_rule(correct: int, wrong: int, ok: bool) -> None:
    passed, checks = promote_v3({"plates": 27, "auto_correct": correct, "wrong_auto_fill": wrong})
    assert passed is ok
    assert len(checks) == 2


def test_write_section_replaces_only_its_own_section(tmp_path: Path) -> None:
    md = tmp_path / "r.md"
    md.write_text("# Results\n\n## Task 3.6 — old\n\nkeep me\n", encoding="utf-8")
    write_section(md, f"{MD_MARKER} — first\n")
    write_section(md, f"{MD_MARKER} — second\n")
    text = md.read_text(encoding="utf-8")
    assert "keep me" in text and "second" in text and "first" not in text


def test_same_weights_detects_identical_and_different_models() -> None:
    import torch

    from src.cv.char_cnn import CharCNN, set_seed
    from src.cv.ocr_tune import same_weights

    set_seed(1)
    a = CharCNN()
    set_seed(1)
    b = CharCNN()
    assert same_weights(a, b)
    with torch.no_grad():
        b.head[-1].bias[0] += 1.0
    assert not same_weights(a, b)
