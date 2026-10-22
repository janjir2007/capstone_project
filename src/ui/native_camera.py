"""Plate camera for the record screen (task 8.4, Ari's mockup).

One custom component (st.components.v2, inline JS, no npm build) in two modes:

- camera():  square live view of the REAR camera (getUserMedia, playsinline, highest
  resolution the browser offers) + round 80 px shutter. The shutter grabs the current video
  frame. If the camera is blocked, missing or stops (no permission, no HTTPS, old browser,
  another app holds it), the view is replaced AUTOMATICALLY by the 8.4 spike's big
  «Зураг авах» button: <input type="file" accept="image/*" capture="environment">, which
  opens the phone's own camera app and needs no permission. Never a dead end.
- gallery_button(): «Галерей» = the same file input without `capture` (photo library).

Every photo is shrunk in the browser to MAX_SIDE px on the long side (JPEG 0.9) and sent to
Python as a one-shot trigger value «photo». A file the browser cannot decode (e.g. HEIC on
Android Chrome) is sent unchanged; the API converts HEIC itself (contract v0.5).
The photo lives only in memory / session state — never written to disk (D-070).

Lifecycle (checked in Streamlit 1.64's BidiComponent): the JS function runs again when its
inputs change, without unmounting, so the stream is kept on the component's root element and
reused; the function's return value (cleanup) runs only when the component leaves the page,
and stops the camera there.
"""

import base64
import binascii
from dataclasses import dataclass
from typing import Any

import streamlit as st

MAX_SIDE = 2560  # px, long side after resize (task 8.4)
ACCENT = "#1F4E9D"  # theme primary (.streamlit/config.toml)

_HTML = """
<div class="pc">
  <div class="pc-live">
    <div class="pc-view">
      <video class="pc-video" playsinline muted autoplay></video>
      <div class="pc-badge"><i></i><span class="pc-badge-text"></span></div>
      <div class="pc-center"></div>
      <div class="pc-hint"></div>
    </div>
    <button type="button" class="pc-shutter"><span></span></button>
  </div>
  <div class="pc-fallback">
    <label class="pc-native">
      <input type="file" accept="image/*" capture="environment" class="pc-in" data-source="native">
      <span class="pc-cam-icon" aria-hidden="true"></span><span class="pc-native-text"></span>
    </label>
    <div class="pc-fallback-hint"></div>
  </div>
  <label class="pc-gal">
    <input type="file" accept="image/*" class="pc-in" data-source="gallery">
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.8"
      stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="4" width="18" height="16"
      rx="2"></rect><circle cx="9" cy="10" r="2"></circle><path d="M21 16l-5-5-9 9"></path></svg>
    <span class="pc-gal-text"></span>
  </label>
  <div class="pc-status" aria-live="polite"></div>
</div>
"""

_CSS = """
.pc { display: flex; flex-direction: column; gap: 14px; color: #111827;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, "Helvetica Neue", Arial, sans-serif; }
.pc-in { position: absolute; width: 1px; height: 1px; opacity: 0; overflow: hidden; }
.pc[data-mode="gallery"] .pc-live, .pc[data-mode="gallery"] .pc-fallback,
.pc[data-mode="live"] .pc-gal { display: none; }
/* live view: square, full width, dark until the first frame */
.pc-live { display: flex; flex-direction: column; align-items: center; gap: 14px; }
.pc-view { position: relative; width: 100%; aspect-ratio: 1 / 1; border-radius: 22px; overflow: hidden;
           background: #1F2328; }
.pc-video { position: absolute; inset: 0; width: 100%; height: 100%; object-fit: cover; opacity: 0; }
.pc.ready .pc-video { opacity: 1; }
.pc-badge { position: absolute; top: 14px; left: 14px; display: flex; align-items: center; gap: 6px;
            background: rgba(0,0,0,.5); color: #fff; font-size: 13px; font-weight: 500;
            padding: 5px 10px; border-radius: 999px; }
.pc-badge i { width: 8px; height: 8px; border-radius: 50%; background: #9CA3AF; }
.pc.ready .pc-badge i { background: #34D399; }
.pc-center { position: absolute; inset: 0; display: flex; align-items: center; justify-content: center;
             padding: 0 24px; text-align: center; color: #D1D5DB; font-size: 15px; }
.pc.ready .pc-center { display: none; }
.pc.busy .pc-center { display: flex; background: rgba(0,0,0,.45); color: #fff; }
.pc-hint { position: absolute; left: 0; right: 0; bottom: 14px; text-align: center; color: #fff;
           font-size: 14px; text-shadow: 0 1px 3px rgba(0,0,0,.6); }
/* shutter: 80 px ring + filled circle */
.pc-shutter { width: 80px; height: 80px; border-radius: 50%; border: 5px solid ACCENT; background: #fff;
              padding: 5px; cursor: pointer; touch-action: manipulation; -webkit-tap-highlight-color: transparent; }
.pc-shutter span { display: block; width: 100%; height: 100%; border-radius: 50%; background: ACCENT; }
.pc-shutter:active span { filter: brightness(0.85); }
.pc-shutter:disabled { opacity: .45; cursor: default; }
/* fallback (camera blocked / missing): the spike's native camera button */
.pc-fallback { display: none; flex-direction: column; gap: 10px; }
.pc.fallback .pc-live { display: none; }
.pc.fallback .pc-fallback { display: flex; }
.pc-native { display: flex; align-items: center; justify-content: center; gap: 10px; width: 100%;
             min-height: 96px; border-radius: 18px; cursor: pointer; background: ACCENT; color: #fff;
             font-size: 20px; font-weight: 600; user-select: none; touch-action: manipulation;
             -webkit-tap-highlight-color: transparent; }
.pc-native:active { filter: brightness(0.9); }
.pc-fallback-hint { text-align: center; font-size: 14px; color: #4B5563; }
.pc-cam-icon { width: 30px; height: 30px; background: currentColor;
  -webkit-mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9 3 7.2 5H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-3.2L15 3H9zm3 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10z"/></svg>') center/contain no-repeat;
          mask: url('data:image/svg+xml;utf8,<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 24 24"><path d="M9 3 7.2 5H4a2 2 0 0 0-2 2v12a2 2 0 0 0 2 2h16a2 2 0 0 0 2-2V7a2 2 0 0 0-2-2h-3.2L15 3H9zm3 15a5 5 0 1 1 0-10 5 5 0 0 1 0 10z"/></svg>') center/contain no-repeat; }
.pc.busy .pc-native { opacity: .6; pointer-events: none; }
/* «Галерей»: 56 px white button with a thin line (mockup) */
.pc-gal { display: flex; align-items: center; justify-content: center; gap: 8px; height: 56px;
          box-sizing: border-box; border: 1px solid #D5D9E0; border-radius: 14px; background: #fff;
          font-size: 16px; font-weight: 500; cursor: pointer; user-select: none; touch-action: manipulation;
          -webkit-tap-highlight-color: transparent; }
.pc.busy .pc-gal { opacity: .6; pointer-events: none; }
.pc-status { font-size: 14px; color: #A05A00; text-align: center; }
.pc-status:empty { display: none; }
""".replace("ACCENT", ACCENT)

_JS = """
function loadImage(blob) {
  return new Promise((resolve, reject) => {
    const url = URL.createObjectURL(blob);
    const img = new Image();
    img.onload = () => { URL.revokeObjectURL(url); resolve(img); };
    img.onerror = () => { URL.revokeObjectURL(url); reject(new Error('decode')); };
    img.src = url;
  });
}

function toBase64(blob) {
  return new Promise((resolve, reject) => {
    const r = new FileReader();
    r.onload = () => resolve(String(r.result).split(',', 2)[1] || '');
    r.onerror = () => reject(r.error);
    r.readAsDataURL(blob);
  });
}

// Draw a source (img / video) of size w x h at <= maxSide px on the long side -> JPEG 0.9.
function drawJpeg(source, w, h, maxSide) {
  const scale = Math.min(1, maxSide / Math.max(w, h));
  const cw = Math.round(w * scale), ch = Math.round(h * scale);
  const canvas = document.createElement('canvas');
  canvas.width = cw; canvas.height = ch;
  canvas.getContext('2d').drawImage(source, 0, 0, cw, ch);
  return new Promise((res) => canvas.toBlob((b) => res({ blob: b, w: cw, h: ch }), 'image/jpeg', 0.9));
}

// File from an <input>: long side -> maxSide px, JPEG 0.9. Browsers apply EXIF orientation when
// drawing an <img> (Safari 13.1+, Chrome 81+), so the result is upright and EXIF-free.
async function shrinkFile(file, maxSide) {
  let img;
  try { img = await loadImage(file); } catch (e) { return { blob: file, resized: false }; }
  const w = img.naturalWidth, h = img.naturalHeight;
  if (Math.max(w, h) <= maxSide && file.type === 'image/jpeg') return { blob: file, resized: false, w, h, srcW: w, srcH: h };
  const out = await drawJpeg(img, w, h, maxSide);
  if (!out.blob) return { blob: file, resized: false, w, h, srcW: w, srcH: h };
  return { blob: out.blob, resized: true, w: out.w, h: out.h, srcW: w, srcH: h };
}

function stopStream(s) {
  if (s.stream) s.stream.getTracks().forEach((t) => t.stop());
  s.stream = null;
}

export default function (component) {
  const { parentElement, setTriggerValue, data } = component;
  const root = parentElement.querySelector('.pc');
  const s = root.__pc || (root.__pc = { stream: null, starting: false, fallback: false, dead: false });
  const $ = (sel) => root.querySelector(sel);
  const video = $('.pc-video');
  const status = $('.pc-status');
  root.dataset.mode = data.mode;
  $('.pc-badge-text').textContent = data.labels.badge;
  $('.pc-hint').textContent = data.labels.hint;
  $('.pc-fallback-hint').textContent = data.labels.hint;
  $('.pc-native-text').textContent = data.labels.native;
  $('.pc-gal-text').textContent = data.labels.gallery;
  const shutter = $('.pc-shutter');
  shutter.setAttribute('aria-label', data.labels.shutter);
  // A rerun of the page re-invokes this function: clear a stuck "busy" (e.g. a photo Python
  // could not read) and resume the paused preview.
  root.classList.remove('busy');
  if (s.stream && video.paused) video.play().catch(() => {});

  const centerText = (t) => { $('.pc-center').textContent = t; };

  const toFallback = () => {
    if (s.dead) return;
    s.fallback = true;
    stopStream(s);
    root.classList.remove('ready');
    root.classList.add('fallback');
  };

  const send = async (blob, meta) => {
    setTriggerValue('photo', { b64: await toBase64(blob), ...meta });
  };

  const fail = () => {
    root.classList.remove('busy');
    status.textContent = data.labels.error;
    if (s.stream && video.paused) video.play().catch(() => {});
  };

  // native camera (fallback) + gallery: file input -> shrink -> Python
  root.querySelectorAll('.pc-in').forEach((input) => {
    input.onchange = async () => {
      const file = input.files && input.files[0];
      input.value = '';  // the same photo can be chosen again
      if (!file) return;
      root.classList.add('busy');
      status.textContent = data.mode === 'gallery' ? data.labels.busy : '';
      centerText(data.labels.busy);
      try {
        const out = await shrinkFile(file, data.max_side);
        await send(out.blob, {
          name: out.resized ? 'photo.jpg' : (file.name || 'photo.jpg'),
          type: out.resized ? 'image/jpeg' : (file.type || ''),
          width: out.w || null, height: out.h || null,
          source_width: out.srcW || null, source_height: out.srcH || null,
          original_bytes: file.size, resized: out.resized, source: input.dataset.source,
        });
      } catch (e) { fail(); }
    };
  });

  if (data.mode !== 'live') return () => {};

  // shutter: grab the current video frame
  shutter.disabled = !root.classList.contains('ready');
  shutter.onclick = async () => {
    const w = video.videoWidth, h = video.videoHeight;
    if (!s.stream || !w || !h) return;
    root.classList.add('busy');
    status.textContent = '';
    centerText(data.labels.busy);
    shutter.disabled = true;
    video.pause();  // freeze the frame the oil changer just took
    try {
      const out = await drawJpeg(video, w, h, data.max_side);
      if (!out.blob) throw new Error('encode');
      await send(out.blob, {
        name: 'photo.jpg', type: 'image/jpeg', width: out.w, height: out.h,
        source_width: w, source_height: h, original_bytes: null,
        resized: Math.max(w, h) > data.max_side, source: 'live',
      });
    } catch (e) { shutter.disabled = false; fail(); }
  };

  const start = async () => {
    if (!(navigator.mediaDevices && navigator.mediaDevices.getUserMedia)) { toFallback(); return; }
    s.starting = true;
    centerText(data.labels.starting);
    try {
      // ideal = "as close as possible", never fails: the browser picks its largest rear mode
      const stream = await navigator.mediaDevices.getUserMedia({
        audio: false,
        video: { facingMode: { ideal: 'environment' }, width: { ideal: 4096 }, height: { ideal: 4096 } },
      });
      if (s.dead) { stream.getTracks().forEach((t) => t.stop()); return; }  // left the page meanwhile
      s.stream = stream;
      stream.getVideoTracks().forEach((t) => t.addEventListener('ended', toFallback));
      video.srcObject = stream;
      await video.play();
      for (let i = 0; i < 50 && !video.videoWidth; i++) await new Promise((r) => setTimeout(r, 100));
      if (!video.videoWidth) throw new Error('no frames');
      if (s.dead) return;
      root.classList.add('ready');
      shutter.disabled = false;
    } catch (e) {
      toFallback();  // NotAllowedError, NotFoundError, NotReadableError, insecure context, no frames
    } finally {
      s.starting = false;
    }
  };

  if (s.fallback) root.classList.add('fallback');
  else if (!s.starting && !(s.stream && s.stream.active)) start();

  return () => { s.dead = true; stopStream(s); };
}
"""

LABELS = {
    "badge": "Арын камер",
    "hint": "2–3 метрээс, урдаас нь авна уу",
    "shutter": "Зураг авах",
    "native": "Зураг авах",
    "gallery": "Галерей",
    "starting": "Камер асааж байна…",
    "busy": "Зураг боловсруулж байна…",
    "error": "Зураг уншигдсангүй — дахин оролдоно уу.",
}


def _register():
    """Register the component in the CURRENT runtime and return its mount command.

    Called on every render, not once at import: a module is imported once per process,
    but each Streamlit runtime (e.g. every AppTest) has its own registry. Re-registering
    the identical definition is silent and cheap.
    """
    return st.components.v2.component("plate_camera", html=_HTML, css=_CSS, js=_JS)


@dataclass(frozen=True)
class CapturedPhoto:
    """A photo from the phone, shaped like Streamlit's UploadedFile where the UI uses it
    (getvalue / name / type), so common.recognize_photo_box takes it unchanged.

    width/height = the photo sent; source_width/source_height = before the resize (live: the
    camera stream's frame size). source = "live" (shutter) | "native" (fallback camera app)
    | "gallery".
    """

    data: bytes
    name: str
    type: str
    width: int | None = None
    height: int | None = None
    original_bytes: int | None = None
    resized: bool = False
    source: str = ""
    source_width: int | None = None
    source_height: int | None = None

    def getvalue(self) -> bytes:
        return self.data


def parse_payload(payload: Any) -> CapturedPhoto | None:
    """Trigger value from the browser -> CapturedPhoto; anything malformed -> None."""
    if not isinstance(payload, dict) or not isinstance(payload.get("b64"), str):
        return None
    try:
        data = base64.b64decode(payload["b64"], validate=True)
    except (binascii.Error, ValueError):
        return None
    if not data:
        return None

    def _int(key: str) -> int | None:
        value = payload.get(key)
        return value if isinstance(value, int) and not isinstance(value, bool) else None

    return CapturedPhoto(
        data=data,
        name=str(payload.get("name") or "photo.jpg"),
        type=str(payload.get("type") or ""),
        width=_int("width"),
        height=_int("height"),
        original_bytes=_int("original_bytes"),
        resized=payload.get("resized") is True,
        source=str(payload.get("source") or ""),
        source_width=_int("source_width"),
        source_height=_int("source_height"),
    )


def _mount(key: str, mode: str, max_side: int) -> CapturedPhoto | None:
    result = _register()(
        key=key,
        data={"mode": mode, "labels": LABELS, "max_side": max_side},
        on_photo_change=lambda: None,  # a trigger needs a callback to be reported back
        width="stretch",
    )
    return parse_payload(getattr(result, "photo", None))


def camera(key: str, max_side: int = MAX_SIDE) -> CapturedPhoto | None:
    """Square live view + shutter (fallback: native camera button).
    Returns the photo on the run right after it is taken, else None."""
    return _mount(key, "live", max_side)


def gallery_button(key: str, max_side: int = MAX_SIDE) -> CapturedPhoto | None:
    """«Галерей» button. Returns the chosen photo on the run right after, else None."""
    return _mount(key, "gallery", max_side)


def size_text(photo: CapturedPhoto) -> str:
    """'2560×1920 (камер 3840×2880, live)' — what reached Python, for the ?diag=1 line."""
    sent = f"{photo.width}×{photo.height}" if photo.width and photo.height else "?"
    src = (f"камер {photo.source_width}×{photo.source_height}, "
           if photo.source_width and photo.source_height else "")
    return f"{sent} ({src}{photo.source or '?'}, {round(len(photo.data) / 1024)} KB)"
