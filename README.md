# Oil Change Predictor — Geo-Expert LLC

A mobile web app for a real oil change service in Mongolia.
The oil changer photographs a truck, the app reads the plate,
and predicts when that truck needs its next oil change.

![App screenshot](docs/figures/app_screenshot.png)

## Key results
- Plate detection (YOLO): mAP50 0.99
- Next-change prediction: beats the fixed-interval baseline (MAE 12.3 vs 13.3 days)
- Live on a cloud server with HTTPS, daily tested backups, CI on every push

## Tech stack
Python · FastAPI · PostgreSQL · Streamlit · YOLO · XGBoost · SHAP · Docker

## Honest note
The model is trained on synthetic data built from real service rules;
real records are used for validation as they come in.
