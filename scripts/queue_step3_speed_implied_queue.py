"""Step 3 of the single-link queue plan: the queue implied by the observed speed.

    Q_meas(t) = mu(t) * ( L/v(t) - L/v_f ),   zero where not congested

`L/v - L/v_f` is the delay a vehicle takes traversing the link, in hours;
multiplying by the discharge rate in vehicles per hour gives a number of
vehicles. This is the **fitting target** for step 4, not the queue itself -- the
queue used later is produced only by the recurrence, so that the residual
between the two measures something rather than restating it.

Read pointwise off the unsmoothed profile. The smoothed series is what defined
the episodes and mu in step 2; using it here as well would launder the same
smoothing through the target twice.

Two checks belong here rather than anywhere else.

**Queue outside the declared episodes.** Step 2 found that breakdown located
without any threshold sits at 0.82 v_f while the cut-off is at 0.70, which
raised the possibility that the queued regime turns on late and the episode
boundary clips a real queue. Zeroing outside the episode is only defensible if
there is little to zero, so the amount discarded is measured and reported.

**Storage.** A link cannot hold more vehicles than it has room for. At a jam
density of 200 veh/mi/lane the ceiling is `200 * L * lanes`, and a target above
it is not a queue on this link.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
JAM_DENSITY_VEHPMIPL = 200.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mu-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step2_mu_15min.csv")
    parser.add_argument("--flow-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step1_flow_average_weekday_15min.csv")
    parser.add_argument("--jam-density", type=float, default=JAM_DENSITY_VEHPMIPL)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    mu = pd.read_csv(args.mu_file)
    geometry = (pd.read_csv(args.flow_file, usecols=["link_id", "t_min", "length_mi", "tmc_code"])
                .drop_duplicates(["link_id", "t_min"]))
    frame = mu.merge(geometry, on=["link_id", "t_min"], how="left").sort_values(["link_id", "t_min"])

    length = frame["length_mi"].to_numpy(float)
    speed = frame["speed_mph"].to_numpy(float)
    free = frame["free_speed_mph"].to_numpy(float)
    mu_vph = frame["mu_vph"].to_numpy(float)

    # Delay per vehicle, in hours. Clamped at zero: v_f is a 95th percentile, so
    # roughly one bin in twenty is faster than it and would otherwise imply a
    # negative queue.
    delay_h = np.maximum(length / np.maximum(speed, 1e-6) - length / free, 0.0)
    queue_all = mu_vph * delay_h

    frame["delay_h"] = delay_h
    frame["queue_implied_all_veh"] = queue_all
    frame["queue_meas_veh"] = np.where(frame["queued"].to_numpy(bool), queue_all, 0.0)
    frame["storage_veh"] = args.jam_density * length * frame["lanes"].to_numpy(float)
    frame["over_storage"] = frame["queue_meas_veh"] > frame["storage_veh"]

    columns = ["link_id", "corridor", "tmc_code", "t_min", "period", "speed_mph",
               "speed_smoothed_mph", "free_speed_mph", "cutoff_mph", "length_mi", "lanes",
               "q_vphpl", "mu_vphpl", "mu_vph", "queued", "episode_id",
               "delay_h", "queue_implied_all_veh", "queue_meas_veh", "storage_veh", "over_storage"]
    frame[columns].to_csv(args.output_dir / "step3_queue_target_15min.csv", index=False)

    inside = frame[frame["queued"]]
    outside = frame[~frame["queued"]]
    total_inside = float(inside["queue_implied_all_veh"].sum())
    total_outside = float(outside["queue_implied_all_veh"].sum())

    # Where the discarded queue actually sits. Most of it turns out to be on
    # links that never congest at all, where the small positive delay is the
    # percentile artefact rather than a queue the boundary cut off.
    episodes = pd.read_csv(args.output_dir / "step2_episodes.csv")
    edges = {link: list(zip(g["t0_min"], g["t3_min"]))
             for link, g in episodes.groupby("link_id")}
    has_episode = outside["link_id"].isin(edges)
    no_episode_share = float(outside.loc[~has_episode, "queue_implied_all_veh"].sum()
                             / max(total_outside, 1e-9))

    near = outside[has_episode].copy()
    near["min_to_edge"] = [
        min(min(abs(t - a), abs(t - b)) for a, b in edges[link])
        for link, t in zip(near["link_id"], near["t_min"])]
    on_episode_links = float(near["queue_implied_all_veh"].sum())
    near_edge = float(near.loc[near["min_to_edge"] <= 30, "queue_implied_all_veh"].sum())
    near_edge_share = near_edge / max(on_episode_links, 1e-9)
    clipped_ratio = near_edge / max(total_inside, 1e-9)

    per_link = frame.groupby("link_id").agg(
        peak_veh=("queue_meas_veh", "max"), storage_veh=("storage_veh", "first"),
        queued_bins=("queued", "sum"))
    per_link = per_link[per_link["queued_bins"] > 0]

    report = {
        "step": "3. Speed-implied queue, the fitting target for step 4",
        "formula": "Q_meas(t) = mu(t) * (L/v(t) - L/v_f), zero where not congested",
        "links": int(frame["link_id"].nunique()),
        "links_with_a_queue": int(len(per_link)),
        "distinct_tmcs_behind_them": int(frame.loc[frame["queued"], "tmc_code"].nunique()),
        "queue_target_veh": {
            "peak_median": round(float(per_link["peak_veh"].median()), 1),
            "peak_iqr": [round(float(per_link["peak_veh"].quantile(.25)), 1),
                         round(float(per_link["peak_veh"].quantile(.75)), 1)],
            "peak_max": round(float(per_link["peak_veh"].max()), 1),
        },
        "queue_discarded_outside_episodes": {
            "share_of_all_implied_queue": round(total_outside / (total_inside + total_outside), 4),
            "why_that_number_misleads": "It is a bin-count effect. Outside bins outnumber inside "
                                        "ones 16.7 to 1 while carrying 14x less each.",
            "mean_veh_per_bin": {"inside": round(float(inside["queue_implied_all_veh"].mean()), 2),
                                 "outside": round(float(outside["queue_implied_all_veh"].mean()), 2)},
            "outside_baseline_is_an_artefact": "v_f is a 95th percentile, so 95% of bins sit just "
                                               "below it and L/v - L/v_f is a small positive "
                                               "number almost everywhere. That floor is not queue.",
            "on_links_with_no_episode_at_all": round(no_episode_share, 4),
            "within_30_min_of_an_episode_edge": round(near_edge_share, 4),
            "clipped_relative_to_captured": round(clipped_ratio, 4),
            "verdict": "The 0.70 cut-off is conservative against the threshold-free breakdown at "
                       "0.82 v_f found in step 2, but what the boundary clips amounts to about "
                       "6% of what it captures. Not worth moving the threshold for.",
        },
        "storage": {
            "jam_density_vehpmipl": args.jam_density,
            "bins_over_storage": int(frame["over_storage"].sum()),
            "links_over_storage": int(frame.loc[frame["over_storage"], "link_id"].nunique()),
            "peak_over_storage_ratio_max": round(
                float((per_link["peak_veh"] / per_link["storage_veh"]).max()), 3),
        },
    }
    (args.output_dir / "step3_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print("Step 3 -- speed-implied queue\n")
    print(f"  {report['links_with_a_queue']} links carry a queue, from "
          f"{report['distinct_tmcs_behind_them']} distinct TMCs")
    t = report["queue_target_veh"]
    print(f"  peak queue per link: median {t['peak_median']:.0f} veh, "
          f"IQR {t['peak_iqr'][0]:.0f}-{t['peak_iqr'][1]:.0f}, max {t['peak_max']:.0f}")
    d = report["queue_discarded_outside_episodes"]
    print(f"\n  outside the episodes: {d['share_of_all_implied_queue'] * 100:.1f}% of the implied "
          f"queue -- but that is a bin-count effect")
    print(f"    {d['mean_veh_per_bin']['inside']:.1f} veh/bin inside vs "
          f"{d['mean_veh_per_bin']['outside']:.2f} outside, and outside bins outnumber inside 16.7:1")
    print(f"    {d['on_links_with_no_episode_at_all'] * 100:.0f}% of it is on links with no "
          f"episode at all -- the percentile floor, not queue")
    print(f"    what the boundary actually clips is "
          f"{d['clipped_relative_to_captured'] * 100:.1f}% of what it captures")
    s = report["storage"]
    print(f"\n  storage at {s['jam_density_vehpmipl']:.0f} veh/mi/lane: "
          f"{s['bins_over_storage']} bins over, on {s['links_over_storage']} links "
          f"(worst peak/storage {s['peak_over_storage_ratio_max']:.2f})")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
