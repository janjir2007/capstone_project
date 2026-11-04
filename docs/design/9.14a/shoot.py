"""Screenshots of the 9.14a-3 screens at 390 px (phone) and 1280 px (computer). Dev tool (Playwright).

Needs an API with contract v0.19 + the demo seed (synthetic data only, RISK-06), e.g. on :8011:
    API_URL=http://localhost:8011 .venv/bin/python docs/design/9.14a/shoot.py
Saves card_*.png (truck card: target km big + due day small, «Км бүртгэл · … км/өдөр»; 9.14a-3b),
card_km_confirm_390.png (the confirm step, reached like the oil changer does: «Сануулга» -> «Км шалгах» ->
«Хариу бүртгэх»), reminders_*.png and km_checks_*.png («Сануулга | Км шалгах»). None may scroll sideways.
"""

import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent
UI_DIR = HERE.parent.parent.parent / "src" / "ui"
API_URL = os.environ.get("API_URL", "http://localhost:8011")
PLATE = os.environ.get("PLATE", "1003 УНА")   # demo truck with a driver reply (docs/demo_data.md)
MAX_HEIGHT = 3200


def wait_ok(url: str, seconds: float = 30) -> None:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return
        except OSError:
            time.sleep(0.5)
    raise SystemExit(f"not reachable: {url}")


def shoot(page, name: str, width: int) -> None:
    """Whole content (Streamlit scrolls inside), at most MAX_HEIGHT; fails on a sideways page."""
    page.wait_for_timeout(1200)
    assert page.evaluate("document.documentElement.scrollWidth") <= width, f"{name}: page scrolls sideways"
    height = page.evaluate("Math.ceil(document.querySelector('.block-container').getBoundingClientRect().bottom)")
    page.screenshot(path=str(HERE / name), clip={"x": 0, "y": 0, "width": width, "height": min(height, MAX_HEIGHT)})


def open_card(page, ui: str) -> None:
    page.goto(ui + "/search")
    page.wait_for_selector("text=Камераар хайх", timeout=20000)
    page.get_by_label("Улсын дугаар эсвэл утас").fill(PLATE)
    page.get_by_role("button", name="Хайх", exact=True).click()
    page.wait_for_selector(".st-key-card_km", timeout=15000)


def km_check_reply() -> tuple[int, float]:
    """The first km check due (service id) + a plausible reply: its odometer + 300 km/day since then."""
    with urllib.request.urlopen(f"{API_URL}/km-checks/due", timeout=5) as r:
        first = json.load(r)["checks"][0]
    return first["service_id"], first["odometer_km"] + 300 * first["days_since"]


def main() -> None:
    wait_ok(f"{API_URL}/health", 5)
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        port = s.getsockname()[1]
    env = {**os.environ, "API_URL": API_URL}
    env.pop("UI_PASSWORD", None)
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
                             "--server.headless", "true"], cwd=UI_DIR, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ui = f"http://127.0.0.1:{port}"
    try:
        wait_ok(f"{ui}/_stcore/health")
        with sync_playwright() as p:
            browser = p.chromium.launch()
            for width, scale in ((390, 2), (1280, 1)):
                page = browser.new_page(viewport={"width": width, "height": MAX_HEIGHT}, device_scale_factor=scale,
                                        is_mobile=width < 768, has_touch=width < 768)
                open_card(page, ui)
                shoot(page, f"card_{width}.png", width)
                page.goto(ui + "/reminders")
                page.wait_for_selector(".st-key-rem_tab", timeout=20000)
                shoot(page, f"reminders_{width}.png", width)
                page.locator(".st-key-rem_tab button", has_text="Км шалгах").click()
                page.wait_for_selector("text=Км асуух (", timeout=10000)
                shoot(page, f"km_checks_{width}.png", width)
                if width == 390:  # «Хариу бүртгэх» -> km -> «Үргэлжлүүлэх» = the confirm step (nothing stored)
                    service_id, km = km_check_reply()
                    page.locator(f".st-key-km_reply_{service_id} button").click()
                    page.wait_for_selector(".st-key-card_km_form", timeout=15000)
                    page.get_by_label("Одоогийн км").fill(str(round(km)))
                    page.get_by_role("button", name="Үргэлжлүүлэх").click()
                    page.wait_for_selector(".st-key-card_km_confirm", timeout=10000)
                    shoot(page, "card_km_confirm_390.png", width)
                page.close()
            browser.close()
    finally:
        proc.terminate()
    print("saved:", ", ".join(sorted(f.name for f in HERE.glob("*.png"))))


if __name__ == "__main__":
    main()
