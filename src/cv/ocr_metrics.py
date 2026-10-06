"""Plate recognition metrics (Task 3.3). Pure Python: no models, no images.

Both recognizers (pretrained EasyOCR and the custom character CNN) are scored
by the same functions on the same test plates, so the comparison is fair.

Every prediction goes through ``src.common.plates.read_plate`` first, exactly
as the app will do (normalize -> format check -> confidence threshold). So a
Latin "A" that OCR returns for Cyrillic "А" is not counted as an error: the app
fixes it too.

Definitions:
- exact match: normalized prediction == normalized label (all 7 characters).
- character accuracy: 1 - (edit distance / label length), floored at 0, summed
  over plates. Edit distance counts substitutions, missing and extra characters,
  so a reading that drops one character is not scored as 7 wrong positions.
- confusions: (true, predicted) character pairs, counted only where the
  prediction has the label's length (position-by-position comparison is then
  meaningful). Length errors are counted separately.
- manual: ``read_plate(...).needs_manual`` at the threshold (default 0.6).
- wrong auto-fill: NOT sent to manual but wrong. The costly error: a service
  is saved under the wrong truck.

Outputs of this module contain single characters and counts only, never a full
plate string, so the report can be shared (RISK-06).
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from math import comb

from src.common.plates import DEFAULT_CONFIDENCE_THRESHOLD, read_plate


@dataclass(frozen=True)
class Prediction:
    """One recognizer output for one test plate."""

    label: str  # normalized ground truth, e.g. "1234УБА"
    raw_text: str  # what the recognizer returned ("" if it read nothing)
    confidence: float  # 0-1
    ms: float  # recognition time for this plate (crop in, text out)


def edit_distance(a: str, b: str) -> int:
    """Levenshtein distance (insert, delete, substitute all cost 1)."""
    previous = list(range(len(b) + 1))
    for i, ca in enumerate(a, start=1):
        current = [i]
        for j, cb in enumerate(b, start=1):
            current.append(min(previous[j] + 1, current[j - 1] + 1, previous[j - 1] + (ca != cb)))
        previous = current
    return previous[-1]


def normalized_text(raw_text: str, confidence: float, threshold: float) -> tuple[str, bool, str | None]:
    """(normalized plate or "", needs_manual, reason) via the app's own ``read_plate``."""
    reading = read_plate(raw_text, confidence, threshold)
    return reading.plate_normalized or "", reading.needs_manual, reading.reason


def char_accuracy(label: str, predicted: str) -> float:
    """Share of the label's characters read correctly, from edit distance (0-1)."""
    return max(0.0, 1.0 - edit_distance(predicted, label) / len(label))


def confusion_pairs(label: str, predicted: str) -> list[tuple[str, str]]:
    """(true, predicted) pairs that differ, position by position. Empty if lengths differ."""
    if len(label) != len(predicted):
        return []
    return [(t, p) for t, p in zip(label, predicted) if t != p]


def evaluate_predictions(
    predictions: list[Prediction], threshold: float = DEFAULT_CONFIDENCE_THRESHOLD
) -> dict[str, object]:
    """All metrics for one recognizer. Count-only, safe to share."""
    n = len(predictions)
    if n == 0:
        raise ValueError("no predictions to evaluate")
    exact = auto_correct = wrong_auto = length_errors = 0
    char_sum = 0.0
    confusions: Counter[tuple[str, str]] = Counter()
    manual_reasons: Counter[str] = Counter()
    for p in predictions:
        text, needs_manual, reason = normalized_text(p.raw_text, p.confidence, threshold)
        correct = text == p.label
        exact += correct
        char_sum += char_accuracy(p.label, text)
        if len(text) != len(p.label):
            length_errors += 1
        confusions.update(confusion_pairs(p.label, text))
        if needs_manual:
            manual_reasons[reason or "unknown"] += 1
        elif correct:
            auto_correct += 1
        else:
            wrong_auto += 1
    times = sorted(p.ms for p in predictions)
    return {
        "plates": n,
        "exact_match": exact / n,
        "char_accuracy": char_sum / n,
        "length_errors": length_errors,
        "threshold": threshold,
        "manual": sum(manual_reasons.values()),
        "manual_rate": sum(manual_reasons.values()) / n,
        "manual_reasons": dict(manual_reasons),
        "auto_correct": auto_correct,
        "wrong_auto_fill": wrong_auto,
        "top_confusions": [{"true": t, "pred": q, "count": c} for (t, q), c in confusions.most_common(10)],
        "ms_median": round(_percentile(times, 50), 1),
        "ms_p95": round(_percentile(times, 95), 1),
    }


def threshold_sweep(predictions: list[Prediction], thresholds: list[float]) -> list[dict[str, float]]:
    """Manual rate and wrong auto-fill rate at each threshold (for the trade-off chart)."""
    rows = []
    for t in thresholds:
        m = evaluate_predictions(predictions, t)
        n = m["plates"]
        rows.append({"threshold": t, "manual_rate": m["manual_rate"],
                     "wrong_auto_rate": m["wrong_auto_fill"] / n, "auto_correct_rate": m["auto_correct"] / n})
    return rows


def mcnemar_exact_p(a_only: int, b_only: int) -> float:
    """Two-sided exact McNemar p-value from the discordant counts.

    Under "both recognizers are equally good", each plate that only one of them
    gets right is a fair coin flip, so ``a_only ~ Binomial(a_only + b_only, 0.5)``.
    """
    n = a_only + b_only
    if n == 0:
        return 1.0
    k = min(a_only, b_only)
    tail = sum(comb(n, i) for i in range(k + 1)) / 2**n
    return min(1.0, 2 * tail)


def paired_comparison(preds_a: list[Prediction], preds_b: list[Prediction]) -> dict[str, float]:
    """Exact-match agreement on the SAME plates + McNemar p-value (ignores confidence)."""
    if [p.label for p in preds_a] != [p.label for p in preds_b]:
        raise ValueError("predictions must be for the same plates in the same order")

    def right(p: Prediction) -> bool:
        return normalized_text(p.raw_text, p.confidence, 0.0)[0] == p.label

    pairs = [(right(a), right(b)) for a, b in zip(preds_a, preds_b)]
    a_only = sum(1 for a, b in pairs if a and not b)
    b_only = sum(1 for a, b in pairs if b and not a)
    return {"both_right": sum(1 for a, b in pairs if a and b), "a_only": a_only, "b_only": b_only,
            "both_wrong": sum(1 for a, b in pairs if not a and not b), "mcnemar_p": mcnemar_exact_p(a_only, b_only)}


def _percentile(sorted_values: list[float], q: float) -> float:
    """Linear-interpolation percentile (same as numpy's default) of an already sorted list."""
    if len(sorted_values) == 1:
        return sorted_values[0]
    pos = (len(sorted_values) - 1) * q / 100
    lo = int(pos)
    hi = min(lo + 1, len(sorted_values) - 1)
    return sorted_values[lo] + (sorted_values[hi] - sorted_values[lo]) * (pos - lo)
