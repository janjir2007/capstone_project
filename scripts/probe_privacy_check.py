"""Privacy check for one saved Artlab probe JSON file (task 9.6c-2b). Standard library only.

deploy/artlab_probe.sh runs it on the server HOST (python3, not the container) after every probe:

    python3 -I scripts/probe_privacy_check.py /root/artlab_probe/<file>.json

It replaces a grep check that broke on the server ("grep: Invalid collation character": a Cyrillic
letter range depends on the locale) and still printed "none found". Here every Cyrillic letter is
a \\u escape and the file is read as UTF-8 explicitly, so the locale does not matter.

Prints COUNTS only, never the matched text. Exit codes:
  0  no plate-like text ("plate check: none found")
  3  plate-like text found: do NOT share the file
  4  the check could not run (missing / empty / not UTF-8 / not JSON / crash): do NOT share
"""

from __future__ import annotations

import json
import re
import sys
from pathlib import Path
from typing import Any, Iterator

# 4 digits, optional space or hyphen, 3 Mongolian Cyrillic letters: A-YA YO OE UE (upper + lower).
_CYR = "\u0410-\u042f\u0401\u04e8\u04ae\u0430-\u044f\u0451\u04e9\u04af"
PLATE = re.compile(f"[0-9]{{4}}[ -]?[{_CYR}]{{3}}")
# The probe's own mask (text_shape: digit -> 9, Cyrillic -> capital A, U+0410) is expected and allowed.
MASK = re.compile("9999[ -]?\u0410\u0410\u0410")
# 8 digits starting 6-9 = phone-shaped (99999999 is the mask). Reported as JSON paths, no values.
PHONE8 = re.compile(r"(?<![0-9])[6-9][0-9]{7}(?![0-9])")

OK, FOUND, CANNOT_RUN = 0, 3, 4


class CheckError(Exception):
    """The file cannot be checked; the message names the reason, never file content."""


def load(path: Path) -> tuple[str, Any]:
    """(raw text, parsed JSON). Raises CheckError when the file cannot be checked."""
    if not path.is_file():
        raise CheckError("file not found")
    try:
        text = path.read_bytes().decode("utf-8")
    except UnicodeDecodeError:
        raise CheckError("file is not UTF-8") from None
    if not text.strip():
        raise CheckError("file is empty")
    try:
        return text, json.loads(text)
    except json.JSONDecodeError:
        raise CheckError("file is not valid JSON") from None


def walk(obj: Any, path: str = "$") -> Iterator[tuple[str, str]]:
    """Every (JSON path, text) for keys and scalar values; decodes \\u escapes via json.loads."""
    if isinstance(obj, dict):
        for key, value in obj.items():
            sub = f"{path}.{key}"
            yield sub, str(key)
            yield from walk(value, sub)
    elif isinstance(obj, list):
        for i, value in enumerate(obj):
            yield from walk(value, f"{path}[{i}]")
    elif obj is not None:
        yield path, str(obj)


def plate_count(text: str) -> int:
    """Plate-like matches that are not the probe's mask."""
    return sum(1 for m in PLATE.finditer(text) if not MASK.fullmatch(m.group()))


def check(path: Path) -> tuple[int, list[str]]:
    """Run both checks -> (exit code, lines to print). Lines hold counts and JSON paths only."""
    try:
        text, data = load(path)
    except CheckError as err:
        return CANNOT_RUN, [f"ERROR: plate check could NOT run ({err}); do NOT share this file"]
    # Raw text AND decoded strings: catches Cyrillic written as \u escapes (ensure_ascii=True).
    plates = max(plate_count(text), sum(plate_count(t) for _, t in walk(data)))
    if plates:
        return FOUND, [f"STOP: {plates} plate-like text(s) found; do NOT share this file"]
    phones = sorted({p for p, t in walk(data) if any(m != "99999999" for m in PHONE8.findall(t))})
    lines = ["plate check: none found",
             f"8-digit numbers: {len(phones)} (each must be a sum / count / id / account code, never a phone)"]
    lines += [f"  at {p}" for p in phones]
    return OK, lines


def main(argv: list[str] | None = None) -> int:
    args = sys.argv[1:] if argv is None else argv
    if len(args) != 1:
        print("usage: probe_privacy_check.py FILE.json", file=sys.stderr)
        return CANNOT_RUN
    try:
        code, lines = check(Path(args[0]))
    except Exception as err:  # never fall through to "none found"; class name only
        code, lines = CANNOT_RUN, [f"ERROR: plate check could NOT run ({type(err).__name__})"]
    for line in lines:
        print(line, file=sys.stdout if code == OK else sys.stderr)
    return code


if __name__ == "__main__":
    sys.exit(main())
