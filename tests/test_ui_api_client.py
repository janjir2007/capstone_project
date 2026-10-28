"""Tests for src/ui/api_client.py with a mocked network (httpx.MockTransport).

Needs only httpx (already in requirements.txt), so it runs in CI.
"""

import json

import httpx
import pytest

from src.ui import api_client


@pytest.fixture
def requests_seen(monkeypatch):
    """Install a mock transport; yields (list of requests, function to set the reply)."""
    seen: list[httpx.Request] = []
    reply = {"response": httpx.Response(200, json={})}

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return reply["response"]

    monkeypatch.delenv("API_URL", raising=False)
    api_client.set_transport(httpx.MockTransport(handler))
    yield seen, lambda resp: reply.update(response=resp)
    api_client.set_transport(None)


def test_api_url_default_and_env(monkeypatch) -> None:
    monkeypatch.delenv("API_URL", raising=False)
    assert api_client.api_url() == "http://localhost:8000"
    monkeypatch.setenv("API_URL", "https://api.example.test/")
    assert api_client.api_url() == "https://api.example.test"


def test_lookup_sends_query(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json={"query": "0001 тес", "match_type": "plate", "normalized": "0001ТЕС", "vehicles": []}))
    result = api_client.lookup("0001 тес")
    assert result["vehicles"] == []
    assert seen[0].method == "GET"
    assert seen[0].url.path == "/vehicles/lookup"
    assert seen[0].url.params["q"] == "0001 тес"
    assert str(seen[0].url).startswith("http://localhost:8000/")


def test_uses_api_url_env(requests_seen, monkeypatch) -> None:
    seen, _ = requests_seen
    monkeypatch.setenv("API_URL", "https://api.example.test")
    api_client.destinations()
    assert seen[0].url.host == "api.example.test"


def test_create_service_posts_json(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(201, json={"service": {}, "vehicle_id": 7, "vehicle_created": True, "company_created": False}))
    result = api_client.create_service({"identifier": "0001 ТЕС"})
    assert result["vehicle_id"] == 7
    assert seen[0].method == "POST"
    assert seen[0].url.path == "/services"
    assert "force" not in seen[0].url.params
    assert json.loads(seen[0].content) == {"identifier": "0001 ТЕС"}


def test_create_service_force(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(201, json={"vehicle_id": 7}))
    api_client.create_service({"identifier": "0001 ТЕС"}, force=True)
    assert seen[0].url.params["force"] == "true"


def test_duplicate_raises_duplicate_service(requests_seen) -> None:
    _, set_reply = requests_seen
    detail = {"code": "duplicate_service", "message": "already serviced", "existing_service_id": 12}
    set_reply(httpx.Response(409, json={"detail": detail}))
    with pytest.raises(api_client.DuplicateService) as info:
        api_client.create_service({"identifier": "0001 ТЕС"})
    assert info.value.status == 409
    assert info.value.existing_service_id == 12


def test_other_409_is_plain_api_error(requests_seen) -> None:
    _, set_reply = requests_seen
    set_reply(httpx.Response(409, json={"detail": "conflict with existing data; nothing saved, retry"}))
    with pytest.raises(api_client.ApiError) as info:
        api_client.create_service({})
    assert not isinstance(info.value, api_client.DuplicateService)
    assert info.value.detail.startswith("conflict")


def test_422_detail_kept(requests_seen) -> None:
    _, set_reply = requests_seen
    set_reply(httpx.Response(422, json={"detail": [{"msg": "Value error, x"}]}))
    with pytest.raises(api_client.ApiError) as info:
        api_client.create_service({})
    assert info.value.status == 422
    assert info.value.detail == [{"msg": "Value error, x"}]


def test_non_json_error_body(requests_seen) -> None:
    _, set_reply = requests_seen
    set_reply(httpx.Response(502, text="Bad Gateway"))
    with pytest.raises(api_client.ApiError) as info:
        api_client.destinations()
    assert info.value.status == 502
    assert info.value.detail == "Bad Gateway"


def test_connection_error_is_status_0() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("refused", request=request)

    api_client.set_transport(httpx.MockTransport(handler))
    try:
        with pytest.raises(api_client.ApiError) as info:
            api_client.destinations()
        assert info.value.status == 0
    finally:
        api_client.set_transport(None)


def test_get_vehicle_and_destinations_paths(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json=[]))
    api_client.destinations()
    api_client.get_vehicle(5)
    assert [r.url.path for r in seen] == ["/destinations", "/vehicles/5"]


def test_recognize_plate_sends_multipart(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json={"plate_raw": "0001 ТЕС", "needs_manual": False}))
    api_client.recognize_plate(b"fake-jpeg-bytes", "truck.jpg")
    assert seen[0].url.path == "/plates/recognize"
    assert seen[0].headers["content-type"].startswith("multipart/form-data")
    assert b'name="file"; filename="truck.jpg"' in seen[0].read()  # contract v0.5 field name


# --- reminders dashboard (5.4, contract v0.5) ------------------------------------------

def test_segment_stats_and_reminders_due_paths(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json={}))
    api_client.segment_stats()
    api_client.reminders_due(as_of="2026-10-12")
    assert [r.url.path for r in seen] == ["/stats/segments", "/reminders/due"]
    assert "as_of" not in seen[0].url.params
    assert seen[1].url.params["as_of"] == "2026-10-12"


def test_mark_reminder_sent_already_sent(requests_seen) -> None:
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json={"id": 1, "service_id": 7, "already_sent": True}))
    row = api_client.mark_reminder_sent(7)
    assert row["already_sent"] is True
    assert (seen[0].method, seen[0].url.path) == ("POST", "/reminders/7/sent")


def test_search_vehicles_get_with_query_and_limit(requests_seen) -> None:
    """9.1: dashboard search is a GET (read only), blank q allowed."""
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json={"query": "", "total": 0, "vehicles": []}))
    api_client.search_vehicles()
    api_client.search_vehicles("говь", limit=50)
    assert [(r.method, r.url.path) for r in seen] == [("GET", "/vehicles/search")] * 2
    assert (seen[0].url.params["q"], seen[0].url.params["limit"]) == ("", "200")
    assert (seen[1].url.params["q"], seen[1].url.params["limit"]) == ("говь", "50")


def test_search_vehicles_sends_only_used_filters(requests_seen) -> None:
    from datetime import date
    seen, set_reply = requests_seen
    set_reply(httpx.Response(200, json={"query": "", "total": 0, "vehicles": []}))
    api_client.search_vehicles(filters={"date_from": date(2026, 10, 1), "date_to": None, "company_id": 3,
                                        "route": "mn_china", "oil_grade": None})
    assert dict(seen[0].url.params) == {"q": "", "limit": "200", "date_from": "2026-10-01",
                                        "company_id": "3", "route": "mn_china"}


def test_mark_reminder_not_latest(requests_seen) -> None:
    _, set_reply = requests_seen
    set_reply(httpx.Response(409, json={"detail": {"code": "not_latest_service", "message": "newer",
                                                   "latest_service_id": 9}}))
    with pytest.raises(api_client.NotLatestService):
        api_client.mark_reminder_sent(7)
