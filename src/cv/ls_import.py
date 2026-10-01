"""Attach pre-label boxes to existing Label Studio tasks as predictions (Task 3.1c, Step 3).

Reads ``data/interim/prelabels/predictions.json`` (from ``src.cv.prelabel run``)
and, for each task of the Label Studio project, creates one prediction with the
boxes at or above the confidence threshold. Each box gets ``plate_type=plate``;
``plate_text`` is left empty for Ari to type.

Safety rules:
- Talks only to Label Studio on this Mac (localhost). Photos are not sent;
  only box coordinates, a score and the model version.
- Never touches tasks that already have annotations (submitted or skipped) or drafts.
- Running twice does not duplicate: tasks that already have a prediction with
  the same model_version are skipped.

API details checked in the installed Label Studio 1.23.2 source:
- Personal Access Token (PAT) -> POST /api/token/refresh/ {"refresh": PAT}
  -> {"access": ...}; requests use "Authorization: Bearer <access>".
  The access token lives 5 minutes (simplejwt default), so a 401 triggers one refresh.
- GET /api/projects/ is paginated {"results": [...]};
  GET /api/tasks/?project=ID is paginated {"tasks": [...], "total": N};
  POST /api/predictions/ creates a prediction.

Usage:
    export LS_API_KEY=...   # the Personal Access Token, never written to a file
    python -m src.cv.ls_import --dry-run        # counts only, writes nothing
    python -m src.cv.ls_import --limit 1        # one task, check it in the UI
    python -m src.cv.ls_import                  # the rest; also sets the project model_version
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.error
import urllib.request
from collections import Counter
from pathlib import Path
from typing import Any
from urllib.parse import urlencode, urlparse

from src.cv.ls_export import BOX_TAG, DEFAULT_TYPE, TYPE_TAG, image_path_from_url

DEFAULT_URL = "http://127.0.0.1:8080"
DEFAULT_PREDICTIONS = Path("data/interim/prelabels/predictions.json")
DEFAULT_PROJECT = "Plates"
DEFAULT_CONF = 0.6  # chosen by Ari after the pilot: drops the weak background/false boxes
IMAGE_TAG = "image"  # <Image name="image"> in docs/labeling/label_config.xml
LOCAL_HOSTS = {"127.0.0.1", "localhost", "::1"}
PAGE_SIZE = 100


# ---------- pure functions (unit-tested) ----------

def to_percent_box(box: dict[str, float], width: int, height: int) -> dict[str, float]:
    """Pixel corners (x1, y1, x2, y2) -> Label Studio box: top-left x/y, width, height in % of the image."""
    x1 = min(max(box["x1"], 0.0), width)
    y1 = min(max(box["y1"], 0.0), height)
    x2 = min(max(box["x2"], 0.0), width)
    y2 = min(max(box["y2"], 0.0), height)
    return {
        "x": x1 / width * 100.0,
        "y": y1 / height * 100.0,
        "width": (x2 - x1) / width * 100.0,
        "height": (y2 - y1) / height * 100.0,
        "rotation": 0,
    }


def build_result(record: dict[str, Any], conf: float) -> list[dict[str, Any]]:
    """Label Studio result entries for one photo: a box + a plate_type choice per region."""
    results: list[dict[str, Any]] = []
    kept = [b for b in record["boxes"] if b["confidence"] >= conf]
    kept.sort(key=lambda b: b["confidence"], reverse=True)
    for i, box in enumerate(kept):
        geo = to_percent_box(box, record["width"], record["height"])
        base = {
            "id": f"pre{i}",  # region id; the box and its choice share it (see ls_export.boxes_from_task)
            "to_name": IMAGE_TAG,
            "original_width": record["width"],
            "original_height": record["height"],
            "image_rotation": 0,
            "score": round(box["confidence"], 4),
        }
        results.append({**base, "from_name": BOX_TAG, "type": "rectanglelabels",
                        "value": {**geo, "rectanglelabels": ["plate"]}})
        results.append({**base, "from_name": TYPE_TAG, "type": "choices",
                        "value": {**geo, "choices": [DEFAULT_TYPE]}})
    return results


def is_untouched(task: dict[str, Any]) -> bool:
    """True if nobody has worked on the task: no annotations (incl. skipped) and no drafts."""
    return not (
        task.get("annotations")
        or task.get("drafts")
        or task.get("total_annotations")
        or task.get("cancelled_annotations")
    )


def plan_import(
    tasks: list[dict[str, Any]],
    pred: dict[str, Any],
    already_predicted: set[int],
    conf: float,
) -> tuple[list[dict[str, Any]], dict[str, int]]:
    """Decide which predictions to create. Returns (payloads, count-only report)."""
    by_image = {rec["image"]: rec for rec in pred["images"]}
    model_version = pred["model_version"]
    report: Counter[str] = Counter(tasks_total=len(tasks))
    payloads: list[dict[str, Any]] = []
    seen_images: set[str] = set()

    for task in tasks:
        image = image_path_from_url(task["data"][IMAGE_TAG])
        seen_images.add(image)
        if not is_untouched(task):
            report["skip_annotated"] += 1
        elif task["id"] in already_predicted:
            report["skip_already_predicted"] += 1
        elif image not in by_image:
            report["skip_no_detection_record"] += 1
        else:
            result = build_result(by_image[image], conf)
            if not result:
                report["skip_no_box_above_threshold"] += 1
                continue
            scores = [r["score"] for r in result if r["from_name"] == BOX_TAG]
            payloads.append({
                "task": task["id"],
                "project": task.get("project"),
                "model_version": model_version,
                "score": max(scores),
                "result": result,
            })
            report["to_create"] += 1
            report["boxes_to_create"] += len(scores)

    report["detection_records_without_task"] = len(set(by_image) - seen_images)
    return payloads, dict(report)


# ---------- Label Studio HTTP client (localhost only) ----------

class LabelStudio:
    """Minimal JSON client for the local Label Studio API using a Personal Access Token."""

    def __init__(self, base_url: str, pat: str) -> None:
        host = urlparse(base_url).hostname
        if host not in LOCAL_HOSTS:
            raise ValueError(f"Refusing non-local Label Studio URL {base_url!r} (RISK-06: data stays on this Mac)")
        self.base_url = base_url.rstrip("/")
        self._pat = pat
        self._access: str | None = None

    def _refresh(self) -> None:
        data = self._send("POST", "/api/token/refresh/", {"refresh": self._pat}, auth=False)
        self._access = data["access"]

    def _send(self, method: str, path: str, body: Any = None, auth: bool = True) -> Any:
        req = urllib.request.Request(self.base_url + path, method=method)
        req.add_header("Content-Type", "application/json")
        if auth:
            req.add_header("Authorization", f"Bearer {self._access}")
        payload = None if body is None else json.dumps(body).encode("utf-8")
        with urllib.request.urlopen(req, data=payload, timeout=30) as resp:
            raw = resp.read()
        return json.loads(raw) if raw else None

    def request(self, method: str, path: str, body: Any = None) -> Any:
        """Authenticated request; refreshes the 5-minute access token once on 401."""
        if self._access is None:
            self._refresh()
        try:
            return self._send(method, path, body)
        except urllib.error.HTTPError as exc:
            if exc.code != 401:
                raise
            self._refresh()
            return self._send(method, path, body)

    def find_project(self, title: str) -> dict[str, Any]:
        """The single project whose title matches ``title`` ignoring case."""
        projects = self.request("GET", "/api/projects/?" + urlencode({"page_size": PAGE_SIZE}))["results"]
        matches = [p for p in projects if p["title"].casefold() == title.casefold()]
        if len(matches) != 1:
            raise ValueError(f"Expected 1 project titled {title!r} (any case), found {len(matches)}")
        return matches[0]

    def list_tasks(self, project_id: int) -> list[dict[str, Any]]:
        """All tasks of a project, with annotations/drafts/predictions included (fields=all)."""
        tasks: list[dict[str, Any]] = []
        page = 1
        while True:
            query = urlencode({"project": project_id, "page": page, "page_size": PAGE_SIZE,
                               "fields": "all", "resolve_uri": "false"})
            data = self.request("GET", f"/api/tasks/?{query}")
            tasks.extend(data["tasks"])
            if not data["tasks"] or len(tasks) >= data["total"]:
                return tasks
            page += 1

    def predicted_task_ids(self, project_id: int, model_version: str) -> set[int]:
        """Tasks that already have a prediction with this model_version."""
        data = self.request("GET", "/api/predictions/?" + urlencode({"project": project_id}))
        rows = data["results"] if isinstance(data, dict) else data
        return {row["task"] for row in rows if row.get("model_version") == model_version}

    def create_prediction(self, payload: dict[str, Any]) -> None:
        """POST one prediction."""
        self.request("POST", "/api/predictions/", payload)

    def set_project_model_version(self, project: dict[str, Any], model_version: str) -> bool:
        """Make the project show this model's predictions as pre-labels. True if it changed.

        Checked on a throwaway Label Studio 1.23.2: with an empty project model_version,
        GET /api/projects/{id}/next/ (the "Label All Tasks" stream) returned the task
        WITHOUT predictions; after setting it, the predictions were included.
        """
        if project.get("model_version") == model_version:
            return False
        self.request("PATCH", f"/api/projects/{project['id']}/", {"model_version": model_version})
        return True


# ---------- CLI ----------

def main(argv: list[str] | None = None) -> int:
    """CLI: plan (and optionally create) predictions; prints counts only."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--predictions", type=Path, default=DEFAULT_PREDICTIONS)
    parser.add_argument("--project", default=DEFAULT_PROJECT, help="project title (case-insensitive)")
    parser.add_argument("--conf", type=float, default=DEFAULT_CONF)
    parser.add_argument("--url", default=os.environ.get("LS_URL", DEFAULT_URL))
    parser.add_argument("--dry-run", action="store_true", help="only print what would be created")
    parser.add_argument("--limit", type=int, default=None, help="create at most N predictions")
    args = parser.parse_args(argv)

    pat = os.environ.get("LS_API_KEY")
    if not pat:
        print("ERROR: set LS_API_KEY to your Label Studio Personal Access Token", file=sys.stderr)
        return 1
    pred = json.loads(args.predictions.read_text(encoding="utf-8"))

    try:
        ls = LabelStudio(args.url, pat)
        project = ls.find_project(args.project)
        tasks = ls.list_tasks(project["id"])
        done = ls.predicted_task_ids(project["id"], pred["model_version"])
        payloads, report = plan_import(tasks, pred, done, args.conf)
        if args.limit is not None:
            payloads = payloads[: args.limit]
        created = 0
        version_set = False
        if not args.dry_run:
            for payload in payloads:
                ls.create_prediction(payload)
                created += 1
            version_set = ls.set_project_model_version(project, pred["model_version"])
    except urllib.error.HTTPError as exc:
        print(f"ERROR: Label Studio answered HTTP {exc.code}: {exc.read()[:500]!r}", file=sys.stderr)
        return 1
    except (urllib.error.URLError, ValueError) as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        return 1

    report.update({"project_id": project["id"], "model_version": pred["model_version"],
                   "conf": args.conf, "dry_run": args.dry_run, "created": created,
                   "project_model_version_set": version_set})
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
