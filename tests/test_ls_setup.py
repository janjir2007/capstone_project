"""Tests for src/cv/ls_setup.py with a fake Label Studio client (no server, no photos)."""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from src.cv.ls_setup import PHOTO_REGEX, setup_project, storage_payload, title_taken


class FakeLS:
    """Records requests; answers like Label Studio 1.23.2 does for the calls we use."""

    def __init__(self, titles: list[str]) -> None:
        self.titles = titles
        self.calls: list[tuple[str, str, Any]] = []

    def request(self, method: str, path: str, body: Any = None) -> Any:
        self.calls.append((method, path, body))
        if path.startswith("/api/projects/?"):
            return {"results": [{"id": i, "title": t} for i, t in enumerate(self.titles, 1)]}
        if path == "/api/projects/":
            return {"id": 99}
        if path == "/api/storages/localfiles/":
            return {"id": 7}
        return None

    def list_tasks(self, project_id: int) -> list[dict[str, Any]]:
        return [{"id": 1}, {"id": 2}]


def test_storage_payload_inside_root(tmp_path: Path) -> None:
    folder = tmp_path / "raw" / "photos_new"
    folder.mkdir(parents=True)
    body = storage_payload(5, folder, tmp_path / "raw")
    assert body == {"project": 5, "title": "photos_new", "path": str(folder.resolve()),
                    "regex_filter": PHOTO_REGEX, "use_blob_urls": True, "recursive_scan": False}


def test_storage_payload_outside_root_refused(tmp_path: Path) -> None:
    (tmp_path / "raw").mkdir()
    with pytest.raises(ValueError):
        storage_payload(5, tmp_path / "elsewhere", tmp_path / "raw")


def test_title_taken_ignores_case() -> None:
    assert title_taken([{"title": "Plates"}], "plates")
    assert not title_taken([{"title": "Plates"}], "plates_new")


def test_setup_refuses_existing_title_and_writes_nothing(tmp_path: Path) -> None:
    ls = FakeLS(["Plates"])
    with pytest.raises(ValueError):
        setup_project(ls, "PLATES", "<View/>", tmp_path, tmp_path)  # type: ignore[arg-type]
    assert all(method == "GET" for method, _, _ in ls.calls)  # old project untouched


def test_setup_creates_project_storage_and_syncs(tmp_path: Path) -> None:
    ls = FakeLS(["Plates"])
    report = setup_project(ls, "plates_new", "<View/>", tmp_path, tmp_path)  # type: ignore[arg-type]
    posts = [path for method, path, _ in ls.calls if method == "POST"]
    assert posts == ["/api/projects/", "/api/storages/localfiles/", "/api/storages/localfiles/7/sync"]
    assert report == {"project_id": 99, "title": "plates_new", "storage_id": 7, "tasks": 2}


def test_regex_matches_photos_only() -> None:
    import re

    rx = re.compile(PHOTO_REGEX)
    assert rx.match("IMG_1.JPG") and rx.match("a.jpeg") and rx.match("b.png")
    assert not rx.match(".DS_Store") and not rx.match("x.heic")
