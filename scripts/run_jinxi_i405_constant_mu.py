"""Run the first real-data I-405 constant-mu single-link benchmark.

This is Stage 1 only: S3/Triangular FD calibration plus one constant service
rate per period.  The queue is continuous across period boundaries.  Dynamic
FDQ service mu(t)=Cap-theta*Q is intentionally not used here.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.calibrate import fit_models  # noqa: E402
from fdqbench.io import write_json  # noqa: E402
from fdqbench.metrics import period_volume_closure, queue_qaqc, regression_metrics  # noqa: E402
from fdqbench.reference import build_reference_day  # noqa: E402


DEFAULT_AVERAGE = ROOT / "data" / "jinxi_i405_week_2025-06-16_to_22" / "average_weekday_fdqbench.csv"
DEFAULT_SOURCE = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\trafficflowbench_five_corridors\data_public\kaggle_release"
    r"\corridors\D12_I405_S"
)


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--average", type=Path, default=DEFAULT_AVERAGE)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--link-id", default="L405S-001")
    p.add_argument("--tmc-id", default="1222782")
    p.add_argument("--output", type=Path, default=ROOT / "outputs" / "jinxi_i405_constant_mu")
    return p.parse_args()


def load_link_metadata(source: Path, link_id: str, tmc_id: str) -> dict:
    links = pd.read_csv(source / "network" / "links.csv")
    row = links[links["link_id"].astype(str).eq(str(link_id))]
    if row.empty:
        raise ValueError(f"Link not found in links.csv: {link_id}")
    r = row.iloc[0]

    fd = pd.read_csv(source / "network" / "fd_parameters.csv")
    fd_row = fd[
        fd["link_id"].astype(str).eq(str(link_id))
        & fd["station_id"].astype(str).eq(str(tmc_id))
    ]
    cutoff = float(fd_row.iloc[0]["v_cut"]) if not fd_row.empty else None
    lanes = float(r["lanes"])
    meta = {
        "link_id": str(link_id),
        "tmc_id": str(tmc_id),
        "lanes": lanes,
        "length_mi": float(r["length_km"]) * 0.621371192237334,
        "free_speed_mph": float(r["free_speed_kmh"]) * 0.621371192237334,
        "capacity_vehphpl": float(r["capacity_vph"]) / lanes,
    }
    if cutoff is not None:
        meta["cutoff_speed_mph"] = cutoff * 0.621371192237334
    return meta


def main() -> None:
    args = parse_args()
    avg_all = pd.read_csv(args.average)
    avg = avg_all[
        avg_all["link_id"].astype(str).eq(str(args.link_id))
        & avg_all["tmc_id"].astype(str).eq(str(args.tmc_id))
    ].copy()
    if len(avg) != 288:
        raise ValueError(
            f"Expected 288 five-minute weekday rows for one link/TMC; got {len(avg)}."
        )
    avg = avg.sort_values("time_of_day").reset_index(drop=True)
    # We have ground-truth flow for this validation run.  Use it as lambda for
    # the queue baseline; speed-derived flow remains a separately scored FD
    # diagnostic and must not contaminate the queue-model assessment.
    avg["arrival_vehph"] = avg["flow_vehph"]
    meta = load_link_metadata(args.source, args.link_id, args.tmc_id)

    models = fit_models(avg, "speed_mph", "flow_vehph", lanes=meta["lanes"])
    periods = [
        {"name": "NT1", "start": "00:00", "end": "06:00"},
        {"name": "AM", "start": "06:00", "end": "10:00"},
        {"name": "MD", "start": "10:00", "end": "15:00"},
        {"name": "PM", "start": "15:00", "end": "19:00"},
        {"name": "NT2", "start": "19:00", "end": "23:59"},
    ]
    # Stage 1: one constant mu per period, no blending and no queue reset.
    speed_volume_model = {
        "name": "s3",
        "parameters": models["s3"]["parameters"],
        "period_volume_anchor": "observed",
    }
    mu_config = {
        "mode": "post_t2_median",
        "flow_col": "flow_observed_vehph",
        "blend_intervals": 0,
        "t2_by_period": {"AM": "08:15", "MD": "13:00", "PM": "17:15"},
    }
    ref, mu_by_period = build_reference_day(
        avg,
        meta,
        periods,
        speed_volume_model,
        mu_config,
        dt_minutes=5,
        initial_queue_veh=0.0,
    )

    args.output.mkdir(parents=True, exist_ok=True)
    ref.to_csv(args.output / "reference_day.csv", index=False)
    write_json(models, args.output / "fitted_models.json")
    write_json(meta, args.output / "link_metadata.json")
    write_json(mu_by_period, args.output / "mu_by_period.json")
    period_volume_closure(ref, dt_minutes=5).to_csv(
        args.output / "period_volume_closure.csv", index=False
    )
    metrics = {
        "link_id": args.link_id,
        "tmc_id": args.tmc_id,
        "model_for_reference": "s3",
        "mu_strategy": "post_t2_median",
        "queue_reset_at_period_boundaries": False,
        "speed_volume": regression_metrics(
            ref["flow_observed_vehph"], ref["flow_speed_only_vehph"]
        ),
        "speed_volume_period_anchored": regression_metrics(
            ref["flow_observed_vehph"], ref["flow_ref_vehph"]
        ),
        "queue_qaqc": queue_qaqc(ref),
    }
    write_json(metrics, args.output / "metrics.json")
    print(json.dumps({"output": str(args.output), "mu_by_period": mu_by_period, **metrics}, indent=2))


if __name__ == "__main__":
    main()
