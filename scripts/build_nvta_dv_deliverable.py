"""The hand-over table: D and V per network link, next to the assignment.

``run_nvta_corridors_dv_from_ritis.py`` reports per TMC, because that is the
resolution the speed arrives at. The assignment is keyed on ``net_link_id``, so
this rolls the TMCs up to network links and joins the DTA columns beside ours.

Roll-up rule: D and V per lane are **length-weighted averages**, not sums. Where
two TMCs cover one network link they are two measurements of the traffic through
that link, so summing them would double the volume. ``miles`` is summed and the
totals are recomputed from the weighted per-lane figures.

The comparison to draw:

``dc_dta_vol``  is a period demand volume over an hourly capacity, the same
                construction as our ``D_over_C_h`` and ``V_over_C_h``. Because
                theirs covers the whole period, ``V_over_C_h`` is the like-for-like
                column and ``D_over_C_h`` is the congested part of it.
``dc_dta_doc``  is the rate ratio, i.e. ``dc_dta_vol`` divided by the period
                length, and compares to our average flow over capacity.

V is an upper bound (see docs/NVTA_D_AND_V.md), so a V/C above dc_dta_vol is the
expected direction, not a contradiction.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NVTA = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\T2_Task_3\NVTA_internal-git"
            r"\t2_analysis\qvdf_projection_dashboard")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--results-file", type=Path,
                        default=ROOT / "outputs/nvta_corridors_dv_ritis/corridor_dv_by_tmc.csv")
    parser.add_argument("--assignment-file", type=Path, default=NVTA / "data/dtalite_assignment_dc.csv")
    parser.add_argument("--clock", default="assignment", choices=["assignment", "pipeline"],
                        help="the DTA periods are 3/6/4 h, so the assignment clock is the "
                             "comparable one; pipeline matches the handoff instead")
    parser.add_argument("--output-file", type=Path,
                        default=ROOT / "outputs/nvta_corridors_dv_ritis/nvta_dv_vs_assignment.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    results = pd.read_csv(args.results_file)
    results = results[(results["clock"] == args.clock) & results["net_link_id"].notna()].copy()
    results["net_link_id"] = results["net_link_id"].astype(int)

    def roll_up(g: pd.DataFrame) -> pd.Series:
        w = g["miles"].to_numpy(float)
        w = w / w.sum() if w.sum() > 0 else np.full(len(g), 1.0 / len(g))
        lanes = int(g["lanes"].iloc[0])
        d_lane = float(np.dot(w, g["D_veh_per_lane"]))
        v_lane = float(np.dot(w, g["V_veh_per_lane"]))
        capacity = float(g["capacity_vphpl"].iloc[0])
        return pd.Series({
            "corridor": g["corridor"].iloc[0],
            "tmcs": int(len(g)),
            "miles": float(g["miles"].sum()),
            "lanes": lanes,
            "capacity_vphpl": capacity,
            "period_hours": float(g["period_hours"].iloc[0]),
            "congested_tmcs": int(g["congested"].sum()),
            "P_h": float(np.dot(w, g["P_h"])),
            "min_speed_mph": float(g["min_speed_mph"].min()),
            "D_veh_per_lane": d_lane,
            "V_veh_per_lane": v_lane,
            "D_veh_total": d_lane * lanes,
            "V_veh_total": v_lane * lanes,
            "D_over_C_h": d_lane / capacity,
            "V_over_C_h": v_lane / capacity,
        })

    links = (results.groupby(["net_link_id", "period"]).apply(roll_up, include_groups=False)
             .reset_index())
    assignment = pd.read_csv(args.assignment_file)
    out = links.merge(assignment, on=["net_link_id", "period"], how="left")

    # Their rate ratio against ours, and their period volume against ours.
    out["our_avg_flow_over_C"] = out["V_over_C_h"] / out["period_hours"]
    out["V_over_C_minus_dta_vol"] = out["V_over_C_h"] - out["dc_dta_vol"]
    out["V_over_C_div_dta_vol"] = out["V_over_C_h"] / out["dc_dta_vol"].replace(0, np.nan)
    out["D_over_C_div_dta_vol"] = out["D_over_C_h"] / out["dc_dta_vol"].replace(0, np.nan)
    out["matched_to_assignment"] = out["dc_dta_vol"].notna()

    columns = ["corridor", "net_link_id", "period", "tmcs", "miles", "lanes", "capacity_vphpl",
               "period_hours", "congested_tmcs", "P_h", "min_speed_mph",
               "D_veh_per_lane", "V_veh_per_lane", "D_veh_total", "V_veh_total",
               "D_over_C_h", "V_over_C_h", "our_avg_flow_over_C",
               "dc_dta_doc", "dc_dta_vol", "matched_to_assignment",
               "V_over_C_minus_dta_vol", "V_over_C_div_dta_vol", "D_over_C_div_dta_vol"]
    out = out[columns].sort_values(["corridor", "period", "net_link_id"])
    out.to_csv(args.output_file, index=False)

    matched = out[out["matched_to_assignment"]]
    print(f"{len(out)} network-link periods, {out['net_link_id'].nunique()} links, "
          f"{len(matched)} matched to the assignment ({args.clock} clock)\n")
    print(f"{'corridor':<11} {'per':<4} {'n':>4} {'our V/C':>8} {'DTA vol':>8} {'ratio':>7} "
          f"{'our D/C':>8} {'DTA doc':>8} {'our q/C':>8}")
    for (corridor, period), g in matched.groupby(["corridor", "period"]):
        print(f"{corridor:<11} {period:<4} {len(g):>4} {g['V_over_C_h'].median():>8.2f} "
              f"{g['dc_dta_vol'].median():>8.2f} {g['V_over_C_div_dta_vol'].median():>7.2f} "
              f"{g['D_over_C_h'].median():>8.2f} {g['dc_dta_doc'].median():>8.2f} "
              f"{g['our_avg_flow_over_C'].median():>8.2f}")
    print(f"\nWrote {args.output_file}")


if __name__ == "__main__":
    main()
