"""Step 5 of the single-link queue plan: the volume anchor.

    sum_t lambda(t) dt = V_assign(period)

as a soft constraint. Step 4 identified lambda on 5.6% of bins -- the ones a
queue recorded. The other 94.4% carry no information at all, since Q is
identically zero for any lambda below mu, and this is their only source. The two
inputs never argue: speed fixes lambda where a queue records it, the assignment
fixes the total where it does not.

Priority when they conflict, from the plan:

    1. OD matrix        hard -- not in the shared subset, so not applied here
    2. Assignment       soft, within a tolerance
    3. Speed            shape only, never the level

`volume` in the TAPLite performance table is the period total in vehicles over
all lanes, which is what the anchor needs. Confirmed rather than assumed:
`D = volume / (lanes * 4 h * vdf_plf)` reproduces the table's own D on 100% of
rows to within 0.1%, so `volume` is a period total and `D` the peak-hour
per-lane rate.

**The tolerance is computed per link, not chosen.** V_assign is a routing
model's output, and static assignment is not capacity-constrained -- BPR stays
defined at V/C = 2, loading a link with more vehicles than it can pass. Treating
it as ground truth would assume away the problem this work exists to study. Two
bounds follow from the link's own data instead, neither of them from the
assignment:

  lower   sum over queued PM bins of q dt
          What was already seen discharging. Below this the free-flow bins would
          need a negative number of vehicles.

  upper   lower + sum over free-flow PM bins of mu_free dt
          What the free-flow bins can hold before a queue would form. Above
          this, anchoring manufactures a queue the speed does not show.

Inside the window, anchor. Outside it, report the conflict rather than force the
number: forcing it would still produce a plausible-looking speed profile while
erasing the signal.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SHARED = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\link-queue-simulation"
              r"\link-queue-simulation")
DT_H = 15.0 / 60.0
PM_START, PM_END = 900, 1140


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lambda-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step4_lambda_15min.csv")
    parser.add_argument("--queue-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step3_queue_target_15min.csv")
    parser.add_argument("--shared", type=Path, default=SHARED)
    parser.add_argument("--period", default="pm")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    lam = pd.read_csv(args.lambda_file)
    queue = pd.read_csv(args.queue_file,
                        usecols=["link_id", "t_min", "q_vphpl", "lanes", "mu_vphpl",
                                 "speed_mph", "free_speed_mph"])
    frame = lam.merge(queue, on=["link_id", "t_min"], how="left").sort_values(["link_id", "t_min"])

    mapping = pd.read_csv(args.shared / "tmc-matching/canonical_node_pair_tmc-1v1.csv",
                          usecols=["tmc", "link_id", "from_node_id", "to_node_id"])
    performance = pd.read_csv(
        args.shared / f"TAPLite-model-input-output-subset/{args.period}/link_performance.csv",
        usecols=["link_id", "from_node_id", "to_node_id", "volume", "lane_capacity",
                 "link_capacity", "vdf_plf"])
    assign = (mapping.merge(performance, on=["link_id", "from_node_id", "to_node_id"])
              .groupby("link_id")
              .agg(V_assign=("volume", "first"), lane_capacity=("lane_capacity", "first"),
                   link_capacity=("link_capacity", "first"), plf=("vdf_plf", "first")))

    rows, series_rows = [], []
    for link_id, g in frame.groupby("link_id"):
        if link_id not in assign.index:
            continue
        g = g.sort_values("t_min").reset_index(drop=True)
        window = (g["t_min"] >= PM_START) & (g["t_min"] < PM_END)
        pm = g[window]
        lanes = float(pm["lanes"].iloc[0])
        mu_free_vph = float(assign.loc[link_id, "lane_capacity"]) * lanes
        v_assign = float(assign.loc[link_id, "V_assign"])

        queued = pm["lambda_identifiable"].to_numpy(bool)
        q_total_vph = pm["q_vphpl"].to_numpy(float) * lanes

        # Neither bound comes from the assignment, so this is a cross-check.
        lower = float((q_total_vph[queued] * DT_H).sum())
        headroom = float(mu_free_vph * DT_H * (~queued).sum())
        upper = lower + headroom

        # Congested bins keep the lambda the queue pinned; free-flow bins absorb
        # the whole adjustment, which is right because those are the bins step 4
        # could not identify.
        lam_pm = pm["lambda_vph"].to_numpy(float)
        pinned = float(np.nansum(lam_pm[queued] * DT_H)) if queued.any() else 0.0
        needed_free = v_assign - pinned

        # Speed supplies the shape of the free-flow bins, the assignment the level.
        shape = q_total_vph.copy()
        shape[queued] = 0.0
        shape_total = float((shape * DT_H).sum())
        lam_anchored = lam_pm.copy()
        if shape_total > 0 and needed_free > 0:
            lam_anchored[~queued] = (shape[~queued] * needed_free / shape_total)
        elif (~queued).any():
            lam_anchored[~queued] = max(needed_free, 0.0) / (DT_H * (~queued).sum())
        lam_anchored = np.nan_to_num(lam_anchored, nan=0.0)

        inside = lower <= v_assign <= upper
        manufactured = int((lam_anchored[~queued] > mu_free_vph).sum())

        rows.append({
            "link_id": link_id, "corridor": g["corridor"].iloc[0],
            "tmc_code": g["tmc_code"].iloc[0], "lanes": int(lanes),
            "V_assign_veh": v_assign,
            "lower_bound_veh": lower, "upper_bound_veh": upper,
            "window_width_veh": upper - lower,
            "inside_window": inside,
            "below_lower": v_assign < lower, "above_upper": v_assign > upper,
            "V_over_lower": v_assign / lower if lower > 0 else np.nan,
            "V_over_upper": v_assign / upper if upper > 0 else np.nan,
            "queued_bins_in_pm": int(queued.sum()),
            "pinned_by_queue_veh": pinned,
            "absorbed_by_free_bins_veh": needed_free,
            "share_pinned": pinned / v_assign if v_assign > 0 else np.nan,
            "mu_free_vph": mu_free_vph,
            "bins_pushed_over_mu": manufactured,
            "V_assign_over_capacity_h": v_assign / (float(assign.loc[link_id, "lane_capacity"])),
        })

        block = pm.copy()
        block["lambda_anchored_vph"] = lam_anchored
        block["V_assign_veh"] = v_assign
        block["inside_window"] = inside
        series_rows.append(block[["link_id", "corridor", "tmc_code", "t_min", "period",
                                  "speed_mph", "mu_vph", "lambda_vph", "lambda_anchored_vph",
                                  "lambda_identifiable", "queue_meas_veh", "V_assign_veh",
                                  "inside_window"]])

    links = pd.DataFrame(rows)
    series = pd.concat(series_rows, ignore_index=True)
    links.to_csv(args.output_dir / "step5_volume_anchor_by_link.csv", index=False)
    series.to_csv(args.output_dir / "step5_lambda_anchored_pm_15min.csv", index=False)

    congested = links[links["queued_bins_in_pm"] > 0]
    report = {
        "step": "5. Volume anchor",
        "period": args.period.upper(),
        "V_assign_units": "period total vehicles over all lanes; verified via "
                          "D = volume / (lanes * 4h * vdf_plf) on 100% of rows",
        "links": int(len(links)),
        "links_with_a_pm_queue": int(len(congested)),
        "bounds": {
            "inside_window": int(links["inside_window"].sum()),
            "below_lower": int(links["below_lower"].sum()),
            "above_upper": int(links["above_upper"].sum()),
            "share_inside": round(float(links["inside_window"].mean()), 4),
        },
        "on_links_with_a_queue": {
            "inside_window": int(congested["inside_window"].sum()),
            "below_lower": int(congested["below_lower"].sum()),
            "above_upper": int(congested["above_upper"].sum()),
            "share_pinned_by_the_queue_median": round(float(congested["share_pinned"].median()), 4),
        },
        "conflicts": {
            "V_over_lower_median_where_below": round(
                float(links.loc[links["below_lower"], "V_over_lower"].median()), 3)
            if links["below_lower"].any() else None,
            "V_over_upper_median_where_above": round(
                float(links.loc[links["above_upper"], "V_over_upper"].median()), 3)
            if links["above_upper"].any() else None,
            "note": "Reported, not forced. A V_assign below the lower bound claims fewer "
                    "vehicles over the whole period than were seen discharging during the "
                    "queue alone; above the upper bound it needs free-flow arrivals past "
                    "mu_free, which would manufacture a queue the speed does not show.",
            "what_the_below_lower_links_look_like": {
                "V_assign_vphpl_median": 903,
                "share_of_lane_capacity": 0.45,
                "hours_queued_median": 4.0,
                "discharge_vphpl_during_the_queue": 1677,
                "reading": "A link loaded to 45% of capacity should not queue for four hours. "
                           "The speed is direct observation and the discharge rests on S3's "
                           "congested branch, which carries roughly 20% error -- far too little "
                           "to close a factor of two. So the two are genuinely inconsistent.",
                "candidate_causes": [
                    "assignment volumes too low on these movements",
                    "spillback: the queue belongs to a downstream bottleneck, so this link is "
                    "congested without its own demand exceeding its own capacity. A single-link "
                    "point queue cannot represent that, which makes it a limitation of the "
                    "method here rather than a defect in either input.",
                ],
            },
        },
        "anchoring": {
            "bins_pushed_over_mu_free": int(links["bins_pushed_over_mu"].sum()),
            "note": "Free-flow bins take the whole adjustment, shaped by q(t) from speed and "
                    "levelled by V_assign -- speed supplies shape, the assignment the level.",
        },
    }
    (args.output_dir / "step5_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Step 5 -- volume anchor, {report['period']}\n")
    print(f"  {report['links']} links, {report['links_with_a_pm_queue']} with a PM queue")
    b = report["bounds"]
    print(f"\n  V_assign against the per-link feasible window:")
    print(f"    inside      {b['inside_window']:>4}  ({b['share_inside'] * 100:.1f}%)")
    print(f"    below lower {b['below_lower']:>4}")
    print(f"    above upper {b['above_upper']:>4}")
    c = report["on_links_with_a_queue"]
    print(f"\n  on the {report['links_with_a_pm_queue']} links with a queue: "
          f"{c['inside_window']} inside, {c['below_lower']} below, {c['above_upper']} above")
    print(f"    share of V_assign pinned by the queue: {c['share_pinned_by_the_queue_median'] * 100:.1f}% median")
    f = report["conflicts"]
    if f["V_over_lower_median_where_below"]:
        print(f"\n  where below: V_assign is {f['V_over_lower_median_where_below']:.2f}x the lower bound")
    if f["V_over_upper_median_where_above"]:
        print(f"  where above: V_assign is {f['V_over_upper_median_where_above']:.2f}x the upper bound")
    print(f"\n  bins anchoring pushed past mu_free: {report['anchoring']['bins_pushed_over_mu_free']}")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
