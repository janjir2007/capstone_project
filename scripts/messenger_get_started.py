"""Check the Page's Messenger «Get Started» button + greeting; set them only when missing (task 9.15a-3).

A driver who opens the m.me link in a NEW thread taps Get Started; that sends a ``messaging_postbacks``
event with the link's ref inside (plan §4.2). The bot answers EVERY postback the same way, whatever its
payload (src/api/messenger/flow.py: link the ref + GREETING). So any non-empty payload already works —
e.g. the one set earlier (likely by n8n) — and is left as it is. Only a Page with no Get Started payload
gets ours (GET_STARTED); the greeting is added only when the Page has none, so nothing set before is
overwritten.

Run on the server inside the api container (reads META_PAGE_TOKEN / META_GRAPH_VERSION from .env):
    docker compose -f docker-compose.prod.yml exec api python -m scripts.messenger_get_started
Prints the current payload + greeting and what it did; never the token.

Meta (verified 2026-11-05, developers.facebook.com/docs/messenger-platform/reference/messenger-profile-api
and .../discovery/welcome-screen): GET / POST https://graph.facebook.com/<version>/me/messenger_profile
?access_token=<Page token>; GET takes ?fields=get_started,greeting and answers {"data": [{...}]}; POST
{"get_started": {"payload": ...}, "greeting": [{"locale": "default", "text": ...}]} -> {"result":
"success"}; at most 10 calls per 10 minutes per Page. The greeting's length limit is NOT stated on those
pages (needs verification; ours is short).
"""

from __future__ import annotations

import json
import sys
import urllib.error
import urllib.request
from collections.abc import Callable
from typing import Any
from urllib.parse import quote, urlencode

from src.api.config import ConfigError, MessengerSettings, messenger_settings
from src.api.messenger import texts
from src.api.messenger.send import GRAPH_HOST, TIMEOUT_SECONDS

# (method, url, body or None) -> (HTTP status, decoded JSON). Tests pass a fake; no network in tests.
Fetch = Callable[[str, str, dict[str, Any] | None], tuple[int, dict[str, Any]]]
FIELDS = {"fields": "get_started,greeting"}


def profile_url(settings: MessengerSettings, query: dict[str, str] | None = None) -> str:
    """The Messenger Profile URL. Holds the token: never printed or logged."""
    params = {**(query or {}), "access_token": settings.page_token}
    return f"{GRAPH_HOST}/{quote(settings.graph_version, safe='.')}/me/messenger_profile?{urlencode(params)}"


def graph_fetch(method: str, url: str, body: dict[str, Any] | None) -> tuple[int, dict[str, Any]]:
    """The real call (standard library only, like src/api/messenger/send.py)."""
    data = None if body is None else json.dumps(body).encode("utf-8")
    request = urllib.request.Request(url, data=data, method=method, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(request, timeout=TIMEOUT_SECONDS) as response:  # noqa: S310 (fixed https host)
            return response.status, json.loads(response.read() or b"{}")
    except urllib.error.HTTPError as exc:
        try:
            return exc.code, json.loads(exc.read() or b"{}")
        except ValueError:
            return exc.code, {}


def meta_error(status: int, answer: dict[str, Any], token: str) -> str:
    """'HTTP 400, code 190 (OAuthException): ...' with the token cut out, just in case."""
    error = answer.get("error") if isinstance(answer.get("error"), dict) else {}
    text = f"HTTP {status}, code {error.get('code', '?')} ({error.get('type', '?')}): {error.get('message', '')}"
    return text.replace(token, "***") if token else text


def current_profile(answer: dict[str, Any]) -> tuple[str | None, str | None]:
    """(get_started payload, default-locale greeting) from a GET answer; None when not set."""
    data = answer.get("data")
    first = data[0] if isinstance(data, list) and data and isinstance(data[0], dict) else {}
    payload = (first.get("get_started") or {}).get("payload")
    greetings = [g.get("text") for g in first.get("greeting") or [] if isinstance(g, dict)]
    default = next((g.get("text") for g in first.get("greeting") or []
                    if isinstance(g, dict) and g.get("locale") == "default"), None)
    return (payload if isinstance(payload, str) and payload else None,
            default or (greetings[0] if greetings else None))


def bot_handles(payload: str | None) -> bool:
    """The bot answers every postback (flow.py), so any non-empty payload works."""
    return bool(payload)


def missing_body(payload: str | None, greeting: str | None) -> dict[str, Any]:
    """What to POST: only the parts the Page does not have yet (empty = nothing to set)."""
    body: dict[str, Any] = {}
    if not bot_handles(payload):
        body["get_started"] = {"payload": texts.GET_STARTED_PAYLOAD}
        if greeting is None:  # a greeting only with a new button: never replace one set before
            body["greeting"] = [{"locale": "default", "text": texts.PROFILE_GREETING}]
    return body


def read(settings: MessengerSettings, fetch: Fetch, out: Callable[[str], None],
         label: str) -> tuple[str | None, str | None] | None:
    """GET the profile and print it; None (after printing why) when Meta refuses or is not reachable."""
    try:
        status, answer = fetch("GET", profile_url(settings, FIELDS), None)
    except (urllib.error.URLError, OSError) as exc:
        out(f"FAILED: Meta not reachable ({type(exc).__name__})")
        return None
    if status != 200:
        out(f"FAILED: {meta_error(status, answer, settings.page_token)}")
        return None
    payload, greeting = current_profile(answer)
    out(f"{label}: get_started payload = {payload!r}")
    out(f"{label}: greeting = {greeting!r}")
    return payload, greeting


def check_get_started(settings: MessengerSettings, fetch: Fetch = graph_fetch,
                      out: Callable[[str], None] = print) -> bool:
    """Print the current button + greeting; set the button only when it is missing. True = a working
    Get Started button is on the Page at the end."""
    if not settings.page_token or not settings.graph_version:
        out("FAILED: META_PAGE_TOKEN and META_GRAPH_VERSION must be set in .env")
        return False
    now = read(settings, fetch, out, "current")
    if now is None:
        return False
    body = missing_body(*now)
    if not body:
        out("OK: Get Started is set and the bot answers it (every postback) — nothing changed")
        return True
    try:
        status, answer = fetch("POST", profile_url(settings), body)
    except (urllib.error.URLError, OSError) as exc:
        out(f"FAILED: Meta not reachable ({type(exc).__name__})")
        return False
    if status != 200 or answer.get("result") != "success":
        out(f"FAILED: {meta_error(status, answer, settings.page_token)}")
        return False
    out(f"set: {', '.join(body)} (result: success)")
    after = read(settings, fetch, out, "after")
    ok = after is not None and bot_handles(after[0])
    out("OK: Get Started is set" if ok else "NOT SET: Meta did not keep the button")
    return ok


def main() -> int:
    try:
        settings = messenger_settings()
    except ConfigError as exc:  # names the setting only, never a value
        print(f"FAILED: {exc}")
        return 1
    return 0 if check_get_started(settings) else 1


if __name__ == "__main__":
    sys.exit(main())
