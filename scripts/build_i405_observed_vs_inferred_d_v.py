"""Observed vs inferred demand and volume, per leave-one-week-out case.

Reports peak demand D, period volume V, and congestion duration P side by side
with the observed value, the speed-only inferred value, and the difference.

Two naming notes, because the meeting shorthand collides with the project
convention:

  * ``P`` is the congestion duration in hours. The meeting notes call it "D",
    but ``D`` in every equation here is the peak demand rate.
  * ``P`` is an *input* to the inversion, not an output. The duration branch is
    inverted to obtain D/C, so a "predicted P" would reproduce the observed P by
    construction. It is reported once, not as an observed/inferred pair.

Coverage is reported next to accuracy on purpose. A conditional error over the
supported subset says nothing about the cases the method declined.
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

from fdqbench.paths import as_repo_relative  # noqa: E402


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-file",
        type=Path,
        default=Path("outputs/i405_multiweek_average_holdout/leave_one_week_out_qvdf_results.csv"),
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=Path("outputs/i405_multiweek_average_holdout"),
    )
    return parser.parse_args()


def assert_capacity_is_training_only(raw: pd.DataFrame) -> None:
    """`dc_rate_observed` divides by capacity, so that capacity must not have seen
    the holdout week.

    The upstream calibration takes the capacity proxy as the median over the
    training weeks only, which is `train = group[week_start != test.week_start]`.
    This recomputes that leave-one-out median from the per-week proxies carried in
    the results file and requires the stored capacity to match it.

    Matching the all-week median is not by itself evidence of a leak: dropping one
    week from an odd-sized set often leaves the median where it was. Only a
    mismatch against the recomputed leave-one-out value is a real finding.
    """
    mismatched = []
    for (link_id, period), group in raw.groupby(["link_id", "period"]):
        proxy = group.set_index("week_start")["capacity_proxy_week_p95_vph"].astype(float)
        for week, row in group.set_index("week_start").iterrows():
            expected = float(proxy.drop(index=week).median())
            if not np.isclose(float(row["capacity_vph"]), expected, rtol=1e-9):
                mismatched.append((link_id, period, week,
                                   float(row["capacity_vph"]), expected))
    if mismatched:
        raise SystemExit(
            f"capacity_vph does not equal the leave-one-week-out median on "
            f"{len(mismatched)} case(s), so it may have seen holdout flow: "
            f"{mismatched[:5]}"
        )


def error_block(frame: pd.DataFrame, observed: str, inferred: str) -> dict:
    if frame.empty:
        return {"cases": 0}
    error = frame[inferred] - frame[observed]
    absolute_percentage = (error.abs() / frame[observed].abs()) * 100.0
    return {
        "cases": int(len(frame)),
        "mae": float(error.abs().mean()),
        "rmse": float(np.sqrt((error ** 2).mean())),
        "bias": float(error.mean()),
        "mape_pct": float(absolute_percentage.mean()),
        "median_ape_pct": float(absolute_percentage.median()),
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(args.results_file)
    assert_capacity_is_training_only(raw)

    frame = pd.DataFrame(
        {
            "link_id": raw["link_id"],
            "period": raw["period"],
            "holdout_week": raw["week_start"],
            "period_hours": raw["period_hours"],
            "episode_identified": raw["episode_identified"],
            "final_supported": raw["final_supported"],
            "evidence_status": raw["evidence_status"],
            "inverse_status": raw["inverse_status"],
            # Congestion duration: observed only, and an input to the inversion.
            "congestion_duration_P_h": raw["P_h"],
            "t0_la": raw["t0_la"],
            "T2_la": raw["T2_la"],
            "t3_la": raw["t3_la"],
            # Peak demand rate D.
            "demand_D_observed_vph": raw["observed_peak_1h_demand_veh_h"],
            "demand_D_inferred_vph": raw["D_hat_veh_h"],
            # Period volume V.
            "volume_V_observed_veh": raw["observed_average_period_volume_veh"],
            "volume_V_inferred_veh": raw["V_hat_veh"],
            # Two different quantities that were previously reported as one.
            #
            # k_d is the peak-load factor D/(V/H): how much the peak hour
            # exceeds the period average. It is always above 1 and says nothing
            # about capacity.
            #
            # D/C is the rate-based demand loading: the peak demand rate over
            # the nominal hourly capacity. It straddles 1.
            #
            # Reporting k_d as the observed D/C compared an inferred D/C against
            # an observed peak-load factor. See docs/VARIABLE_CONTRACT.md 2.1.
            "peak_load_factor_kd_observed": raw["k_d_observed"],
            "dc_rate_observed": raw["observed_peak_1h_demand_veh_h"] / raw["capacity_vph"],
            "dc_rate_inferred": raw["D_hat_veh_h"] / raw["capacity_vph"],
            "capacity_vph": raw["capacity_vph"],
            # Minimum speed, the one quantity already checked against holdout.
            "vT2_observed_mph": raw["vT2_mph"],
            "vT2_predicted_mph": raw["vT2_predicted_mph"],
        }
    )

    for label, observed, inferred in [
        ("demand_D", "demand_D_observed_vph", "demand_D_inferred_vph"),
        ("volume_V", "volume_V_observed_veh", "volume_V_inferred_veh"),
        ("dc_rate", "dc_rate_observed", "dc_rate_inferred"),
    ]:
        difference = frame[inferred] - frame[observed]
        frame[f"{label}_delta"] = difference
        frame[f"{label}_ape_pct"] = (difference.abs() / frame[observed].abs()) * 100.0
    frame["vT2_error_mph"] = frame["vT2_predicted_mph"] - frame["vT2_observed_mph"]

    frame = frame.sort_values(["link_id", "period", "holdout_week"]).reset_index(drop=True)
    frame.to_csv(args.output_dir / "observed_vs_inferred_D_V.csv", index=False)

    episodes = frame.loc[frame["episode_identified"].astype(bool)]
    supported = frame.loc[frame["final_supported"].astype(bool)]

    summary = {
        "schema_version": "0.3",
        "source": as_repo_relative(args.results_file),
        "definitions": {
            "D": "peak one-hour demand rate, veh/h",
            "V": "period volume, vehicles",
            "P": "congestion duration, hours; observed only, and an input to the inversion",
            "k_d": (
                "peak-load factor D/(V/H), dimensionless. Always above 1. Not D/C, and "
                "not comparable with an inferred D/C."
            ),
            "dc_rate": (
                "rate-based demand loading D/C, dimensionless. The capacity is the "
                "training-only capacity for that leave-one-week-out case."
            ),
            "note_on_V": (
                "V_inferred = D_inferred / PLF, where PLF is a per-link peak-load factor "
                "calibrated on the training weeks. V and D are therefore not independent "
                "estimates; they are one estimate reported in two units."
            ),
        },
        "coverage": {
            "total_cases": int(len(frame)),
            "episode_identified": int(len(episodes)),
            "supported_both_gates": int(len(supported)),
            "supported_pct": float(100.0 * len(supported) / max(len(frame), 1)),
            "abstained": int(len(frame) - len(supported)),
        },
        "supported_cases": {
            "demand_D": error_block(supported, "demand_D_observed_vph", "demand_D_inferred_vph"),
            "volume_V": error_block(supported, "volume_V_observed_veh", "volume_V_inferred_veh"),
            "dc_rate": error_block(supported, "dc_rate_observed", "dc_rate_inferred"),
            "vT2_mae_mph": float(supported["vT2_error_mph"].abs().mean()),
        },
        "peak_load_factor_kd_observed": {
            "median": float(frame["peak_load_factor_kd_observed"].median()),
            "min": float(frame["peak_load_factor_kd_observed"].min()),
            "max": float(frame["peak_load_factor_kd_observed"].max()),
            "note": (
                "Reported on its own, never against an inferred D/C. This field was "
                "previously emitted as d_over_c_observed."
            ),
        },
        "all_episode_cases": {
            "demand_D": error_block(episodes, "demand_D_observed_vph", "demand_D_inferred_vph"),
            "volume_V": error_block(episodes, "volume_V_observed_veh", "volume_V_inferred_veh"),
        },
        "reading": (
            "Accuracy is conditional on the supported subset. The method declines the "
            "remaining cases rather than guessing, so the error figures and the coverage "
            "figure must be quoted together."
        ),
    }
    (args.output_dir / "observed_vs_inferred_D_V_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))
    columns = [
        "link_id", "period", "holdout_week", "congestion_duration_P_h",
        "demand_D_observed_vph", "demand_D_inferred_vph", "demand_D_delta", "demand_D_ape_pct",
        "volume_V_observed_veh", "volume_V_inferred_veh", "volume_V_delta", "volume_V_ape_pct",
    ]
    print("\nSupported cases:")
    print(supported[columns].round(1).to_string(index=False))


if __name__ == "__main__":
    main()
