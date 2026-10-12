"""Check the RUNNING API on the held-out test photos (task 4.3 handoff numbers).

Posts every test-split photo (same 27 as docs/cv_ocr_results.md) to
POST /plates/recognize and compares the answer with the label. Prints COUNTS
and timings only — never a plate, a file name or a photo (RISK-06).
Also reads the container's memory with ``docker stats`` before and after.

Start the stack first (fresh container = "idle" RAM):

    docker compose up -d --build && docker compose restart api
    python -m src.cv.check_serving
"""

from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
import urllib.request
import uuid
from collections import Counter
from pathlib import Path

from src.cv.plate_split import DEFAULT_DATASET

DEFAULT_INDEX = Path("data/interim/plate_ocr/index.json")  # from src.cv.ocr_data (task 3.3)


def container_mem_mb(container: str) -> float | None:
    """Current memory use of a container in MB (docker stats), None if docker is not available."""
    try:
        out = subprocess.run(["docker", "stats", "--no-stream", "--format", "{{.MemUsage}}", container],
                             capture_output=True, text=True, check=True, timeout=30).stdout
    except (OSError, subprocess.SubprocessError):
        return None
    used = out.split("/")[0].strip()  # e.g. "143.2MiB"
    units = {"KiB": 1 / 1024, "MiB": 1.0, "GiB": 1024.0, "kB": 1e3 / 2**20, "MB": 1e6 / 2**20, "GB": 1e9 / 2**20}
    for unit, factor in units.items():
        if used.endswith(unit):
            return round(float(used[: -len(unit)]) * factor * 2**20 / 1e6, 1)  # -> MB (10^6 bytes)
    return None


def post_photo(url: str, data: bytes) -> tuple[dict, float]:
    """multipart POST of one photo; returns (json, round-trip ms)."""
    boundary = uuid.uuid4().hex
    body = (f"--{boundary}\r\nContent-Disposition: form-data; name=\"file\"; filename=\"photo.jpg\"\r\n"
            f"Content-Type: image/jpeg\r\n\r\n").encode() + data + f"\r\n--{boundary}--\r\n".encode()
    req = urllib.request.Request(url, data=body, method="POST",
                                 headers={"Content-Type": f"multipart/form-data; boundary={boundary}"})
    start = time.perf_counter()
    with urllib.request.urlopen(req, timeout=60) as resp:
        out = json.loads(resp.read())
    return out, (time.perf_counter() - start) * 1000.0


def summarize(results: list[tuple[dict, str, float]]) -> dict:
    """Counts like docs/cv_ocr_results.md + latency. ``results`` = (response, label, round-trip ms)."""
    exact = [r["plate_normalized"] == label for r, label, _ in results]
    auto = [not r["needs_manual"] for r, _, _ in results]
    server = [r["ms"] for r, _, _ in results]
    trip = [ms for _, _, ms in results]
    return {
        "photos": len(results),
        "exact_plate_match": sum(exact),
        "auto_filled_correct": sum(e and a for e, a in zip(exact, auto)),
        "sent_to_manual": sum(not a for a in auto),
        "auto_filled_WRONG": sum(a and not e for e, a in zip(exact, auto)),
        "manual_reasons": dict(Counter(r["reason"] for r, _, _ in results if r["needs_manual"])),
        "first_correct_photo_number": next((i + 1 for i, e in enumerate(exact) if e), None),
        "server_ms_median": round(statistics.median(server), 1),
        "server_ms_p95": round(sorted(server)[max(0, round(0.95 * len(server)) - 1)], 1),
        "round_trip_ms_median": round(statistics.median(trip), 1),
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: post the test photos, print counts + timings + container RAM."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--url", default="http://localhost:8000/plates/recognize")
    parser.add_argument("--index", type=Path, default=DEFAULT_INDEX)
    parser.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    parser.add_argument("--container", default="ocp-api")
    args = parser.parse_args(argv)

    rows = [r for r in json.loads(args.index.read_text(encoding="utf-8")) if r["split"] == "test"]
    ram_idle = container_mem_mb(args.container)
    results = []
    for row in rows:
        data = (args.dataset / "images" / "test" / f"{row['stem']}.jpg").read_bytes()
        out, ms = post_photo(args.url, data)
        results.append((out, row["label"], ms))
    summary = summarize(results) | {"ram_idle_mb": ram_idle, "ram_after_recognize_mb": container_mem_mb(args.container)}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
