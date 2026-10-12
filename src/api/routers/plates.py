"""Plate recognition from a photo (task 4.3).

POST /plates/recognize   multipart form, field "file" = the photo

Photo -> yolo26n box -> 7 characters -> character CNN -> read_plate (D-044).
The photo is processed in memory and NOT stored (RISK-06); the response
carries only the reading, so the app pre-fills the plate field and asks the
oil changer to confirm or type it when needs_manual is true.
"""

from typing import Annotated

from fastapi import APIRouter, Depends, File, HTTPException, Request, UploadFile, status

from src.api.schemas import DetectionOut, PlateRecognitionOut
from src.cv.plate_reader import PlateRecognizer

router = APIRouter(prefix="/plates", tags=["plates"])

MAX_UPLOAD_BYTES = 15 * 1024 * 1024  # a phone photo is ~2–8 MB; larger = refuse before decoding
DETECTOR_NAME = "yolo26n (onnx)"
RECOGNIZER_NAME = "char_cnn (onnx)"  # recognizer B, docs/cv_ocr_results.md


def get_recognizer(request: Request) -> PlateRecognizer | None:
    """FastAPI dependency: the recognizer loaded at startup (None if its files were missing)."""
    return getattr(request.app.state, "recognizer", None)


@router.post("/recognize", response_model=PlateRecognitionOut)
def recognize(
    file: Annotated[UploadFile, File(description="Photo of the truck (JPEG, PNG or HEIC)")],
    recognizer: Annotated[PlateRecognizer | None, Depends(get_recognizer)],
) -> PlateRecognitionOut:
    """Read the plate on a photo.

    200 always when the photo is readable, also when no plate is found (needs_manual = true).
    413 file too large · 422 not an image · 503 recognizer not loaded.
    A plain ``def`` (not async): FastAPI runs it in a worker thread, so CPU work does not block other requests.
    """
    if recognizer is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "plate recognizer not loaded")
    data = file.file.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        raise HTTPException(status.HTTP_413_CONTENT_TOO_LARGE, f"photo larger than {MAX_UPLOAD_BYTES // 2**20} MB")
    try:
        result = recognizer.recognize_bytes(data)
    except ValueError as exc:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, str(exc)) from exc
    r, det = result.reading, result.detection
    return PlateRecognitionOut(
        plate_raw=r.plate_raw,
        plate_normalized=r.plate_normalized,
        confidence=round(r.confidence, 4),
        needs_manual=r.needs_manual,
        reason=r.reason,
        detection=None if det is None else DetectionOut(box=tuple(round(v, 1) for v in det.xyxy),
                                                        confidence=round(det.confidence, 4)),
        detector=DETECTOR_NAME,
        recognizer=RECOGNIZER_NAME,
        ms=round(result.ms_detect + result.ms_read, 1),
    )
