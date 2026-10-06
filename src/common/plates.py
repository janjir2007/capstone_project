"""Plate normalization — the ONLY place plates are normalized (CLAUDE.md).

Used by the API (lookup + saving a service, task 4.2) and by plate
recognition (task 3.4), so a plate typed by hand and a plate read from a photo
end up as the same database key (vehicles.plate_normalized).

Mongolian plates are 4 digits + 3 Cyrillic letters, e.g. "1234УБА" (all 183
labeled plates match, task 3.1d).

Rules, in order (task 3.4):
1. Remove whitespace, hyphens, dots; upper-case. "1234-уба." -> "1234УБА"
2. Latin look-alike letters (+ U) -> Cyrillic.    "1234 YBA" -> "1234УВА"
3. Position fixes, only for 7-character plates:   "1O34УБ0"  -> "1034УБО"
   O/О in the digit part -> 0; 0 in the letter part -> О.
Then ``read_plate`` checks the format and the OCR confidence and sets
``needs_manual`` so the oil changer types or confirms the plate by hand.
"""

from __future__ import annotations

from dataclasses import dataclass

# OCR confidence below this -> ask the oil changer to check the plate.
DEFAULT_CONFIDENCE_THRESHOLD = 0.6

# Latin capitals that look the same as a Cyrillic capital (task 3.4 brief).
# Keys are Latin, values are Cyrillic; they look identical but are different
# Unicode characters, so "A" (U+0041) != "А" (U+0410) in the database.
LATIN_TO_CYRILLIC: dict[str, str] = {
    "A": "А",
    "B": "В",
    "E": "Е",
    "K": "К",
    "M": "М",
    "H": "Н",
    "O": "О",
    "P": "Р",
    "C": "С",
    "T": "Т",
    "X": "Х",
    "Y": "У",
    "U": "У",  # not a look-alike: how У is typed on a Latin keyboard (PM decision, task 3.4)
}
_LATIN_TABLE = str.maketrans(LATIN_TO_CYRILLIC)

# Separators OCR or a person may put between digits and letters (PM decision, task 3.4).
_SEPARATORS = str.maketrans("", "", "-.")

DIGIT_COUNT = 4
LETTER_COUNT = 3
PLATE_LENGTH = DIGIT_COUNT + LETTER_COUNT

# Letter that OCR confuses with a digit, by plate part. Only O <-> 0 for now
# (task 3.4 brief); more pairs once task 3.3 shows real OCR mistakes.
_DIGIT_PART_FIXES = str.maketrans({"О": "0"})  # Cyrillic О (Latin O is already Cyrillic by rule 2)
_LETTER_PART_FIXES = str.maketrans({"0": "О"})

# The 35 capital letters of the Mongolian Cyrillic alphabet (33 Russian + Ө, Ү).
MONGOLIAN_CYRILLIC_CAPITALS: frozenset[str] = frozenset("АБВГДЕЁЖЗИЙКЛМНОӨПРСТУҮФХЦЧШЩЪЫЬЭЮЯ")

# Letters allowed in the letter part of a plate: the 21 letters SEEN in the
# 183 labeled plates (export 2026-10-01, `python -m src.cv.plate_letters`),
# not assumed. A plate with any other letter fails the format check -> manual
# input. Add a letter here only when a real plate shows it.
PLATE_LETTERS: frozenset[str] = frozenset("АБВГДЕКМНОПРСТУХЦЧЭҮӨ")

_DIGITS = "0123456789"  # not \d: \d also matches Arabic-Indic and other Unicode digits


@dataclass(frozen=True)
class PlateReading:
    """Result of turning raw OCR text into a plate (fields match POST /plates/recognize)."""

    plate_raw: str
    plate_normalized: str | None  # None if the OCR text was blank (or only separators)
    confidence: float
    needs_manual: bool
    reason: str | None  # why manual input is needed: "empty", "invalid_format", "low_confidence"


def normalize_plate(raw: str) -> str:
    """Return the database key for a licence plate.

    Removes every whitespace character (spaces, tabs, non-breaking spaces),
    hyphens and dots, upper-cases (str.upper() handles Cyrillic, including Ө and Ү), maps Latin
    look-alikes to Cyrillic and, for 7-character plates, fixes O/0 by position.
    Does NOT check the format: the API still accepts unusual plates typed by hand.

    Raises ValueError if nothing is left (a blank plate is never valid).
    """
    plate = "".join(raw.split()).translate(_SEPARATORS).upper()
    if not plate:
        raise ValueError("plate is empty")
    plate = plate.translate(_LATIN_TABLE)
    if len(plate) == PLATE_LENGTH:
        plate = fix_by_position(plate)
    return plate


def fix_by_position(plate: str) -> str:
    """Fix O/0 confusions: first 4 characters must be digits, last 3 letters."""
    digits, letters = plate[:DIGIT_COUNT], plate[DIGIT_COUNT:]
    return digits.translate(_DIGIT_PART_FIXES) + letters.translate(_LETTER_PART_FIXES)


def is_valid_plate(plate: str, letters: frozenset[str] = PLATE_LETTERS) -> bool:
    """True if ``plate`` (already normalized) is 4 ASCII digits + 3 allowed letters."""
    if len(plate) != PLATE_LENGTH:
        return False
    digits, tail = plate[:DIGIT_COUNT], plate[DIGIT_COUNT:]
    return all(c in _DIGITS for c in digits) and all(c in letters for c in tail)


def read_plate(
    raw_text: str,
    confidence: float,
    threshold: float = DEFAULT_CONFIDENCE_THRESHOLD,
) -> PlateReading:
    """Turn raw OCR text into a plate and decide if a person must check it.

    needs_manual is True when the text is blank, the normalized plate fails the
    format check, or ``confidence < threshold``. Format is checked first, so the
    reason names the more useful problem.

    Raises ValueError if confidence or threshold is outside 0-1 (a caller bug).
    """
    for name, value in (("confidence", confidence), ("threshold", threshold)):
        if not 0.0 <= value <= 1.0:
            raise ValueError(f"{name} must be between 0 and 1, got {value}")

    try:
        plate = normalize_plate(raw_text)
    except ValueError:
        return PlateReading(raw_text, None, confidence, needs_manual=True, reason="empty")

    if not is_valid_plate(plate):
        reason: str | None = "invalid_format"
    elif confidence < threshold:
        reason = "low_confidence"
    else:
        reason = None
    return PlateReading(raw_text, plate, confidence, needs_manual=reason is not None, reason=reason)
