"""OPT-IN real-browser check of the UI at phone width (~390 px) + screenshots.

Skipped unless UI_BROWSER=1 (needs Playwright, a running API and Chrome), so the
normal `pytest` run and CI are unchanged. It starts Streamlit itself from src/ui/
(theme loads), opens every screen in a 390×844 phone viewport, checks there is no
sideways scroll, and saves screenshots for the slides.

Run (repo root, API up on :8000, e.g. `docker compose up -d`):
    pip install playwright==1.55.0          # dev tool only, not in requirements-ui.txt
    playwright install chromium             # once: Playwright's own browser (~82 MB)
    UI_BROWSER=1 pytest -v tests/test_ui_browser.py
Options (env):
    API_URL              default http://localhost:8000
    UI_BROWSER_PLATE     a plate that exists in the DB -> also checks its vehicle card (demo: "1001 УБА")
    UI_SCREENSHOT_DIR    folder for PNGs (default: pytest's tmp dir). PNGs are git-ignored.
    UI_BROWSER_CHANNEL   unset = Playwright's Chromium (default) · "chrome" = installed Google Chrome
"""

import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import pytest

if os.environ.get("UI_BROWSER") != "1":
    pytest.skip("opt-in: set UI_BROWSER=1 (see module docstring)", allow_module_level=True)
playwright = pytest.importorskip("playwright.sync_api")

UI_DIR = Path(__file__).resolve().parent.parent / "src" / "ui"
API_URL = os.environ.get("API_URL", "http://localhost:8000").rstrip("/")
PHONE = {"width": 390, "height": 844}
# path -> text that proves the screen rendered
SCREENS = {
    "/": "Тос солилт",
    "/record": "Дугаарыг гараар оруулах",
    "/search": "Камераар хайх",
    "/reminders": "Сегмент",
}


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_ok(url: str, seconds: float) -> bool:
    deadline = time.time() + seconds
    while time.time() < deadline:
        try:
            urllib.request.urlopen(url, timeout=2)
            return True
        except OSError:
            time.sleep(0.5)
    return False


@pytest.fixture(scope="module")
def ui_url():
    """Streamlit started from src/ui/ on a free port, login off, pointing at API_URL."""
    if not _wait_ok(f"{API_URL}/health", 3):
        pytest.skip(f"API not reachable at {API_URL}")
    port = _free_port()
    env = {**os.environ, "API_URL": API_URL}
    env.pop("UI_PASSWORD", None)
    proc = subprocess.Popen(
        [sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
         "--server.headless", "true"],
        cwd=UI_DIR, env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
    )
    try:
        assert _wait_ok(f"http://127.0.0.1:{port}/_stcore/health", 30), "Streamlit did not start"
        yield f"http://127.0.0.1:{port}"
    finally:
        proc.terminate()
        proc.wait(timeout=10)


@pytest.fixture(scope="module")
def phone_page():
    channel = os.environ.get("UI_BROWSER_CHANNEL") or None
    with playwright.sync_playwright() as p:
        browser = p.chromium.launch(channel=channel)
        page = browser.new_page(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True)
        yield page
        browser.close()


@pytest.fixture(scope="module")
def shot_dir(tmp_path_factory) -> Path:
    folder = Path(os.environ.get("UI_SCREENSHOT_DIR") or tmp_path_factory.mktemp("ui_screens"))
    folder.mkdir(parents=True, exist_ok=True)
    return folder


def _check_phone_width(page, shot_dir: Path, name: str) -> None:
    page.wait_for_timeout(800)  # let Streamlit finish drawing
    width = page.evaluate("document.documentElement.scrollWidth")
    page.screenshot(path=str(shot_dir / f"{name}.png"), full_page=True)
    assert width <= PHONE["width"], f"{name}: page is {width}px wide (sideways scroll at 390px)"


@pytest.mark.parametrize("path", list(SCREENS))
def test_screen_fits_phone(ui_url, phone_page, shot_dir, path) -> None:
    phone_page.goto(ui_url + path)
    phone_page.wait_for_selector(f"text={SCREENS[path]}", timeout=20000)
    _check_phone_width(phone_page, shot_dir, "screen_" + (path.strip("/") or "home"))


def test_theme_loaded(ui_url, phone_page) -> None:
    """Started from src/ui/ -> .streamlit/config.toml applies (background #F6F7F9)."""
    phone_page.goto(ui_url + "/")
    phone_page.wait_for_selector("text=Тос солилт", timeout=20000)
    bg = phone_page.evaluate("getComputedStyle(document.querySelector('.stApp')).backgroundColor")
    assert bg == "rgb(246, 247, 249)"


def test_vehicle_card_fits_phone(ui_url, phone_page, shot_dir) -> None:
    plate = os.environ.get("UI_BROWSER_PLATE")
    if not plate:
        pytest.skip("set UI_BROWSER_PLATE to a plate in the DB to check the card")
    phone_page.goto(ui_url + "/search")
    phone_page.wait_for_selector("text=Камераар хайх", timeout=20000)
    phone_page.get_by_label("Улсын дугаар эсвэл утас").fill(plate)
    phone_page.get_by_role("button", name="Хайх", exact=True).click()
    phone_page.wait_for_selector(".plate", timeout=15000)
    _check_phone_width(phone_page, shot_dir, "screen_card")


def test_header_not_hidden_and_light_buttons(ui_url, phone_page) -> None:
    """CSS regressions AppTest cannot see: the header row must sit below Streamlit's top bar
    (T6), and secondary buttons in a card are borderless grey (T7: no outlines)."""
    phone_page.goto(ui_url + "/search")
    phone_page.wait_for_selector("text=Камераар хайх", timeout=20000)
    phone_page.wait_for_timeout(800)
    pill = phone_page.locator(".geo-pill").bounding_box()
    bar = phone_page.locator('[data-testid="stHeader"]').bounding_box()
    assert pill["y"] >= bar["y"] + bar["height"], "header row hidden under the top bar"
    bg, border = phone_page.locator(".st-key-btn_cam button").evaluate(
        "e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).borderTopStyle]")
    assert (bg, border) == ("rgb(243, 244, 246)", "none")


MAX_WEIGHT_JS = """() => Math.max(0, ...[...document.querySelectorAll('.block-container *')]
  .filter(e => [...e.childNodes].some(n => n.nodeType === 3 && n.textContent.trim()))
  .map(e => parseInt(getComputedStyle(e).fontWeight)))"""


@pytest.mark.parametrize("path", list(SCREENS))
def test_max_font_weight_600(ui_url, phone_page, path) -> None:
    """T7: lighter type, nothing heavier than 600."""
    phone_page.goto(ui_url + path)
    phone_page.wait_for_selector(f"text={SCREENS[path]}", timeout=20000)
    phone_page.wait_for_timeout(800)
    assert phone_page.evaluate(MAX_WEIGHT_JS) <= 600


def test_home_card_tap_opens_screen(ui_url, phone_page) -> None:
    """T7: the whole «Хайх» card is the tap target (button stretched over the HTML card)."""
    phone_page.goto(ui_url + "/")
    phone_page.wait_for_selector("text=Сайн байна уу", timeout=20000)
    box = phone_page.locator(".st-key-act_search").bounding_box()
    assert box["height"] >= 52
    phone_page.mouse.click(box["x"] + box["width"] * 0.3, box["y"] + box["height"] / 2)
    phone_page.wait_for_selector("text=Камераар хайх", timeout=10000)


def test_selected_chip_is_primary(ui_url, phone_page) -> None:
    """T7: selected chip = primary fill, white text (oil grade defaults to 15W-40 on a new truck)."""
    phone_page.goto(ui_url + "/record")
    phone_page.wait_for_selector("text=Дугаарыг гараар оруулах", timeout=20000)
    phone_page.get_by_role("button", name="Дугаарыг гараар оруулах").click()
    phone_page.get_by_label("Улсын дугаар").fill("0000 ТЕС")
    phone_page.get_by_role("button", name="Шалгах").click()
    phone_page.get_by_role("button", name="Зөв, үргэлжлүүлэх").click()
    chip = phone_page.locator('[data-testid="stButtonGroup"] button[aria-checked="true"]', has_text="15W-40")
    chip.wait_for(timeout=10000)
    bg, fg, height = chip.evaluate(
        "e => [getComputedStyle(e).backgroundColor, getComputedStyle(e).color, e.getBoundingClientRect().height]")
    assert (bg, fg) == ("rgb(31, 78, 157)", "rgb(255, 255, 255)") and height >= 36
