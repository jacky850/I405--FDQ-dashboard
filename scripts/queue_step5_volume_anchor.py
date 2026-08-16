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

Run over AM, MD and PM together, because step 6 is one continuous recurrence and
a queue standing at 15:00 has to be carried in rather than reset. The period
boundaries are the assignment's own, read off its 5-minute speed columns: AM
06:00-09:00, MD 09:00-15:00, PM 15:00-19:00.

`volume` in the TAPLite performance table is the period total in vehicles over
all lanes, which is what the anchor needs. Confirmed rather than assumed:
`D = volume / (lanes * period_hours * vdf_plf)` reproduces the table's own D on
100% of rows to within 0.1%, so `volume` is a period total and `D` the peak-hour
per-lane rate.

**The tolerance is computed per link, not chosen.** V_assign is a routing
model's output, and static assignment is not capacity-constrained -- BPR stays
defined at V/C = 2, loading a link with more vehicles than it can pass. Treating
it as ground truth would assume away the problem this work exists to study. Two
bounds follow from the link's own data instead, neither of them from the
assignment:

  lower   sum over queued bins of q dt
          What was already seen discharging. Below this the free-flow bins would
          need a negative number of vehicles.

  upper   lower + sum over free-flow bins of mu_free dt
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
PERIOD_WINDOWS = {"am": (360, 540), "md": (540, 900), "pm": (900, 1140)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--lambda-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step4_lambda_15min.csv")
    parser.add_argument("--queue-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step3_queue_target_15min.csv")
    parser.add_argument("--shared", type=Path, default=SHARED)
    parser.add_argument("--periods", nargs="+", default=["am", "md", "pm"],
                        help="step 6 runs one continuous recurrence across these, so a queue "
                             "standing at 15:00 is carried in rather than reset")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def anchor_one_period(frame: pd.DataFrame, assign: pd.DataFrame, period: str,
                      start: int, end: int) -> tuple[list[dict], list[pd.DataFrame]]:
    """Anchor lambda over one period, and bound V_assign from the link's own data."""
    rows: list[dict] = []
    series_rows: list[pd.DataFrame] = []
    hours = (end - start) / 60.0

    for link_id, g in frame.groupby("link_id"):
        if link_id not in assign.index:
            continue
        g = g.sort_values("t_min").reset_index(drop=True)
        block = g[(g["t_min"] >= start) & (g["t_min"] < end)].copy()
        if block.empty:
            continue

        lanes = float(block["lanes"].iloc[0])
        mu_free_vph = float(assign.loc[link_id, "lane_capacity"]) * lanes
        v_assign = float(assign.loc[link_id, "V_assign"])
        queued = block["lambda_identifiable"].to_numpy(bool)
        q_total_vph = block["q_vphpl"].to_numpy(float) * lanes

        # Neither bound comes from the assignment, so this is a cross-check
        # rather than the model validating itself.
        lower = float((q_total_vph[queued] * DT_H).sum())
        upper = lower + float(mu_free_vph * DT_H * (~queued).sum())

        # Congested bins keep the lambda the queue pinned; free-flow bins absorb
        # the whole adjustment, which is right because those are exactly the bins
        # step 4 could not identify.
        lam_period = block["lambda_vph"].to_numpy(float)
        pinned = float(np.nansum(lam_period[queued] * DT_H)) if queued.any() else 0.0
        needed_free = v_assign - pinned

        # phi: the free-flow shape from speed, normalised over the free-flow bins
        # only. Extending it across the queued bins would invert the peak, since
        # there q is throughput rather than demand -- the flow is lowest exactly
        # when demand is highest.
        shape = q_total_vph.copy()
        shape[queued] = 0.0
        shape_total = float((shape * DT_H).sum())
        lam_anchored = lam_period.copy()
        if shape_total > 0 and needed_free > 0:
            lam_anchored[~queued] = shape[~queued] * needed_free / shape_total
        elif (~queued).any():
            lam_anchored[~queued] = max(needed_free, 0.0) / (DT_H * (~queued).sum())
        lam_anchored = np.nan_to_num(lam_anchored, nan=0.0)

        # The assignment is a soft constraint, so it does not get to push a
        # free-flow bin past mu_free. Doing so manufactures a queue the speed
        # does not show: run unclipped, the four links this affects produced
        # queues up to 55 times the link's physical storage, three of them on
        # links whose measured queue is exactly zero. Clip, and carry the volume
        # that could not be placed as a reported shortfall.
        over = (~queued) & (lam_anchored > mu_free_vph)
        unplaced = float(((lam_anchored[over] - mu_free_vph) * DT_H).sum())
        lam_anchored[over] = mu_free_vph

        rows.append({
            "period": period.upper(), "link_id": link_id,
            "corridor": g["corridor"].iloc[0], "tmc_code": g["tmc_code"].iloc[0],
            "lanes": int(lanes), "period_hours": hours,
            "V_assign_veh": v_assign,
            "lower_bound_veh": lower, "upper_bound_veh": upper,
            "inside_window": bool(lower <= v_assign <= upper),
            "below_lower": bool(v_assign < lower), "above_upper": bool(v_assign > upper),
            "V_over_lower": v_assign / lower if lower > 0 else np.nan,
            "V_over_upper": v_assign / upper if upper > 0 else np.nan,
            "queued_bins": int(queued.sum()),
            "pinned_by_queue_veh": pinned,
            "absorbed_by_free_bins_veh": needed_free,
            "share_pinned": pinned / v_assign if v_assign > 0 else np.nan,
            "mu_free_vph": mu_free_vph,
            "bins_clipped_at_mu_free": int(over.sum()),
            "volume_not_placed_veh": unplaced,
            "share_not_placed": unplaced / v_assign if v_assign > 0 else np.nan,
            "V_assign_vphpl": v_assign / lanes / hours,
        })

        block["lambda_anchored_vph"] = lam_anchored
        block["V_assign_veh"] = v_assign
        block["anchor_period"] = period.upper()
        block["inside_window"] = bool(lower <= v_assign <= upper)
        series_rows.append(block[["link_id", "corridor", "tmc_code", "t_min", "anchor_period",
                                  "speed_mph", "mu_vph", "lambda_vph", "lambda_anchored_vph",
                                  "lambda_identifiable", "queue_meas_veh", "lanes",
                                  "V_assign_veh", "inside_window"]])
    return rows, series_rows


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

    rows: list[dict] = []
    series_rows: list[pd.DataFrame] = []
    for period in args.periods:
        start, end = PERIOD_WINDOWS[period]
        performance = pd.read_csv(
            args.shared / f"TAPLite-model-input-output-subset/{period}/link_performance.csv",
            usecols=["link_id", "from_node_id", "to_node_id", "volume", "lane_capacity",
                     "link_capacity", "vdf_plf"])
        assign = (mapping.merge(performance, on=["link_id", "from_node_id", "to_node_id"])
                  .groupby("link_id")
                  .agg(V_assign=("volume", "first"), lane_capacity=("lane_capacity", "first"),
                       link_capacity=("link_capacity", "first"), plf=("vdf_plf", "first")))
        r, s = anchor_one_period(frame, assign, period, start, end)
        rows += r
        series_rows += s

    links = pd.DataFrame(rows)
    series = pd.concat(series_rows, ignore_index=True).sort_values(["link_id", "t_min"])
    links.to_csv(args.output_dir / "step5_volume_anchor_by_link.csv", index=False)
    series.to_csv(args.output_dir / "step5_lambda_anchored_15min.csv", index=False)

    def summarise(g: pd.DataFrame) -> dict:
        q = g[g["queued_bins"] > 0]
        return {
            "links": int(len(g)),
            "inside_window": int(g["inside_window"].sum()),
            "below_lower": int(g["below_lower"].sum()),
            "above_upper": int(g["above_upper"].sum()),
            "links_with_a_queue": int(len(q)),
            "of_those_inside": int(q["inside_window"].sum()),
            "of_those_below": int(q["below_lower"].sum()),
            "V_over_lower_median_where_below": round(
                float(g.loc[g["below_lower"], "V_over_lower"].median()), 3)
            if g["below_lower"].any() else None,
            "V_assign_vphpl_median": round(float(g["V_assign_vphpl"].median()), 0),
        }

    report = {
        "step": "5. Volume anchor",
        "periods": [p.upper() for p in args.periods],
        "V_assign_units": "period total vehicles over all lanes; verified via "
                          "D = volume / (lanes * period_hours * vdf_plf) on 100% of rows",
        "by_period": {p.upper(): summarise(links[links["period"] == p.upper()])
                      for p in args.periods},
        "anchoring": {
            "bins_clipped_at_mu_free": int(links["bins_clipped_at_mu_free"].sum()),
            "links_clipped": int((links["bins_clipped_at_mu_free"] > 0).sum()),
            "volume_not_placed_veh": round(float(links["volume_not_placed_veh"].sum()), 0),
            "clipping_note": "A free-flow bin is never pushed past mu_free. Unclipped, the four "
                             "links affected produced queues up to 55x the link's storage, three "
                             "of them where the measured queue is exactly zero -- which is the "
                             "manufactured queue the upper bound predicts.",
            "note": "Free-flow bins take the whole adjustment, shaped by phi -- q(t) from speed "
                    "normalised over the free-flow bins only -- and levelled by V_assign. phi is "
                    "not extended across the queued bins: there q is throughput rather than "
                    "demand, so the flow is lowest exactly when demand is highest and the shape "
                    "would come out inverted.",
        },
        "conflict": {
            "note": "Reported, not forced. Below the lower bound the assignment claims fewer "
                    "vehicles over the whole period than were seen discharging during the queue "
                    "alone. Two causes are plausible: the volumes are too low, or the queue "
                    "spilled back from a downstream bottleneck, in which case the link is "
                    "congested without its own demand exceeding its own capacity -- which a "
                    "single-link point queue cannot represent.",
        },
    }
    (args.output_dir / "step5_summary.json").write_text(json.dumps(report, indent=2),
                                                        encoding="utf-8")

    print("Step 5 -- volume anchor\n")
    print(f"  {'period':<7} {'links':>6} {'inside':>7} {'below':>6} {'above':>6} | "
          f"{'w/queue':>8} {'inside':>7} {'below':>6} | {'V_assign':>12}")
    for p in args.periods:
        b = report["by_period"][p.upper()]
        print(f"  {p.upper():<7} {b['links']:>6} {b['inside_window']:>7} {b['below_lower']:>6} "
              f"{b['above_upper']:>6} | {b['links_with_a_queue']:>8} {b['of_those_inside']:>7} "
              f"{b['of_those_below']:>6} | {b['V_assign_vphpl_median']:>6.0f} vphpl")
    a = report["anchoring"]
    print(f"\n  clipped at mu_free: {a['bins_clipped_at_mu_free']} bins on "
          f"{a['links_clipped']} links, {a['volume_not_placed_veh']:,.0f} veh could not be placed")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
