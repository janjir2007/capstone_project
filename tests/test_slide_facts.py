"""Tests for task 7.1c: scripts/slide_facts.py and scripts/latency_bench.py (fixtures only, no model files)."""

import io

import pandas as pd
import pytest
from PIL import Image

from scripts import latency_bench as lb
from scripts import slide_facts as sf

MD = """# Doc

| Baseline | MAE (days) | Reminder hit rate |
|---|---|---|
| B0 (median) | 13.3 | 35.5% |
| Ridge | 12.3 | 38.6% |

text

| Other | x |
|---|---|
| a | 1 |
"""


def test_md_table_finds_table_by_exact_header():
    t = sf.md_table(MD, ["Baseline", "MAE (days)", "Reminder hit rate"]).set_index("Baseline")
    assert list(t.index) == ["B0 (median)", "Ridge"]
    assert t.loc["Ridge", "Reminder hit rate"] == "38.6%"


def test_md_table_missing_header_raises():
    with pytest.raises(ValueError):
        sf.md_table(MD, ["Baseline", "MAE (days)"])  # partial header is not a match


@pytest.mark.parametrize("cell,value", [("38.6%", 38.6), ("+0.98", 0.98), ("-0.76", -0.76), ("1,752", 1752.0)])
def test_num_parses_doc_cells(cell, value):
    assert sf.num(cell) == value


def _ocr(model, exact, plates, auto, wrong, manual):
    return {"model": model, "plates": plates, "exact_match": exact / plates, "auto_correct": auto,
            "wrong_auto_fill": wrong, "manual": manual}


def test_ocr_comparison_uses_threshold_06_rows_and_counts():
    test_metrics = {"models": [_ocr("A: EasyOCR mn (pretrained)", 9, 27, 8, 0, 19), _ocr("B: custom char CNN", 19, 27, 9, 0, 18)]}
    final = {"sets": {"old_test": [
        {"model": "v1", "threshold": 0.55, "metrics": _ocr("v1", 19, 27, 99, 0, 18)},  # must be ignored
        {"model": "v1", "threshold": 0.6, "metrics": _ocr("v1", 19, 27, 9, 0, 18)},
        {"model": "v2", "threshold": 0.6, "metrics": _ocr("v2", 20, 27, 14, 0, 13)},
    ]}}
    out = sf.ocr_comparison(test_metrics, final)
    assert out["EasyOCR"] == {"plates": 27, "exact": 9, "auto": 8, "wrong": 0, "manual": 19}
    assert out["CNN v1"]["auto"] == 9
    assert out["CNN v2"]["exact"] == 20


def _facts() -> sf.Facts:
    tuning = {"test": {"n_test": 197, "n_test_trucks": 42, "rows": {
        "Oracle (noise floor)": {"mae": 11.34, "rmse": 14.7, "gain_vs_b0": [1.94, 0.75, 3.05]},
        "B0 (median)": {"mae": 13.28, "rmse": 16.9, "gain_vs_b0": [0.0, 0.0, 0.0]},
        "Current Ridge (served)": {"mae": 12.30, "rmse": 15.6, "gain_vs_b0": [0.98, 0.38, 1.55]}}}}
    results = pd.DataFrame({"MAE (days)": ["13.3", "12.3", "12.4"], "RMSE (days)": ["16.9", "15.6", "15.7"],
                            "R²": ["-0.01", "0.14", "0.13"]}, index=["B0 (median)", "Ridge", "Random Forest"])
    return sf.Facts(tuning, results, pd.DataFrame(), pd.DataFrame(), {}, {}, None)


def test_regression_rows_one_row_per_method():
    rows = sf.regression_rows(_facts(), "T", "R")
    names = [r[0] for r in rows]
    assert len(names) == 4  # oracle, B0, served Ridge (merged with "Ridge"), Random Forest
    ridge = next(r for r in rows if "Current Ridge" in r[0])
    assert ridge[1] == "12.30" and ridge[3] == "0.14"  # MAE from tuning, R² from results
    oracle = rows[0]
    assert oracle[3] == "—"  # no R² in any source
    assert any("Random Forest" in n for n in names)


def test_git_commit_reports_ignored_and_tracked():
    assert sf.git_commit(sf.Path("models/plate_yolo/test_metrics.json")) == "git-ignored"
    assert len(sf.git_commit(sf.Path("CLAUDE.md")).split()[0]) >= 7  # a short hash


def test_percentiles_and_parse_ids():
    p = lb.percentiles([float(i) for i in range(1, 101)])
    assert p["p50"] == 50.5 and p["p99"] == 99.0 and p["max"] == 100.0
    assert lb.parse_ids("1-3,7") == [1, 2, 3, 7]


def test_synthetic_photo_is_phone_sized_jpeg_and_deterministic():
    a, b = lb.synthetic_photo(size=(640, 480)), lb.synthetic_photo(size=(640, 480))
    assert a == b
    img = Image.open(io.BytesIO(a))
    assert img.format == "JPEG" and img.size == (640, 480)
