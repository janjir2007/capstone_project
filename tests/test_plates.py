"""Plate normalization + format check + confidence fallback (src/common/plates.py, tasks 4.2, 3.4).

All plates here are made up.
"""

import pytest

from src.common.plates import (
    DEFAULT_CONFIDENCE_THRESHOLD,
    LATIN_TO_CYRILLIC,
    MONGOLIAN_CYRILLIC_CAPITALS,
    PLATE_LETTERS,
    fix_by_position,
    is_valid_plate,
    normalize_plate,
    read_plate,
)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234 УБА", "1234УБА"),
        ("1234уба", "1234УБА"),        # lower case Cyrillic
        ("  1234  у б а ", "1234УБА"),  # spaces anywhere
        ("3456 өма", "3456ӨМА"),   # non-breaking space; Ө (Mongolian letter) upper-cased
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


# --- Task 3.4: look-alike map


def test_lookalike_map_is_latin_to_cyrillic() -> None:
    assert len(LATIN_TO_CYRILLIC) == 13  # 12 look-alikes from the brief + U (PM decision)
    assert all(k.isascii() and k.isupper() for k in LATIN_TO_CYRILLIC)
    assert set(LATIN_TO_CYRILLIC.values()) <= MONGOLIAN_CYRILLIC_CAPITALS


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234 ABE", "1234АВЕ"),
        ("1234 KMH", "1234КМН"),
        ("1234 OPC", "1234ОРС"),
        ("1234 TXY", "1234ТХУ"),
        ("1234 txy", "1234ТХУ"),   # lower-case Latin: upper() first, then map
        ("1234 AБ" + "C", "1234АБС"),  # Latin and Cyrillic mixed
    ],
)
def test_latin_lookalikes_become_cyrillic(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected


def test_typed_and_ocr_plate_get_same_key() -> None:
    # Same picture, different Unicode: Latin "TEM" vs Cyrillic "ТЕМ".
    assert normalize_plate("5678 TEM") == normalize_plate("5678 ТЕМ")


def test_u_becomes_cyrillic_u() -> None:
    # PM decision: U is how У is typed on a Latin keyboard.
    assert normalize_plate("1234 uba") == "1234УВА"
    assert normalize_plate("1234 UBA") == normalize_plate("1234 УВА")


def test_other_latin_is_kept() -> None:
    # "D" is not in the map -> stays Latin -> the format check fails later.
    assert normalize_plate("1234 DBA") == "1234DВА"


# --- Task 3.4: separators (PM decision)


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1234-УБА", "1234УБА"),
        ("1234.УБА", "1234УБА"),
        ("12-34 У.Б.А.", "1234УБА"),
        ("1O34-УБ0", "1034УБО"),  # stripped first, so the position fixes still apply
    ],
)
def test_hyphens_and_dots_removed(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected


@pytest.mark.parametrize("raw", ["-", " . - "])
def test_only_separators_is_blank(raw: str) -> None:
    with pytest.raises(ValueError):
        normalize_plate(raw)


# --- Task 3.4: position fixes


@pytest.mark.parametrize(
    ("raw", "expected"),
    [
        ("1O34УБА", "1034УБА"),  # Latin O in digit part -> 0
        ("1О34УБА", "1034УБА"),  # Cyrillic О in digit part -> 0
        ("OOOOУБА", "0000УБА"),
        ("1234УБ0", "1234УБО"),  # zero in letter part -> Cyrillic О
        ("1234000", "1234ООО"),
        ("1234ОУБ", "1234ОУБ"),  # О in letter part stays a letter
    ],
)
def test_position_fixes(raw: str, expected: str) -> None:
    assert normalize_plate(raw) == expected


def test_position_fixes_only_for_seven_characters() -> None:
    # Unknown shape (e.g. a foreign plate): no guessing which part is which.
    assert normalize_plate("O12") == "О12"
    assert normalize_plate("12345УБА") == "12345УБА"


def test_fix_by_position_directly() -> None:
    assert fix_by_position("О0О0000") == "0000ООО"


# --- Task 3.4: format check


def test_plate_letters_are_mongolian_cyrillic() -> None:
    assert PLATE_LETTERS
    assert PLATE_LETTERS <= MONGOLIAN_CYRILLIC_CAPITALS


@pytest.mark.parametrize(
    "plate",
    ["1234УБА", "0000ААА", "9999ООО"],
)
def test_valid_plates(plate: str) -> None:
    letters = frozenset("УБАО")
    assert is_valid_plate(plate, letters)


@pytest.mark.parametrize(
    "plate",
    [
        "123УБА",      # 3 digits
        "12345УБ",     # 5 digits
        "1234УБ",      # 2 letters
        "1234УБАА",    # 4 letters
        "1234DBA",     # Latin letters
        "1234УБ?",     # unreadable char from labeling
        "12З4УБА",     # Cyrillic З instead of 3
        "١٢٣٤УБА",     # Arabic-Indic digits: str.isdigit() would say True
        "1234УБЯ",     # letter not in the allowed set
        "",
    ],
)
def test_invalid_plates(plate: str) -> None:
    assert not is_valid_plate(plate, frozenset("УБА"))


def test_plate_letters_are_the_21_seen_in_labels() -> None:
    # From the 183 labeled plates (task 3.4 plate_letters run, export 2026-10-01).
    assert PLATE_LETTERS == frozenset("АБВГДЕКМНОПРСТУХЦЧЭҮӨ")
    assert is_valid_plate("1234УНА")
    assert not is_valid_plate("1234УНЯ")  # Я never seen on a labeled plate -> manual input


def test_format_check_default_uses_plate_letters() -> None:
    letter = sorted(PLATE_LETTERS)[0]
    assert is_valid_plate(f"1234{letter * 3}")


# --- Task 3.4: read_plate (OCR text -> plate or manual input)


def test_good_reading() -> None:
    r = read_plate("1234 yba", 0.95)
    assert (r.plate_raw, r.plate_normalized, r.confidence) == ("1234 yba", "1234УВА", 0.95)
    assert (r.needs_manual, r.reason) == (False, None)


def test_low_confidence_needs_manual() -> None:
    r = read_plate("1234УБА", 0.59)
    assert (r.plate_normalized, r.needs_manual, r.reason) == ("1234УБА", True, "low_confidence")


def test_threshold_is_inclusive_and_default_is_0_6() -> None:
    assert DEFAULT_CONFIDENCE_THRESHOLD == 0.6
    assert read_plate("1234УБА", 0.6).needs_manual is False


def test_threshold_is_configurable() -> None:
    assert read_plate("1234УБА", 0.7, threshold=0.8).needs_manual is True
    assert read_plate("1234УБА", 0.3, threshold=0.2).needs_manual is False
    assert read_plate("1234УБА", 0.0, threshold=0.0).needs_manual is False


def test_invalid_format_needs_manual_even_with_high_confidence() -> None:
    r = read_plate("123УБА", 0.99)
    assert (r.plate_normalized, r.needs_manual, r.reason) == ("123УБА", True, "invalid_format")


def test_invalid_format_reported_before_low_confidence() -> None:
    assert read_plate("12УБ", 0.1).reason == "invalid_format"


def test_ocr_text_with_separators_passes() -> None:
    letter = sorted(PLATE_LETTERS)[0]
    r = read_plate(f"1234-{letter}.{letter}.{letter}", 0.9)
    assert (r.plate_normalized, r.needs_manual) == (f"1234{letter * 3}", False)


@pytest.mark.parametrize("raw", ["", "  ", "-.-"])
def test_blank_ocr_text_needs_manual(raw: str) -> None:
    r = read_plate(raw, 0.9)
    assert (r.plate_raw, r.plate_normalized, r.needs_manual, r.reason) == (raw, None, True, "empty")


@pytest.mark.parametrize(("confidence", "threshold"), [(-0.1, 0.6), (1.1, 0.6), (0.5, 1.5), (0.5, -1.0)])
def test_out_of_range_numbers_rejected(confidence: float, threshold: float) -> None:
    with pytest.raises(ValueError):
        read_plate("1234УБА", confidence, threshold)
