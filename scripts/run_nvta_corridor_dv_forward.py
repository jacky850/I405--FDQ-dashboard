"""Period demand D and volume V per link, built forward from q(t).

This follows the advisor's recipe rather than inverting the QVDF duration
branch::

    infer q(t) first, and then derive D = sum of q(t) for v < v_cutoff

so D and V are accumulated vehicle counts over a period, not flow rates. That
distinction is the whole point: ``D/C`` here divides a period volume by an
*hourly* capacity, so it carries units of hours and values of 3-4 are ordinary.
The advisor's own assignment table confirms the convention -- across 208 rows
``dc_dta_vol / dc_dta_doc`` equals 3.000 / 6.000 / 4.000 for AM / MD / PM, the
period lengths in hours.

Two independent q(t) series are carried side by side:

``handoff``
    ``count_total_15min`` as delivered.
``s3``
    re-inferred here from ``speed_smoothed`` through the S3 fundamental
    diagram, so D does not depend on a column whose derivation we did not run.

They agree closely, which is expected -- the handoff counts are themselves
speed-derived (a single-valued unimodal function of speed peaking at the
cutoff, no bin above capacity, every link one lane). Neither is an independent
traffic count, so D and V here are *served volume* reconstructed from speed.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
# Read off the handoff's own period labels; note these are NOT the assignment
# clock, where the same labels span 3 / 6 / 4 hours.
PERIOD_BOUNDS_MIN = {"AM": (300, 600), "MD": (600, 840), "PM": (840, 1200), "NT": (1200, 1320)}
BIN_H = 0.25


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-file", type=Path,
                        default=ROOT / "data/nvta_i395nb_handoff/handoff_avgweekday_timedependent.csv")
    parser.add_argument("--params-file", type=Path,
                        default=ROOT / "data/nvta_i395nb_handoff/handoff_link_qvdf_params.csv")
    parser.add_argument("--corridor", default="I-395 NB")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "outputs/nvta_corridor_dv_forward_i395nb")
    return parser.parse_args()


def s3_flow(speed: np.ndarray, free_speed: float, speed_at_capacity: float,
            capacity: float) -> np.ndarray:
    """Flow implied by speed through the S3 fundamental diagram, veh/h.

    ``v(k) = vf / [1 + (k/kc)^m]^(2/m)`` inverts to
    ``k(v) = kc [ (vf/v)^(m/2) - 1 ]^(1/m)``, and ``m`` follows from the pair
    (vf, vc) because ``v = vf * 2^(-2/m)`` at ``k = kc``.

    The inversion picks the congested branch, so free-flow bins come back at
    capacity rather than at their true (lower) flow. Those bins are excluded
    from D by the cutoff, but they do enter V -- see the summary's
    ``s3_vs_handoff`` block for how far apart the two series land.
    """
    m = 2.0 * np.log(2.0) / np.log(free_speed / speed_at_capacity)
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    density = k_c * np.maximum((free_speed / v) ** (m / 2.0) - 1.0, 0.0) ** (1.0 / m)
    return np.minimum(density * v, capacity)


def longest_run_h(below: np.ndarray) -> float:
    """Duration of the longest contiguous span below the cutoff, hours."""
    best = run = 0
    for flag in below:
        run = run + 1 if flag else 0
        best = max(best, run)
    return best * BIN_H


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    profile = pd.read_csv(args.profile_file)
    params = pd.read_csv(args.params_file)

    # The parameter table varies only by period, so key it that way.
    by_period = (
        params.dropna(subset=["dominant_period", "f_d", "n", "f_p", "s"])
        .groupby("dominant_period")[["f_d", "n", "f_p", "s"]].median().to_dict("index")
    )

    rows = []
    for (link_id, period), group in profile.groupby(["link_id", "period"], sort=True):
        group = group.sort_values("t_min")
        cutoff = float(group["cutoff"].iloc[0])
        free_speed = float(group["free_flow"].iloc[0])
        lanes = int(group["lanes"].iloc[0])
        capacity = float(group["capacity_vphpl"].iloc[0]) * lanes
        start_min, end_min = PERIOD_BOUNDS_MIN[period]
        period_hours = (end_min - start_min) / 60.0

        speed = group["speed_smoothed"].to_numpy(float)
        below = speed < cutoff
        q_handoff = group["count_total_15min"].to_numpy(float) / BIN_H      # veh/h
        q_s3 = s3_flow(speed, free_speed, 49.5, capacity)                    # veh/h

        row = {
            "corridor": args.corridor,
            "link_id": int(link_id),
            "from_node_id": int(group["from_node_id"].iloc[0]),
            "to_node_id": int(group["to_node_id"].iloc[0]),
            "period": period,
            "period_start_min": start_min,
            "period_hours": period_hours,
            "length_mi": float(group["length_mi"].iloc[0]),
            "lanes": lanes,
            "capacity_vphpl": float(group["capacity_vphpl"].iloc[0]),
            "capacity_vph": capacity,
            "cutoff_mph": cutoff,
            "free_speed_mph": free_speed,
            "min_speed_mph": float(speed.min()),
            "bins_total": int(len(speed)),
            "bins_below_cutoff": int(below.sum()),
            "congested": bool(below.any()),
            # P as the advisor defines the episode, plus the contiguous span for
            # the duration-branch cross-check below.
            "P_h_below_cutoff": float(below.sum()) * BIN_H,
            "P_h_longest_episode": longest_run_h(below),
            # The deliverable. D restricted to congested bins, V over the period.
            "D_congested_veh": float((q_handoff[below] * BIN_H).sum()),
            "V_period_veh": float((q_handoff * BIN_H).sum()),
            "D_congested_veh_s3": float((q_s3[below] * BIN_H).sum()),
            "V_period_veh_s3": float((q_s3 * BIN_H).sum()),
        }
        row["D_over_C_h"] = row["D_congested_veh"] / capacity
        row["V_over_C_h"] = row["V_period_veh"] / capacity
        row["qbar_over_C_congested"] = (
            row["D_congested_veh"] / (capacity * row["P_h_below_cutoff"]) if below.any() else np.nan
        )
        row["peak_1h_flow_vph"] = float(pd.Series(q_handoff).rolling(4, min_periods=4).mean().max())

        # Cross-check only: does inverting the duration branch land on the same
        # D/C the forward sum produced? Parameters exist for AM and PM only.
        if period in by_period and below.any():
            p = by_period[period]
            branch = (row["P_h_longest_episode"] / p["f_d"]) ** (1.0 / p["n"])
            row.update({
                "f_d": p["f_d"], "n": p["n"], "f_p": p["f_p"], "s": p["s"],
                "D_over_C_duration_branch": branch,
                "D_over_C_branch_ape_pct": abs(branch - row["D_over_C_h"]) / row["D_over_C_h"] * 100.0,
            })
        rows.append(row)

    frame = pd.DataFrame(rows).sort_values(["period", "link_id"]).reset_index(drop=True)
    frame["D_vs_V_share"] = frame["D_congested_veh"] / frame["V_period_veh"]
    frame["s3_V_ape_pct"] = (frame["V_period_veh_s3"] - frame["V_period_veh"]).abs() / frame["V_period_veh"] * 100.0
    frame.to_csv(args.output_dir / "corridor_dv_forward.csv", index=False)

    order = ["AM", "MD", "PM", "NT"]
    summary = {
        "corridor": args.corridor,
        "method": "D = sum of q(t) for v < v_cutoff; V = sum of q(t) over the period",
        "units": {"D": "veh per period", "V": "veh per period",
                  "D_over_C_h": "period volume / hourly capacity, units of hours"},
        "source": {"profile": str(args.profile_file), "params": str(args.params_file)},
        "coverage": {
            "links": int(frame["link_id"].nunique()),
            "link_periods": int(len(frame)),
            "corridor_length_mi": float(frame.groupby("link_id")["length_mi"].first().sum()),
            "congested_link_periods": int(frame["congested"].sum()),
            "uncongested_link_periods": int((~frame["congested"]).sum()),
        },
        "period_clock_min": PERIOD_BOUNDS_MIN,
        "by_period": {},
        "s3_vs_handoff": {},
    }
    for period in order:
        g = frame[frame["period"] == period]
        c = g[g["congested"]]
        summary["by_period"][period] = {
            "period_hours": float(g["period_hours"].iloc[0]),
            "links": int(len(g)),
            "congested_links": int(len(c)),
            "V_median_veh": float(g["V_period_veh"].median()),
            "V_corridor_total_veh": float(g["V_period_veh"].sum()),
            "D_median_veh": float(c["D_congested_veh"].median()) if len(c) else 0.0,
            "D_over_C_median_h": float(c["D_over_C_h"].median()) if len(c) else 0.0,
            "V_over_C_median_h": float(g["V_over_C_h"].median()),
            "P_median_h": float(c["P_h_below_cutoff"].median()) if len(c) else 0.0,
            "qbar_over_C_median": float(c["qbar_over_C_congested"].median()) if len(c) else None,
            "duration_branch_check": (
                {
                    "D_over_C_branch_median": float(c["D_over_C_duration_branch"].median()),
                    "mape_pct": float(c["D_over_C_branch_ape_pct"].mean()),
                    "corr": float(c["D_over_C_h"].corr(c["D_over_C_duration_branch"])),
                }
                if "D_over_C_duration_branch" in c and c["D_over_C_duration_branch"].notna().any()
                else "no calibrated parameters for this period"
            ),
        }
        summary["s3_vs_handoff"][period] = {
            "V_mape_pct": float(g["s3_V_ape_pct"].mean()),
            "D_mape_pct": float(
                ((c["D_congested_veh_s3"] - c["D_congested_veh"]).abs() / c["D_congested_veh"] * 100).mean()
            ) if len(c) else None,
        }
    # Where the duration branch and the forward sum disagree, and why. The branch
    # implicitly assumes flow holds near a fixed share of capacity through the
    # episode; the error tracks how far that share actually falls.
    branch = frame[frame.get("D_over_C_duration_branch", pd.Series(dtype=float)).notna()]
    summary["branch_error_vs_flow_during_congestion"] = {
        period: {
            "qbar_over_C_min": round(float(g["qbar_over_C_congested"].min()), 3),
            "qbar_over_C_max": round(float(g["qbar_over_C_congested"].max()), 3),
            "corr_qbar_over_C_with_branch_error": round(
                float(g["qbar_over_C_congested"].corr(g["D_over_C_branch_ape_pct"])), 3),
        }
        for period, g in branch.groupby("period")
    } if len(branch) else {}
    summary["censored_episodes"] = {
        period: int((g["P_h_below_cutoff"] >= g["period_hours"] - 1e-9).sum())
        for period, g in frame[frame["congested"]].groupby("period")
    }
    summary["caveat"] = {
        "q_is_speed_derived": (
            "count_total_15min is not an independent count: it reproduces an S3 "
            "evaluation of speed_smoothed to 3.3% (R2 0.94), and at a given speed it "
            "varies only 1.5x across the day where measured I-405 flow varies 22.8x. "
            "Its daily mean/peak ratio is 0.94 against 0.57 for measured I-405 flow."
        ),
        "D_is_defensible": (
            "D sums bins below the cutoff, where the congested branch is steep and the "
            "speed-to-flow inversion is well posed."
        ),
        "V_is_not": (
            "V sums free-flow bins too, where one speed is consistent with a wide band "
            "of flows. Scored against measured counts on I-405 the same speed-only "
            "inversion overstates period volume by +19% (AM), +29% (MD), +34% (PM), "
            "+58% (NT), +53% full day. V here should be treated as an upper bound."
        ),
        "period_clock_mismatch": (
            "The handoff clock (AM 5h, MD 4h, PM 6h, NT 2h) differs from the assignment "
            "clock implied by dc_dta_vol/dc_dta_doc (AM 3h, MD 6h, PM 4h). V must be "
            "re-cut to the assignment periods before the two are compared."
        ),
    }
    (args.output_dir / "corridor_dv_forward_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    show = ["link_id", "period", "P_h_below_cutoff", "D_congested_veh", "V_period_veh",
            "D_over_C_h", "V_over_C_h", "D_over_C_duration_branch"]
    for period in order:
        g = frame[frame["period"] == period]
        print(f"\n=== {period}  ({g['period_hours'].iloc[0]:.0f} h, {int(g['congested'].sum())}/{len(g)} links congested) ===")
        print(g[[c for c in show if c in g]].to_string(index=False, float_format=lambda v: f"{v:,.2f}"))
    print("\n" + json.dumps(summary["by_period"], indent=2))
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
