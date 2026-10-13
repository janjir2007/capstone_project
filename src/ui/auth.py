"""Simple password gate (D-061).

The password comes from the env var UI_PASSWORD. If it is unset or empty
(local development), there is no login. This module has no Streamlit import:
the screen itself is in app.py.
"""

import hmac
import os


def required_password() -> str | None:
    """The configured UI password, or None when login is disabled."""
    return os.environ.get("UI_PASSWORD") or None


def login_required() -> bool:
    """True when UI_PASSWORD is set, i.e. the login screen must be shown."""
    return required_password() is not None


def check_password(entered: str | None) -> bool:
    """Compare the entered password with UI_PASSWORD in constant time.

    Always True when login is disabled. compare_digest avoids leaking how many
    leading characters were right through response timing.
    """
    expected = required_password()
    if expected is None:
        return True
    return hmac.compare_digest((entered or "").encode(), expected.encode())
