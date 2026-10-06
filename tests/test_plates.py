"""Plate normalization tests (src/common/plates.py, task 4.2 minimal rule)."""

import pytest

from src.common.plates import normalize_plate


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234 УБА", "1234УБА"),
        ("1234уба", "1234УБА"),        # lower case Cyrillic
        ("  1234  у б а ", "1234УБА"),  # spaces anywhere
        ("3456 өма", "3456ӨМА"),   # non-breaking space; Ө (Mongolian letter) upper-cased
        ("1234\tүха", "1234ҮХА"),       # tab; Ү upper-cased
        ("1234УБА", "1234УБА"),         # already normalized -> unchanged
    ],
)
def test_normalize_plate(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected


@pytest.mark.parametrize("raw", ["", "   ", "\t\n"])
def test_blank_plate_rejected(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_plate(raw)
