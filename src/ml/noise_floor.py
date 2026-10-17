"""Noise floor: the best MAE any model could reach on the synthetic data (Task 2.9 step 1).

The generator (src/data/generator.py) draws random things AFTER every service that
no feature can know: on time vs late (D-031), the km the driver changes at
(uniform 15k–20k, D-030), the extra late days, per-trip noise (V2), waiting days,
route switches (V6). So even a perfect model has an error.

Oracle = a predictor that knows EVERYTHING the generator knows at the service
moment: the truck's hidden speed, driving hours and late chance, the true
destination, the date. It does not know the random draws that come after.
For MAE the best such prediction is the MEDIAN of the possible outcomes, so:

    oracle(visit) = median of N re-simulations of ``generator.simulate_interval``
                    from that visit's true state, with a fresh random stream.

Only outcomes that could appear in the scored rows are kept (rejection):
the truck returns (not "never"), and the next visit is inside the window that
made the row a train or test row (train: next visit before the split cutoff;
test: next visit not after the generator's end date). Oracle MAE = mean
|actual − oracle| over the scored rows. The generator is imported, never changed.

Usage (train only, as in brief step 1; test is scored once in src/ml/tune.py):
    python -m src.ml.noise_floor
"""

from __future__ import annotations

import argparse
import math
from datetime import date
from pathlib import Path

import numpy as np
import pandas as pd

from src.data.generator import CLEAN_FILE, Vehicle, load_config, simulate_interval, value
from src.ml.dataset import TARGET, build_dataset, load_ml_config, make_split

DEFAULT_SIMS = 1000  # re-simulations per visit; train oracle MAE 11.69 at 400 vs 11.65 at 1000 (converged)
MAX_TRIES_FACTOR = 20  # give up after N × this many draws (only if almost every draw is rejected)


def load_truth(gen_cfg: dict) -> pd.DataFrame:
    """Generator truth (clean file, seed from configs/generator.yaml), indexed by record_id."""
    clean = pd.read_csv(Path(gen_cfg["output_dir"]) / CLEAN_FILE, parse_dates=["service_date"], encoding="utf-8")
    return clean.set_index("record_id")


def visit_vehicle(row: pd.Series) -> Vehicle:
    """The hidden truck parameters ``simulate_interval`` uses (speed, hours, late chance)."""
    return Vehicle(vehicle_id=int(row["vehicle_id"]), speed_kmh=float(row["veh_speed_kmh"]),
                   hours_per_day=float(row["veh_hours_per_day"]), late_prob=float(row["veh_late_prob"]),
                   home_dest=0, first_day=0, start_odometer=0)  # last three are not used by simulate_interval


def simulate_days(rng: np.random.Generator, gen_cfg: dict, vehicle: Vehicle, day: int, dest: int,
                  start_date: date, last_ok_day: int, n: int) -> np.ndarray:
    """Up to ``n`` possible "days to next change" of one visit, as the generator would draw them.

    Same rounding as ``generator.simulate_vehicle``: next day = max(floor(end), day + 1).
    Draws where the truck never returns or comes back after ``last_ok_day`` are rejected.
    """
    out: list[int] = []
    for _ in range(n * MAX_TRIES_FACTOR):
        iv = simulate_interval(rng, gen_cfg, vehicle, float(day), dest, start_date)
        if iv.outcome != "never":
            next_day = max(math.floor(iv.end), day + 1)
            if next_day <= last_ok_day:
                out.append(next_day - day)
                if len(out) == n:
                    break
    return np.asarray(out, dtype=float)


def oracle_predictions(rows: pd.DataFrame, truth: pd.DataFrame, gen_cfg: dict, last_ok_days: pd.Series,
                       n_sims: int, seed: int) -> pd.Series:
    """Oracle prediction (median of re-simulations) for every row of the ML dataset.

    ``rows`` needs ``record_id``; ``last_ok_days`` = per row, the last day offset the next
    visit may fall on to be in this set. Each visit gets its own random stream
    (seed, 29, record_id), so the result does not depend on row order.
    """
    start_date = date.fromisoformat(value(gen_cfg["fleet"]["start_date"]))
    dest_index = {d["name"]: i for i, d in enumerate(gen_cfg["destinations"])}
    preds = {}
    for idx, rid in rows["record_id"].items():
        t = truth.loc[int(rid)]
        day = (pd.Timestamp(t["service_date"]).date() - start_date).days  # CSV Timestamp or in-memory date
        rng = np.random.default_rng([seed, 29, int(rid)])
        sims = simulate_days(rng, gen_cfg, visit_vehicle(t), day, dest_index[t["destination_name"]], start_date,
                             int(last_ok_days.loc[idx]), n_sims)
        preds[idx] = float(np.median(sims)) if len(sims) else np.nan
    return pd.Series(preds, name="oracle").reindex(rows.index)


def last_ok_day_for(rows: pd.DataFrame, gen_cfg: dict, window_end: pd.Timestamp, strict: bool) -> pd.Series:
    """Same last day for every row: ``window_end`` as a day offset (strict = next visit BEFORE it)."""
    start = pd.Timestamp(value(gen_cfg["fleet"]["start_date"]))
    last = (window_end.normalize() - start).days - (1 if strict else 0)
    return pd.Series(last, index=rows.index)


def oracle_for_split(df: pd.DataFrame, split, gen_cfg: dict, part: str, n_sims: int, seed: int) -> pd.Series:
    """Oracle predictions for ``part`` = "train" (next visit < cutoff) or "test" (next visit ≤ end date)."""
    truth = load_truth(gen_cfg)
    if part == "train":
        rows = df.loc[split.train]
        last = last_ok_day_for(rows, gen_cfg, split.cutoff, strict=True)
    elif part == "test":
        rows = df.loc[split.test]
        last = last_ok_day_for(rows, gen_cfg, pd.Timestamp(value(gen_cfg["fleet"]["end_date"])), strict=False)
    else:
        raise ValueError(f"part must be train or test, got {part!r}")
    return oracle_predictions(rows, truth, gen_cfg, last, n_sims, seed)


def oracle_mae(y: pd.Series, oracle: pd.Series) -> float:
    """Mean |actual − oracle| (days)."""
    return float((y - oracle).abs().mean())


def main(argv: list[str] | None = None) -> int:
    """CLI: oracle MAE on TRAIN (test is scored once, in src/ml/tune.py)."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("--config", type=Path, default=Path("configs/ml.yaml"))
    parser.add_argument("--sims", type=int, default=DEFAULT_SIMS)
    args = parser.parse_args(argv)
    cfg = load_ml_config(args.config)
    gen_cfg = load_config(Path(cfg["generator_config"]))
    df, _ = build_dataset(cfg)
    split = make_split(df, cfg)
    oracle = oracle_for_split(df, split, gen_cfg, "train", args.sims, cfg["seed"])
    y = df.loc[split.train, TARGET]
    print(f"generator seed {gen_cfg['seed']}; train {len(y)} visits; oracle MAE {oracle_mae(y, oracle):.2f} days "
          f"({oracle.isna().sum()} visits without an oracle)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
