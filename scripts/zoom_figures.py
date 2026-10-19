"""Real visuals for the slide-3 zoom-in steps (task 7.1e): app -> API -> YOLO + CNN -> DB -> prediction.

Every file comes from the RUNNING system (API on :8000 with the seeded demo DB, docs/demo_data.md,
and the Streamlit UI, which this script starts itself like tests/test_ui_browser.py). Nothing is
retrained and no app code or model is changed.

Privacy (RISK-06): only demo data appears. The plate photo is DRAWN here (a cartoon truck with the
demo plate «1001 УБА», no real photo is opened), and every vehicle shown is checked to be a seed
truck ("Демо …" company, phones 0000xxxx) before anything is written.

Output, docs/figures/slides/zoom/:
    0_demo_photo.png      synthetic input photo (the one sent in 2 and drawn in 3)
    1_app_capture.png     capture screen, 390×844 phone viewport (@2x pixels)
    1_app_form.png        form pre-filled after reading the demo photo (1001 УБА)
    2_api_request.txt     curl POST /plates/recognize + JSON response
    3_yolo_box.png        demo photo with the detector's box
    3_chars.png           the 7 segmented characters + CNN label + probability each
    4_db_rows.txt         service_records rows of 1001 УБА (as the API returns them)
    5_prediction.json     GET /vehicles/{id}/prediction for 1001 УБА
    5_viber.png           reminder screen, 1002 УБЕ row with its message + «Viber-ээр илгээх»

Run (repo root; API up and demo-seeded; Playwright as in docs/ui_run.md §0):
    .venv/bin/python -m scripts.zoom_figures
"""

from __future__ import annotations

import argparse
import json
import os
import socket
import subprocess
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import httpx
import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw, ImageFilter, ImageFont  # noqa: E402

from src.common.plates import normalize_plate  # noqa: E402
from src.cv.char_segment import segment  # noqa: E402
from src.cv.ocr_data import padded_crop  # noqa: E402
from src.cv.plate_reader import OnnxCharCNN, PlateRecognizer, softmax  # noqa: E402

ROOT = Path(__file__).resolve().parent.parent
OUT_DIR = ROOT / "docs" / "figures" / "slides" / "zoom"
UI_DIR = ROOT / "src" / "ui"
MODEL_DIR = ROOT / "models"
FORM_PLATE = "1001 УБА"  # loyal demo truck, Ridge prediction (docs/demo_data.md)
REMINDER_PLATE = "1002 УБЕ"  # overdue demo truck, on the due list
FONT = "/System/Library/Fonts/Supplemental/Arial Narrow Bold.ttf"  # macOS; has Cyrillic
PHONE = {"width": 390, "height": 844}
SEED = 0
DB_COLUMNS = ("id", "vehicle_id", "service_date", "odometer_km", "engine_hours", "oil_grade", "liters",
              "route", "destination_id", "destination_raw", "driver_name", "driver_phone", "oil_changer")


# --- synthetic photo -----------------------------------------------------------------------

def render_plate(text: str, width: int = 520, height: int = 112) -> Image.Image:
    """White one-row plate with a black border and black text (Mongolian layout, drawn, not photographed)."""
    img = Image.new("RGB", (width, height), (245, 245, 242))
    draw = ImageDraw.Draw(img)
    draw.rounded_rectangle([2, 2, width - 3, height - 3], radius=10, outline=(20, 20, 20), width=6)
    font = ImageFont.truetype(FONT, int(height * 0.82))
    left, top, right, bottom = draw.textbbox((0, 0), text, font=font)
    draw.text(((width - (right - left)) / 2 - left, (height - (bottom - top)) / 2 - top), text,
              fill=(15, 15, 15), font=font)
    return img


def render_demo_photo(text: str = FORM_PLATE, seed: int = SEED) -> Image.Image:
    """1280×960 cartoon truck front with the plate on the bumper, slight blur + sensor noise.

    Shapes are plain rectangles on purpose: it must be obviously not a real truck. Of 12 tried
    variants (cab colour, plate size, blur) the detector found 4; this one (red cab, 300 px plate)
    is detected and read correctly (numbers in the handoff).
    """
    width, height = 1280, 960
    sky = np.linspace(200, 150, height)[:, None, None] * np.ones((1, width, 3)) * np.array([0.85, 0.92, 1.0])
    img = Image.fromarray(sky.astype(np.uint8))
    draw = ImageDraw.Draw(img)
    draw.rectangle([0, 700, width, height], fill=(110, 105, 95))       # ground
    draw.rectangle([220, 120, 1060, 780], fill=(170, 30, 30))         # cab
    draw.rectangle([290, 160, 990, 390], fill=(60, 80, 95))           # windscreen
    for y in range(430, 600, 22):
        draw.rectangle([380, y, 900, y + 12], fill=(35, 35, 35))      # grille
    for x in (240, 930):
        draw.rectangle([x, 470, x + 110, 540], fill=(235, 235, 210))  # headlights
    draw.rectangle([200, 640, 1080, 760], fill=(45, 45, 45))          # bumper
    plate = render_plate(text)
    plate = plate.resize((300, round(300 * plate.height / plate.width)))
    img.paste(plate, (640 - plate.width // 2, 700 - plate.height // 2))
    for x in (290, 940):
        draw.ellipse([x - 70, 740, x + 70, 900], fill=(20, 20, 20))   # wheels
    img = img.filter(ImageFilter.GaussianBlur(0.8))
    noisy = np.asarray(img).astype(np.float32) + np.random.default_rng(seed).normal(0, 4, (height, width, 3))
    return Image.fromarray(np.clip(noisy, 0, 255).astype(np.uint8))


def write_y4m(img: Image.Image, path: Path, frames: int = 30) -> None:
    """Still image -> Y4M video file, used as Chrome's fake camera (--use-file-for-fake-video-capture)."""
    rgb = np.asarray(img.convert("RGB").resize((640, 480)))
    i420 = cv2.cvtColor(rgb, cv2.COLOR_RGB2YUV_I420).tobytes()
    with path.open("wb") as f:
        f.write(b"YUV4MPEG2 W640 H480 F30:1 Ip A1:1 C420jpeg\n")
        for _ in range(frames):
            f.write(b"FRAME\n" + i420)


# --- privacy guard -------------------------------------------------------------------------

def assert_demo_vehicle(card: dict) -> None:
    """Stop unless the vehicle is a demo-seed truck: company "Демо …", every phone 0000xxxx or empty."""
    company = (card.get("company") or {}).get("name", "")
    if not company.startswith("Демо"):
        raise RuntimeError(f"vehicle {card.get('id')} is not demo data (company not 'Демо …') — seed the demo DB")
    phones = [s.get("driver_phone") for s in card.get("history") or []]
    if any(p and not p.startswith("0000") for p in phones):
        raise RuntimeError(f"vehicle {card.get('id')} has a non-demo phone — seed the demo DB")


# --- text outputs ----------------------------------------------------------------------------

def service_row(service: dict) -> dict:
    """ServiceOut (API) -> the service_records columns (destination object -> destination_id)."""
    row = {c: service.get(c) for c in DB_COLUMNS}
    row["destination_id"] = (service.get("destination") or {}).get("id")
    return row


def db_rows_text(card: dict) -> str:
    """psql-style table of the vehicle's service_records rows, oldest first."""
    rows = [service_row(s) for s in reversed(card.get("history") or [])]
    cells = [[("" if r[c] is None else str(r[c])) for c in DB_COLUMNS] for r in rows]
    widths = [max(len(c), *(len(row[i]) for row in cells)) for i, c in enumerate(DB_COLUMNS)]
    line = lambda vals: " " + " | ".join(v.ljust(w) for v, w in zip(vals, widths))  # noqa: E731
    head = (f"-- service_records for {card['identifier']} (vehicle_id {card['id']}, {card['company']['name']})\n"
            f"-- demo data from src/data/seed_demo.py (synthetic, RISK-06); rows as returned by\n"
            f"-- GET /vehicles/lookup?q={card['plate_normalized']} (same columns as the table)\n")
    sep = "-" + "-+-".join("-" * w for w in widths) + "-"
    return "\n".join([head, line(DB_COLUMNS), sep, *map(line, cells), f"({len(rows)} rows)", ""])


def curl_text(command: str, response: dict) -> str:
    """The request as typed + the pretty JSON the API answered."""
    return f"$ {command}\n\n{json.dumps(response, ensure_ascii=False, indent=2)}\n"


# --- CV figures ------------------------------------------------------------------------------

def per_char(reader: OnnxCharCNN, chars: np.ndarray) -> list[tuple[str, float]]:
    """Each of the 7 characters' label + probability, exactly as OnnxCharCNN.predict_chars picks them."""
    logits = reader.session.run(None, {reader.input_name: chars[:, None].astype(np.float32)})[0]
    probs = softmax(logits + reader.mask)
    return [(reader.classes[i], float(probs[k, i])) for k, i in enumerate(probs.argmax(axis=1))]


def box_figure(photo: Image.Image, box: list[float], confidence: float) -> Image.Image:
    """Photo with the detector box and its score."""
    img = photo.copy()
    draw = ImageDraw.Draw(img)
    x1, y1, x2, y2 = box
    draw.rectangle([x1, y1, x2, y2], outline=(0, 200, 90), width=6)
    font = ImageFont.truetype(FONT, 40)
    label = f"plate {confidence:.2f}"
    left, top, right, bottom = draw.textbbox((x1, y1 - 52), label, font=font)
    draw.rectangle([left - 8, top - 6, right + 8, bottom + 6], fill=(0, 200, 90))
    draw.text((x1, y1 - 52), label, fill="white", font=font)
    return img


def chars_figure(chars: np.ndarray, labels: list[tuple[str, float]], path: Path) -> None:
    """7 character images in a row, CNN label + probability under each."""
    fig, axes = plt.subplots(1, len(chars), figsize=(10, 2.4), dpi=200)
    for ax, img, (label, prob) in zip(axes, chars, labels):
        ax.imshow(img, cmap="gray", vmin=0, vmax=1)
        ax.set_xticks([])
        ax.set_yticks([])
        ax.set_xlabel(f"{label}\n{prob:.2f}", fontsize=16, fontname="Arial")
    fig.tight_layout()
    fig.savefig(path, facecolor="white")
    plt.close(fig)


# --- live system -----------------------------------------------------------------------------

def lookup(api: str, plate: str) -> dict:
    """The VehicleCard for a plate (demo-checked)."""
    found = httpx.get(f"{api}/vehicles/lookup", params={"q": plate}, timeout=30).raise_for_status().json()
    if not found["vehicles"]:
        raise RuntimeError(f"{plate} not in the DB — seed the demo DB (docs/demo_data.md)")
    card = found["vehicles"][0]
    assert_demo_vehicle(card)
    return card


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


def screenshots(api: str, photo_png: Path, fake_cam: Path, reminder_sid: int, out: Path) -> None:
    """Start Streamlit (login off), take the three app screenshots in a 390×844 phone viewport."""
    from playwright.sync_api import sync_playwright  # dev tool only (docs/ui_run.md §0)

    port = _free_port()
    env = {**os.environ, "API_URL": api}
    env.pop("UI_PASSWORD", None)
    proc = subprocess.Popen([sys.executable, "-m", "streamlit", "run", "app.py", "--server.port", str(port),
                             "--server.headless", "true"], cwd=UI_DIR, env=env,
                            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    ui = f"http://127.0.0.1:{port}"
    try:
        if not _wait_ok(f"{ui}/_stcore/health", 30):
            raise RuntimeError("Streamlit did not start")
        with sync_playwright() as p:
            browser = p.chromium.launch(args=["--use-fake-ui-for-media-stream", "--use-fake-device-for-media-stream",
                                              f"--use-file-for-fake-video-capture={fake_cam}"])
            context = browser.new_context(viewport=PHONE, device_scale_factor=2, is_mobile=True, has_touch=True,
                                          permissions=["camera"])
            page = context.new_page()

            page.goto(f"{ui}/record")
            page.wait_for_selector("text=Дугаарыг гараар оруулах", timeout=20000)
            page.wait_for_selector("video", timeout=15000)
            page.wait_for_timeout(2500)  # camera preview frames arrive
            page.screenshot(path=str(out / "1_app_capture.png"))

            page.locator('[data-testid="stFileUploaderDropzoneInput"]').set_input_files(str(photo_png))
            page.wait_for_selector("text=Машин танигдлаа", timeout=30000)
            page.wait_for_timeout(1500)
            # Streamlit scrolls inside its own container (full_page sees only the viewport):
            # make the viewport as tall as the form for this one shot, same 390 px width.
            tall = page.evaluate("document.querySelector('[data-testid=\"stMain\"]').scrollHeight")
            page.set_viewport_size({"width": PHONE["width"], "height": max(PHONE["height"], tall)})
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "1_app_form.png"))
            page.set_viewport_size(PHONE)

            page.goto(f"{ui}/reminders")
            page.wait_for_selector("text=Гараар илгээнэ", timeout=20000)
            row_end = page.locator(f".st-key-rem_act_{reminder_sid}")
            row_end.wait_for(timeout=20000)
            plate = page.get_by_text(REMINDER_PLATE, exact=True).first
            plate.evaluate("e => e.scrollIntoView({block: 'start'})")
            page.mouse.wheel(0, -70)  # the driver name sits above the plate chip: show it + some air
            page.wait_for_timeout(800)
            page.screenshot(path=str(out / "5_viber.png"))
            browser.close()
    finally:
        proc.terminate()
        proc.wait(timeout=10)


def main(argv: list[str] | None = None) -> int:
    """Write the 8 zoom-in files (+ the synthetic input photo) to docs/figures/slides/zoom/."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--api", default=os.environ.get("API_URL", "http://localhost:8000").rstrip("/"))
    parser.add_argument("--out", type=Path, default=OUT_DIR)
    parser.add_argument("--no-screenshots", action="store_true", help="skip the 3 Streamlit screenshots")
    args = parser.parse_args(argv)
    out: Path = args.out
    out.mkdir(parents=True, exist_ok=True)

    # 0 + 2: synthetic photo -> real API
    photo = render_demo_photo()
    photo_png = out / "0_demo_photo.png"
    photo.save(photo_png)
    rel = photo_png.relative_to(ROOT) if photo_png.is_relative_to(ROOT) else photo_png
    command = f'curl -s -X POST {args.api}/plates/recognize -F "file=@{rel}"'
    raw = subprocess.run(["curl", "-s", "-X", "POST", f"{args.api}/plates/recognize", "-F", f"file=@{photo_png}"],
                         capture_output=True, text=True, check=True).stdout
    recognized = json.loads(raw)
    if recognized.get("plate_normalized") != normalize_plate(FORM_PLATE):
        raise RuntimeError(f"API did not read the demo photo as {FORM_PLATE}: {recognized}")
    (out / "2_api_request.txt").write_text(curl_text(command, recognized), encoding="utf-8")

    # 3: same models locally (files in models/, the API container mounts the same folder)
    rec = PlateRecognizer(MODEL_DIR)
    rgb = np.asarray(photo)
    det = rec.detector.detect(rgb)
    chars = segment(padded_crop(rgb, list(det.xyxy)))
    labels = per_char(rec.reader, chars)
    if "".join(c for c, _ in labels) != normalize_plate(FORM_PLATE):
        raise RuntimeError(f"local CNN read {labels}, API read {recognized['plate_normalized']}")
    box_figure(photo, recognized["detection"]["box"], recognized["detection"]["confidence"]).save(
        out / "3_yolo_box.png")
    chars_figure(chars, labels, out / "3_chars.png")

    # 4 + 5: demo DB through the API
    card = lookup(args.api, FORM_PLATE)
    (out / "4_db_rows.txt").write_text(db_rows_text(card), encoding="utf-8")
    prediction = httpx.get(f"{args.api}/vehicles/{card['id']}/prediction", timeout=30).raise_for_status().json()
    (out / "5_prediction.json").write_text(json.dumps(prediction, ensure_ascii=False, indent=2) + "\n",
                                           encoding="utf-8")

    reminder_card = lookup(args.api, REMINDER_PLATE)
    due = httpx.get(f"{args.api}/reminders/due", timeout=30).raise_for_status().json()["reminders"]
    sid = next((r["service_id"] for r in due if r["vehicle_id"] == reminder_card["id"]), None)
    if sid is None:
        raise RuntimeError(f"{REMINDER_PLATE} is not on the due list — re-seed the demo DB")

    if not args.no_screenshots:
        fake_cam = out.parent / ".zoom_fake_cam.y4m"
        write_y4m(photo, fake_cam)
        try:
            screenshots(args.api, photo_png, fake_cam, sid, out)
        finally:
            fake_cam.unlink(missing_ok=True)

    print(f"plate read: {recognized['plate_normalized']} conf {recognized['confidence']:.3f}, "
          f"box conf {recognized['detection']['confidence']:.3f}, needs_manual {recognized['needs_manual']}")
    print("chars:", " ".join(f"{c}={p:.3f}" for c, p in labels), f"product={np.prod([p for _, p in labels]):.3f}")
    print(f"prediction 1001 УБА: {prediction['method']} {prediction['predicted_date']} "
          f"({prediction['status']}, {prediction['days_left']} days left)")
    for f in sorted(out.iterdir()):
        print(f"  {f.relative_to(ROOT) if f.is_relative_to(ROOT) else f}  {f.stat().st_size:,} B")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
