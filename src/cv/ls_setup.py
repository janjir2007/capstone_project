"""Create a NEW Label Studio project that reads photos from a local folder (Task 3.6a).

Does by API what LABELING_GUIDE.md section 3 does by hand: project + our
label config (docs/labeling/label_config.xml) + "Local files" source storage
+ Sync. Then ``src.cv.ls_import --project <title>`` attaches the pre-labels.

Safety rules:
- Refuses if a project with the same title already exists, so the old 3.1
  project is never changed.
- Local Label Studio only (same client as ls_import). Photos are not uploaded:
  the storage only records their paths; the browser reads them from disk.
- The folder must be inside the local-files root (data/raw), as Label Studio
  requires (LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT in start_label_studio.sh).

API checked in the installed Label Studio 1.23.2 source (io_storages/urls.py,
io_storages/localfiles/models.py): POST /api/storages/localfiles/ with
project, title, path, regex_filter, use_blob_urls, recursive_scan; then
POST /api/storages/localfiles/{id}/sync. The regex is matched on the file name.

Usage (Label Studio running, LS_API_KEY = your Personal Access Token):
    python -m src.cv.ls_setup --title plates_new --photos data/raw/photos_new
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
from pathlib import Path
from typing import Any

from src.cv.ls_import import DEFAULT_URL, LabelStudio

DEFAULT_CONFIG = Path("docs/labeling/label_config.xml")
DEFAULT_ROOT = Path("data/raw")  # = LABEL_STUDIO_LOCAL_FILES_DOCUMENT_ROOT
PHOTO_REGEX = r"(?i).*\.(jpe?g|png)$"  # same filter as LABELING_GUIDE.md (skips .DS_Store etc.)


def storage_payload(project_id: int, photos: Path, root: Path) -> dict[str, Any]:
    """Body for POST /api/storages/localfiles/. Raises ValueError if ``photos`` is outside ``root``."""
    folder, base = photos.resolve(), root.resolve()
    if not folder.is_relative_to(base):
        raise ValueError(f"{photos} is not inside the local-files root {root}")
    return {
        "project": project_id,
        "title": folder.name,
        "path": str(folder),  # Label Studio wants an absolute path
        "regex_filter": PHOTO_REGEX,
        "use_blob_urls": True,  # = "Files - one task per file", not "Tasks - JSON"
        "recursive_scan": False,
    }


def title_taken(projects: list[dict[str, Any]], title: str) -> bool:
    """True if any project already has this title (ignoring case, like ls_import.find_project)."""
    return any(p["title"].casefold() == title.casefold() for p in projects)


def setup_project(ls: LabelStudio, title: str, label_config: str, photos: Path, root: Path) -> dict[str, Any]:
    """Create project + storage, sync, and return a count-only report."""
    projects = ls.request("GET", "/api/projects/?page_size=100")["results"]
    if title_taken(projects, title):
        raise ValueError(f"A project titled {title!r} already exists; choose another --title")
    project = ls.request("POST", "/api/projects/", {"title": title, "label_config": label_config})
    storage = ls.request("POST", "/api/storages/localfiles/", storage_payload(project["id"], photos, root))
    ls.request("POST", f"/api/storages/localfiles/{storage['id']}/sync")
    tasks = ls.list_tasks(project["id"])
    return {"project_id": project["id"], "title": title, "storage_id": storage["id"], "tasks": len(tasks)}


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; prints counts only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--title", required=True, help="new project title (must not exist yet)")
    parser.add_argument("--photos", type=Path, required=True, help="folder inside data/raw")
    parser.add_argument("--root", type=Path, default=DEFAULT_ROOT)
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--url", default=os.environ.get("LS_URL", DEFAULT_URL))
    args = parser.parse_args(argv)

    pat = os.environ.get("LS_API_KEY")
    if not pat:
        print("ERROR: set LS_API_KEY to your Label Studio Personal Access Token", file=sys.stderr)
        return 1
    try:
        report = setup_project(LabelStudio(args.url, pat), args.title,
                               args.config.read_text(encoding="utf-8"), args.photos, args.root)
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Label Studio answered HTTP {exc.code}: {exc.read()[:500]!r}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
