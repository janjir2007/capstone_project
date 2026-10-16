# Plate labeling guide (Task 3.1) — Label Studio, local only

Tool: **Label Studio 1.23.2** (open source), in its own venv `~/.venvs/label-studio`.
Why Label Studio: runs 100% on this Mac, reads photos straight from disk,
supports a box + per-box text + per-box choice in one screen, and exports JSON
that keeps box and text together. (CVAT was the alternative in D-013; it needs
Docker and several containers — heavier for 1 person.)

## Privacy (RISK-06)
- Photos stay in `data/raw/photos/`. Label Studio **reads** them from disk; nothing is uploaded.
- Label Studio's database (your labels = real plate strings) lives in `data/labelstudio/` — git-ignored.
- Exports go to `data/interim/labelstudio_export/` — git-ignored.
- The start script turns off telemetry (`COLLECT_ANALYTICS=false`) and the PyPI version check,
  and listens on `127.0.0.1` only (other devices on the Wi-Fi cannot open it).
- Do **not** use the project's "Import" / upload button — it copies photos into Label Studio's media folder.
- Share only the count summary from `src.cv.ls_export`, never plate strings or photos.

## 1. Install (one time — already done on Ari's Mac)
```bash
python3.11 -m venv ~/.venvs/label-studio
~/.venvs/label-studio/bin/pip install label-studio==1.23.2
```
This is **not** in `requirements.txt`: our code never imports it; it's a tool.

## 2. Start
```bash
cd ~/Downloads/Capstone/oil-change-predictor
bash docs/labeling/start_label_studio.sh
```
Open http://localhost:8080 . Stop with `Ctrl+C` in that terminal.
(Other port: `LS_PORT=8081 bash docs/labeling/start_label_studio.sh`.)

First visit: **Sign up** with any email + password. This account exists only in
the local SQLite file, not online.

## 3. Create the project (one time)
1. **Create Project** → name `plates`.
2. Labeling setup → choose the **Custom template** option → **Code** view → paste all of
   `docs/labeling/label_config.xml` → **Save**. (Later edits: project **Settings →
   Labeling Interface → Code**.) The config itself was validated by Label Studio
   1.23.2; exact button names in the wizard may differ slightly.
3. Project → **Settings → Cloud Storage → Add Source Storage**:
   - Storage type: **Local files**
   - Storage Name: `photos`
   - Absolute local path: `/Users/sanchirariunbold/Downloads/Capstone/oil-change-predictor/data/raw/photos`
   - File Filter Regex: `(?i).*\.(jpe?g|png)$` (skips `.DS_Store` etc.; matched on the file name)
   - Import method: **"Files – Automatically creates a task for each storage object"**
     (NOT "Tasks – Treat each JSON…")
   - If photos are in subfolders, turn on **Recursive scan**.
   - Save → **Sync**. The task count should equal your photo count.

**HEIC note:** iPhone `.heic` photos may not display in Chrome/Firefox (needs
verification in your browser). If photos are HEIC, tell the CV Eng before labeling.

## 4. Labeling rules (per photo)
1. Select the `plate` label, draw a **tight** box around the plate's **outer border**
   (include the whole plate frame, not just the characters). Zoom in if needed.
2. With the box selected, the side panel shows:
   - **plate_type**: `plate` (normal registration plate) or `fleet_no` (mine fleet number).
     Default is `plate` (verify on your first photo that it is preselected).
   - **plate_text**: type **exactly what you see**, no spaces, e.g. `1234УБА`.
     - Use Cyrillic letters for Cyrillic (switch keyboard to Mongolian/Russian).
     - Unreadable character → `?` (e.g. `12?4УБА`). Don't guess.
     - Do not "fix" look-alikes — normalization is done later in `src/common/plates.py`.
3. More than one plate in the photo (e.g. front + trailer) → one box per plate, each with its own text.
4. No plate visible / completely unreadable → **Skip** the task.
5. **Submit** (or **Update** when editing).

## 5. Export
Project → **Export** → **JSON** (the full one, not JSON-MIN, not YOLO) →
save the file as `data/interim/labelstudio_export/export_<date>.json`.

Why only JSON (tested on synthetic images, Label Studio 1.23.2):
| Format | Problem |
|---|---|
| YOLO | Treats the `plate_type` choices as extra classes: `classes.txt` = `fleet_no, plate` → our only class gets id **1**; plate text is lost |
| JSON-MIN | With 2 boxes in a photo, text and type become lists — the link to each box is lost |
| **JSON** | Box, type and text share one region id ✅ |

The YOLO dataset (single class `plate` = id 0, split by vehicle, D-009) is built
from this JSON by our own script in the next step — not by Label Studio's YOLO export.

Check an export (prints counts only, safe to share):
```bash
.venv/bin/python -m src.cv.ls_export data/interim/labelstudio_export/export_<date>.json
```

## 6. First: test on 2–3 photos, then label the rest
1. Label 2–3 photos (ideally: one with 2 plates, one `fleet_no` if you have one, one with a `?`).
2. Export JSON, run the check command above.
3. Expect: `tasks_labeled` = 2–3, `boxes_missing_text` = 0, `boxes_out_of_bounds` = 0,
   `boxes_by_type` matches what you chose.
4. Paste the summary to the CV Eng chat. If it looks right → label the rest.

## Backups
Export JSON after each labeling session (the SQLite DB is the only copy of your
work). Keep exports outside git (they already are).

## 7. Pre-labels from a pretrained detector (task 3.1c)
Boxes are proposed by the open-image-models detector `yolo-v9-t-640-license-plate-end2end`
(runs on this Mac, CPU). You only fix boxes and type `plate_text`.

### 7a. Detect on all photos (local, ~a few minutes)
```bash
.venv/bin/python -m src.cv.prelabel run
```
Writes `data/interim/prelabels/predictions.json` (git-ignored; contains file names — do not share).
The printed summary is count-only and safe to share.

### 7b. Create a Personal Access Token (one time)
Label Studio 1.23.2 uses **Personal Access Tokens** (legacy tokens are off by default).
1. Start Label Studio, log in, click your avatar (top right) → **Account & Settings**.
2. Find the **Personal Access Token** section → **Create** → copy the token.
   (Exact labels may differ slightly.) Only **one** valid token per user: if you lose it,
   revoke it on the same page and create a new one.
3. In the terminal where you run the import (the token is never saved to a file):
   ```bash
   export LS_API_KEY='paste-token-here'
   ```

### 7c. Import as predictions (Label Studio must be running)
```bash
.venv/bin/python -m src.cv.ls_import --dry-run    # counts only, changes nothing
.venv/bin/python -m src.cv.ls_import --limit 1    # one task: open it and check the box
.venv/bin/python -m src.cv.ls_import              # the rest (safe to re-run: no duplicates)
```
- Uses boxes with confidence ≥ 0.6 (`--conf` to change). Photos with no box ≥ 0.6 get no prediction.
- Skips any task you already submitted, skipped, or have a draft on.
- Talks only to `127.0.0.1` / `localhost` (refuses other hosts).
- Sets the project's model version to the detector's version, so **Label All Tasks**
  shows the boxes (without it, the labeling stream showed no pre-labels in our test).

### 7d. Labeling with pre-labels
Open a task: the red box is already there with `plate_type = plate`.
Fix the box if needed (drag corners), delete false boxes, draw any missed plate,
select the box, type `plate_text`, **Submit**. A photo with no plate → **Skip** as before.

## 8. New photos with our own detector (task 3.6a)
Photos: `data/raw/photos_new/` (copied from "More photos", all JPEG). New project `plates_new`;
the old `Plates` project is not touched (`ls_setup` refuses an existing title).
```bash
.venv/bin/python -m src.cv.prelabel run --detector yolo26n --photos data/raw/photos_new \
    --out data/interim/prelabels/predictions_new.json            # done by CV Eng, counts only
export LS_API_KEY='paste-token-here'                             # Personal Access Token, see 7b
.venv/bin/python -m src.cv.ls_setup --title plates_new --photos data/raw/photos_new
.venv/bin/python -m src.cv.ls_import --project plates_new --predictions data/interim/prelabels/predictions_new.json
```
Detector = fine-tuned yolo26n ONNX (D-028), all boxes after NMS (IoU 0.7), import threshold 0.6,
`plate_text` empty. Short rules for labeling: `docs/labeling_howto.md`.
