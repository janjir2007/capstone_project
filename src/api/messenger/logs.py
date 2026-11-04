"""Keep the webhook's secrets out of the logs (task 9.15a, P5).

Meta sends the verify token in the query string (GET /messenger/webhook?hub.verify_token=...), and
uvicorn's access log prints the path WITH the query: '%s - "%s %s HTTP/%s" %d' with
args (client, method, path?query, http version, status) (uvicorn 0.54, protocols/http/h11_impl.py).
This filter drops the query of /messenger/webhook lines and blanks any hub.verify_token= value
in any other text of the record.
Our own log lines name the event type and the result only: never a PSID, text, token or secret.
"""

from __future__ import annotations

import logging
import re

WEBHOOK_PATH = "/messenger/webhook"
TOKEN_RE = re.compile(r"(hub\.verify_token=)[^&\s\"']*")
ACCESS_LOGGER = "uvicorn.access"


def _scrub(value: object) -> object:
    if not isinstance(value, str):
        return value
    if value.startswith(WEBHOOK_PATH):
        return value.split("?", 1)[0]
    return TOKEN_RE.sub(r"\1***", value)


class HideWebhookQuery(logging.Filter):
    """Rewrites the record's args (it never drops a line)."""

    def filter(self, record: logging.LogRecord) -> bool:
        if isinstance(record.args, tuple):
            record.args = tuple(_scrub(a) for a in record.args)
        if isinstance(record.msg, str):
            record.msg = TOKEN_RE.sub(r"\1***", record.msg)
        return True


def install_log_filter() -> None:
    """Add the filter to uvicorn's access logger once (create_app may run several times in tests)."""
    logger = logging.getLogger(ACCESS_LOGGER)
    if not any(isinstance(f, HideWebhookQuery) for f in logger.filters):
        logger.addFilter(HideWebhookQuery())
