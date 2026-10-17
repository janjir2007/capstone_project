"""Tests for task 1.6: src/data/external_api.py (OSRM road km, cache, skip rules).

The API is NEVER called: every test passes a fake ``fetch`` that returns a
saved-style OSRM answer and counts its calls.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest
import yaml

from src.data import external_api as X

CONFIG = Path("configs/routes_1_6.yaml")
POINTS = {"a": X.Point(106.9, 47.9), "b": X.Point(106.5, 50.3), "c": X.Point(107.6, 51.8)}
ROUTE = {"name": "Ulan-Ude (test)", "name_mn": "Улаан-Үд", "route_category": "mn_russia",
         "start": "a", "crossing": "b", "destination": "c"}


def ok_answer(metres: float, snaps: tuple[float, ...] = (10.0, 10.0, 10.0)) -> dict:
    """Shape of a real OSRM 'Ok' answer (only the fields the code reads)."""
    return {"code": "Ok", "routes": [{"distance": metres, "duration": 1.0, "legs": []}],
            "waypoints": [{"distance": s} for s in snaps]}


class FakeFetch:
    """Returns one fixed answer and remembers which URLs were asked."""

    def __init__(self, answer: dict) -> None:
        self.answer, self.urls = answer, []

    def __call__(self, url: str) -> dict:
        self.urls.append(url)
        return self.answer


# ---------------- request / answer ----------------

def test_url_goes_through_the_crossing_in_order() -> None:
    url = X.osrm_url([POINTS["a"], POINTS["b"], POINTS["c"]])
    assert url == ("https://router.project-osrm.org/route/v1/driving/"
                   "106.9000000,47.9000000;106.5000000,50.3000000;107.6000000,51.8000000?overview=false")


def test_parse_ok_gives_km() -> None:
    assert X.parse_osrm(ok_answer(578_123.4), 2000) == (pytest.approx(578.1234), "")


@pytest.mark.parametrize("answer", [
    {"code": "NoRoute", "message": "Impossible route between points"},
    {"code": "Ok", "routes": []},
    {"code": "InvalidQuery"},
])
def test_parse_no_route_gives_none(answer: dict) -> None:
    km, reason = X.parse_osrm(answer, 2000)
    assert km is None and reason


def test_point_far_from_any_road_is_no_route() -> None:
    """OSRM snaps to the nearest road even 50 km away; that is not a real route."""
    km, reason = X.parse_osrm(ok_answer(900_000, snaps=(10, 50_000, 10)), 2000)
    assert km is None and "[1]" in reason


# ---------------- one route ----------------

def test_route_ok_rounds_km_and_keeps_source() -> None:
    fetch = FakeFetch(ok_answer(577_600))
    r = X.resolve_route(ROUTE, POINTS, {}, {}, fetch, 2000)
    assert (r.status, r.one_way_km) == ("ok", 578)
    assert r.source == fetch.urls[0]


def test_no_route_gets_no_km() -> None:
    r = X.resolve_route(ROUTE, POINTS, {}, {}, FakeFetch({"code": "NoRoute"}), 2000)
    assert (r.status, r.one_way_km) == ("no_route", None)


@pytest.mark.parametrize("taken", ["Улаан-Үд", "  ulan-ude (TEST) "])
def test_existing_destination_is_skipped_without_api_call(taken: str) -> None:
    fetch = FakeFetch(ok_answer(1))
    existing = X.existing_names([{"name": "Old place", "aliases": [taken]}])
    r = X.resolve_route(ROUTE, POINTS, existing, {}, fetch, 2000)
    assert r.status == "skipped_existing" and r.one_way_km is None
    assert "Old place" in r.reason
    assert fetch.urls == []


def test_a_route_is_not_a_duplicate_of_itself() -> None:
    """After migration 005 the route is in cleaning.yaml too; a rerun must still give its km."""
    existing = X.existing_names([{"name": ROUTE["name"], "aliases": [ROUTE["name_mn"]]}], exclude=[ROUTE["name"]])
    assert existing == {}


# ---------------- cache ----------------

def test_cache_second_run_makes_no_call(tmp_path: Path) -> None:
    path = tmp_path / "osrm_cache.json"
    fetch = FakeFetch(ok_answer(247_000))
    cache = X.load_cache(path)
    X.resolve_route(ROUTE, POINTS, {}, cache, fetch, 2000)
    X.save_cache(path, cache)

    again = FakeFetch(ok_answer(1))  # would give a wrong km if it were used
    r = X.resolve_route(ROUTE, POINTS, {}, X.load_cache(path), again, 2000)
    assert r.one_way_km == 247
    assert again.urls == [] and len(fetch.urls) == 1


def test_missing_cache_file_is_empty(tmp_path: Path) -> None:
    assert X.load_cache(tmp_path / "nope.json") == {}


# ---------------- the real 1.6 config ----------------

def test_config_routes_use_known_points_and_categories() -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    assert len(cfg["routes"]) == 4
    for r in cfg["routes"]:
        assert {r["start"], r["crossing"], r["destination"]} <= cfg["points"].keys()
        assert r["route_category"] in {"mn_china", "mn_russia"}  # D-081: categories stay


def test_config_resolves_with_fake_fetch_one_call_per_route() -> None:
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    cleaning = yaml.safe_load(Path("configs/cleaning.yaml").read_text(encoding="utf-8"))["destinations"]
    fetch = FakeFetch(ok_answer(500_000))
    results = X.resolve_routes(cfg, cleaning, {}, fetch)
    assert [r.status for r in results] == ["ok"] * 4  # none of Ari's 4 is an existing destination
    assert len(set(fetch.urls)) == 4


def test_generator_and_migration_use_the_config_routes() -> None:
    """configs/generator.yaml and migration 005 carry the same name, km and OSRM link."""
    cfg = yaml.safe_load(CONFIG.read_text(encoding="utf-8"))
    gen = {d["name"]: d for d in yaml.safe_load(Path("configs/generator.yaml").read_text(encoding="utf-8"))["destinations"]}
    sql = Path("src/data/migrations/005_destinations_cross_border.up.sql").read_text(encoding="utf-8")
    points = {k: X.Point(p["lon"], p["lat"]) for k, p in cfg["points"].items()}
    for r in cfg["routes"]:
        url = X.osrm_url(points[r[k]] for k in ("start", "crossing", "destination"))
        assert gen[r["name"]]["tag"] == f"[SOURCE: OSRM {url}]"
        row = rf"'{re.escape(r['name'])}',\s*'{r['name_mn']}',\s*'{r['route_category']}',\s*{gen[r['name']]['one_way_km']},\s*'{re.escape(url)}'"
        assert re.search(row, sql), r["name"]
