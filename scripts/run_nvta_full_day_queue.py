"""Stage 2 of the NVTA speed-only full-day queue case.

Runs one continuous whole-day point queue on a single INRIX link.  NVTA has no
observed flow, so both boundaries are inferred and two independent arrival
branches are carried side by side:

  Branch B (speed inversion)  lambda_B is a smooth spline in time of day and the
                              queue comes only from the recurrence, so Q(t) always
                              carries Q(t-1).  The speed-implied queue is the
                              fitting target, so the residual measures how much of
                              the observed speed a physically smooth arrival
                              process can account for.

  Branch A (QVDF prior)       lambda_A comes from the week-average QVDF demand
                              and never looks at the day's speed.  Because that
                              demand is S3-inverted from speed it can never
                              exceed capacity, so Branch A is run as a capacity
                              sweep: the reported result is the assumed capacity
                              a queue would require, not a single curve.

Both branches share one recurrence over all 288 bins.  AM/MD/PM/NT are labels;
nothing is reset at a period boundary.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import BSpline
from scipy.optimize import least_squares


DT_H = 5.0 / 60.0
JAM_DENSITY_VEHPMIPL = 200.0
PERIOD_WINDOWS = [("AM", 360, 540), ("MD", 540, 900), ("PM", 900, 1140), ("NT", 1140, 1800)]
BOUNDARIES = {"AM->MD 09:00": 540, "MD->PM 15:00": 900, "PM->NT 19:00": 1140}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mu-config", type=Path, required=True)
    parser.add_argument("--free-speed-source", default="observed_p95",
                        choices=["observed_p95", "inrix_reference", "network_attribute",
                                 "qvdf_calibration_constant"])
    # Display only: the queue no longer depends on a smoothed speed, because the
    # recurrence supplies the inertia that the pointwise formula lacked.
    parser.add_argument("--speed-smoothing-bins", type=int, default=3)
    parser.add_argument("--arrival-knot-spacing-min", type=float, default=60.0)
    return parser.parse_args()


def run_queue(arrival_vph: np.ndarray, service_vph: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One continuous point queue over the whole day.  No period reset."""
    n = len(arrival_vph)
    queue = np.zeros(n)
    outflow = np.zeros(n)
    for i in range(n):
        available = arrival_vph[i] + queue[i] / DT_H
        outflow[i] = min(service_vph[i], available)
        if i + 1 < n:
            queue[i + 1] = max(0.0, queue[i] + (arrival_vph[i] - outflow[i]) * DT_H)
    return queue, outflow


def service_profile(queued: np.ndarray, capacity_vphpl: float, drop: float, lanes: int) -> np.ndarray:
    free = capacity_vphpl * lanes
    return np.where(queued, free * (1.0 - drop), free)


def spline_basis(clock: np.ndarray, knot_spacing_min: float, degree: int = 3) -> np.ndarray:
    """Cubic B-spline design matrix over the analysis clock.

    Arrival demand is a smooth function of time of day, so lambda is carried by
    a spline rather than by a free value per bin.  This is the polynomial
    approximation the advisor asked for as the way to stabilise lambda and mu.
    """
    lo, hi = float(clock[0]), float(clock[-1])
    interior = np.arange(lo + knot_spacing_min, hi, knot_spacing_min)
    knots = np.r_[[lo] * (degree + 1), interior, [hi] * (degree + 1)]
    n_basis = len(knots) - degree - 1
    columns = []
    for i in range(n_basis):
        coefficients = np.zeros(n_basis)
        coefficients[i] = 1.0
        columns.append(BSpline(knots, coefficients, degree, extrapolate=False)(clock))
    return np.nan_to_num(np.column_stack(columns))


def fit_smooth_arrival(
    basis: np.ndarray,
    service_vph: np.ndarray,
    queue_target_veh: np.ndarray,
    start: np.ndarray,
) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Find the smooth arrival profile whose recurrence best explains the speed.

    The queue is produced only by the recurrence, so it carries Q(t-1) by
    construction and cannot jump between bins.  The speed-implied queue is the
    fitting target, not the queue itself, which turns the closure residual from
    a tautology into a measure of how much of the observed speed a physically
    smooth arrival process can account for.
    """

    def residual(coefficients: np.ndarray) -> np.ndarray:
        arrival = np.maximum(basis @ np.abs(coefficients), 0.0)
        queue, _ = run_queue(arrival, service_vph)
        return queue - queue_target_veh

    solution = least_squares(residual, start, method="lm", max_nfev=20000)
    arrival = np.maximum(basis @ np.abs(solution.x), 0.0)
    queue, outflow = run_queue(arrival, service_vph)
    # When lambda lands entirely below mu the queue is identically zero, the
    # residual stops depending on the coefficients and the search stalls in a
    # flat region.  Restart just above the service rate so a queue exists and
    # the gradient is informative again.
    if queue.max() < 1.0 and queue_target_veh.max() > 1.0:
        restart = np.full(basis.shape[1], float(service_vph.mean()) * 1.05)
        solution = least_squares(residual, restart, method="lm", max_nfev=20000)
        arrival = np.maximum(basis @ np.abs(solution.x), 0.0)
        queue, outflow = run_queue(arrival, service_vph)
    return arrival, queue, outflow, np.abs(solution.x)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    day = pd.read_csv(args.data_dir / "speed_5min.csv")
    link = json.loads((args.data_dir / "link.json").read_text(encoding="utf-8"))
    mu_config = json.loads(args.mu_config.read_text(encoding="utf-8"))

    speed_raw = day["speed"].to_numpy(float)
    speed = (
        pd.Series(speed_raw)
        .rolling(args.speed_smoothing_bins, center=True, min_periods=1)
        .median()
        .to_numpy()
    )
    clock = day["clock_min"].to_numpy(float)
    lanes = int(link["lanes"])
    length_mi = float(link["length_mi"])
    free_speed = float(link["free_speed_mph"][args.free_speed_source])
    cutoff = float(link["qvdf_cutoff_mph"])

    # Regime from the persistent speed episodes detected in stage 1.
    episodes = pd.read_csv(args.output_dir / "speed_episodes.csv")
    anchor = pd.Timestamp(day["timestamp"].iloc[0]).normalize()
    queued = np.zeros(len(speed), dtype=bool)
    for _, episode in episodes.iterrows():
        start = (pd.Timestamp(episode["t0_la"]) - anchor).total_seconds() / 60.0
        end = (pd.Timestamp(episode["t3_la"]) - anchor).total_seconds() / 60.0
        queued |= (clock >= start) & (clock <= end)

    capacity = float(mu_config["capacity_vphpl"])
    drop = float(mu_config["capacity_drop_fraction"])
    mu = service_profile(queued, capacity, drop, lanes)

    # ---------- Branch B: queue read directly off the observed speed ----------
    # The speed-implied queue is a measurement, not the estimate.  It is read
    # pointwise off the unsmoothed speed and carries the full five-minute noise.
    free_travel_time_h = length_mi / free_speed
    queue_measurement = (
        np.maximum(length_mi / np.maximum(speed_raw, 1.0) - free_travel_time_h, 0.0) * mu
    )
    queue_measurement[~queued] = 0.0

    # The estimate comes only from the recurrence driven by a smooth arrival
    # profile, so Q(t) always carries Q(t-1) and cannot jump between bins.
    basis = spline_basis(clock, args.arrival_knot_spacing_min)
    lambda_b_forward, queue_b, outflow_b, _ = fit_smooth_arrival(
        basis, mu, queue_measurement, np.full(basis.shape[1], float(mu.mean()))
    )
    # Where the speed shows no queue for a sustained stretch, the arrival rate is
    # not identifiable: any lambda below mu gives the same zero queue.
    lambda_b_identifiable = (queue_measurement > 0.5) | (queue_b > 0.5)

    # ---------- Branch A: QVDF prior, run as a capacity sweep ----------
    # Every quantity here comes from the week-average calibration, never from the
    # day's own speed, which is what keeps Branch A independent of Branch B.
    qvdf = link["qvdf_periods"]
    lambda_a = np.zeros(len(speed))
    episode_volume_pl = 0.0
    whole_day_volume_pl = 0.0
    for params in qvdf.values():
        if params.get("P") in (None, 0) or params.get("demand") is None:
            continue
        t0_min = float(params["t0"]) * 60.0
        t3_min = float(params["t3"]) * 60.0
        window = (clock >= t0_min) & (clock <= t3_min)
        if not window.any():
            continue
        # demand is the per-lane volume accumulated over T0..T3 (qvdf_core.py).
        volume_pl = float(params["demand"])
        hours = max((t3_min - t0_min) / 60.0, 1e-6)
        lambda_a[window] = volume_pl * lanes / hours
        episode_volume_pl += volume_pl
        qdf = float(params.get("qdf") or 0.0)
        if qdf > 0:
            whole_day_volume_pl = max(whole_day_volume_pl, volume_pl / qdf)

    # qdf is the episode share of the whole-day per-lane volume, so the residual
    # is what the same calibration assigns to every remaining bin.
    off_episode = lambda_a <= 0
    residual_pl = max(whole_day_volume_pl - episode_volume_pl, 0.0)
    off_episode_hours = max(off_episode.sum() * DT_H, 1e-6)
    lambda_a[off_episode] = residual_pl * lanes / off_episode_hours

    storage_veh = length_mi * lanes * JAM_DENSITY_VEHPMIPL
    plausible_low, plausible_high = mu_config["physically_plausible_capacity_vphpl"]

    sweep_rows = []
    for sweep_capacity in mu_config["capacity_sweep_vphpl"]:
        mu_sweep = service_profile(queued, float(sweep_capacity), drop, lanes)
        queue_a_sweep, _ = run_queue(lambda_a, mu_sweep)
        queue_b_sweep = np.maximum(
            length_mi / np.maximum(speed_raw, 1.0) - free_travel_time_h, 0.0
        ) * mu_sweep
        queue_b_sweep[~queued] = 0.0
        qmax_a = float(queue_a_sweep.max())
        end_a = float(queue_a_sweep[-1])
        # Admissible means: a queue exists at all (the day shows four hours below
        # 30 mph), it fits inside the link, and it clears before the night ends.
        sweep_rows.append(
            {
                "assumed_capacity_vphpl": float(sweep_capacity),
                "branch_a_qmax_veh": qmax_a,
                "branch_a_peak_clock_min": float(clock[int(queue_a_sweep.argmax())]),
                "branch_a_queue_at_0900_veh": float(queue_a_sweep[clock == 540][0]),
                "branch_a_end_of_day_veh": end_a,
                "a_produces_queue": bool(qmax_a > 1.0),
                "a_within_storage": bool(qmax_a <= storage_veh),
                "a_clears_by_end_of_day": bool(end_a <= 1.0),
                "a_admissible": bool(qmax_a > 1.0 and qmax_a <= storage_veh and end_a <= 1.0),
                "branch_b_qmax_veh": float(queue_b_sweep.max()),
                "branch_b_peak_clock_min": float(clock[int(queue_b_sweep.argmax())]),
            }
        )
    sweep = pd.DataFrame(sweep_rows)

    admissible = sweep.loc[sweep["a_admissible"], "assumed_capacity_vphpl"]
    admissible_window = (
        [float(admissible.min()), float(admissible.max())] if not admissible.empty else None
    )
    overlaps_plausible = (
        None
        if admissible_window is None
        else bool(admissible_window[1] >= plausible_low and admissible_window[0] <= plausible_high)
    )

    mu_a = service_profile(queued, capacity, drop, lanes)
    queue_a, outflow_a = run_queue(lambda_a, mu_a)

    period_labels = []
    for value in clock:
        label = "OUT"
        for name, start, end in PERIOD_WINDOWS:
            if start <= value < end:
                label = name
        period_labels.append(label)

    series = pd.DataFrame(
        {
            "clock_min": clock.astype(int),
            "wall_clock": day["wall_clock"],
            "period": period_labels,
            "speed_raw_mph": speed_raw,
            "speed_mph": speed,
            "queued_regime": queued,
            "mu_vph": mu,
            "lambda_b_vph": lambda_b_forward,
            "lambda_b_identifiable": lambda_b_identifiable,
            "queue_b_measurement_veh": queue_measurement,
            "queue_b_recurrence_veh": queue_b,
            "outflow_b_vph": outflow_b,
            "lambda_a_vph": lambda_a,
            "queue_a_veh": queue_a,
            "outflow_a_vph": outflow_a,
        }
    )
    series.to_csv(args.output_dir / "full_day_queue_5min.csv", index=False)
    sweep.to_csv(args.output_dir / "branch_a_capacity_sweep.csv", index=False)

    residual = queue_b - queue_measurement
    summary = {
        "case_id": f"nvta_{link['net_link_id']}_{args.data_dir.name.split('_')[-1]}",
        "tmc": link["tmc"],
        "net_link_id": link["net_link_id"],
        "lanes": lanes,
        "length_mi": length_mi,
        "clock": "continuous minutes 360-1800, no midnight reset, 288 bins",
        "free_speed_used_mph": free_speed,
        "free_speed_source": args.free_speed_source,
        "arrival_model": {
            "form": "cubic B-spline in time of day",
            "knot_spacing_min": args.arrival_knot_spacing_min,
            "basis_functions": int(basis.shape[1]),
            "bins": int(len(clock)),
            "note": (
                "lambda is carried by a smooth spline and the queue is produced only by "
                "the recurrence, so Q(t) always uses Q(t-1). The speed-implied queue is "
                "the fitting target, which makes the residual below a real measure of "
                "model adequacy rather than a tautology."
            ),
        },
        "service_rate": {
            "capacity_vphpl": capacity,
            "capacity_drop_fraction": drop,
            "mu_free_vph": capacity * lanes,
            "mu_queued_vph": capacity * lanes * (1.0 - drop),
            "provenance": mu_config["capacity_source"],
            "replaceable_input": str(args.mu_config),
        },
        "branch_b_speed_inversion": {
            "qmax_veh": float(queue_b.max()),
            "peak_clock_min": float(clock[int(queue_b.argmax())]),
            "queue_at_period_boundaries_veh": {
                name: float(queue_b[clock == minute][0]) for name, minute in BOUNDARIES.items()
            },
            "end_of_day_queue_veh": float(queue_b[-1]),
            "measurement_residual_veh": {
                "rmse": float(np.sqrt(np.mean(residual ** 2))),
                "mae": float(np.mean(np.abs(residual))),
                "max_abs": float(np.max(np.abs(residual))),
            },
            "largest_single_bin_change_veh": float(
                np.abs(np.diff(queue_b, prepend=queue_b[0])).max()
            ),
            "measurement_largest_single_bin_change_veh": float(
                np.abs(np.diff(queue_measurement, prepend=queue_measurement[0])).max()
            ),
            "lambda_identifiable_bins": int(lambda_b_identifiable.sum()),
            "lambda_not_identifiable_bins": int((~lambda_b_identifiable).sum()),
        },
        "branch_a_qvdf_prior": {
            "lambda_mean_in_episode_vphpl": float(lambda_a[queued].mean() / lanes),
            "lambda_off_episode_vphpl": float(lambda_a[~queued].mean() / lanes),
            "whole_day_volume_vehpl": whole_day_volume_pl,
            "episode_volume_vehpl": episode_volume_pl,
            "qmax_veh_at_default_capacity": float(queue_a.max()),
            "qmax_range_over_sweep_veh": [
                float(sweep["branch_a_qmax_veh"].min()),
                float(sweep["branch_a_qmax_veh"].max()),
            ],
            "admissible_capacity_window_vphpl": admissible_window,
            "physically_plausible_capacity_vphpl": [plausible_low, plausible_high],
            "admissible_window_overlaps_plausible": overlaps_plausible,
            "peak_time_gap_vs_branch_b_min": (
                None
                if admissible_window is None
                else float(
                    sweep.loc[sweep["a_admissible"], "branch_a_peak_clock_min"].iloc[0]
                    - float(clock[int(queue_b.argmax())])
                )
            ),
            "interpretation": (
                "The admissible window is the set of assumed capacities at which the "
                "QVDF prior yields a queue that exists, fits inside the link, and clears "
                "by the end of the day. A window that is empty, or that misses the "
                "physically plausible capacity range, falsifies the parameter chain for "
                "this link. A window that is narrow relative to the sweep shows the "
                "result is governed by the capacity assumption rather than by the data."
            ),
        },
        "spatial_storage": {
            "storage_veh": storage_veh,
            "jam_density_vehpmipl": JAM_DENSITY_VEHPMIPL,
            "branch_b_exceeds_storage": bool(queue_b.max() > storage_veh),
            "branch_a_exceeds_storage": bool(queue_a.max() > storage_veh),
        },
        "scope": (
            "NVTA has no observed flow. Both lambda and mu are inferred, so neither "
            "branch is an accuracy validation. Branch B is an internal consistency "
            "check; Branch A is a falsification test of the existing QVDF parameters."
        ),
    }
    (args.output_dir / "queue_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    print("\ncapacity sweep:")
    print(sweep.round(1).to_string(index=False))


if __name__ == "__main__":
    main()
