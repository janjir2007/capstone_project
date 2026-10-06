"""Which letters appear on the labeled plates, and do all labels pass the format check (Task 3.4).

Reads the Label Studio full JSON export, takes every box of type "plate" that
has text, normalizes it with src/common/plates.py and reports:
- how many texts pass the format check (DONE criterion: all 183),
- how many texts normalization changed (e.g. a Latin letter typed by mistake),
- how often each letter appears in the letter part,
- a ready-to-paste ``PLATE_LETTERS`` line for src/common/plates.py.

Printed output is counts and single letters only, never a plate string or a
file name, so Ari can share it (RISK-06).

Usage (Ari runs it):
    python -m src.cv.plate_letters data/interim/labelstudio_export/<newest>.json
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path
from typing import Any

from src.common.plates import (
    DIGIT_COUNT,
    MONGOLIAN_CYRILLIC_CAPITALS,
    PLATE_LENGTH,
    is_valid_plate,
    normalize_plate,
)
from src.cv.ls_export import boxes_from_task, load_export


def plate_texts(tasks: list[dict[str, Any]]) -> list[str]:
    """Every non-empty plate_text of a "plate" box (fleet numbers are skipped)."""
    return [
        box.plate_text
        for task in tasks
        for box in boxes_from_task(task)
        if box.plate_type == "plate" and box.plate_text
    ]


def letter_report(texts: list[str]) -> dict[str, Any]:
    """Count-only report. Letter set is taken from the format-shaped texts' letter part."""
    normalized = [normalize_plate(text) for text in texts]
    shaped = [p for p in normalized if len(p) == PLATE_LENGTH and p[:DIGIT_COUNT].isascii() and p[:DIGIT_COUNT].isdigit()]
    letters = Counter(c for p in shaped for c in p[DIGIT_COUNT:])
    observed = frozenset(letters)
    return {
        "plate_texts": len(texts),
        "unique_plate_texts": len(set(normalized)),
        "changed_by_normalization": sum(1 for raw, norm in zip(texts, normalized) if raw != norm),
        "wrong_length_or_digits": len(normalized) - len(shaped),
        "letters_outside_mongolian_alphabet": sorted(observed - MONGOLIAN_CYRILLIC_CAPITALS),
        "pass_format_with_observed_letters": sum(1 for p in normalized if is_valid_plate(p, observed)),
        "letter_counts": dict(sorted(letters.items(), key=lambda kv: (-kv[1], kv[0]))),
        "plate_letters_line": f'PLATE_LETTERS: frozenset[str] = frozenset("{"".join(sorted(observed))}")',
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: print the shareable letter report."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("export_json", type=Path, help="Label Studio full JSON export")
    args = parser.parse_args(argv)
    try:
        tasks = load_export(args.export_json)
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(letter_report(plate_texts(tasks)), indent=2, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
