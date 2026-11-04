"""Read a driver's Messenger message as «plate + km», in any order (task 9.15a, plan §4.3). Pure.

Rules:
- exactly ONE plate: 4 digits not right after another digit, an optional space / hyphen, then 3
  letters (Cyrillic, or Latin look-alikes) not followed by another letter. It is normalized and
  checked by src/common/plates.py (the only place with plate rules, CLAUDE.md).
- the rest of the text, without «км» / «km», must be ONE number of 3-7 digits. Groups of 3 digits
  may be split by a space, comma or dot («871 234», «871,234»); anything else (two numbers, words)
  means it is not a km message.
- anything else -> None: the bot does not answer, a person reads it in the Page inbox.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

from src.common.plates import is_valid_plate, normalize_plate

# Letters a plate may be typed with: Cyrillic (any case) + the Latin look-alikes normalize_plate maps.
_LETTER = "[А-яЁёӨөҮүABEKMHOPCTXYUabekmhopctxyu]"
PLATE_RE = re.compile(rf"(?<![0-9])([0-9]{{4}})[ \-]?({_LETTER}{{3}})(?![^\W\d_])")
UNIT_RE = re.compile(r"(км|km)\.?", re.IGNORECASE)  # left-over letters of a longer word still fail below
# One number: plain 3-7 digits, or 1-3 digits followed by groups of 3 split by ONE space / comma / dot.
NUMBER_RE = re.compile(r"[0-9]{3,7}|[0-9]{1,3}(?:[ ,.][0-9]{3})+")
EDGE_PUNCTUATION = " \t\n,.;:!-–—"

YES_WORDS = frozenset({"тийм", "тиймээ"})
NO_WORDS = frozenset({"үгүй"})


@dataclass(frozen=True)
class KmMessage:
    """A message read as a km reading."""

    plate: str  # normalized, e.g. "9988НАА"
    km: int


def parse_km_message(text: str | None) -> KmMessage | None:
    """``text`` -> KmMessage, or None when it is not exactly one valid plate + one number."""
    if not text:
        return None
    plates = list(PLATE_RE.finditer(text))
    if len(plates) != 1:
        return None
    match = plates[0]
    plate = normalize_plate(match.group(1) + match.group(2))
    if not is_valid_plate(plate):
        return None
    rest = text[:match.start()] + " " + text[match.end():]
    rest = UNIT_RE.sub(" ", rest)
    rest = " ".join(rest.split()).strip(EDGE_PUNCTUATION)
    if not NUMBER_RE.fullmatch(rest):
        return None
    digits = re.sub(r"[ ,.]", "", rest)
    if not 3 <= len(digits) <= 7:
        return None
    km = int(digits)
    return KmMessage(plate=plate, km=km) if km > 0 else None


def _word(text: str | None) -> str:
    return " ".join((text or "").lower().split()).strip(EDGE_PUNCTUATION)


def is_yes(text: str | None) -> bool:
    """«Тийм» typed (any case, with or without punctuation)."""
    return _word(text) in YES_WORDS


def is_no(text: str | None) -> bool:
    """«Үгүй» typed."""
    return _word(text) in NO_WORDS
