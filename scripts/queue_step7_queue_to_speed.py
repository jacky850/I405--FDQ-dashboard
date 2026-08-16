"""Step 7 of the single-link queue plan: the queue back to speed.

    TT(t) = L/v_f + Q(t)/mu(t)          free-flow traversal plus queueing delay
    v_hat(t) = L / TT(t)

This is the quantity the advisor asked for -- the back-calculated speed -- and
it is a different object from the one delivered earlier. That one read t0, T2,
t3 and v(T2) off the observation and redrew a QVDF bowl through them, so the
trough matched by construction. Here **P, T2 and v(T2) are outputs**: they are
whatever the queue happens to produce, and the same episode detector is run over
v_hat to extract them so step 8 can compare like with like.

Nothing in this step is fitted. Q comes from step 6's recurrence, mu from step
2, and the arithmetic above is the only thing applied.

Two structural consequences, both expected and neither a defect:

**v_hat equals v_f wherever Q = 0**, which is 94% of bins. The model has nothing
to say about free-flow speed variation, because a point queue with no queue in it
produces no delay. Comparisons against the observed speed therefore mean
something only inside an episode, and step 8 scores the two windows separately.

**v_hat cannot exceed v_f.** The observed speed does, on roughly one bin in
twenty, since v_f is a 95th percentile.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.episodes import EpisodeDetectionConfig, detect_speed_episodes  # noqa: E402

DT_MIN = 15
CUTOFF_RATIO = 0.70
EXIT_RATIO = 0.75
MIN_EPISODE_H = 0.5
MIN_DEPTH_MPH = 3.0
TIMEZONE = "America/New_York"
NOMINAL_DAY = "2025-10-15"
PERIOD_WINDOWS = [("AM", 360, 540), ("MD", 540, 900), ("PM", 900, 1140)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--run-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step6_queue_run_15min.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def period_of(minute: float) -> str:
    for name, start, end in PERIOD_WINDOWS:
        if start <= minute < end:
            return name
    return "NT"


def detect(t_min: np.ndarray, speed: np.ndarray, free_speed: float) -> pd.DataFrame:
    """The same detector step 2 ran on the observation, run here on the model."""
    stamps = pd.Timestamp(NOMINAL_DAY, tz=TIMEZONE) + pd.to_timedelta(t_min, unit="m")
    config = EpisodeDetectionConfig(
        interval_min=DT_MIN, smoothing_bins=1,
        enter_ratio=CUTOFF_RATIO, exit_ratio=EXIT_RATIO,
        enter_persistence_bins=1, exit_persistence_bins=1,
        minimum_duration_min=MIN_EPISODE_H * 60.0, minimum_depth_mph=MIN_DEPTH_MPH)
    episodes, _ = detect_speed_episodes(stamps, speed, free_speed, config)
    if episodes.empty:
        return episodes
    midnight = pd.Timestamp(NOMINAL_DAY, tz=TIMEZONE)
    for source, target in [("t0_la", "t0_min"), ("T2_la", "T2_min"), ("t3_la", "t3_min")]:
        episodes[target] = [(pd.Timestamp(v) - midnight).total_seconds() / 60.0
                            for v in episodes[source]]
    return episodes


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(args.run_file).sort_values(["link_id", "t_min"])

    length = frame["length_mi"].to_numpy(float)
    free = frame["free_speed_mph"].to_numpy(float)
    queue = frame["queue_model_veh"].to_numpy(float)
    mu = frame["mu_vph"].to_numpy(float)

    free_travel_h = length / free
    delay_h = queue / np.maximum(mu, 1e-6)
    frame["travel_time_h"] = free_travel_h + delay_h
    frame["delay_h"] = delay_h
    frame["speed_model_mph"] = length / np.maximum(frame["travel_time_h"].to_numpy(float), 1e-9)

    series_rows, episode_rows = [], []
    for link_id, g in frame.groupby("link_id"):
        g = g.sort_values("t_min").reset_index(drop=True)
        free_speed = float(g["free_speed_mph"].iloc[0])
        t = g["t_min"].to_numpy(float)
        episodes = detect(t, g["speed_model_mph"].to_numpy(float), free_speed)
        model_id = np.full(len(g), "", dtype=object)
        for _, episode in episodes.iterrows():
            inside = (t >= episode["t0_min"]) & (t <= episode["t3_min"])
            model_id[inside] = episode["episode_id"]
            episode_rows.append({
                "link_id": link_id, "corridor": g["corridor"].iloc[0],
                "tmc_code": g["tmc_code"].iloc[0], "source": "model",
                "episode_id": episode["episode_id"],
                "t0_min": episode["t0_min"], "T2_min": episode["T2_min"],
                "t3_min": episode["t3_min"], "P_h": float(episode["P_h"]),
                "vT2_mph": float(episode["vT2_robust_mph"]),
                "period_by_T2": period_of(episode["T2_min"]),
                "onset_to_T2_h": float(episode["onset_to_T2_h"]),
                "T2_to_recovery_h": float(episode["T2_to_recovery_h"]),
                "free_speed_mph": free_speed,
                "cutoff_mph": free_speed * CUTOFF_RATIO,
                # The run stops at 19:00, so an episode still active then never
                # finds its recovery and is censored at midnight. Its P is a
                # window artefact; T2 and v(T2) sit inside the window and are not.
                "quality_flags": episode["quality_flags"],
                "right_censored": "right_censored" in str(episode["quality_flags"]),
            })
        g["model_episode_id"] = model_id
        series_rows.append(g)

    series = pd.concat(series_rows, ignore_index=True)
    episodes = pd.DataFrame(episode_rows)
    keep = ["link_id", "corridor", "tmc_code", "t_min", "anchor_period", "lanes", "length_mi",
            "free_speed_mph", "cutoff_mph", "mu_vph", "lambda_anchored_vph", "outflow_vph",
            "queue_model_veh", "queue_meas_veh", "delay_h", "travel_time_h",
            "speed_mph", "speed_model_mph", "lambda_identifiable", "model_episode_id"]
    series[keep].to_csv(args.output_dir / "step7_speed_model_15min.csv", index=False)
    episodes.to_csv(args.output_dir / "step7_model_episodes.csv", index=False)

    queued = series["lambda_identifiable"].to_numpy(bool)
    error = series["speed_model_mph"] - series["speed_mph"]
    at_free = np.abs(series["speed_model_mph"] - series["free_speed_mph"]) < 1e-6

    report = {
        "step": "7. Queue back to speed",
        "formula": "TT = L/v_f + Q/mu;  v_hat = L/TT",
        "nothing_is_fitted_here": True,
        "links": int(series["link_id"].nunique()),
        "bins": int(len(series)),
        "model_speed": {
            "bins_pinned_at_free_speed": int(at_free.sum()),
            "share_pinned": round(float(at_free.mean()), 4),
            "note": "v_hat = v_f wherever Q = 0. A point queue with no queue produces no delay, "
                    "so the model says nothing about free-flow speed variation and only the "
                    "in-episode comparison carries information.",
            "min_mph": round(float(series["speed_model_mph"].min()), 2),
            "median_in_episode_mph": round(float(series.loc[queued, "speed_model_mph"].median()), 2),
        },
        "model_episodes": {
            "links_with_a_model_episode": int(episodes["link_id"].nunique()) if len(episodes) else 0,
            "episodes": int(len(episodes)),
            "by_period": episodes["period_by_T2"].value_counts().to_dict() if len(episodes) else {},
            "P_median_h": round(float(episodes["P_h"].median()), 2) if len(episodes) else None,
            "vT2_median_mph": round(float(episodes["vT2_mph"].median()), 2) if len(episodes) else None,
            "note": "P, T2 and v(T2) are read off v_hat, so they are outputs of the queue rather "
                    "than inputs used to shape it. That is the substantive difference from the "
                    "earlier QVDF reconstruction and what makes step 8 a real comparison.",
        },
        "speed_error_preview": {
            "in_episode_mae_mph": round(float(error[queued].abs().mean()), 3),
            "in_episode_bias_mph": round(float(error[queued].median()), 3),
            "whole_run_mae_mph": round(float(error.abs().mean()), 3),
            "note": "Scored properly in step 8. The whole-run figure is dominated by the 94% of "
                    "bins where the model is pinned at v_f by construction.",
        },
    }
    (args.output_dir / "step7_summary.json").write_text(json.dumps(report, indent=2),
                                                        encoding="utf-8")

    print("Step 7 -- queue back to speed\n")
    print(f"  {report['links']} links, {report['bins']:,} bins")
    m = report["model_speed"]
    print(f"  v_hat pinned at v_f on {m['share_pinned'] * 100:.1f}% of bins (Q = 0 there)")
    print(f"  v_hat minimum {m['min_mph']:.1f} mph, median inside an episode "
          f"{m['median_in_episode_mph']:.1f} mph")
    e = report["model_episodes"]
    print(f"\n  model episodes: {e['episodes']} on {e['links_with_a_model_episode']} links, "
          f"{e['by_period']}")
    print(f"    P median {e['P_median_h']:.2f} h, v(T2) median {e['vT2_median_mph']:.1f} mph")
    print(f"    -- these are OUTPUTS of the queue, not inputs")
    s = report["speed_error_preview"]
    print(f"\n  preview: in-episode MAE {s['in_episode_mae_mph']:.2f} mph, "
          f"bias {s['in_episode_bias_mph']:+.2f}")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
