"""Build the PM deliverable from the single-link queue run.

The advisor's list is D, C, observed speed(t), back-calculated speed(t), and the
P / v(T2) / T2 comparison. That is the same list as the earlier QVDF delivery,
so the summary keeps the same column names -- the two files are meant to be
read side by side. What changed is where the numbers come from: P, T2 and v(T2)
are now read off the queue's own speed, not off the observation.

Three files:

  nvta_queue_pm_link_summary.csv   the advisor's list, one row per link with an
                                   observed PM episode. Nothing else.
  nvta_queue_pm_link_full.csv      all 252 links, all three periods, every
                                   diagnostic column. Documented separately.
  nvta_queue_pm_speed_15min.csv    the two speed series plus the assignment-only
                                   variant, whole run window.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "outputs/nvta_queue"
PM_START, PM_END = 900, 1140          # 15:00 to 19:00, the assignment's PM clock
PM_HOURS = 4.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-dir", type=Path, default=QUEUE)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue_pm")
    return parser.parse_args()


def clock(minute: float) -> str:
    if not np.isfinite(minute):
        return ""
    minute = int(round(minute)) % 1440
    return f"{minute // 60:02d}:{minute % 60:02d}"


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    q = args.queue_dir

    series = pd.read_csv(q / "step8_speed_variants_15min.csv")
    scores = pd.read_csv(q / "step8_speed_scores_by_link.csv")
    anchors = pd.read_csv(q / "step5_volume_anchor_by_link.csv")
    obs_ep = pd.read_csv(q / "step2_episodes.csv")
    mod_ep = pd.read_csv(q / "step7_model_episodes.csv")
    by_link = pd.read_csv(q / "step6_by_link.csv")
    geometry = pd.read_csv(q / "step3_queue_target_15min.csv",
                           usecols=["link_id", "length_mi", "lanes", "free_speed_mph",
                                    "cutoff_mph", "storage_veh"]).groupby("link_id").first()

    # ---- the two speed series, whole run window -----------------------------
    out = series[["link_id", "corridor", "tmc_code", "t_min", "anchor_period",
                  "lanes", "length_mi", "free_speed_mph", "cutoff_mph",
                  "speed_mph", "speed_model_mph", "speed_assignment_only_mph",
                  "queue_model_veh", "queue_meas_veh", "model_episode_id"]].copy()
    out = out.rename(columns={"speed_mph": "obs_speed_mph",
                              "speed_model_mph": "model_speed_mph",
                              "speed_assignment_only_mph": "assignment_only_speed_mph"})
    out["clock"] = [clock(v) for v in out["t_min"]]
    out["in_pm_period"] = (out["t_min"] >= PM_START) & (out["t_min"] < PM_END)
    out["in_episode_obs"] = out["obs_speed_mph"] < out["cutoff_mph"]
    out["in_episode_model"] = out["model_episode_id"].fillna("").astype(str) != ""
    out.drop(columns=["model_episode_id"]).to_csv(
        args.output_dir / "nvta_queue_pm_speed_15min.csv", index=False)

    # ---- per-link assembly --------------------------------------------------
    pm_anchor = anchors[anchors["period"] == "PM"].set_index("link_id")
    obs_pm = (obs_ep[obs_ep["period_by_T2"] == "PM"]
              .sort_values("P_h", ascending=False).groupby("link_id").first())
    mod_pm = (mod_ep[mod_ep["period_by_T2"] == "PM"]
              .sort_values("P_h", ascending=False).groupby("link_id").first())
    censored = mod_ep.groupby("link_id")["right_censored"].any()

    def variant(name: str) -> pd.DataFrame:
        return scores[scores["variant"] == name].set_index("link_id")

    anchored, assign_only, free_flow = variant("anchored"), variant("assignment"), variant("free_flow")

    rows = []
    for link_id, obs in obs_pm.iterrows():
        if link_id not in geometry.index or link_id not in pm_anchor.index:
            continue
        geo, anc = geometry.loc[link_id], pm_anchor.loc[link_id]
        lanes = int(geo["lanes"])
        mod = mod_pm.loc[link_id] if link_id in mod_pm.index else None
        a = anchored.loc[link_id] if link_id in anchored.index else None

        capacity_vphpl = float(anc["mu_free_vph"]) / lanes
        d_assign = float(anc["V_assign_veh"]) / (lanes * PM_HOURS)
        d_obs = float(anc["lower_bound_veh"]) / (lanes * PM_HOURS)

        is_censored = bool(censored.get(link_id, False))
        notes = []
        if mod is None:
            notes.append("model found no PM episode")
        if is_censored:
            notes.append("model episode still open at 19:00; P not comparable")
        if bool(anc["below_lower"]):
            notes.append("V_assign below the observed discharge")
        if bool(anc["above_upper"]):
            notes.append("V_assign above what free-flow bins can absorb")

        row = {
            "corridor": obs["corridor"], "net_link_id": link_id,
            "tmc_code": a["tmc_code"] if a is not None else "",
            "lanes": lanes, "miles": round(float(geo["length_mi"]), 4),
            "C_vphpl": round(capacity_vphpl, 1),
            "C_veh_per_h": round(capacity_vphpl * lanes, 1),
            "free_speed_mph": round(float(geo["free_speed_mph"]), 2),
            "cutoff_mph": round(float(geo["cutoff_mph"]), 2),
            "D_assign_vphpl": round(d_assign, 1),
            "D_obs_vphpl": round(d_obs, 1),
            "D_ratio": round(d_assign / d_obs, 3) if d_obs > 0 else np.nan,
            "P_h_obs": round(float(obs["P_h"]), 2),
            "T2_clock_obs": clock(obs["T2_min"]),
            "vT2_mph_obs": round(float(obs["vT2_mph"]), 2),
            "P_h_model": round(float(mod["P_h"]), 2) if mod is not None else np.nan,
            "T2_clock_model": clock(mod["T2_min"]) if mod is not None else "",
            "vT2_mph_model": round(float(mod["vT2_mph"]), 2) if mod is not None else np.nan,
        }
        if mod is not None:
            row["P_h_err"] = np.nan if is_censored else round(float(mod["P_h"] - obs["P_h"]), 2)
            row["T2_min_err"] = round(float(mod["T2_min"] - obs["T2_min"]), 1)
            row["vT2_mph_err"] = round(float(mod["vT2_mph"] - obs["vT2_mph"]), 2)
        else:
            row.update({"P_h_err": np.nan, "T2_min_err": np.nan, "vT2_mph_err": np.nan})
        row.update({
            "speed_mae_episode_mph": round(float(a["mae_episode_mph"]), 2)
            if a is not None and np.isfinite(a["mae_episode_mph"]) else np.nan,
            "speed_mae_pm_mph": round(float(a["mae_period_mph"]), 2) if a is not None else np.nan,
            "mae_episode_assignment_only_mph":
                round(float(assign_only.loc[link_id, "mae_episode_mph"]), 2)
                if link_id in assign_only.index
                and np.isfinite(assign_only.loc[link_id, "mae_episode_mph"]) else np.nan,
            "note": "; ".join(notes),
        })
        rows.append(row)

    summary = pd.DataFrame(rows).sort_values(["corridor", "net_link_id"])
    summary.to_csv(args.output_dir / "nvta_queue_pm_link_summary.csv", index=False)

    # ---- the full table: every link, every period, every diagnostic ----------
    # storage_veh is carried by step 6 as well; taking it from the geometry too
    # would only produce a suffixed duplicate.
    full = (anchors.merge(by_link.drop(columns=["corridor", "tmc_code", "lanes"]),
                          on="link_id", how="left")
            .merge(geometry[["length_mi", "free_speed_mph", "cutoff_mph"]],
                   on="link_id", how="left"))
    for name, frame in [("anchored", anchored), ("assignment", assign_only),
                        ("free_flow", free_flow)]:
        cols = frame[["mae_period_mph", "mae_episode_mph", "bias_episode_mph", "episode_bins"]]
        full = full.merge(cols.add_suffix(f"_{name}"), on="link_id", how="left")
    for source, frame in [("obs", obs_ep), ("model", mod_ep)]:
        best = (frame.sort_values("P_h", ascending=False)
                .groupby(["link_id", "period_by_T2"]).first()
                [["t0_min", "T2_min", "t3_min", "P_h", "vT2_mph"]].add_suffix(f"_{source}"))
        full = full.merge(best, left_on=["link_id", "period"],
                          right_index=True, how="left")
    full.to_csv(args.output_dir / "nvta_queue_pm_link_full.csv", index=False)

    matched = summary.dropna(subset=["vT2_mph_model"])
    print(f"PM links with an observed episode : {len(summary)}")
    print(f"  model reproduced an episode on  : {len(matched)}")
    print(f"  D_assign / D_obs median         : {summary['D_ratio'].median():.3f}")
    print(f"  below the observed discharge    : {(summary['D_ratio'] < 1).sum()}")
    print(f"  MAE in episode, anchored        : {summary['speed_mae_episode_mph'].median():.2f} mph")
    print(f"  MAE in episode, assignment only : "
          f"{summary['mae_episode_assignment_only_mph'].median():.2f} mph")
    print(f"  T2 exact                        : {(matched['T2_min_err'] == 0).sum()} / {len(matched)}")
    print(f"  v(T2) within 1 mph              : "
          f"{(matched['vT2_mph_err'].abs() <= 1).sum()} / {len(matched)}")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
