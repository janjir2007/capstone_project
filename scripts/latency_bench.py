"""Local latency of two API endpoints for the slides (task 7.1c).

Calls a RUNNING API sequentially (one client, no concurrency) and writes p50 / p95 / p99:

- POST /plates/recognize        -- default photo = a SYNTHETIC phone-sized JPEG (no real plate,
  RISK-06), so the detector runs on the full image but usually finds no plate and the character
  CNN is skipped. Pass --photo to time a real photo yourself (only timings are written).
- GET  /vehicles/{id}/prediction -- cycles through --vehicle-ids (the demo DB).

Only status codes and timings are saved, never a response body.

    .venv/bin/python -m scripts.latency_bench --url http://localhost:8001
"""

from __future__ import annotations

import argparse
import io
import json
import platform
import subprocess
import time
import urllib.error
import urllib.request
from datetime import date
from pathlib import Path

import numpy as np
from PIL import Image

from src.cv.check_serving import post_photo

DEFAULT_OUT = Path("docs/latency_7_1c.json")
PHOTO_SIZE = (4032, 3024)  # typical 12 MP phone photo


def synthetic_photo(size: tuple[int, int] = PHOTO_SIZE, seed: int = 42) -> bytes:
    """A phone-sized JPEG of smooth noise (no plate, no person). Same bytes for the same seed."""
    rng = np.random.default_rng(seed)
    small = rng.integers(0, 256, size=(size[1] // 32, size[0] // 32, 3), dtype=np.uint8)
    img = Image.fromarray(small).resize(size, Image.Resampling.BILINEAR)
    buf = io.BytesIO()
    img.save(buf, format="JPEG", quality=90)
    return buf.getvalue()


def parse_ids(text: str) -> list[int]:
    """'1-3,7' -> [1, 2, 3, 7]."""
    ids: list[int] = []
    for part in text.split(","):
        lo, _, hi = part.partition("-")
        ids.extend(range(int(lo), int(hi or lo) + 1))
    return ids


def percentiles(ms: list[float]) -> dict[str, float]:
    """p50 / p95 / p99 / mean / max in ms (numpy linear interpolation), rounded to 0.1."""
    a = np.asarray(ms, dtype=float)
    p50, p95, p99 = np.percentile(a, [50, 95, 99])
    return {"p50": round(float(p50), 1), "p95": round(float(p95), 1), "p99": round(float(p99), 1),
            "mean": round(float(a.mean()), 1), "max": round(float(a.max()), 1)}


def get_ms(url: str) -> tuple[int, float]:
    """GET; returns (HTTP status, round-trip ms). Body is read and dropped."""
    start = time.perf_counter()
    try:
        with urllib.request.urlopen(url, timeout=60) as resp:
            resp.read()
            code = resp.status
    except urllib.error.HTTPError as exc:
        code = exc.code
    return code, (time.perf_counter() - start) * 1000.0


def bench_recognize(base: str, photo: bytes, n: int, warmup: int) -> dict:
    """n timed POSTs of the same photo after ``warmup`` untimed ones."""
    url = f"{base}/plates/recognize"
    for _ in range(warmup):
        post_photo(url, photo)
    trip, server, manual = [], [], 0
    for _ in range(n):
        out, ms = post_photo(url, photo)  # raises on non-200
        trip.append(ms)
        server.append(float(out["ms"]))
        manual += bool(out["needs_manual"])
    return {"calls": n, "ok_200": n, "needs_manual": manual, "round_trip_ms": percentiles(trip),
            "server_ms": percentiles(server), "photo_bytes": len(photo)}


def bench_prediction(base: str, ids: list[int], n: int, warmup: int) -> dict:
    """n timed GETs cycling through vehicle ids after ``warmup`` untimed ones."""
    for i in range(warmup):
        get_ms(f"{base}/vehicles/{ids[i % len(ids)]}/prediction")
    trip, codes = [], {}
    for i in range(n):
        code, ms = get_ms(f"{base}/vehicles/{ids[i % len(ids)]}/prediction")
        codes[str(code)] = codes.get(str(code), 0) + 1
        if code == 200:
            trip.append(ms)
    return {"calls": n, "status_codes": codes, "vehicles": len(ids), "round_trip_ms": percentiles(trip)}


def git_head() -> str:
    """Short hash of HEAD (+ '-dirty' when tracked files changed)."""
    head = subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True).stdout.strip()
    dirty = subprocess.run(["git", "diff", "--quiet", "HEAD", "--", "src"]).returncode != 0
    return head + ("-dirty(src)" if dirty else "")


def main(argv: list[str] | None = None) -> int:
    """Run both benchmarks and write the JSON summary."""
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("--url", default="http://localhost:8001")
    p.add_argument("--n", type=int, default=200)
    p.add_argument("--warmup", type=int, default=10)
    p.add_argument("--vehicle-ids", default="1-40")
    p.add_argument("--photo", type=Path, help="time this photo instead of the synthetic one")
    p.add_argument("--out", type=Path, default=DEFAULT_OUT)
    args = p.parse_args(argv)

    photo = args.photo.read_bytes() if args.photo else synthetic_photo()
    result = {
        "date": date.today().isoformat(),
        "code_commit": git_head(),
        "machine": f"{platform.platform()}, {platform.processor() or platform.machine()}",
        "setup": "uvicorn (1 process) from .venv on the Mac + local Postgres in Docker; one client, "
                 "sequential calls; round trip = urllib on the same machine",
        "photo": "real photo (timings only)" if args.photo else
                 f"synthetic {PHOTO_SIZE[0]}x{PHOTO_SIZE[1]} JPEG, no plate (detector runs, char CNN skipped)",
        "warmup_calls": args.warmup,
        "plates_recognize": bench_recognize(args.url, photo, args.n, args.warmup),
        "vehicle_prediction": bench_prediction(args.url, parse_ids(args.vehicle_ids), args.n, args.warmup),
    }
    args.out.write_text(json.dumps(result, indent=1, ensure_ascii=False) + "\n", encoding="utf-8")
    for k in ("plates_recognize", "vehicle_prediction"):
        print(k, result[k]["round_trip_ms"])
    print(f"-> {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
