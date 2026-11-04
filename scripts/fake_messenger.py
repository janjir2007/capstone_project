"""Send a fake, correctly SIGNED Messenger event to a local API (task 9.15a-2; no Meta needed).

    python -m scripts.fake_messenger --text "9988НАА 871234"
    python -m scripts.fake_messenger --text "Тийм" --yes
    python -m scripts.fake_messenger --ref K7Q2M9XA            # an m.me link tap

Reads META_APP_SECRET and META_PAGE_ID from the environment (the same values as the local API's
.env; the API needs MESSENGER_ENABLED=true). Prints only the HTTP status. The bot's reply goes to
Meta's Send API, which refuses a fake page token: the API logs "messenger reply not sent" — see the
result in the database (messenger_pending, odometer_readings source 'messenger').
For local use only: never point it at the live server.
"""

from __future__ import annotations

import argparse
import hashlib
import hmac
import json
import os
import sys
import time
import urllib.error
import urllib.request

DEFAULT_URL = "http://localhost:8000/messenger/webhook"


def build_event(psid: str, text: str | None, ref: str | None, yes: bool, now_ms: int) -> dict:
    """One Meta-shaped delivery with one event."""
    if ref:
        event = {"referral": {"ref": ref, "source": "SHORTLINK", "type": "OPEN_THREAD"}}
    else:
        message: dict = {"mid": f"fake.{now_ms}", "text": text or ""}
        if yes:
            message["quick_reply"] = {"payload": "KM_YES"}
        event = {"message": message}
    page = os.environ.get("META_PAGE_ID", "")
    return {"object": "page", "entry": [{"id": page, "time": now_ms, "messaging": [
        {"sender": {"id": psid}, "recipient": {"id": page}, "timestamp": now_ms, **event}]}]}


def signature(secret: str, body: bytes) -> str:
    return "sha256=" + hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--psid", default="1000000000000001", help="fake Facebook id (digits)")
    parser.add_argument("--text")
    parser.add_argument("--ref")
    parser.add_argument("--yes", action="store_true", help="send as a «Тийм» quick-reply tap")
    parser.add_argument("--url", default=DEFAULT_URL)
    args = parser.parse_args(argv)
    secret = os.environ.get("META_APP_SECRET", "")
    if not secret:
        print("Set META_APP_SECRET (the local API's value).", file=sys.stderr)
        return 2
    body = json.dumps(build_event(args.psid, args.text, args.ref, args.yes, int(time.time() * 1000))).encode("utf-8")
    request = urllib.request.Request(args.url, data=body, method="POST", headers={
        "Content-Type": "application/json", "X-Hub-Signature-256": signature(secret, body)})
    try:
        with urllib.request.urlopen(request, timeout=10) as response:  # noqa: S310 (local URL by the user)
            print(response.status)
    except urllib.error.HTTPError as exc:
        print(exc.code)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
