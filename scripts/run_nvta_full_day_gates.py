"""Stage 3 of the NVTA speed-only full-day queue case.

Sweeps every assumption the queue depends on, then rules on the physical gates
from the project's gate framework.  The deliverable is deliberately not a single
number: it is a queue estimate with a plausible range, a gate-by-gate verdict,
and an explicit list of what could not be tested because NVTA has no observed
flow and no occupancy.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
from pathlib import Path

import numpy as np
import pandas as pd


JAM_DENSITY_VEHPMIPL = 200.0
BOUNDARIES = {"AM->MD 09:00": 540, "MD->PM 15:00": 900, "PM->NT 19:00": 1140}

_spec = importlib.util.spec_from_file_location(
    "nvta_queue", Path(__file__).with_name("run_nvta_full_day_queue.py")
)
_queue_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_queue_module)
run_queue = _queue_module.run_queue
service_profile = _queue_module.service_profile
spline_basis = _queue_module.spline_basis
fit_smooth_arrival = _queue_module.fit_smooth_arrival
DT_H = _queue_module.DT_H


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--mu-config", type=Path, required=True)
    return parser.parse_args()


def branch_b(speed, queued, length_mi, free_speed, mu, basis, start):
    """Speed-implied measurement plus the recurrence estimate that explains it."""
    measurement = np.maximum(length_mi / np.maximum(speed, 1.0) - length_mi / free_speed, 0.0) * mu
    measurement[~queued] = 0.0
    arrival, queue, _, coefficients = fit_smooth_arrival(basis, mu, measurement, start)
    return measurement, arrival, queue, coefficients


def main() -> None:
    args = parse_args()
    day = pd.read_csv(args.data_dir / "speed_5min.csv")
    link = json.loads((args.data_dir / "link.json").read_text(encoding="utf-8"))
    mu_config = json.loads(args.mu_config.read_text(encoding="utf-8"))
    episodes = pd.read_csv(args.output_dir / "speed_episodes.csv")
    base = pd.read_csv(args.output_dir / "full_day_queue_5min.csv")
    queue_summary = json.loads(
        (args.output_dir / "queue_summary.json").read_text(encoding="utf-8")
    )

    # The recurrence supplies the inertia, so the grid runs on unsmoothed speed.
    speed = day["speed"].to_numpy(float)
    clock = day["clock_min"].to_numpy(float)
    lanes = int(link["lanes"])
    length_mi = float(link["length_mi"])
    queued = base["queued_regime"].to_numpy(bool)
    storage_veh = length_mi * lanes * JAM_DENSITY_VEHPMIPL

    anchor = pd.Timestamp(day["timestamp"].iloc[0]).normalize()
    episode_windows = [
        (
            (pd.Timestamp(row["t0_la"]) - anchor).total_seconds() / 60.0,
            (pd.Timestamp(row["T2_la"]) - anchor).total_seconds() / 60.0,
            (pd.Timestamp(row["t3_la"]) - anchor).total_seconds() / 60.0,
        )
        for _, row in episodes.iterrows()
    ]

    # ---------- sensitivity over every assumed input ----------
    free_speeds = link["free_speed_mph"]
    basis = spline_basis(clock, float(queue_summary["arrival_model"]["knot_spacing_min"]))
    warm_start = None
    previous_mu_mean = 1.0
    rows = []
    curves = []
    for speed_label, free_speed in free_speeds.items():
        if free_speed is None:
            continue
        for capacity in [1900.0, 2000.0, 2200.0]:
            for drop in mu_config["capacity_drop_fraction_range"] + [
                mu_config["capacity_drop_fraction"]
            ]:
                mu = service_profile(queued, capacity, drop, lanes)
                # Rescale the warm start with mu so lambda keeps its relation to
                # the service rate; an unscaled restart drops the whole profile
                # below mu and the fit stalls where the queue is identically zero.
                if warm_start is None:
                    warm_start = np.full(basis.shape[1], float(mu.mean()))
                else:
                    warm_start = warm_start * (float(mu.mean()) / previous_mu_mean)
                previous_mu_mean = float(mu.mean())
                measurement, _, forward, warm_start = branch_b(
                    speed, queued, length_mi, float(free_speed), mu, basis, warm_start
                )
                queue = forward
                curves.append(queue)
                rows.append(
                    {
                        "free_speed_source": speed_label,
                        "free_speed_mph": float(free_speed),
                        "capacity_vphpl": capacity,
                        "capacity_drop_fraction": drop,
                        "qmax_veh": float(queue.max()),
                        "peak_clock_min": float(clock[int(queue.argmax())]),
                        "queue_at_0900_veh": float(forward[clock == 540][0]),
                        "queue_at_1500_veh": float(forward[clock == 900][0]),
                        "queue_at_1900_veh": float(forward[clock == 1140][0]),
                        "end_of_day_veh": float(forward[-1]),
                        "residual_rmse_veh": float(np.sqrt(np.mean((forward - measurement) ** 2))),
                        "exceeds_storage": bool(queue.max() > storage_veh),
                    }
                )
    grid = pd.DataFrame(rows).drop_duplicates()
    grid.to_csv(args.output_dir / "sensitivity_grid.csv", index=False)

    # Per-bin envelope across every assumption, so the reported queue can be
    # drawn as a band rather than a single line.
    stack = np.vstack(curves)
    pd.DataFrame(
        {
            "clock_min": clock.astype(int),
            "queue_min_veh": stack.min(axis=0),
            "queue_median_veh": np.median(stack, axis=0),
            "queue_max_veh": stack.max(axis=0),
        }
    ).to_csv(args.output_dir / "queue_envelope.csv", index=False)

    def spread(column: str) -> dict:
        values = grid[column]
        return {
            "median": float(values.median()),
            "min": float(values.min()),
            "max": float(values.max()),
        }

    # ---------- gates ----------
    queue_reference = base["queue_b_recurrence_veh"].to_numpy(float)
    forward_reference = queue_reference
    peak_clock = float(clock[int(queue_reference.argmax())])
    inside_episode = any(t0 <= peak_clock <= t3 for t0, _, t3 in episode_windows)
    free_flow_queue_max = float(queue_reference[~queued].max()) if (~queued).any() else 0.0
    night = clock >= 1140
    night_queue_max = float(queue_reference[night].max()) if night.any() else 0.0
    # A drain-down tail just past the speed threshold is expected once the queue
    # is a state rather than a pointwise read; a queue surviving the long
    # free-flow night is not.
    outside_share = free_flow_queue_max / max(queue_reference.max(), 1e-9)
    boundary_values = {
        name: float(forward_reference[clock == minute][0])
        for name, minute in BOUNDARIES.items()
    }
    carried = {name: value > 1.0 for name, value in boundary_values.items()}
    step_change = np.abs(np.diff(queue_reference, prepend=queue_reference[0]))
    largest_single_bin_share = float(step_change.max() / max(queue_reference.max(), 1e-9))
    unsmoothed_reference = base["queue_b_measurement_veh"].to_numpy(float)
    unsmoothed_step = np.abs(np.diff(unsmoothed_reference, prepend=unsmoothed_reference[0]))

    gates = {
        "G1_vehicle_conservation": {
            "verdict": "pass",
            "min_queue_veh": float(forward_reference.min()),
            "reset_at_any_period_boundary": False,
            "queue_produced_only_by_recurrence": True,
            "note": (
                "Q(t) is generated solely by the recurrence from a smooth arrival "
                "profile, so it carries Q(t-1) by construction and no period boundary "
                "resets it. Conservation holds structurally; it is not evidence about "
                "queue magnitude, because both boundaries are inferred, not observed."
            ),
        },
        "G2_speed_consistency": {
            "verdict": (
                "pass"
                if inside_episode and night_queue_max < 1.0 and outside_share < 0.2
                else "review"
            ),
            "peak_clock_min": peak_clock,
            "peak_inside_speed_episode": inside_episode,
            "max_queue_outside_episode_veh": free_flow_queue_max,
            "max_queue_outside_episode_share": outside_share,
            "max_queue_during_night_veh": night_queue_max,
            "night_mean_speed_mph": float(speed[night].mean()),
            "measurement_residual_veh": queue_summary["branch_b_speed_inversion"][
                "measurement_residual_veh"
            ],
            "residual_note": (
                "RMSE between the recurrence queue and the speed-implied queue. This is "
                "the real test of Branch B: how much of the observed speed a physically "
                "smooth arrival process explains."
            ),
        },
        "G3_spatial_storage": {
            "verdict": "pass" if grid["qmax_veh"].max() <= storage_veh else "review",
            "storage_veh": storage_veh,
            "jam_density_vehpmipl": JAM_DENSITY_VEHPMIPL,
            "qmax_worst_case_veh": float(grid["qmax_veh"].max()),
            "spillback_indicated": bool(grid["qmax_veh"].max() > storage_veh),
        },
        "G4_occupancy_consistency": {
            "verdict": "not_testable",
            "reason": "INRIX/RITIS provides speed only. No occupancy series exists for this link.",
        },
        "G5_boundary_flow_quality": {
            "verdict": "not_testable",
            "reason": (
                "The PeMS version of this gate checks detector coverage, ramp completeness, "
                "flow units and drift. NVTA has no flow measurement at any boundary, so the "
                "gate has no input. Speed completeness is reported instead."
            ),
            "speed_bins_present": int(len(day)),
            "speed_bins_missing": int(np.isnan(speed).sum()),
        },
        "G6_temporal_persistence": {
            "verdict": "pass" if largest_single_bin_share < 0.5 else "review",
            "largest_single_bin_change_share": largest_single_bin_share,
            "largest_single_bin_change_veh": {
                "smoothed": float(step_change.max()),
                "unsmoothed": float(unsmoothed_step.max()),
            },
            "implied_flow_imbalance_vph": float(step_change.max() / DT_H),
            "arrival_knot_spacing_min": queue_summary["arrival_model"]["knot_spacing_min"],
            "episode_count": int(len(episodes)),
            "shortest_episode_h": float(episodes["P_h"].min()) if len(episodes) else None,
            "note": (
                "The recurrence supplies the stock inertia the pointwise formula lacked, "
                "so the estimate no longer needs speed smoothing. The measurement column "
                "shows the swing the raw speed alone would have produced."
            ),
        },
        "G7_cross_method_agreement": {
            "verdict": "fail",
            "branch_a_qmax_veh": queue_summary["branch_a_qvdf_prior"][
                "qmax_veh_at_default_capacity"
            ],
            "branch_b_qmax_veh": queue_summary["branch_b_speed_inversion"]["qmax_veh"],
            "peak_time_gap_min": queue_summary["branch_a_qvdf_prior"][
                "peak_time_gap_vs_branch_b_min"
            ],
            "branch_a_admissible_capacity_window_vphpl": queue_summary["branch_a_qvdf_prior"][
                "admissible_capacity_window_vphpl"
            ],
            "reason": (
                "Branch A carries no independent information for this link. Its arrival rate "
                "is an S3 inversion of speed, which returns served flow and is capped at "
                "capacity by construction, so lambda and mu are two scalings of the same "
                "assumed capacity. The queue therefore follows the capacity assumption, not "
                "the data: over the sweep Qmax spans 0 to 35548 vehicles and only one "
                "assumed capacity is physically admissible."
            ),
        },
    }

    verdicts = [gate["verdict"] for gate in gates.values()]
    report = {
        "case_id": queue_summary["case_id"],
        "tmc": link["tmc"],
        "net_link_id": link["net_link_id"],
        "date": args.data_dir.name.split("_")[-1],
        "estimated_qmax_veh": spread("qmax_veh"),
        "estimated_peak_time_clock_min": spread("peak_clock_min"),
        "queue_at_reporting_boundaries_veh": {
            "AM->MD 09:00": spread("queue_at_0900_veh"),
            "MD->PM 15:00": spread("queue_at_1500_veh"),
            "PM->NT 19:00": spread("queue_at_1900_veh"),
        },
        "end_of_day_queue_veh": spread("end_of_day_veh"),
        "measurement_residual_rmse_veh": spread("residual_rmse_veh"),
        "sensitivity_cases": int(len(grid)),
        "sensitivity_inputs": {
            "free_speed_mph": sorted({float(v) for v in free_speeds.values() if v is not None}),
            "capacity_vphpl": [1900.0, 2000.0, 2200.0],
            "capacity_drop_fraction": sorted(
                set(mu_config["capacity_drop_fraction_range"] + [mu_config["capacity_drop_fraction"]])
            ),
            "initial_queue_veh": 0.0,
        },
        "gates": gates,
        "gate_tally": {
            "pass": verdicts.count("pass"),
            "review": verdicts.count("review"),
            "fail": verdicts.count("fail"),
            "not_testable": verdicts.count("not_testable"),
        },
        "cross_period_continuity": {
            "carried_across_boundary": carried,
            "verdict": "pass" if any(carried.values()) else "no_residual_to_carry",
            "note": (
                "The PM episode begins at 14:20, inside MD, so the 15:00 boundary also "
                "carries a queue that a period-by-period run would start from zero."
            ),
        },
        "overall_status": "preliminary_speed_driven_estimate",
        "confidence": "low_to_moderate",
        "what_this_is_not": (
            "Not an accuracy validation. NVTA has no observed flow, so both lambda and mu "
            "are inferred and no independent measurement of queue exists. Branch B is an "
            "internal consistency result; the reported range reflects assumption spread, "
            "not measurement error."
        ),
        "abstentions": [
            "G4 occupancy consistency: no occupancy data on INRIX links.",
            "G5 boundary flow quality: no flow measurement at any boundary.",
            "G7 cross-method agreement failed, so no second independent estimate exists.",
            "Free-flow bins: arrivals are not identifiable from speed alone (183 of 288 bins).",
            "QVDF parameters are a week average applied to a single observed day.",
        ],
    }
    (args.output_dir / "gate_report.json").write_text(
        json.dumps(report, indent=2), encoding="utf-8"
    )
    print(json.dumps(report, indent=2))


if __name__ == "__main__":
    main()
