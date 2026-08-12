"""Recover a continuous full-day point queue for one PeMS sensor segment.

The reference implementation keeps all 288 five-minute bins connected.  Its
primary PeMS reference uses time-shifted upstream flow plus on-ramp flow for
arrivals, downstream flow for discharge, and their drift-corrected cumulative
difference for queue.  A separate speed-delay branch is retained only as a
diagnostic for the future speed-only NVTA setting.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd


DT_H = 5.0 / 60.0
KM_TO_MI = 0.621371
RAW_COLUMNS = [
    "timestamp",
    "station_id",
    "district",
    "freeway",
    "direction",
    "lane_type",
    "station_length",
    "samples",
    "pct_observed",
    "flow_5min",
    "occupancy",
    "speed_mph",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--upstream-detector", type=int, default=1201497)
    parser.add_argument("--ramp-detector", type=int, default=1201517)
    parser.add_argument("--downstream-detector", type=int, default=1201525)
    parser.add_argument("--upstream-link", default="L405S-041")
    parser.add_argument("--downstream-link", default="L405S-004")
    parser.add_argument("--segment-length-km", type=float, default=1.480596)
    parser.add_argument("--free-speed-percentile", type=float, default=95.0)
    parser.add_argument("--entry-ratio", type=float, default=0.70)
    parser.add_argument("--exit-ratio", type=float, default=0.75)
    parser.add_argument("--minimum-episode-minutes", type=int, default=20)
    parser.add_argument("--baseline-polynomial-degree", type=int, default=4)
    return parser.parse_args()


def load_detector(raw: pd.DataFrame, station_id: int) -> pd.DataFrame:
    frame = raw.loc[raw["station_id"].eq(station_id)].copy()
    if frame.empty:
        raise ValueError(f"Detector {station_id} is absent from {raw.iloc[0]['timestamp']!s}")
    frame = frame.sort_values("timestamp").drop_duplicates("timestamp")
    if len(frame) != 288:
        raise ValueError(f"Detector {station_id} has {len(frame)} rows; expected 288")
    return frame.reset_index(drop=True)


def detect_episodes(
    speed: np.ndarray,
    entry_threshold: float,
    exit_threshold: float,
    minimum_bins: int,
) -> tuple[np.ndarray, list[dict[str, int]]]:
    episode_id = np.zeros(len(speed), dtype=int)
    episodes: list[dict[str, int]] = []
    active = False
    start = -1
    recovery_bins = 0

    for i, value in enumerate(speed):
        if not active and value < entry_threshold:
            active = True
            start = i
            recovery_bins = 0
        elif active:
            recovery_bins = recovery_bins + 1 if value >= exit_threshold else 0
            if recovery_bins >= 2:
                end = i - recovery_bins
                if end - start + 1 >= minimum_bins:
                    episodes.append({"start": start, "end": end})
                active = False
                start = -1
                recovery_bins = 0

    if active and len(speed) - start >= minimum_bins:
        episodes.append({"start": start, "end": len(speed) - 1})

    for number, episode in enumerate(episodes, start=1):
        episode_id[episode["start"] : episode["end"] + 1] = number
    return episode_id, episodes


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(
        args.raw_file,
        header=None,
        usecols=range(12),
        names=RAW_COLUMNS,
    )
    raw["timestamp"] = pd.to_datetime(raw["timestamp"], format="%m/%d/%Y %H:%M:%S")
    upstream = load_detector(raw, args.upstream_detector)
    ramp = load_detector(raw, args.ramp_detector)
    downstream = load_detector(raw, args.downstream_detector)

    if not (
        upstream["timestamp"].equals(ramp["timestamp"])
        and upstream["timestamp"].equals(downstream["timestamp"])
    ):
        raise ValueError("The three detector time axes are not identical")

    timestamps = downstream["timestamp"].dt.tz_localize("America/Los_Angeles")
    speed_raw = downstream["speed_mph"].to_numpy(float)
    speed = pd.Series(speed_raw).rolling(3, center=True, min_periods=1).median().to_numpy()
    discharge_raw = downstream["flow_5min"].to_numpy(float) / DT_H
    mu = pd.Series(discharge_raw).rolling(3, center=True, min_periods=1).median().to_numpy()

    free_speed = float(np.percentile(speed, args.free_speed_percentile))
    entry_threshold = args.entry_ratio * free_speed
    exit_threshold = args.exit_ratio * free_speed
    episode_id, episodes = detect_episodes(
        speed,
        entry_threshold,
        exit_threshold,
        max(1, args.minimum_episode_minutes // 5),
    )
    congested = episode_id > 0

    time_h = np.arange(len(speed)) * DT_H
    normalized_time = (time_h - 12.0) / 12.0
    fit_mask = ~congested
    coefficients = np.polyfit(
        normalized_time[fit_mask],
        speed[fit_mask],
        args.baseline_polynomial_degree,
    )
    baseline_speed = np.polyval(coefficients, normalized_time)
    baseline_speed = np.clip(baseline_speed, 0.85 * free_speed, 1.05 * free_speed)

    length_mi = args.segment_length_km * KM_TO_MI
    observed_tt_h = length_mi / np.maximum(speed, 5.0)
    baseline_tt_h = length_mi / baseline_speed
    queue_reference = mu * np.maximum(observed_tt_h - baseline_tt_h, 0.0)
    queue_reference[~congested] = 0.0
    queue_reference = (
        pd.Series(queue_reference)
        .rolling(3, center=True, min_periods=1)
        .median()
        .to_numpy(copy=True)
    )
    queue_reference[~congested] = 0.0

    lambda_inferred = mu.copy()
    lambda_inferred[:-1] += np.diff(queue_reference) / DT_H
    if np.any(lambda_inferred < 0):
        raise ValueError("Inverse recovery produced a negative arrival rate")

    queue_forward = np.zeros(len(speed))
    outflow_forward = np.zeros(len(speed))
    for i in range(len(speed) - 1):
        available_rate = lambda_inferred[i] + queue_forward[i] / DT_H
        outflow_forward[i] = min(mu[i], available_rate)
        queue_forward[i + 1] = max(
            0.0,
            queue_forward[i] + (lambda_inferred[i] - outflow_forward[i]) * DT_H,
        )
    outflow_forward[-1] = min(
        mu[-1], lambda_inferred[-1] + queue_forward[-1] / DT_H
    )
    reconstructed_speed = length_mi / (
        baseline_tt_h + queue_forward / np.maximum(mu, 1.0)
    )

    upstream_rate = upstream["flow_5min"].to_numpy(float) / DT_H
    ramp_rate = ramp["flow_5min"].to_numpy(float) / DT_H
    tau_h = args.segment_length_km / 105.0
    shifted_upstream = np.interp(
        time_h - tau_h,
        time_h,
        upstream_rate,
        left=upstream_rate[0],
        right=upstream_rate[-1],
    )
    observed_arrival = shifted_upstream + ramp_rate

    # Independent cumulative-count queue.  This branch does not use speed or
    # the speed-derived queue.  A raw pre-episode baseline is retained, and a
    # second series removes only the linear detector drift observed between
    # free-flow windows before and after each episode.
    # State at timestamp i is the queue at the *start* of interval i.  Flow in
    # interval i updates that state to timestamp i+1; the leading zero avoids a
    # one-bin shift between cumulative counts and the recurrence equation.
    cumulative_gap = np.r_[
        0.0,
        np.cumsum((observed_arrival - discharge_raw) * DT_H),
    ][:-1]
    count_queue_raw = np.full(len(speed), np.nan)
    count_queue_drift_corrected = np.full(len(speed), np.nan)
    count_reference_queue = np.zeros(len(speed))
    count_reference_lambda = observed_arrival.copy()
    count_diagnostics: dict[int, dict[str, float]] = {}
    window_bins = 12  # 60 minutes
    guard_bins = 2  # keep 10 minutes away from threshold crossings
    for number, episode in enumerate(episodes, start=1):
        start, end = episode["start"], episode["end"]
        pre = np.arange(max(0, start - window_bins), max(0, start - guard_bins))
        post = np.arange(
            min(len(speed), end + guard_bins + 1),
            min(len(speed), end + guard_bins + 1 + window_bins),
        )
        if len(pre) < 3 or len(post) < 3:
            continue

        raw_baseline = float(np.median(cumulative_gap[pre]))
        raw_series = np.maximum(0.0, cumulative_gap - raw_baseline)

        pre_level = float(np.median(cumulative_gap[pre]))
        post_level = float(np.median(cumulative_gap[post]))
        pre_center = float(np.median(pre))
        post_center = float(np.median(post))
        drift_baseline = pre_level + (post_level - pre_level) * (
            (np.arange(len(speed)) - pre_center) / (post_center - pre_center)
        )
        corrected_series = np.maximum(0.0, cumulative_gap - drift_baseline)
        drift_rate_vph = (post_level - pre_level) / (
            (post_center - pre_center) * DT_H
        )
        validation_start = int(pre[0])
        validation_end = int(post[-1])
        count_queue_raw[validation_start : validation_end + 1] = raw_series[
            validation_start : validation_end + 1
        ]
        count_queue_drift_corrected[validation_start : validation_end + 1] = corrected_series[
            validation_start : validation_end + 1
        ]
        # PeMS reference state: conserve observed counts during the speed-defined
        # episode, carry it across assignment-period boundaries, and clear it
        # only after the episode recovery gate.  The tiny linear correction is
        # the measured detector drift, not a fit to the queue curve.
        count_reference_queue[start : end + 1] = corrected_series[start : end + 1]
        count_reference_lambda[start : end + 1] = (
            observed_arrival[start : end + 1] - drift_rate_vph
        )

        event_slice = slice(start, end + 1)
        speed_event = queue_reference[event_slice]
        count_event = corrected_series[event_slice]
        count_peak_index = start + int(np.argmax(count_event))
        speed_peak_index = start + int(np.argmax(speed_event))
        correlation = (
            float(np.corrcoef(speed_event, count_event)[0, 1])
            if np.std(speed_event) > 0 and np.std(count_event) > 0
            else float("nan")
        )
        count_diagnostics[number] = {
            "raw_pre_baseline_veh": raw_baseline,
            "free_flow_pre_level_veh": pre_level,
            "free_flow_post_level_veh": post_level,
            "detector_drift_over_validation_window_veh": post_level - pre_level,
            "count_queue_max_veh": float(count_event.max()),
            "count_queue_peak_index": count_peak_index,
            "count_queue_at_t3_veh": float(corrected_series[end]),
            "speed_queue_vs_count_queue_mae_veh": float(
                np.mean(np.abs(speed_event - count_event))
            ),
            "speed_queue_vs_count_queue_correlation": correlation,
            "queue_peak_time_gap_min": float(abs(speed_peak_index - count_peak_index) * 5),
        }

    output = pd.DataFrame(
        {
            "timestamp_la": timestamps.astype(str),
            "time_bin": np.arange(len(speed)),
            "period": pd.cut(
                time_h,
                [-0.001, 6, 10, 15, 19, 24],
                labels=["NT1", "AM", "MD", "PM", "NT2"],
                right=False,
            ).astype(str),
            "episode_id": episode_id,
            "observed_speed_mph": speed_raw,
            "smoothed_speed_mph": speed,
            "baseline_free_speed_mph": baseline_speed,
            "observed_arrival_vph": observed_arrival,
            "count_reference_lambda_vph": count_reference_lambda,
            "inferred_lambda_vph": lambda_inferred,
            "reference_mu_vph": mu,
            "observed_discharge_vph": discharge_raw,
            "speed_delay_diagnostic_queue_veh": queue_reference,
            "cumulative_count_gap_veh": cumulative_gap,
            "count_queue_raw_veh": count_queue_raw,
            "count_queue_drift_corrected_veh": count_queue_drift_corrected,
            "count_reference_queue_veh": count_reference_queue,
            "forward_queue_veh": queue_forward,
            "forward_outflow_vph": outflow_forward,
            "reconstructed_speed_mph": reconstructed_speed,
            "upstream_pct_observed": upstream["pct_observed"].to_numpy(float),
            "ramp_pct_observed": ramp["pct_observed"].to_numpy(float),
            "downstream_pct_observed": downstream["pct_observed"].to_numpy(float),
        }
    )
    output.to_csv(args.output_dir / "full_day_timeseries_5min.csv", index=False)

    episode_rows = []
    for number, episode in enumerate(episodes, start=1):
        start, end = episode["start"], episode["end"]
        t2 = start + int(np.argmin(speed[start : end + 1]))
        episode_rows.append(
            {
                "episode_id": number,
                "t0_la": timestamps.iloc[start].isoformat(),
                "t2_la": timestamps.iloc[t2].isoformat(),
                "t3_la": timestamps.iloc[end].isoformat(),
                "duration_min": int((end - start + 1) * 5),
                "minimum_speed_mph": float(speed[t2]),
                "speed_delay_diagnostic_queue_max_veh": float(
                    queue_reference[start : end + 1].max()
                ),
                "count_queue_max_veh": count_diagnostics.get(number, {}).get(
                    "count_queue_max_veh", np.nan
                ),
                "count_queue_peak_time_la": (
                    timestamps.iloc[
                        int(count_diagnostics[number]["count_queue_peak_index"])
                    ].isoformat()
                    if number in count_diagnostics
                    else ""
                ),
                "speed_queue_vs_count_queue_mae_veh": count_diagnostics.get(number, {}).get(
                    "speed_queue_vs_count_queue_mae_veh", np.nan
                ),
                "speed_queue_vs_count_queue_correlation": count_diagnostics.get(number, {}).get(
                    "speed_queue_vs_count_queue_correlation", np.nan
                ),
                "queue_peak_time_gap_min": count_diagnostics.get(number, {}).get(
                    "queue_peak_time_gap_min", np.nan
                ),
            }
        )
    pd.DataFrame(episode_rows).to_csv(args.output_dir / "congestion_episodes.csv", index=False)

    error = lambda_inferred - observed_arrival
    boundaries = {label: int(hour / DT_H) for label, hour in [("06:00", 6), ("10:00", 10), ("15:00", 15), ("19:00", 19)]}
    summary = {
        "date": str(downstream["timestamp"].dt.date.iloc[0]),
        "timezone": "America/Los_Angeles",
        "resolution_minutes": 5,
        "bins": int(len(output)),
        "upstream_link": args.upstream_link,
        "downstream_link": args.downstream_link,
        "upstream_detector": args.upstream_detector,
        "ramp_detector": args.ramp_detector,
        "downstream_detector": args.downstream_detector,
        "segment_length_km": args.segment_length_km,
        "free_speed_mph": free_speed,
        "entry_threshold_mph": entry_threshold,
        "exit_threshold_mph": exit_threshold,
        "episode_count": len(episodes),
        "speed_delay_diagnostic_queue_max_veh": float(queue_reference.max()),
        "speed_delay_diagnostic_queue_max_time_la": timestamps.iloc[
            int(queue_reference.argmax())
        ].isoformat(),
        "inferred_arrival_volume_veh": float(lambda_inferred.sum() * DT_H),
        "observed_arrival_volume_veh": float(observed_arrival.sum() * DT_H),
        "arrival_mae_vph": float(np.mean(np.abs(error))),
        "arrival_rmse_vph": float(np.sqrt(np.mean(np.square(error)))),
        "arrival_mape_pct": float(np.mean(np.abs(error) / np.maximum(observed_arrival, 1.0)) * 100),
        "all_day_speed_mae_mph": float(np.mean(np.abs(reconstructed_speed - speed))),
        "congested_speed_mae_mph": float(np.mean(np.abs(reconstructed_speed[congested] - speed[congested]))),
        "queue_forward_closure_max_abs_veh": float(np.max(np.abs(queue_forward - queue_reference))),
        "end_of_day_queue_veh": float(queue_forward[-1]),
        "speed_delay_diagnostic_queue_at_period_boundaries_veh": {
            label: float(queue_forward[index]) for label, index in boundaries.items()
        },
        "count_reference_maximum_queue_veh": float(count_reference_queue.max()),
        "count_reference_maximum_queue_time_la": timestamps.iloc[
            int(count_reference_queue.argmax())
        ].isoformat(),
        "count_reference_queue_at_period_boundaries_veh": {
            label: float(count_reference_queue[index])
            for label, index in boundaries.items()
        },
        "independent_count_queue_validation": {
            str(number): {
                key: (
                    timestamps.iloc[int(value)].isoformat()
                    if key == "count_queue_peak_index"
                    else value
                )
                for key, value in diagnostics.items()
            }
            for number, diagnostics in count_diagnostics.items()
        },
        "coverage_pct_median": {
            "upstream": float(upstream["pct_observed"].median()),
            "ramp": float(ramp["pct_observed"].median()),
            "downstream": float(downstream["pct_observed"].median()),
        },
        "method_note": (
            "The primary PeMS reference uses upstream-plus-ramp counts for lambda(t), "
            "downstream counts for discharge, and their drift-corrected cumulative "
            "difference for Q(t). Speed detects episode recovery but never resets Q "
            "at an AM/MD/PM boundary. The older speed-delay Q and its algebraic lambda "
            "remain in the CSV only as explicitly named diagnostics."
        ),
    }
    (args.output_dir / "summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
