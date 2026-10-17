"""Road distances from the OSRM API for the new cross-border routes (Task 1.6, also R1).

One route = start -> border crossing -> destination (configs/routes_1_6.yaml).
OSRM (the routing engine on OpenStreetMap data, same server as the
distances in migration 001) is asked for the driving route through those
three points; the crossing is a waypoint, so the route must pass it.

Rules (1.6 brief):
- one-way road km, start -> crossing -> destination (round trip = 2 x one-way,
  done later by the generator, synthetic_rules §1);
- a route whose name or Mongolian name already belongs to another destination
  is SKIPPED (reported, no API call);
- if OSRM finds no road (code "NoRoute"), or a point is farther than
  ``max_snap_m`` from any road (OSRM would silently start on a far road),
  the route is reported as "no_route" and gets NO km — we never guess;
- every answer is cached in a JSON file, keyed by the request URL, so a second
  run makes no API call. Tests pass their own ``fetch`` and never use the network.

Run:  python -m src.data.external_api [--config configs/routes_1_6.yaml]
      (prints one line per route + the OSRM link to put in the config as source)
"""

from __future__ import annotations

import argparse
import json
import urllib.error
import urllib.request
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_CONFIG = Path("configs/routes_1_6.yaml")
CLEANING_CONFIG = Path("configs/cleaning.yaml")
OSRM_BASE = "https://router.project-osrm.org/route/v1/driving/"
USER_AGENT = "oil-change-predictor-capstone/1.0 (task 1.6)"

# fetch(url) -> parsed JSON answer. The real one calls the API; tests pass a fake.
Fetch = Callable[[str], dict]


@dataclass(frozen=True)
class Point:
    """A place on the map (WGS84 degrees)."""

    lon: float
    lat: float


@dataclass(frozen=True)
class RouteResult:
    """What happened to one route line."""

    name: str
    name_mn: str
    route_category: str
    status: str  # "ok", "skipped_existing" or "no_route"
    one_way_km: int | None
    source: str | None  # OSRM URL (None when skipped)
    reason: str = ""


# ---------------------------------------------------------------------------
# OSRM request / answer
# ---------------------------------------------------------------------------

def osrm_url(points: Iterable[Point]) -> str:
    """OSRM route URL through ``points`` in order ("lon,lat;lon,lat;...")."""
    coords = ";".join(f"{p.lon:.7f},{p.lat:.7f}" for p in points)
    return f"{OSRM_BASE}{coords}?overview=false"


def http_fetch(url: str, timeout_s: float = 30.0) -> dict:
    """GET ``url`` and parse the JSON answer (the real API call)."""
    request = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    try:
        with urllib.request.urlopen(request, timeout=timeout_s) as response:
            return json.load(response)
    except urllib.error.HTTPError as exc:  # OSRM answers 400 with a JSON body, e.g. code "NoRoute"
        return json.load(exc)


def parse_osrm(answer: dict, max_snap_m: float) -> tuple[float | None, str]:
    """(one-way km, "") from an OSRM answer, or (None, reason) if there is no usable road route."""
    if answer.get("code") != "Ok" or not answer.get("routes"):
        return None, f"OSRM code {answer.get('code')!r}: {answer.get('message', 'no route')}"
    # waypoints[i].distance = metres from the given point to the road OSRM snapped it to.
    snaps = [w.get("distance", 0.0) for w in answer.get("waypoints", [])]
    far = [i for i, s in enumerate(snaps) if s > max_snap_m]
    if far:
        return None, f"point(s) {far} are {[round(snaps[i]) for i in far]} m from the nearest road (> {max_snap_m:.0f} m)"
    return answer["routes"][0]["distance"] / 1000.0, ""


# ---------------------------------------------------------------------------
# Cache
# ---------------------------------------------------------------------------

def load_cache(path: Path) -> dict[str, dict]:
    """URL -> saved OSRM answer ({} if the file does not exist yet)."""
    if not path.exists():
        return {}
    return json.loads(path.read_text(encoding="utf-8"))


def save_cache(path: Path, cache: dict[str, dict]) -> None:
    """Write the cache (sorted keys -> stable file)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(cache, ensure_ascii=False, indent=1, sort_keys=True), encoding="utf-8")


def cached_answer(url: str, cache: dict[str, dict], fetch: Fetch) -> dict:
    """The OSRM answer for ``url``: from the cache, else fetched and added to the cache."""
    if url not in cache:
        cache[url] = fetch(url)
    return cache[url]


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

def name_key(text: str) -> str:
    """Comparison key for names: trimmed, single spaces, case-folded."""
    return " ".join(text.split()).casefold()


def existing_names(destinations: list[dict], exclude: Iterable[str] = ()) -> dict[str, str]:
    """{name key: destination name} for every name and alias of the current destinations.

    ``destinations`` = cleaning.yaml's list (name + aliases, aliases include the
    Mongolian label). Destinations in ``exclude`` are left out, so a 1.6 route
    that was already added does not count as a duplicate of itself.
    """
    skip = {name_key(n) for n in exclude}
    keys: dict[str, str] = {}
    for d in destinations:
        if name_key(d["name"]) in skip:
            continue
        for text in [d["name"], *d.get("aliases", [])]:
            keys[name_key(text)] = d["name"]
    return keys


def resolve_route(route: dict, points: dict[str, Point], existing: dict[str, str],
                  cache: dict[str, dict], fetch: Fetch, max_snap_m: float) -> RouteResult:
    """One route line -> RouteResult (skipped / no_route / ok with km)."""
    base = {"name": route["name"], "name_mn": route["name_mn"], "route_category": route["route_category"]}
    for text in (route["name"], route["name_mn"]):
        if name_key(text) in existing:
            return RouteResult(**base, status="skipped_existing", one_way_km=None, source=None,
                               reason=f"{text!r} is already destination {existing[name_key(text)]!r}")
    url = osrm_url(points[route[k]] for k in ("start", "crossing", "destination"))
    km, reason = parse_osrm(cached_answer(url, cache, fetch), max_snap_m)
    if km is None:
        return RouteResult(**base, status="no_route", one_way_km=None, source=url, reason=reason)
    return RouteResult(**base, status="ok", one_way_km=round(km), source=url)


def resolve_routes(cfg: dict, destinations: list[dict], cache: dict[str, dict], fetch: Fetch) -> list[RouteResult]:
    """All route lines of the 1.6 config, in config order."""
    points = {key: Point(p["lon"], p["lat"]) for key, p in cfg["points"].items()}
    existing = existing_names(destinations, exclude=[r["name"] for r in cfg["routes"]])
    return [resolve_route(r, points, existing, cache, fetch, cfg["max_snap_m"]) for r in cfg["routes"]]


# ---------------------------------------------------------------------------
# Command line
# ---------------------------------------------------------------------------

def load_yaml(path: Path) -> dict:
    """Read a UTF-8 YAML file."""
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def main(argv: list[str] | None = None) -> int:
    """Resolve every route (cached API calls) and print the results."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=DEFAULT_CONFIG)
    parser.add_argument("--cleaning-config", type=Path, default=CLEANING_CONFIG,
                        help="current destinations (name + aliases) for the duplicate check")
    args = parser.parse_args(argv)

    cfg = load_yaml(args.config)
    cache_path = Path(cfg["cache_path"])
    cache = load_cache(cache_path)
    results = resolve_routes(cfg, load_yaml(args.cleaning_config)["destinations"], cache, http_fetch)
    save_cache(cache_path, cache)
    for r in results:
        km = f"{r.one_way_km} km" if r.one_way_km is not None else "-"
        print(f"{r.status:17} {r.name_mn:10} {r.name:48} {km:>8}  {r.reason}")
        if r.source:
            print(f"{'':17} source: {r.source}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
