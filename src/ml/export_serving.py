"""Numbers the API needs besides the Ridge file (task 4.3) -> models/serving_params.json.

The model file (models/next_change_model.joblib) keeps its keys (2.4b), so the
two fallbacks get their numbers from here, computed exactly as in training:

- B0 = median days to next change on TRAIN (``baselines.predict_b0``, same split ``make_split``)
- B1 = b1_interval_km ÷ route km/day (``baselines.predict_b1``, D-035/D-049)
- route table = ``dataset.route_table`` (configs/generator.yaml [ESTIMATE] midpoints), the same
  numbers ``build_features`` got in training. The destinations table has no round-trip days yet
  (TO FILL, migration 001), so the API cannot build them from the database.
- reminder buffers for B0 and B1 (task 4.4) = ``train.tune_buffer`` on their TRAIN validation
  predictions (``train.baseline_validation``), the same numbers as docs/ml_evaluation.md §4.
  Ridge's buffer is already in the model file (``buffer_days``).
- prediction ranges (task 2.9) = 10th–90th percentile of TRAIN out-of-fold residuals
  (actual − predicted) per method: ridge = the saved pipeline refit per GroupKFold fold
  (``train.oof_predictions``), b0/b1 = their validation predictions. The API adds them to
  the prediction ("≈ date (low – high)"). Same numbers as docs/ml_results.md §5.3.

Run after training (no retraining here):

    python -m src.ml.export_serving
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import joblib
import pandas as pd

from src.common.features import FEATURE_COLUMNS
from src.data.generator import load_config as load_generator_config
from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split, route_table
from src.ml.train import MODEL_FILE, baseline_validation, oof_predictions, tune_buffer
from src.ml.tune import RANGE_QUANTILES, residual_range

PARAMS_FILE = "serving_params.json"


def route_params(generator_cfg: dict) -> dict[str, dict]:
    """``route_table`` as plain JSON values (Route(**value) gives the same Route back)."""
    return {name: {"route": r.route, "one_way_km": r.one_way_km, "km_per_day": r.km_per_day}
            for name, r in route_table(generator_cfg).items()}


def prediction_ranges(train: pd.DataFrame, cfg: dict, b0_val: pd.Series, b1_val: pd.Series) -> dict[str, list[float]]:
    """{method: [low, high]} days to add to a prediction (TRAIN out-of-fold residual percentiles)."""
    bundle = joblib.load(Path(cfg["models"]["model_dir"]) / MODEL_FILE)
    y, groups = train[TARGET], train[cfg["vehicle_col"]]
    ridge_oof = oof_predictions(bundle["pipeline"], train[FEATURE_COLUMNS], y, groups, cfg["models"]["cv_folds"])
    return {method: [round(v, 2) for v in residual_range(y, pred)]
            for method, pred in (("ridge", ridge_oof), ("b0", b0_val), ("b1", b1_val))}


def serving_params(cfg: dict) -> dict:
    """B0 days, B1 km, the route table, buffers and ranges, from the same data/split/config as training."""
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    train = df.loc[split.train]
    window, buffer_range = tuple(cfg["reminder"]["window_days_early"]), tuple(cfg["models"]["buffer_range_days"])
    b0_val, b1_val = baseline_validation(train, cfg).values()  # order: B0, B1
    return {
        "b0_days": float(df.loc[split.train, TARGET].median()),
        "b1_interval_km": float(cfg["baselines"]["b1_interval_km"]),
        "routes": route_params(load_generator_config(Path(cfg["generator_config"]))),
        "late_km": float(cfg["features"]["late_km"]),
        "buffers": {"b0": tune_buffer(train[TARGET], b0_val, window, buffer_range),
                    "b1": tune_buffer(train[TARGET], b1_val, window, buffer_range),
                    "window_days_early": list(window)},
        "ranges": prediction_ranges(train, cfg, b0_val, b1_val) | {"quantiles": list(RANGE_QUANTILES)},
        "source": {"data": cfg["input"], "split_cutoff": f"{split.cutoff:%Y-%m-%d}", "seed": cfg["seed"],
                   "generator_config": cfg["generator_config"]},
    }


def main(argv: list[str] | None = None) -> int:
    """CLI: write models/serving_params.json and print it (synthetic numbers only)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/ml.yaml"))
    args = parser.parse_args(argv)
    cfg = load_ml_config(args.config)
    params = serving_params(cfg)
    out = Path(cfg["models"]["model_dir"]) / PARAMS_FILE
    out.write_text(json.dumps(params, indent=2, ensure_ascii=False), encoding="utf-8")
    print(json.dumps(params, indent=2, ensure_ascii=False))
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
