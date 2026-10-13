# HANDOFF REPORT — 5.3b (queue T2)

```
HANDOFF REPORT
TASK ID: 5.3b (queue T2)
STATUS: DONE
SUMMARY: origin/main (contract v0.5, tasks 4.3 + 4.4) merged into ui, no conflicts.
  UI wired to POST /plates/recognize and the card's Prediction object.
  - Record: a new photo (camera/upload, jpg/png/heic) is sent at once. A clear read
    fills the plate (plate_normalized) and looks it up right away. needs_manual fills
    what was read plus a reason-specific warning, and the oil changer fixes it and presses
    «Шалгах». Recognizer errors (503/413/422/offline) → "type it" message, manual entry.
  - Search: «📷 Камераар хайх». A clear read searches at once; needs_manual fills the
    field and waits for «Хайх».
  - Card: prediction card tinted by status (DESIGN v2 colors: Хэвийн / Удахгүй /
    Хэтэрсэн) with big «N хоног үлдсэн/хэтэрсэн», predicted_date, progress bar, method +
    fallback_reason note. null → grey card «Таамаглал удахгүй нэмэгдэнэ».
  - UI_ENABLE_RECOGNIZE flag removed (4.3 merged).
FILES: src/ui/api_client.py, src/ui/logic.py, src/ui/common.py, src/ui/views/record.py,
  src/ui/views/lookup.py, tests/test_ui_logic.py, tests/test_ui_api_client.py,
  tests/test_ui_app.py, docs/ui_screens.md, docs/ui_handoff_5.3b.md
HOW TO RUN: as 5.1–5.3 (docs/ui_screens.md). For live predictions the API needs
  ./models (see below).
DECISIONS MADE:
  - Recognize runs automatically on a new photo (no extra button): fewer taps on a phone.
  - Clear read → lookup at once; needs_manual → never auto-lookup (contract: "check it first").
  - With needs_manual, plate_raw is put in the field even if plate_normalized is null, so the
    oil changer corrects 1–2 characters instead of typing all 7.
  - Progress bar = (today − last_service_date) / (predicted_date − last_service_date), 0–1.
  - Method notes: ridge «Загварын таамаглал», b1 «Маршрутын тооцоо», b0 «Дундаж хугацаа»,
    plus fallback_reason in brackets. model_version kept in the view data, not shown (noise
    for the oil changer).
METRICS / EVIDENCE:
  - pytest (full repo, after merge): 565 passed, 2 skipped (backend ONNX tests; recognizer
    files are not on the iMac). UI tests: 67 (new: prediction view ×4, recognize outcome ×3,
    photo→lookup, needs_manual, recognizer down, search by camera, card prediction, field "file").
  - Live API on the iMac (Chrome 390 px): 1234 УБА → red «Хэтэрсэн · 5 хоног хэтэрсэн ·
    Дундаж хугацаа (очих газар тодорхойгүй)»; HT-12 → amber «Удахгүй · 10 хоног үлдсэн».
    Real upload with recognizer not loaded → «Автомат таних одоогоор ажиллахгүй байна —
    дугаараа гараар оруулна уу.»
  - Model files on the iMac were rebuilt from SYNTHETIC data only (generator → cleaning →
    train → export_serving, seed 42). Tracked reports came out byte-identical (git clean),
    Ridge test MAE 11.9 as in D-051. No real data on this machine.
ASSUMPTIONS NEEDING PM/ARI CONFIRMATION:
  1. Automatic recognize on photo (vs. a button) OK?
  2. Mongolian wording of the recognize reasons and method notes (Ari to proofread).
PROBLEMS / RISKS:
  - The real recognize path (clear read from a real photo) is tested only with a mocked
    API: the ONNX recognizer cannot be built on the iMac (trained on private photos). Needs
    one live check on the Mac with a fake/demo plate photo.
  - CI still installs only requirements.txt → UI screen tests skip in CI (see 5.1–5.3).
CONTRACT CHANGES: none.
SLIDE MATERIAL: prediction card colors = D-007 status buckets; "recognition never blocks
  the flow" (any failure → manual entry).
NEXT STEP: T3 (5.3c) DESIGN v2.
```
