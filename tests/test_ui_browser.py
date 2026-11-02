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
    "/": "Сайн байна уу",
    "/record": "Гараар бичих",
    "/search": "Камераар хайх",
    "/reminders": "Гараар илгээнэ",
    "/dashboard": "Машинууд",   # 9.12 section (was «Сегмент»)
}
# T9 page padding (top right bottom left); 9.12: the dashboard is on the 4/8/12/16/24/32 scale
PAGE_PAD = {"/dashboard": "12px 16px 32px 16px"}


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
def pw():
    """One Playwright per module (a second sync_playwright() inside a running one fails)."""
    with playwright.sync_playwright() as p:
        yield p


@pytest.fixture(scope="module")
def phone_page(pw):
    channel = os.environ.get("UI_BROWSER_CHANNEL") or None
    browser = pw.chromium.launch(channel=channel)
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
    phone_page.wait_for_selector("text=Сайн байна уу", timeout=20000)
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


def test_top_row_and_light_buttons(ui_url, phone_page) -> None:
    """CSS regressions AppTest cannot see: Streamlit's top bar is hidden and our top row (back
    chevron + title, T9) starts at 12 px, and secondary buttons in a card are borderless grey."""
    phone_page.goto(ui_url + "/search")
    phone_page.wait_for_selector("text=Камераар хайх", timeout=20000)
    phone_page.wait_for_timeout(800)
    assert not phone_page.locator('[data-testid="stHeader"]').is_visible()  # T8: no Streamlit top bar
    top = phone_page.locator(".st-key-topbar").bounding_box()
    assert (round(top["y"]), round(top["height"])) == (12, 48)            # T9: 12 px page top, 48 px row
    assert phone_page.locator(".st-key-topbar h1").count() == 1           # title on the same row
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


@pytest.mark.parametrize("x_frac", [0.08, 0.5, 0.95])
@pytest.mark.parametrize(("card", "proof"), [
    ("act_record", "Гараар бичих"), ("act_search", "Камераар хайх"), ("act_reminders", "Гараар илгээнэ"),
    ("act_dashboard", "Машинууд")])
def test_home_card_tap_opens_screen(ui_url, phone_page, card, proof, x_frac) -> None:
    """T7 / 5.9b: the WHOLE card is the tap target (button stretched over the HTML card), for
    every home card, tapped at its left, middle and right."""
    phone_page.goto(ui_url + "/")
    phone_page.wait_for_selector("text=Сайн байна уу", timeout=20000)
    phone_page.wait_for_timeout(500)
    box = phone_page.locator(f".st-key-{card}").bounding_box()
    assert box["height"] >= 52
    phone_page.mouse.click(box["x"] + box["width"] * x_frac, box["y"] + box["height"] / 2)
    phone_page.wait_for_selector(f"text={proof}", timeout=10000)


SPACING_JS = """() => {
  const r = e => e.getBoundingClientRect(), bc = document.querySelector('.block-container');
  const cs = getComputedStyle(bc);
  // 9.5a: only what the browser draws (checkVisibility): the 9.1 dashboard keeps the computer table
  // inside a display:none wrapper on a phone, and a closed expander lays out its fields unseen.
  const shown = e => e.checkVisibility();
  const empty = [...bc.querySelectorAll('[data-testid="stElementContainer"]')]
    .filter(e => shown(e) && r(e).height < 2).length;
  // visible content of each top-level block; the next block must start >= 12 px below it
  const kids = [...bc.querySelector('[data-testid="stVerticalBlock"]').children]
    .filter(e => getComputedStyle(e).display !== 'none' && r(e).height > 0);
  const bottom = e => Math.max(r(e).bottom, ...[...e.querySelectorAll('*')].filter(shown).map(c => r(c).bottom));
  let tight = 0;
  // a section label (st.subheader, or common.section's .sec-row) sits 8 px above its own card
  const label = e => e.matches(':has(> .stHeading h3)') || e.matches('[data-testid="stElementContainer"]:has(.sec-row)');
  for (let i = 1; i < kids.length; i++)
    if (!label(kids[i - 1]) && r(kids[i]).top - bottom(kids[i - 1]) < 11.5) tight++;
  return {pad: [cs.paddingTop, cs.paddingRight, cs.paddingBottom, cs.paddingLeft].join(' '), empty, tight};
}"""


@pytest.mark.parametrize("path", list(SCREENS))
def test_spacing_exact_values(ui_url, phone_page, path) -> None:
    """T9: page padding 12/20/40 (dashboard: PAGE_PAD), no empty blocks taking a gap, and no block overlapping or
    touching the next (HTML content spilling out of its Streamlit box, e.g. markdown's -1rem)."""
    phone_page.goto(ui_url + path)
    phone_page.wait_for_selector(f"text={SCREENS[path]}", timeout=20000)
    phone_page.wait_for_timeout(800)
    m = phone_page.evaluate(SPACING_JS)
    assert m == {"pad": PAGE_PAD.get(path, "12px 20px 40px 20px"), "empty": 0, "tight": 0}, m


def test_oil_segment_selected_is_white(ui_url, phone_page) -> None:
    """T9 mockup: oil grade = segmented control; the selected segment (default 15W-40 on a new
    truck) is white on the grey track, full width, nothing cut off."""
    phone_page.goto(ui_url + "/record")
    phone_page.wait_for_selector("text=Гараар бичих", timeout=20000)
    phone_page.get_by_role("button", name="Гараар бичих").click()
    phone_page.get_by_label("Улсын дугаар").fill("0000 ТЕС")
    phone_page.get_by_role("button", name="Үргэлжлүүлэх").click()
    chip = phone_page.locator('.st-key-f_oil_choice button[aria-checked="true"]', has_text="15W-40")
    chip.wait_for(timeout=10000)
    phone_page.wait_for_timeout(500)
    bg, height, clipped = chip.evaluate(
        "e => [getComputedStyle(e).backgroundColor, e.getBoundingClientRect().height,"
        " [...e.querySelectorAll('p')].some(p => p.scrollWidth > p.clientWidth + 1)]")
    assert bg == "rgb(255, 255, 255)" and height >= 44 and not clipped
    track = phone_page.locator(".st-key-f_oil_choice").bounding_box()
    card = phone_page.locator(".st-key-card_fresh").bounding_box()
    assert track["width"] >= card["width"] - 2 * 20 - 1                  # full card width (padding 20)


NO_ZOOM_JS = """() => {
  const fields = [...document.querySelectorAll('input, textarea, select')]
    .filter(e => e.offsetParent !== null && e.type !== 'file');
  const taps = [...document.querySelectorAll('button, [data-baseweb="select"]')].filter(e => e.offsetParent !== null);
  return {fields: fields.length,
          small: fields.filter(e => parseFloat(getComputedStyle(e).fontSize) < 16).map(e => e.outerHTML.slice(0, 80)),
          taps: taps.length,
          zoomable: taps.filter(e => getComputedStyle(e).touchAction !== 'manipulation').map(e => e.outerHTML.slice(0, 80)),
          viewport: document.querySelector('meta[name=viewport]')?.content || ''};
}"""


def test_no_tap_zoom_on_new_vehicle_form(ui_url, phone_page) -> None:
    """8.1: on the longest form (new truck: text, number, model dropdown, pills) every visible
    field is >= 16 px (iOS does not zoom on focus) and every button / dropdown has
    touch-action: manipulation; the viewport does not block pinch zoom."""
    phone_page.goto(ui_url + "/record")
    phone_page.wait_for_selector("text=Гараар бичих", timeout=20000)
    phone_page.get_by_role("button", name="Гараар бичих").click()
    phone_page.get_by_label("Улсын дугаар").fill("0000 ТЕС")
    phone_page.get_by_role("button", name="Үргэлжлүүлэх").click()
    phone_page.wait_for_selector("text=Машины загвар", timeout=10000)
    phone_page.wait_for_timeout(800)
    m = phone_page.evaluate(NO_ZOOM_JS)
    assert m["fields"] > 0 and m["taps"] > 0, m
    assert m["small"] == [] and m["zoomable"] == [], m
    assert "maximum-scale" not in m["viewport"] and "user-scalable" not in m["viewport"], m


def _phone_photos(folder: Path) -> dict[str, Path]:
    """A real-format iPhone-like HEIC and JPEG (4032x3024, synthetic content, RISK-06)."""
    pillow_heif = pytest.importorskip("pillow_heif")
    from PIL import Image, ImageDraw
    pillow_heif.register_heif_opener()
    img = Image.new("RGB", (4032, 3024), (90, 110, 130))
    draw = ImageDraw.Draw(img)
    for x in range(0, 4032, 48):  # some detail, so the files are not tiny
        draw.line([(x, 0), (4032 - x, 3024)], fill=(x % 255, 140, 200 - x % 120), width=9)
    paths = {"heic": folder / "IMG_0001.HEIC", "jpeg": folder / "IMG_0002.JPG"}
    img.save(paths["heic"], quality=80)
    img.save(paths["jpeg"], quality=90)
    return paths


@pytest.mark.parametrize("engine", ["webkit", "chromium"])
@pytest.mark.parametrize("kind", ["heic", "jpeg"])
def test_gallery_photo_reaches_result(ui_url, pw, shot_dir, engine, kind) -> None:
    """8.4b: «Галерей» with an iPhone HEIC / JPEG -> result screen (plate read or the orange
    not-read message), never the component's «Зураг уншигдсангүй». WebKit = Safari's engine
    (decodes HEIC -> resized JPEG); Chromium cannot decode HEIC -> the file is sent as is.
    Needs `playwright install webkit` once for the webkit case."""
    photo = _phone_photos(shot_dir)[kind]
    browser = getattr(pw, engine).launch()
    try:
        page = browser.new_page(viewport=PHONE)
        errors: list[str] = []
        page.on("console", lambda m: errors.append(m.text) if "plate_camera" in m.text else None)
        page.goto(ui_url + "/record")
        page.locator(".pc[data-mode=gallery] .pc-gal").wait_for(timeout=20000)
        page.locator(".pc[data-mode=gallery] .pc-gal input").set_input_files(str(photo))
        page.get_by_role("button", name="Үргэлжлүүлэх").wait_for(timeout=60000)
        body = page.inner_text("body")
    finally:
        browser.close()
    assert "Зураг уншигдсангүй" not in body and errors == []
    assert "Дугаарыг таньлаа" in body or "Дугаарыг уншиж чадсангүй" in body


def test_payments_fit_phone(ui_url, phone_page, shot_dir) -> None:
    """9.6b-5: with payments connected, the «Төлбөр» block (sync line, «Төлөөгүй» list, «Залгах»)
    fits 390 px, and every «Залгах» is a 44 px tap target. Skipped when the API's database has no
    successful Artlab sync yet (the block is hidden then, which test_screen_fits_phone covers)."""
    phone_page.goto(ui_url + "/dashboard")
    phone_page.wait_for_selector("text=Машинууд", timeout=20000)
    phone_page.wait_for_timeout(1500)
    if phone_page.locator("text=Сүүлд шинэчилсэн").count() == 0:
        pytest.skip("payments not connected in this API's database")
    assert phone_page.locator(".st-key-card_dash_unpaid").is_visible()
    calls = phone_page.locator(".unpaid .call")
    for i in range(calls.count()):
        box = calls.nth(i).bounding_box()
        assert box["height"] >= 44 and box["x"] + box["width"] <= PHONE["width"], box
    _check_phone_width(phone_page, shot_dir, "screen_dashboard_payments")


def test_card_payment_pills_fit_phone(ui_url, phone_page, shot_dir) -> None:
    """9.6b-5: the card's payment pill under each service stays inside 390 px."""
    plate = os.environ.get("UI_BROWSER_PLATE")
    if not plate:
        pytest.skip("set UI_BROWSER_PLATE to a plate in the DB to check the card")
    phone_page.goto(ui_url + "/search")
    phone_page.wait_for_selector("text=Камераар хайх", timeout=20000)
    phone_page.get_by_label("Улсын дугаар эсвэл утас").fill(plate)
    phone_page.get_by_role("button", name="Хайх", exact=True).click()
    phone_page.wait_for_selector(".plate", timeout=15000)
    phone_page.wait_for_timeout(800)
    pills = phone_page.locator(".tl .pill-st.pay")
    if pills.count() == 0:
        pytest.skip("payments not connected in this API's database")
    for i in range(pills.count()):
        box = pills.nth(i).bounding_box()
        assert box["x"] >= 0 and box["x"] + box["width"] <= PHONE["width"], box
    _check_phone_width(phone_page, shot_dir, "screen_card_payments")


# --- «Хяналтын самбар» 9.12 at phone / tablet / computer width ---------------------------------
# Needs an API with contract v0.17 (GET /stats/period). The demo DB (seed_demo) has 40 trucks.

WIDTHS = {390: 844, 900: 1000, 1280: 900}
DASH_JS = """() => {
  const q = s => document.querySelector(s), box = s => q(s) && q(s).getBoundingClientRect();
  const cols = s => q(s) ? getComputedStyle(q(s)).gridTemplateColumns.split(' ').length : 0;
  const sc = q('.st-key-dash_table_wrap .dvn-scroller');
  return {page: document.documentElement.scrollWidth, kpi: cols('.tiles.kpi'), segs: cols('.st-key-dash_segs'),
    pads: [q('.tiles.kpi > div'), q('.st-key-act_seg_all'), q('.st-key-card_dash_search')].map(e => getComputedStyle(e).padding),
    input: box('.st-key-card_dash_search [data-testid="stTextInputRootElement"]'),
    button: box('.st-key-card_dash_search .stFormSubmitButton button'),
    filters: box('.st-key-card_dash_search [data-testid="stExpander"] summary p'),
    // the placeholder's text width vs the field's inner width (canvas: the input's own font)
    hint: (i => { const c = document.createElement('canvas').getContext('2d'), st = getComputedStyle(i);
      c.font = st.fontSize + ' ' + st.fontFamily;
      return [Math.ceil(c.measureText(i.placeholder).width),
              i.clientWidth - parseFloat(st.paddingLeft) - parseFloat(st.paddingRight)]; })(q('.st-key-card_dash_search input')),
    track: box('.st-key-dash_period div:has(> button)'),
    table: !!q('.st-key-dash_table_wrap')?.checkVisibility(), scroller: sc ? [sc.scrollWidth, sc.clientWidth] : null};
}"""


@pytest.fixture(scope="module", params=list(WIDTHS), ids=lambda w: f"{w}px")
def dash(request, pw, ui_url, shot_dir):
    """The dashboard open at one width (390 = phone, 900 = small laptop / tablet, 1280 = computer)."""
    width = request.param
    browser = pw.chromium.launch(channel=os.environ.get("UI_BROWSER_CHANNEL") or None)
    page = browser.new_page(viewport={"width": width, "height": WIDTHS[width]},
                            is_mobile=width < 768, has_touch=width < 768)
    page.goto(ui_url + "/dashboard")
    page.wait_for_selector(".tiles.kpi", timeout=20000)
    page.wait_for_timeout(1500)
    page.width = width
    yield page
    page.set_viewport_size({"width": width, "height": 3200})  # whole screen (Streamlit scrolls inside)
    page.wait_for_timeout(500)
    page.screenshot(path=str(shot_dir / f"dashboard_{width}.png"))
    browser.close()


def test_dashboard_layout_per_width(dash) -> None:
    """No sideways page scroll; KPI tiles + segment cards 2×2 on a phone, 4 across from 768 px;
    card padding 16 / 24; «Хайх» BESIDE the field, both 48 px, bottoms in line, the placeholder not
    cut off; «Шүүлтүүр» starts at the field's left edge; the period switch is full width on a phone, word-wide on a computer."""
    m = dash.evaluate(DASH_JS)
    wide = dash.width >= 768
    assert m["page"] <= dash.width, m
    assert (m["kpi"], m["segs"]) == ((4, 4) if wide else (2, 2)), m
    assert m["pads"] == ["24px" if wide else "16px"] * 3, m
    assert round(m["input"]["height"]) == round(m["button"]["height"]) == 48, m
    assert abs(m["input"]["bottom"] - m["button"]["bottom"]) < 1 and m["button"]["left"] > m["input"]["right"], m
    assert abs(m["filters"]["left"] - m["input"]["left"]) < 1, m
    assert m["hint"][0] <= m["hint"][1], m                           # the whole placeholder is visible
    assert (m["track"]["width"] < 500) if wide else (m["track"]["width"] >= dash.width - 2 * 16 - 1), m
    assert m["table"] == wide, m                                     # phone: tappable cards instead


def test_dashboard_table_scrolls_inside_its_box(dash) -> None:
    """768-1180 px: the 10-column table scrolls sideways INSIDE its box, the page never does;
    at 1280 px every column fits (nothing clipped)."""
    if dash.width < 768:
        pytest.skip("phone: cards, no table")
    m = dash.evaluate(DASH_JS)
    inner, shown = m["scroller"]
    assert m["page"] <= dash.width, m
    assert (inner > shown) if dash.width < 1180 else (inner <= shown + 1), m


def test_dashboard_segment_card_filters_and_outlines(dash) -> None:
    """Tap «Шинэ»: blue outline moves to it and the list shows that many trucks; «Бүгд» brings all back."""
    new = dash.locator(".st-key-act_seg_new")
    count = int(new.locator(".segc .v").inner_text())
    new.click()
    dash.wait_for_function(f"document.body.innerText.includes('Шүүсэн · {count} машин')", timeout=15000)
    outline = lambda key: dash.locator(f".st-key-act_seg_{key}").evaluate("e => getComputedStyle(e).outlineStyle")
    assert outline("new") == "solid" and outline("all") == "none"
    dash.locator(".st-key-act_seg_all").click()
    dash.wait_for_function("document.body.innerText.includes('Бүх машин ·')", timeout=15000)
    assert outline("all") == "solid"


def test_dashboard_history_below_list_and_in_view(dash) -> None:
    """Pick a truck (phone: its row; computer: the table's row marker): the history opens BELOW the
    list, full width, and is scrolled into view."""
    if dash.width < 768:
        dash.locator('[class*="st-key-act_dash_"]').first.click()
    else:
        table = dash.locator(".st-key-dash_table_wrap")
        dash.wait_for_timeout(1500)                                 # the last tap's rerun redraws the table
        table.wait_for(state="visible", timeout=15000)
        table.scroll_into_view_if_needed()
        box = table.bounding_box()
        dash.mouse.click(box["x"] + 14, box["y"] + 35 * 1.5)       # row 1's selection marker
    panel = dash.locator(".st-key-card_dash_history")
    panel.wait_for(timeout=15000)
    dash.wait_for_timeout(1200)                                     # smooth scroll
    p = panel.bounding_box()
    list_box = dash.locator(".st-key-dash_list").bounding_box()
    assert p["y"] >= list_box["y"] + list_box["height"] - 1         # below the list
    assert abs(p["width"] - list_box["width"]) < 1                  # full width, nothing clipped
    assert 0 <= p["y"] < WIDTHS[dash.width]                         # its top is on screen
    assert dash.evaluate("document.documentElement.scrollWidth") <= dash.width
    dash.get_by_role("button", name="Хаах").click()
    panel.wait_for(state="detached", timeout=15000)
