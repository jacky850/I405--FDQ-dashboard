"""Package the single-link queue outputs as link observations for ODME.

The assignment's own link table carries obs_volume = -1 on all 756 link-period
rows, i.e. no counted volume anywhere on this subnetwork. Everything here is
inferred from observed speed instead, so each column is labelled by provenance
in the accompanying data dictionary and the columns that came from the
assignment are kept separate from the ones that did not.

Both free-flow speeds are carried side by side. They are the input the two
sides disagree on most, and the disagreement propagates into every volume
through the congestion cut-off.

Two files:

  odme_link_period.csv   756 rows, one per link and period. The ODME input.
  odme_link_15min.csv    13,104 rows, one per link and 15-minute bin over the
                         06:00-19:00 run window (52 bins), which is where the
                         model columns exist.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "outputs/nvta_queue"
SHARED = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\link-queue-simulation"
              r"\link-queue-simulation")
DT_H = 0.25
PERIOD_HOURS = {"AM": 3.0, "MD": 6.0, "PM": 4.0}
BINS_IN_PERIOD = {"AM": 12, "MD": 24, "PM": 16}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-dir", type=Path, default=QUEUE)
    parser.add_argument("--shared", type=Path, default=SHARED)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_odme")
    return parser.parse_args()


def clock(minute: float) -> str:
    if not np.isfinite(minute):
        return ""
    minute = int(round(minute)) % 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def episode_block(frame: pd.DataFrame, suffix: str) -> pd.DataFrame:
    """Deepest episode per link and period, flattened onto the period row."""
    columns = ["t0_min", "T2_min", "t3_min", "P_h", "vT2_mph"]
    best = (frame.sort_values("P_h", ascending=False)
            .groupby(["link_id", "period_by_T2"]).first())
    out = best[columns].add_suffix(f"_{suffix}")
    out.index = out.index.set_names(["link_id", "period"])
    return out


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    q = args.queue_dir

    anchors = pd.read_csv(q / "step5_volume_anchor_by_link.csv")
    scores = pd.read_csv(q / "step8_speed_scores_by_link.csv")
    obs_ep = pd.read_csv(q / "step2_episodes.csv")
    mod_ep = pd.read_csv(q / "step7_model_episodes.csv")
    audit = pd.read_csv(q / "free_speed_audit_by_tmc.csv")

    # step 1 is the only output carrying the node ids and both free speeds.
    base = (pd.read_csv(q / "step1_flow_average_weekday_15min.csv",
                        usecols=["link_id", "tmc_code", "corridor", "road", "direction",
                                 "from_node_id", "to_node_id", "length_mi", "lanes",
                                 "links_sharing_this_tmc", "lane_capacity",
                                 "free_speed_mph", "cutoff_speed_mph",
                                 "free_speed_observed_mph", "cutoff_observed_mph"])
            .groupby("link_id").first())
    base = base.rename(columns={"free_speed_mph": "free_speed_assign_mph",
                                "cutoff_speed_mph": "cutoff_assign_mph",
                                "free_speed_observed_mph": "free_speed_obs_p95_mph",
                                "cutoff_observed_mph": "cutoff_obs_mph",
                                "lane_capacity": "lane_capacity_vphpl"})

    # The assignment's free speed is impossible wherever it exceeds the fastest
    # speed the segment was ever observed to run. Carried as a flag so the
    # disagreement is visible per link rather than only in prose.
    observed_max = audit.set_index("tmc_code")["observed_max"]

    # Per-episode service rates, matched to the period the trough falls in.
    mu_by_period = (obs_ep.sort_values("P_h", ascending=False)
                    .groupby(["link_id", "period_by_T2"])
                    [["mu_queued_vph", "capacity_drop"]].first())
    mu_by_period.index = mu_by_period.index.set_names(["link_id", "period"])

    # ---- File A: link x period ---------------------------------------------
    a = anchors.copy()
    a = a.rename(columns={"lower_bound_veh": "V_throughput_obs_veh",
                          "pinned_by_queue_veh": "V_demand_obs_veh",
                          "upper_bound_veh": "V_max_feasible_veh"})
    a = a.join(base.drop(columns=["tmc_code", "corridor", "lanes"]), on="link_id")
    a = a.join(mu_by_period, on=["link_id", "period"])

    a["period_hours"] = a["period"].map(PERIOD_HOURS)
    a["bins_in_period"] = a["period"].map(BINS_IN_PERIOD)
    a["observation_weight"] = (a["queued_bins"] / a["bins_in_period"]).round(4)
    a["free_speed_diff_mph"] = (a["free_speed_assign_mph"]
                                - a["free_speed_obs_p95_mph"]).round(2)
    a["observed_max_mph"] = a["tmc_code"].map(observed_max).round(2)
    a["assign_free_speed_impossible"] = a["free_speed_assign_mph"] > a["observed_max_mph"]

    lane_hours = a["lanes"] * a["period_hours"]
    a["D_assign_vphpl"] = (a["V_assign_veh"] / lane_hours).round(1)
    a["D_obs_vphpl"] = (a["V_throughput_obs_veh"] / lane_hours).round(1)
    a["D_ratio"] = np.where(a["V_throughput_obs_veh"] > 0,
                            a["V_assign_veh"] / a["V_throughput_obs_veh"], np.nan).round(3)

    for source, frame in [("obs", obs_ep), ("model", mod_ep)]:
        a = a.join(episode_block(frame, source), on=["link_id", "period"])
    censored = mod_ep.groupby("link_id")["right_censored"].any()
    a["right_censored"] = a["link_id"].map(censored).fillna(False)
    a.loc[a["right_censored"], "P_h_model"] = np.nan

    anchored = scores[scores["variant"] == "anchored"].set_index("link_id")
    a["speed_mae_episode_mph"] = a["link_id"].map(anchored["mae_episode_mph"]).round(2)
    a["speed_mae_period_mph"] = a["link_id"].map(anchored["mae_period_mph"]).round(2)

    order = [
        "link_id", "from_node_id", "to_node_id", "tmc_code", "corridor", "road",
        "direction", "period", "period_hours", "bins_in_period", "lanes", "length_mi",
        "links_sharing_this_tmc",
        "free_speed_obs_p95_mph", "free_speed_assign_mph", "free_speed_diff_mph",
        "observed_max_mph", "assign_free_speed_impossible",
        "cutoff_obs_mph", "cutoff_assign_mph",
        "lane_capacity_vphpl", "mu_free_vph", "mu_queued_vph", "capacity_drop",
        "V_assign_veh", "V_throughput_obs_veh", "V_demand_obs_veh",
        "V_max_feasible_veh",
        "D_assign_vphpl", "D_obs_vphpl", "D_ratio",
        "queued_bins", "observation_weight", "inside_window", "below_lower", "above_upper",
        "t0_min_obs", "T2_min_obs", "t3_min_obs", "P_h_obs", "vT2_mph_obs",
        "t0_min_model", "T2_min_model", "t3_min_model", "P_h_model", "vT2_mph_model",
        "right_censored", "speed_mae_episode_mph", "speed_mae_period_mph",
    ]
    a = a[order].sort_values(["link_id", "period"])
    a.to_csv(args.output_dir / "odme_link_period.csv", index=False)

    # ---- File B: link x 15 minutes -----------------------------------------
    series = pd.read_csv(q / "step5_lambda_anchored_15min.csv")
    q3 = pd.read_csv(q / "step3_queue_target_15min.csv",
                     usecols=["link_id", "t_min", "period", "speed_mph", "q_vphpl",
                              "queue_meas_veh", "storage_veh"])
    run = pd.read_csv(q / "step8_speed_variants_15min.csv",
                      usecols=["link_id", "t_min", "outflow_vph", "queue_model_veh",
                               "speed_model_mph", "speed_assignment_only_mph"])
    b = (series[["link_id", "corridor", "tmc_code", "t_min", "lanes",
                 "lambda_anchored_vph", "mu_vph", "lambda_identifiable"]]
         .merge(q3, on=["link_id", "t_min"], how="left")
         .merge(run, on=["link_id", "t_min"], how="left")
         .merge(base[["length_mi", "free_speed_obs_p95_mph", "free_speed_assign_mph",
                      "cutoff_obs_mph"]], on="link_id", how="left"))
    b["clock"] = [clock(v) for v in b["t_min"]]
    b = b.rename(columns={"speed_mph": "obs_speed_mph",
                          "lambda_anchored_vph": "lambda_vph",
                          "speed_model_mph": "model_speed_mph",
                          "speed_assignment_only_mph": "assignment_only_speed_mph"})
    b = b[["link_id", "tmc_code", "corridor", "t_min", "clock", "period", "lanes",
           "length_mi", "free_speed_obs_p95_mph", "free_speed_assign_mph",
           "cutoff_obs_mph", "obs_speed_mph", "q_vphpl", "mu_vph", "lambda_vph",
           "lambda_identifiable", "outflow_vph", "queue_meas_veh", "queue_model_veh",
           "storage_veh", "model_speed_mph", "assignment_only_speed_mph"]]
    b = b.sort_values(["link_id", "t_min"])
    b.to_csv(args.output_dir / "odme_link_15min.csv", index=False)

    informative = a[a["queued_bins"] > 0]
    print(f"File A  {a.shape[0]} rows x {a.shape[1]} cols   odme_link_period.csv")
    print(f"File B  {b.shape[0]:,} rows x {b.shape[1]} cols   odme_link_15min.csv")
    print(f"\n  rows carrying an observation : {len(informative)} / {len(a)} "
          f"({100 * len(informative) / len(a):.0f}%)")
    print(f"  counts in the assignment      : 0 (obs_volume is -1 on every row)")
    print(f"\n  free speed, ours vs assignment: median diff "
          f"{a['free_speed_diff_mph'].median():+.2f} mph")
    print(f"  links where the assignment's free speed exceeds the observed maximum: "
          f"{int(a.groupby('link_id')['assign_free_speed_impossible'].first().sum())} / "
          f"{a['link_id'].nunique()}")
    print(f"\n  V_assign below the observed discharge: "
          f"{int(informative['below_lower'].sum())} / {len(informative)} informative rows")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
