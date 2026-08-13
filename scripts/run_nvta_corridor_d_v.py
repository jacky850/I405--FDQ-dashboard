"""Inferred peak demand D and period volume V for an NVTA corridor.

Runs the QVDF duration branch over every link of a corridor using the advisor's
own calibrated parameters, and reports D and V per link and period.

Everything here follows the advisor's conventions rather than the I-405 ones,
because his ``f_d`` and ``n`` were fitted against his definitions:

  * the congestion episode is the span below a fixed ``cutoff`` speed, not the
    0.70/0.75 hysteresis rule used on PeMS;
  * ``n`` and ``s`` come from his parameter file, not the frozen 1.10 / 1.40;
  * capacity and free speed are his hardcoded constants.

Provenance warning
------------------
``count_total_15min`` in the time-dependent handoff is not an independent
measurement. Across 1,564 bins it is a single-valued unimodal function of speed
peaking at the cutoff, no bin exceeds capacity (max 99.64% of it), an S3
inversion reproduces it to 2.73%, and every link reports one lane. It is
therefore treated as speed-derived: the observed columns below are labelled
``speed_derived`` and a comparison against them is a self-consistency check, not
a validation. Both sides trace back to the same speed curve.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# The advisor's reporting clock, read off the handoff's own period labels.
PERIOD_BOUNDS_MIN = {"AM": (300, 600), "MD": (600, 840), "PM": (840, 1200), "NT": (1200, 1320)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-file", type=Path, required=True,
                        help="handoff_avgweekday_timedependent.csv")
    parser.add_argument("--params-file", type=Path, required=True,
                        help="handoff_link_qvdf_params.csv")
    parser.add_argument("--corridor", default="I-395 NB")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "outputs/nvta_corridor_d_v_i395nb")
    return parser.parse_args()


def episode_from_cutoff(speed: np.ndarray, minutes: np.ndarray, cutoff: float) -> dict:
    """Longest contiguous run below the cutoff speed — the advisor's P.

    His f_d and n were calibrated against a fixed-threshold episode, so the
    PeMS hysteresis detector would produce a P his parameters never saw.
    """
    below = speed < cutoff
    if not below.any():
        return {"episode": False}
    runs, start = [], None
    for i, flag in enumerate(below):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(below) - 1))
    first, last = max(runs, key=lambda r: r[1] - r[0])
    step = float(np.median(np.diff(minutes))) if len(minutes) > 1 else 15.0
    window = speed[first:last + 1]
    t2_index = first + int(np.argmin(window))
    return {
        "episode": True,
        # Duration spans the bins below cutoff, so it includes the last bin's width.
        "P_h": (last - first + 1) * step / 60.0,
        "t0_min": float(minutes[first]),
        "T2_min": float(minutes[t2_index]),
        "t3_min": float(minutes[last] + step),
        "vT2_mph": float(speed[t2_index]),
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile = pd.read_csv(args.profile_file)
    params = pd.read_csv(args.params_file)

    # The parameter table varies only by period: one AM row, one PM row, repeated
    # per link. Keyed that way it applies to any link without an id crosswalk.
    by_period = (
        params.dropna(subset=["dominant_period", "f_d", "n", "f_p", "s"])
        .groupby("dominant_period")[["f_d", "n", "f_p", "s"]]
        .median()
        .to_dict("index")
    )

    rows = []
    for (link_id, period), group in profile.groupby(["link_id", "period"], sort=True):
        if period not in by_period:
            continue
        group = group.sort_values("t_min")
        p = by_period[period]
        cutoff = float(group["cutoff"].iloc[0])
        lanes = int(group["lanes"].iloc[0])
        capacity_per_lane = float(group["capacity_vphpl"].iloc[0])
        capacity = capacity_per_lane * lanes
        start_min, end_min = PERIOD_BOUNDS_MIN[period]
        period_hours = (end_min - start_min) / 60.0

        episode = episode_from_cutoff(
            group["speed_smoothed"].to_numpy(float),
            group["t_min"].to_numpy(float),
            cutoff,
        )

        rate = group["count_total_15min"].to_numpy(float) * 4.0  # veh/h
        volume = float(group["count_total_15min"].sum())
        peak_1h = float(pd.Series(rate).rolling(4, min_periods=4).mean().max())
        k_d = peak_1h / (volume / period_hours) if volume > 0 else np.nan

        row = {
            "corridor": args.corridor,
            "link_id": int(link_id),
            "period": period,
            "period_hours": period_hours,
            "lanes": lanes,
            "length_mi": float(group["length_mi"].iloc[0]),
            "capacity_vphpl": capacity_per_lane,
            "capacity_vph": capacity,
            "cutoff_mph": cutoff,
            "free_speed_mph": float(group["free_flow"].iloc[0]),
            "f_d": p["f_d"], "n": p["n"], "f_p": p["f_p"], "s": p["s"],
            "minimum_speed_mph": float(group["speed_smoothed"].min()),
            # Speed-derived, not measured. See the module docstring.
            "volume_V_speed_derived_veh": volume,
            "demand_D_speed_derived_vph": peak_1h,
            "k_d_speed_derived": k_d,
            **{k: v for k, v in episode.items() if k != "episode"},
            "episode_identified": bool(episode["episode"]),
        }

        if episode["episode"]:
            P = episode["P_h"]
            x_hat = (P / p["f_d"]) ** (1.0 / p["n"])
            demand = capacity * x_hat
            row.update({
                "x_hat_D_over_C": x_hat,
                "demand_D_inferred_vph": demand,
                "volume_V_inferred_veh": period_hours * demand / k_d if k_d and np.isfinite(k_d) else np.nan,
                "z_predicted": p["f_p"] * P ** p["s"],
                "vT2_predicted_mph": cutoff / (1.0 + p["f_p"] * P ** p["s"]),
                "z_from_speed": cutoff / episode["vT2_mph"] - 1.0,
            })
        rows.append(row)

    frame = pd.DataFrame(rows).sort_values(["period", "link_id"]).reset_index(drop=True)
    for label in ["demand_D", "volume_V"]:
        inferred, derived = f"{label}_inferred_{'vph' if label[-1] == 'D' else 'veh'}", f"{label}_speed_derived_{'vph' if label[-1] == 'D' else 'veh'}"
        frame[f"{label}_delta"] = frame[inferred] - frame[derived]
        frame[f"{label}_ape_pct"] = (frame[f"{label}_delta"].abs() / frame[derived]) * 100.0
    frame.to_csv(args.output_dir / "corridor_d_v.csv", index=False)

    identified = frame[frame["episode_identified"]]
    summary = {
        "corridor": args.corridor,
        "source": {"profile": str(args.profile_file), "params": str(args.params_file)},
        "parameters_by_period": by_period,
        "conventions": {
            "episode": "longest contiguous run below the advisor's fixed cutoff speed",
            "periods_min": PERIOD_BOUNDS_MIN,
            "n_and_s": "from the advisor's parameter file, not the I-405 frozen 1.10 / 1.40",
        },
        "coverage": {
            "link_periods": int(len(frame)),
            "episode_identified": int(len(identified)),
            "links": int(frame["link_id"].nunique()),
        },
        "inferred": {
            period: {
                "link_periods": int(len(g)),
                "D_median_vph": float(g["demand_D_inferred_vph"].median()),
                "D_min_vph": float(g["demand_D_inferred_vph"].min()),
                "D_max_vph": float(g["demand_D_inferred_vph"].max()),
                "V_median_veh": float(g["volume_V_inferred_veh"].median()),
                "x_hat_median": float(g["x_hat_D_over_C"].median()),
                "P_median_h": float(g["P_h"].median()),
            }
            for period, g in identified.groupby("period")
        },
        "self_consistency_against_speed_derived_counts": {
            period: {
                "demand_D_mape_pct": float(g["demand_D_ape_pct"].mean()),
                "volume_V_mape_pct": float(g["volume_V_ape_pct"].mean()),
            }
            for period, g in identified.groupby("period")
        },
        "provenance_warning": (
            "count_total_15min is speed-derived, not measured: it is a single-valued "
            "unimodal function of speed peaking at the cutoff, no bin of 1,564 exceeds "
            "capacity (max 99.64%), an S3 inversion reproduces it to 2.73%, and every "
            "link reports one lane. The comparison above is a self-consistency check "
            "between two speed-derived quantities, not a validation against counts."
        ),
    }
    (args.output_dir / "corridor_d_v_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
