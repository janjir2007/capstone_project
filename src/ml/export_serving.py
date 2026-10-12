"""Numbers the API needs besides the Ridge file (task 4.3) -> models/serving_params.json.

The model file (models/next_change_model.joblib) keeps its keys (2.4b), so the
two fallbacks get their numbers from here, computed exactly as in training:

- B0 = median days to next change on TRAIN (``baselines.predict_b0``, same split ``make_split``)
- B1 = b1_interval_km ÷ route km/day (``baselines.predict_b1``, D-035/D-049)
- route table = ``dataset.route_table`` (configs/generator.yaml [ESTIMATE] midpoints), the same
  numbers ``build_features`` got in training. The destinations table has no round-trip days yet
  (TO FILL, migration 001), so the API cannot build them from the database.

Run after training (no retraining here):

    python -m src.ml.export_serving
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from src.data.generator import load_config as load_generator_config
from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split, route_table

PARAMS_FILE = "serving_params.json"


def route_params(generator_cfg: dict) -> dict[str, dict]:
    """``route_table`` as plain JSON values (Route(**value) gives the same Route back)."""
    return {name: {"route": r.route, "one_way_km": r.one_way_km, "km_per_day": r.km_per_day}
            for name, r in route_table(generator_cfg).items()}


def serving_params(cfg: dict) -> dict:
    """B0 days, B1 km and the route table, from the same data/split/config as training."""
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    return {
        "b0_days": float(df.loc[split.train, TARGET].median()),
        "b1_interval_km": float(cfg["baselines"]["b1_interval_km"]),
        "routes": route_params(load_generator_config(Path(cfg["generator_config"]))),
        "late_km": float(cfg["features"]["late_km"]),
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
