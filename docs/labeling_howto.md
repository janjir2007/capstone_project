# Labeling how-to (project `plates_new`, task 3.6a) — full guide: docs/labeling/LABELING_GUIDE.md
1. Start: `bash docs/labeling/start_label_studio.sh` → http://localhost:8080 → project **plates_new** → **Label All Tasks**.
2. Red `plate` boxes are pre-labels from yolo26n (conf ≥ 0.6). Drag the corners to fit the plate's **outer border**.
3. Box **every** real readable plate, including background trucks. Missing one? Pick the `plate` label and draw it.
4. Delete any box that is not a plate (select it → Delete / trash icon).
5. Click each box, then check **plate_type** (`plate` = registration plate, `fleet_no` = mine fleet number).
6. Type **plate_text**: exactly what you see, Cyrillic, no spaces (e.g. `1234УБА`); unreadable char = `?`. It starts empty on purpose (D-025).
7. **Submit** (or **Update** when editing). No plate in the photo → **Skip**.
8. When done: **Export → JSON** to `data/interim/labelstudio_export/`; then run `.venv/bin/python -m src.cv.ls_export <file>` and share only those counts.
