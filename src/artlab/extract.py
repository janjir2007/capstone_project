"""Plates and phones from an Artlab receipt description (task 9.6b-2).

The oil changer types the truck's plate and the driver's phone into the receipt's free-text
`description` (Ari, PM review 9.6a). This module turns that text into normalized plates and
8-digit phones. The text itself is NOT kept: callers store only what `extract()` returns
(privacy, RISK-06 / PM 9.6b: "store only what matching needs").

Plates are normalized ONLY by src/common/plates.py (CLAUDE.md): this module finds candidates in the
text, `normalize_plate()` + `is_valid_plate()` decide. Typos it tolerates (all via normalize_plate):
lower case, Latin look-alike letters ("1234 UBA" -> 1234УБА), spaces / "-" / "." between digits
and letters, О/0 mix-ups by position. A wrong letter or a missing digit is not "fixed": that plate
does not match, and matching falls back to the phone.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.common.plates import LATIN_TO_CYRILLIC, is_valid_plate, normalize_plate

# Letters that can stand in the letter part: Cyrillic (incl. Ө Ү Ё) + the Latin look-alikes that
# normalize_plate() maps to Cyrillic, in both cases.
_LATIN_LOOKALIKES = "".join(LATIN_TO_CYRILLIC) + "".join(LATIN_TO_CYRILLIC).lower()
_PLATE_LETTER = f"[А-ЯЁӨҮа-яёөү{_LATIN_LOOKALIKES}]"
# 4 digits, optional separators, 3 letters, and NOT followed by another letter (so "5000 төгрөг"
# is no plate). (?![^\W\d_]) = "next character is not a letter" (any script).
_PLATE_IN_TEXT = re.compile(
    rf"(?<![0-9])([0-9]{{4}})[\s\-.]*({_PLATE_LETTER}{{3}})(?![^\W\d_])"
)
# Letter triples that are common receipt words, not plates: "5000 төг" (tugrik) would read as
# 5000ТӨГ, "5000 тос" (oil) as 5000ТОС. A real plate ending in one of these is not found by
# plate; matching then falls back to the phone.
NOT_PLATE_LETTERS = frozenset({"ТӨГ", "ТОС"})
# Mongolian phone numbers have 8 digits, often written "9911 2233" or "9911-2233".
_PHONE_IN_TEXT = re.compile(r"(?<![0-9])([0-9]{4})[\s\-]?([0-9]{4})(?![0-9])")


@dataclass(frozen=True)
class Extracted:
    """What matching needs from one description; the description itself is dropped."""

    plates: tuple[str, ...]  # normalized + valid, unique, in text order
    phones: tuple[str, ...]  # 8 digits, unique, in text order


def find_plates(text: str | None) -> list[str]:
    """Valid normalized plates in free text, unique, in order of appearance.

    Four digits that belong to a phone number are never read as a plate's digits.
    """
    text = text or ""
    phone_spans = [m.span() for m in _PHONE_IN_TEXT.finditer(text)]
    found: list[str] = []
    for match in _PLATE_IN_TEXT.finditer(text):
        # "9911 2233 тос": the 2nd half of a phone is not a plate's digits
        if any(start <= match.start() < end for start, end in phone_spans):
            continue
        digits, letters = match.groups()
        plate = normalize_plate(digits + letters)
        if is_valid_plate(plate) and plate[-3:] not in NOT_PLATE_LETTERS and plate not in found:
            found.append(plate)
    return found


def find_phones(text: str | None) -> list[str]:
    """8-digit phone numbers in free text (digits only), unique, in order of appearance."""
    found: list[str] = []
    for a, b in _PHONE_IN_TEXT.findall(text or ""):
        if a + b not in found:
            found.append(a + b)
    return found


def extract(description: str | None) -> Extracted:
    """Plates + phones from one receipt description."""
    return Extracted(plates=tuple(find_plates(description)), phones=tuple(find_phones(description)))
