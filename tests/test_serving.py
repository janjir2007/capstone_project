"""Tests for task 4.3: prediction + plate recognition served by the API.

No real photos or real records: fake trucks, a small Ridge fitted on fake
visits, synthetic images. Tests that need the real exported model files
(git-ignored) or a running Postgres skip when those are missing.
"""

from __future__ import annotations

import io
import json
from collections.abc import Iterator
from datetime import date
from pathlib import Path

import cv2
import joblib
import numpy as np
import pandas as pd
import pytest
from fastapi.testclient import TestClient
from PIL import Image
from sqlalchemy import Connection, create_engine
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from src.api import prediction as P
from src.api.clock import get_today
from src.api.db import get_session
from src.api.main import create_app
from src.api.routers import plates as plates_router
from src.common.features import FEATURE_COLUMNS, Route, build_features
from src.common.plates import PlateReading
from src.cv import plate_reader as R
from src.data.generator import load_config as load_generator_config
from src.ml.dataset import TARGET, route_table
from src.ml.export_serving import route_params
from tests.test_api_data import pg  # noqa: F401  (Postgres fixture: schema + migration 001 + sample data)

ROOT = Path(__file__).resolve().parent.parent
REAL_MODELS = ROOT / "models"
TODAY = date(2026, 10, 12)
GEN_CFG = load_generator_config(ROOT / "configs/generator.yaml")


# ==========================================================================
# Fake model folder: same file names and keys as the real one
# ==========================================================================

@pytest.fixture(scope="module")
def model_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    """Ridge fitted on fake visits + serving_params.json with the REAL route table."""
    from src.ml import train as T
    from tests.test_ml_train import fake_train

    folder = tmp_path_factory.mktemp("models")
    df = fake_train()
    pipe = T.model_specs(0)["Ridge"].pipeline().fit(df[FEATURE_COLUMNS], df[TARGET])
    joblib.dump({"pipeline": pipe, "model": "Ridge", "buffer_days": 7, "features": FEATURE_COLUMNS, "target": TARGET,
                 "window_days_early": [1, 14], "best_params": {}, "split_cutoff": "2025-08-23", "seed": 42,
                 "data": "fake"}, folder / P.MODEL_FILE)
    (folder / P.PARAMS_FILE).write_text(json.dumps({"b0_days": 58.0, "b1_interval_km": 17_500.0, "late_km": 20_000.0,
                                                     "routes": route_params(GEN_CFG),
                                                     "buffers": {"b0": 12, "b1": 1}}), encoding="utf-8")
    return folder


@pytest.fixture(scope="module")
def predictor(model_dir: Path) -> P.Predictor:
    return P.load_predictor(model_dir)


def visit(i: int, day: str, km: int | None, dest: str | None = "Beijing", raw: str | None = None,
          route: str | None = None) -> P.Visit:
    """Fake service row; route defaults to the destination's route."""
    info = route_table(GEN_CFG).get(dest) if dest else None
    return P.Visit(id=i, service_date=date.fromisoformat(day), odometer_km=km,
                   route=route or (info.route if info else None), destination_id=None if dest is None else 100 + i,
                   destination_name=dest, destination_raw=raw)


# ==========================================================================
# Prediction
# ==========================================================================

def test_route_params_round_trip_equals_training_route_table() -> None:
    """serving_params.json routes = the exact Route objects build_features got in training (R8)."""
    assert {name: Route(**v) for name, v in route_params(GEN_CFG).items()} == route_table(GEN_CFG)


def test_first_visit_uses_b1(predictor: P.Predictor) -> None:
    p = predictor.predict(1, [visit(1, "2026-10-01", 100_000)], TODAY)
    km_per_day = route_table(GEN_CFG)["Beijing"].km_per_day
    assert (p.method, p.fallback_reason) == ("b1", "first_visit")
    assert p.predicted_days == round(17_500 / km_per_day, 1)


def test_history_uses_ridge_on_features_py_row(predictor: P.Predictor) -> None:
    """The served number = pipeline on build_features' last row (no second feature code path)."""
    visits = [visit(1, "2026-06-01", 300_000), visit(2, "2026-07-20", 318_000), visit(3, "2026-09-10", 336_500)]
    p = predictor.predict(1, visits, TODAY)
    records = pd.DataFrame({"vehicle_key": 0, "service_date": pd.to_datetime([v.service_date for v in visits]),
                            "odometer_km": [float(v.odometer_km) for v in visits],
                            "destination_name": [v.destination_name for v in visits], "route": [v.route for v in visits]})
    row = build_features(records, route_table(GEN_CFG)).iloc[[-1]]
    assert p.method == "ridge" and p.fallback_reason is None
    assert p.predicted_days == round(float(predictor.pipeline.predict(row[FEATURE_COLUMNS])[0]), 1)
    assert p.based_on_service_id == 3 and p.last_service_date == date(2026, 9, 10)


@pytest.mark.parametrize(("last", "reason"), [
    (visit(2, "2026-09-01", 1, dest="Other / several / unknown", route="mixed"), "route_not_modelled"),
    (visit(2, "2026-09-01", 1, dest=None, raw="Darkhan", route="ub_city"), "route_not_modelled"),
    (visit(2, "2026-09-01", 1, dest=None, raw="Sainshand", route="mn_china"), "destination_raw_only"),
    (visit(2, "2026-09-01", 1, dest=None, route="mn_china"), "unknown_destination"),
    (visit(2, "2026-09-01", 1, dest="New border post", route="mn_russia"), "unknown_destination"),
])
def test_fallbacks_to_b0(predictor: P.Predictor, last: P.Visit, reason: str) -> None:
    p = predictor.predict(1, [visit(1, "2026-07-01", 0), last], TODAY)
    assert (p.method, p.fallback_reason, p.predicted_days) == ("b0", reason, 58.0)


def test_dates_days_left_and_status_in_given_today(predictor: P.Predictor) -> None:
    p = predictor.predict(1, [visit(1, "2026-08-10", None, dest=None, route="mixed")], TODAY)
    assert p.predicted_date == date(2026, 10, 7)  # 2026-08-10 + 58 days
    assert (p.days_left, p.status, p.today) == (-5, "overdue", TODAY)


@pytest.mark.parametrize("days_left", [-30, -1, 0, 1, 13, 14, 15, 90])
def test_status_matches_evaluation_rule(days_left: int) -> None:
    from src.ml.evaluate import status_of

    assert P.status_of(days_left) == str(status_of([days_left], P.DUE_SOON_DAYS)[0])


def test_prediction_never_before_next_day(model_dir: Path, tmp_path: Path) -> None:
    params = json.loads((model_dir / P.PARAMS_FILE).read_text()) | {"b0_days": -3.0}
    for f in (P.MODEL_FILE,):
        (tmp_path / f).write_bytes((model_dir / f).read_bytes())
    (tmp_path / P.PARAMS_FILE).write_text(json.dumps(params))
    p = P.load_predictor(tmp_path).predict(1, [visit(1, "2026-10-01", 1, dest=None, route="mixed")], TODAY)
    assert p.predicted_days == P.MIN_DAYS


def test_model_with_other_features_is_refused(model_dir: Path, tmp_path: Path) -> None:
    bundle = joblib.load(model_dir / P.MODEL_FILE) | {"features": [*FEATURE_COLUMNS[:-1], "n_prior_visits"]}
    joblib.dump(bundle, tmp_path / P.MODEL_FILE)
    (tmp_path / P.PARAMS_FILE).write_text((model_dir / P.PARAMS_FILE).read_text())
    with pytest.raises(ValueError, match="features"):
        P.load_predictor(tmp_path)


def test_version_is_model_name_plus_file_hash(predictor: P.Predictor) -> None:
    name, digest = predictor.version.split("-")
    assert name == "ridge" and len(digest) == 8


def test_no_visits_is_an_error(predictor: P.Predictor) -> None:
    with pytest.raises(ValueError):
        predictor.predict(1, [], TODAY)


# ==========================================================================
# Plate reader (no model files needed)
# ==========================================================================

@pytest.mark.parametrize("shape", [(720, 1280), (1280, 720), (640, 640), (300, 400)])
def test_letterbox_is_square_and_box_maps_back(shape: tuple[int, int]) -> None:
    rgb = np.zeros((*shape, 3), np.uint8)
    padded, scale, (left, top) = R.letterbox(rgb)
    assert padded.shape == (R.IMGSZ, R.IMGSZ, 3)
    # a box at photo pixels (100, 50)-(200, 90), written as the detector would output it
    x1, y1, x2, y2 = 100, 50, 200, 90
    out = np.zeros((1, 5, 3), np.float32)
    out[0, :, 1] = [((x1 + x2) / 2) * scale + left, ((y1 + y2) / 2) * scale + top, (x2 - x1) * scale,
                    (y2 - y1) * scale, 0.9]
    out[0, 4, 0] = 0.3
    det = R.best_box(out, scale, (left, top), shape)
    assert det is not None and det.confidence == pytest.approx(0.9)
    assert det.xyxy == pytest.approx((x1, y1, x2, y2), abs=1e-3)


def test_best_box_below_threshold_is_none() -> None:
    out = np.zeros((1, 5, 4), np.float32)
    out[0, 4] = [0.1, 0.24, 0.2, 0.0]
    assert R.best_box(out, 1.0, (0, 0), (640, 640)) is None


def test_position_mask_digits_first_four_letters_last_three() -> None:
    classes = "0123456789АБВ"
    mask = R.position_mask(classes)
    assert np.isfinite(mask[:4, :10]).all() and np.isneginf(mask[:4, 10:]).all()
    assert np.isneginf(mask[4:, :10]).all() and np.isfinite(mask[4:, 10:]).all()


def test_softmax_with_masked_entries() -> None:
    probs = R.softmax(np.array([[1.0, -np.inf, 2.0], [0.0, 0.0, 0.0]]))
    assert probs.sum(axis=1) == pytest.approx([1.0, 1.0]) and probs[0, 1] == 0.0


def test_exif_rotation_is_applied_and_garbage_rejected() -> None:
    img = Image.new("RGB", (40, 20))
    exif = img.getexif()
    exif[0x0112] = 6  # Orientation: rotate 90° clockwise to display
    buf = io.BytesIO()
    img.save(buf, format="JPEG", exif=exif)
    assert R.load_upright_rgb(buf.getvalue()).shape == (40, 20, 3)
    with pytest.raises(ValueError):
        R.load_upright_rgb(b"not an image")


CNN_PARITY = """
import json, sys
from pathlib import Path
import numpy as np, torch
from src.cv import char_cnn as C
from src.cv import plate_reader as R
from src.cv.export_onnx import export_char_cnn
tmp = Path(sys.argv[1])
torch.manual_seed(0)
C.save(C.CharCNN().eval(), tmp / "cnn.pt")
served = R.OnnxCharCNN(export_char_cnn(tmp / "cnn.pt", tmp / "cnn.onnx"))
chars = np.random.default_rng(0).random((7, 32, 32), dtype=np.float32)
text, conf = C.predict_chars(C.load(tmp / "cnn.pt"), chars)
o_text, o_conf = served.predict_chars(chars)
print(json.dumps({"classes": served.classes == C.CLASSES, "text": text == o_text, "conf_diff": abs(conf - o_conf)}))
"""


def test_char_cnn_onnx_matches_torch(tmp_path: Path) -> None:
    """Export a (random) CharCNN the way export_onnx does: same text, same confidence.

    Separate Python: torch must not share a process with XGBoost's OpenMP on macOS (see test_ml_evaluate).
    """
    import subprocess
    import sys

    pytest.importorskip("onnx")
    done = subprocess.run([sys.executable, "-c", CNN_PARITY, str(tmp_path)], cwd=ROOT, capture_output=True,
                          text=True, timeout=300)
    assert done.returncode == 0, done.stderr[-2000:]
    out = json.loads(done.stdout.strip().splitlines()[-1])
    assert out["classes"] and out["text"] and out["conf_diff"] < 1e-5


needs_real_onnx = pytest.mark.skipif(not (REAL_MODELS / R.DETECTOR_FILE).exists()
                                     or not (REAL_MODELS / R.RECOGNIZER_FILE).exists(),
                                     reason="exported ONNX files missing (python -m src.cv.export_onnx)")


@needs_real_onnx
def test_real_recognizer_on_synthetic_photo() -> None:
    from src.cv.export_onnx import synthetic_photo

    ok, jpg = cv2.imencode(".jpg", synthetic_photo()[..., ::-1])
    result = R.PlateRecognizer(REAL_MODELS).recognize_bytes(jpg.tobytes())
    assert result.detection is not None  # the white plate-like box is found
    assert result.reading.needs_manual or result.reading.plate_normalized is not None


@needs_real_onnx
def test_real_recognizer_blank_photo_needs_manual() -> None:
    result = R.PlateRecognizer(REAL_MODELS).recognize_rgb(np.full((480, 640, 3), 128, np.uint8))
    assert result.detection is None and result.reading.reason == "no_plate" and result.reading.needs_manual


# ==========================================================================
# Endpoints
# ==========================================================================

class StubRecognizer:
    """Stands in for PlateRecognizer: real image decoding, fixed reading."""

    def recognize_bytes(self, data: bytes) -> R.Recognition:
        R.load_upright_rgb(data)  # ValueError for non-images, as the real one
        reading = PlateReading("1234 уба", "1234УБА", 0.91, needs_manual=False, reason=None)
        return R.Recognition(reading, R.Detection((1.0, 2.0, 3.0, 4.0), 0.8), 10.0, 2.5)


def png_bytes() -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", (8, 8)).save(buf, format="PNG")
    return buf.getvalue()


@pytest.fixture
def sqlite_client(tmp_path: Path) -> Iterator[tuple[TestClient, object]]:
    """App without a database and without model files (empty model folder)."""
    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=tmp_path)
    with TestClient(app) as client:
        yield client, app


def test_models_missing_api_still_starts_and_answers_503(sqlite_client: tuple[TestClient, object]) -> None:
    client, app = sqlite_client
    assert app.state.predictor is None and app.state.recognizer is None
    assert client.get("/health").status_code == 200
    assert client.post("/plates/recognize", files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 503
    assert client.get("/vehicles/1/prediction").status_code == 503


def test_recognize_endpoint_shape(sqlite_client: tuple[TestClient, object]) -> None:
    client, app = sqlite_client
    app.state.recognizer = StubRecognizer()
    r = client.post("/plates/recognize", files={"file": ("a.png", png_bytes(), "image/png")})
    assert r.status_code == 200
    assert r.json() == {"plate_raw": "1234 уба", "plate_normalized": "1234УБА", "confidence": 0.91,
                        "needs_manual": False, "reason": None, "detection": {"box": [1.0, 2.0, 3.0, 4.0], "confidence": 0.8},
                        "detector": plates_router.DETECTOR_NAME, "recognizer": plates_router.RECOGNIZER_NAME, "ms": 12.5}


def test_recognize_rejects_non_image_and_too_large(sqlite_client: tuple[TestClient, object],
                                                   monkeypatch: pytest.MonkeyPatch) -> None:
    client, app = sqlite_client
    app.state.recognizer = StubRecognizer()
    assert client.post("/plates/recognize", files={"file": ("a.txt", b"hello", "text/plain")}).status_code == 422
    assert client.post("/plates/recognize").status_code == 422  # no file
    monkeypatch.setattr(plates_router, "MAX_UPLOAD_BYTES", 10)
    assert client.post("/plates/recognize", files={"file": ("a.png", png_bytes(), "image/png")}).status_code == 413


@pytest.fixture
def client(pg: Connection, model_dir: Path) -> Iterator[TestClient]:  # noqa: F811
    """Postgres test schema (sample data) + the fake model folder; same savepoint trick as test_api_data."""
    savepoint = pg.begin_nested()

    def test_session() -> Iterator[Session]:
        with Session(bind=pg, join_transaction_mode="create_savepoint") as session:
            yield session

    app = create_app(engine=create_engine("sqlite://", poolclass=StaticPool), model_dir=model_dir)
    app.dependency_overrides[get_session] = test_session
    app.dependency_overrides[get_today] = lambda: TODAY
    with TestClient(app) as test_client:
        yield test_client
    savepoint.rollback()


def new_service(client: TestClient, plate: str, day: str, km: int, destination: str) -> int:
    dest_id = next(d["id"] for d in client.get("/destinations").json() if d["name"] == destination)
    r = client.post("/services", json={"identifier": plate, "company_name": "Test 4.3", "service_date": day,
                                       "odometer_km": km, "oil_grade": "15W-40", "liters": 38, "destination_id": dest_id})
    assert r.status_code == 201, r.text
    return r.json()["vehicle_id"]


def test_card_and_endpoint_show_the_same_prediction(client: TestClient) -> None:
    vid = new_service(client, "0000 ТЕС", "2026-08-01", 250_000, "Beijing")
    first = client.get(f"/vehicles/{vid}/prediction").json()
    assert (first["method"], first["fallback_reason"]) == ("b1", "first_visit")
    new_service(client, "0000 ТЕС", "2026-09-25", 268_000, "Beijing")
    card = client.get(f"/vehicles/{vid}").json()
    assert card["prediction"]["method"] == "ridge"
    assert card["prediction"] == client.get(f"/vehicles/{vid}/prediction").json()
    assert card["prediction"]["today"] == TODAY.isoformat()
    looked_up = client.get("/vehicles/lookup", params={"q": "0000тес"}).json()["vehicles"][0]
    assert looked_up["prediction"] == card["prediction"]


def test_sample_vehicles_without_destination_fall_back_to_b0(client: TestClient) -> None:
    cards = [client.get(f"/vehicles/{v['id']}").json()
             for v in client.get("/vehicles/lookup", params={"q": "99110001"}).json()["vehicles"]]
    assert cards and all(c["prediction"]["method"] == "b0" for c in cards)


def test_prediction_unknown_vehicle_is_404(client: TestClient) -> None:
    assert client.get("/vehicles/999999/prediction").status_code == 404
