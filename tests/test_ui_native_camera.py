"""Tests for the plate camera component's Python side (task 8.4).

The browser part (live view, shutter, fallback, file inputs, resize, base64) is checked in
Chromium with Playwright's fake camera (see the 8.4 handoff); real phones are checked by Ari.
Here: the payload parser that turns the browser's trigger value into bytes, and the size line.
Synthetic bytes only (RISK-06).
"""

import base64

import pytest

pytest.importorskip("streamlit")

from src.ui import native_camera  # noqa: E402
from src.ui.native_camera import CapturedPhoto, parse_payload  # noqa: E402


def payload(data: bytes = b"\xff\xd8fake-jpeg", **extra) -> dict:
    return {"b64": base64.b64encode(data).decode(), "name": "photo.jpg", "type": "image/jpeg",
            "width": 1920, "height": 2560, "original_bytes": 4_000_000, "resized": True,
            "source": "live", "source_width": 3024, "source_height": 4032, **extra}


def test_valid_payload_gives_bytes_and_metadata() -> None:
    photo = parse_payload(payload())
    assert photo == CapturedPhoto(b"\xff\xd8fake-jpeg", "photo.jpg", "image/jpeg", 1920, 2560, 4_000_000, True,
                                  "live", 3024, 4032)


def test_photo_looks_like_uploaded_file_for_recognize() -> None:
    """common.recognize_photo_box uses .getvalue(), .name, .type — same as st.UploadedFile."""
    photo = parse_payload(payload(b"abc"))
    assert photo.getvalue() == b"abc" and photo.name == "photo.jpg" and photo.type == "image/jpeg"


@pytest.mark.parametrize("bad", [None, "x", 42, [], {}, {"b64": 5}, {"b64": "not base64!!"}, {"b64": ""}])
def test_malformed_payload_is_none(bad) -> None:
    assert parse_payload(bad) is None


def test_missing_optional_fields_get_safe_defaults() -> None:
    photo = parse_payload({"b64": base64.b64encode(b"heic-bytes").decode()})
    assert photo.name == "photo.jpg" and photo.type == "" and photo.width is None and photo.resized is False
    assert photo.source == "" and photo.source_width is None


def test_non_int_sizes_are_dropped() -> None:
    photo = parse_payload(payload(width="1920", height=True, original_bytes=1.5))
    assert photo.width is None and photo.height is None and photo.original_bytes is None


def test_max_side_is_2560() -> None:
    assert native_camera.MAX_SIDE == 2560


def test_size_text_shows_sent_and_camera_size() -> None:
    photo = parse_payload(payload(b"x" * 2048))
    assert native_camera.size_text(photo) == "1920×2560 (камер 3024×4032, live, 2 KB)"


def test_size_text_without_sizes() -> None:
    photo = parse_payload({"b64": base64.b64encode(b"heic").decode(), "source": "gallery"})
    assert native_camera.size_text(photo) == "? (gallery, 0 KB)"


def test_labels_are_mongolian_mockup_text() -> None:
    labels = native_camera.LABELS
    assert (labels["badge"], labels["hint"], labels["gallery"], labels["native"]) == (
        "Арын камер", "2–3 метрээс, урдаас нь авна уу", "Галерей", "Зураг авах")
