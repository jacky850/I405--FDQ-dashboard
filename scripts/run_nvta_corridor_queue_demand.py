"""Recover I-395 NB demand from conservation instead of the QVDF duration branch.

The duration branch obtains D by inverting a power law in P. This script obtains
it from the queue instead:

    Q(t) = mu * max(0, L/v(t) - L/v_free)        delay converted to vehicles
    D(t) = mu + dQ/dt                            conservation

No f_d, no n, no power law. The only inputs are the speed profile, the link
geometry, and an assumed service rate — so the two estimates share the speed
data but nothing else, and the comparison is informative.

What this does and does not claim
---------------------------------
The queue here is delay-based, not counted. On the one PeMS case where both a
counted queue and this delay queue exist, they correlate 0.485 and their peaks
sit 60 minutes apart, so the level should be read as an order of magnitude, not
a measurement. What survives that imprecision is the *scale* of D/C, which is
the quantity in dispute: a delay queue would have to be wrong by a factor of
three for the duration branch's D/C of 3-4 to be right.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PERIOD_BOUNDS_MIN = {"AM": (300, 600), "MD": (600, 840), "PM": (840, 1200), "NT": (1200, 1320)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-file", type=Path, required=True)
    parser.add_argument("--qvdf-result", type=Path,
                        default=ROOT / "outputs/nvta_corridor_d_v_i395nb/corridor_d_v.csv")
    parser.add_argument("--capacity-drop", type=float, default=0.10,
                        help="fractional discharge loss while a queue is present")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "outputs/nvta_corridor_d_v_i395nb")
    return parser.parse_args()


def queue_demand(speed: np.ndarray, minutes: np.ndarray, length_mi: float,
                 free_speed: float, service_vph: float, drop: float) -> dict:
    """Delay-based queue and the demand implied by conservation."""
    dt_h = float(np.median(np.diff(minutes))) / 60.0
    free_tt = length_mi / free_speed
    excess_tt = np.maximum(length_mi / np.maximum(speed, 1.0) - free_tt, 0.0)
    queued = excess_tt > 0
    # Discharge drops once a queue forms; that is the standard capacity-drop
    # convention and it raises, not lowers, the demand implied by a given queue.
    service = np.where(queued, service_vph * (1.0 - drop), service_vph)
    queue = service * excess_tt
    # Forward difference keeps dQ/dt aligned with the interval it describes; a
    # centred difference would offset demand by half a bin against the queue.
    demand = service + np.diff(queue, append=queue[-1]) / dt_h
    return {"queue_veh": queue, "demand_vph": np.maximum(demand, 0.0), "dt_h": dt_h}


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile = pd.read_csv(args.profile_file)
    qvdf = pd.read_csv(args.qvdf_result)

    bins, rows = [], []
    for link_id, group in profile.groupby("link_id", sort=True):
        group = group.sort_values("t_min")
        minutes = group["t_min"].to_numpy(float)
        lanes = int(group["lanes"].iloc[0])
        capacity = float(group["capacity_vphpl"].iloc[0]) * lanes
        result = queue_demand(
            group["speed_smoothed"].to_numpy(float), minutes,
            float(group["length_mi"].iloc[0]), float(group["free_flow"].iloc[0]),
            capacity, args.capacity_drop,
        )
        frame = pd.DataFrame({
            "link_id": link_id, "t_min": minutes, "period": group["period"].to_numpy(),
            "speed_mph": group["speed_smoothed"].to_numpy(float),
            "queue_veh": result["queue_veh"], "demand_vph": result["demand_vph"],
        })
        bins.append(frame)

        window = int(round(1.0 / result["dt_h"]))  # bins in one hour
        for period, part in frame.groupby("period"):
            if period not in PERIOD_BOUNDS_MIN:
                continue
            start, end = PERIOD_BOUNDS_MIN[period]
            hours = (end - start) / 60.0
            rate = part["demand_vph"]
            rows.append({
                "link_id": int(link_id), "period": period, "period_hours": hours,
                "capacity_vph": capacity,
                "demand_D_queue_vph": float(rate.rolling(window, min_periods=window).mean().max()),
                "volume_V_queue_veh": float(rate.sum() * result["dt_h"]),
                "queue_max_veh": float(part["queue_veh"].max()),
                "queue_at_period_end_veh": float(part["queue_veh"].iloc[-1]),
            })

    per_bin = pd.concat(bins, ignore_index=True)
    queue_frame = pd.DataFrame(rows)
    queue_frame["d_over_c_queue"] = queue_frame["demand_D_queue_vph"] / queue_frame["capacity_vph"]

    merged = qvdf.merge(queue_frame, on=["link_id", "period"], how="inner",
                        suffixes=("", "_q"))
    merged["D_ratio_qvdf_over_queue"] = merged["demand_D_inferred_vph"] / merged["demand_D_queue_vph"]
    merged.to_csv(args.output_dir / "duration_branch_vs_queue.csv", index=False)
    per_bin.to_csv(args.output_dir / "queue_demand_15min.csv", index=False)

    # A queue is one physical object spread over consecutive links, so the
    # per-link split is not where it lives. On a 0.34-mile median link the delay
    # queue holds ~15 vehicles and dQ/dt is 0.5% of mu, which makes the per-link
    # estimate collapse to mu. Summing the corridor restores the signal.
    corridor = (
        per_bin.groupby("t_min")
        .agg(queue_veh=("queue_veh", "sum"), period=("period", "first"))
        .reset_index()
        .sort_values("t_min")
    )
    dt_h = float(np.median(np.diff(corridor["t_min"]))) / 60.0
    per_lane_capacity = float(profile["capacity_vphpl"].iloc[0])
    lanes = int(profile["lanes"].iloc[0])
    service = per_lane_capacity * lanes * (1.0 - args.capacity_drop)
    corridor["demand_vph"] = service + np.diff(
        corridor["queue_veh"].to_numpy(), append=corridor["queue_veh"].iloc[-1]
    ) / dt_h
    corridor.to_csv(args.output_dir / "corridor_queue_demand_15min.csv", index=False)

    window = int(round(1.0 / dt_h))
    corridor_result = {}
    for period, g in corridor.groupby("period"):
        if period not in PERIOD_BOUNDS_MIN:
            continue
        peak = float(g["demand_vph"].rolling(window, min_periods=window).mean().max())
        corridor_result[period] = {
            "peak_1h_demand_vph": peak,
            "d_over_c": peak / (per_lane_capacity * lanes),
            "queue_max_veh": float(g["queue_veh"].max()),
        }

    # Falsification: a demand held at D for the episode duration must deposit
    # (D - mu) * P vehicles somewhere. Compare that against the queue actually
    # observed and against what the corridor can physically hold.
    corridor_length_mi = float(profile.groupby("link_id")["length_mi"].first().sum())
    JAM_DENSITY_VEH_PER_MI_LN = 200.0
    storage = corridor_length_mi * lanes * JAM_DENSITY_VEH_PER_MI_LN
    observed_queue_max = float(corridor["queue_veh"].max())
    falsification = {
        "corridor_length_mi": corridor_length_mi,
        "lanes": lanes,
        "storage_at_jam_density_veh": storage,
        "observed_delay_queue_max_veh": observed_queue_max,
    }
    for period, g in merged[merged["episode_identified"]].groupby("period"):
        demand = float(g["demand_D_inferred_vph"].median())
        duration = float(g["P_h"].median())
        implied = (demand - service) * duration
        falsification[period] = {
            "duration_branch_D_vph": demand,
            "median_P_h": duration,
            "implied_queue_accumulation_veh": implied,
            "times_larger_than_observed_queue": implied / observed_queue_max,
            "times_larger_than_corridor_storage": implied / storage,
        }

    comparable = merged[merged["episode_identified"]]
    summary = {
        "corridor": "I-395 NB",
        "method": "D = mu + dQ/dt with a delay-based queue; no duration power law",
        "capacity_drop_fraction": args.capacity_drop,
        "by_period": {
            period: {
                "link_periods": int(len(g)),
                "d_over_c_queue_median": float(g["d_over_c_queue"].median()),
                "d_over_c_queue_range": [float(g["d_over_c_queue"].min()), float(g["d_over_c_queue"].max())],
                "d_over_c_duration_branch_median": float(g["x_hat_D_over_C"].median()),
                "D_queue_median_vph": float(g["demand_D_queue_vph"].median()),
                "D_duration_branch_median_vph": float(g["demand_D_inferred_vph"].median()),
                "duration_branch_over_queue_median": float(g["D_ratio_qvdf_over_queue"].median()),
                "queue_max_veh_median": float(g["queue_max_veh"].median()),
            }
            for period, g in comparable.groupby("period")
        },
        "corridor_level": corridor_result,
        "falsification_by_accumulation": falsification,
        "link_level_caveat": (
            "The per-link estimate degenerates: on a 0.34-mile median link the delay queue "
            "holds about 15 vehicles and dQ/dt is 0.5% of mu, so D collapses to the assumed "
            "service rate. Only the corridor aggregate carries signal, where dQ/dt reaches "
            "15% of mu. Read the corridor numbers, not the per-link ones."
        ),
        "reading": (
            "The queue route uses the same speed profile but no power law. Where the two "
            "disagree by a factor of three or more, the disagreement is in the duration "
            "branch's scale, not in the episode timing, because both read P from the same "
            "curve."
        ),
        "limitation": (
            "The queue is delay-based rather than counted. Against the counted queue on "
            "the PeMS case it correlates 0.485 with peaks 60 minutes apart, so its level "
            "is an order of magnitude, not a measurement."
        ),
    }
    (args.output_dir / "duration_branch_vs_queue_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
