"""Screenshots of the 9.12 mockup at 390 px (phone) and 1280 px (computer). Dev tool (Playwright).

    .venv/bin/python docs/design/9.12/shoot.py
"""

from pathlib import Path

from playwright.sync_api import sync_playwright

HERE = Path(__file__).resolve().parent

with sync_playwright() as p:
    browser = p.chromium.launch()
    # 900 px: the table scrolls inside its card; the page itself must not (PM 9.12 review).
    for width, scale, name in ((390, 2, "mockup_390.png"), (900, 1, "mockup_900.png"), (1280, 1, "mockup_1280.png")):
        page = browser.new_page(viewport={"width": width, "height": 900}, device_scale_factor=scale)
        page.goto((HERE / "mockup.html").as_uri())
        assert page.evaluate("document.documentElement.scrollWidth") <= width, f"{name}: page scrolls sideways"
        page.screenshot(path=str(HERE / name), full_page=True)
        page.close()
    browser.close()
print("saved:", ", ".join(sorted(f.name for f in HERE.glob("*.png"))))
