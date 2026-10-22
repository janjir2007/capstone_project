"""Tests for scripts/zoom_figures.py (task 7.1e): the parts that need no running API or browser."""

from pathlib import Path

import matplotlib
import numpy as np
import pytest

from scripts import zoom_figures as zf

MODELS = Path(__file__).resolve().parent.parent / "models"
FONT_MISSING = not Path(zf.FONT).exists()
MODELS_MISSING = not (MODELS / "plate_ocr" / "char_cnn.onnx").exists()
# 8.1b: Linux CI has no macOS fonts; matplotlib (requirements.txt) ships DejaVu Sans Bold, which has Cyrillic.
FALLBACK_FONT = Path(matplotlib.get_data_path()) / "fonts" / "ttf" / "DejaVuSans-Bold.ttf"


def _card(phone: str | None = "00000009", company: str = "Демо Экспресс ХХК") -> dict:
    service = {"id": 31, "vehicle_id": 18, "service_date": "2026-09-27", "odometer_km": 511548,
               "engine_hours": None, "oil_grade": "10W-40", "liters": 32.0, "route": "mn_china",
               "destination": {"id": 4, "name": "Beijing"}, "destination_raw": None, "driver_name": "Г. Оюун",
               "driver_phone": phone, "oil_changer": "Демо ажилтан", "photo_ref": None, "created_at": "x"}
    older = {**service, "id": 30, "service_date": "2026-08-09"}
    return {"id": 18, "identifier": "1001 УБА", "plate_normalized": "1001УБА",
            "company": {"id": 1, "name": company}, "history": [service, older]}


def test_demo_vehicle_accepted() -> None:
    zf.assert_demo_vehicle(_card())
    zf.assert_demo_vehicle(_card(phone=None))  # no phone recorded is fine


@pytest.mark.parametrize("card", [_card(phone="99112233"), _card(company="Real LLC")])
def test_non_demo_vehicle_refused(card: dict) -> None:
    """RISK-06: a real-looking phone or a non-demo company stops the script."""
    with pytest.raises(RuntimeError):
        zf.assert_demo_vehicle(card)


def test_service_row_maps_destination_to_id() -> None:
    row = zf.service_row(_card()["history"][0])
    assert tuple(row) == zf.DB_COLUMNS
    assert row["destination_id"] == 4
    assert "created_at" not in row and "photo_ref" not in row


def test_db_rows_text_oldest_first_and_counted() -> None:
    text = zf.db_rows_text(_card())
    lines = text.splitlines()
    assert lines[-1] == "(2 rows)"
    assert text.index(" 30 ") < text.index(" 31 ")  # history is newest first; table is oldest first
    assert "1001 УБА" in lines[0]


def test_curl_text_keeps_cyrillic() -> None:
    text = zf.curl_text("curl x", {"plate_raw": "1001УБА"})
    assert text.startswith("$ curl x\n\n")
    assert '"plate_raw": "1001УБА"' in text


def test_demo_photo_is_deterministic(monkeypatch) -> None:
    """Same seed -> same pixels. Without the macOS font (CI) it runs with DejaVu instead of skipping (8.1b)."""
    if FONT_MISSING:
        monkeypatch.setattr(zf, "FONT", str(FALLBACK_FONT))
    a, b = zf.render_demo_photo(), zf.render_demo_photo()
    assert a.size == (1280, 960)
    assert np.array_equal(np.asarray(a), np.asarray(b))


def test_y4m_header_and_frames(tmp_path: Path) -> None:
    from PIL import Image

    path = tmp_path / "cam.y4m"
    zf.write_y4m(Image.new("RGB", (100, 80), "red"), path, frames=3)
    data = path.read_bytes()
    assert data.startswith(b"YUV4MPEG2 W640 H480")
    assert data.count(b"FRAME\n") == 3
    header = len(b"YUV4MPEG2 W640 H480 F30:1 Ip A1:1 C420jpeg\n")
    assert len(data) == header + 3 * (len(b"FRAME\n") + 640 * 480 * 3 // 2)


# pytest reports the skipif closest to the function first: models is the reason CI must see when both
# are missing (allowed in scripts/ci_check_pytest.py). Only the macOS font gives the photo the detector
# was tuned on, so no DejaVu fallback here.
@pytest.mark.skipif(FONT_MISSING, reason=f"macOS font missing: {zf.FONT} (demo photo is tuned on it)")
@pytest.mark.skipif(MODELS_MISSING, reason="needs models/ (git-ignored): plate_ocr/char_cnn.onnx")
def test_demo_photo_read_and_per_char_matches_reader() -> None:
    """The synthetic photo is read as 1001УБА, and per_char gives the same text + product as predict_chars."""
    from src.cv.char_segment import segment
    from src.cv.ocr_data import padded_crop
    from src.cv.plate_reader import PlateRecognizer

    rec = PlateRecognizer(MODELS)
    rgb = np.asarray(zf.render_demo_photo())
    det = rec.detector.detect(rgb)
    assert det is not None
    chars = segment(padded_crop(rgb, list(det.xyxy)))
    labels = zf.per_char(rec.reader, chars)
    text, conf = rec.reader.predict_chars(chars)
    assert "".join(c for c, _ in labels) == text == "1001УБА"
    assert np.prod([p for _, p in labels]) == pytest.approx(conf, rel=1e-5)
