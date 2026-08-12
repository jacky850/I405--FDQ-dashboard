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
from pathlib import Path

import numpy as np
import pandas as pd


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
            # Demand-to-capacity ratio.
            "d_over_c_observed": raw["k_d_observed"],
            "d_over_c_inferred": raw["x_hat_D_over_C"],
            "capacity_vph": raw["capacity_vph"],
            # Minimum speed, the one quantity already checked against holdout.
            "vT2_observed_mph": raw["vT2_mph"],
            "vT2_predicted_mph": raw["vT2_predicted_mph"],
        }
    )

    for label, observed, inferred in [
        ("demand_D", "demand_D_observed_vph", "demand_D_inferred_vph"),
        ("volume_V", "volume_V_observed_veh", "volume_V_inferred_veh"),
        ("d_over_c", "d_over_c_observed", "d_over_c_inferred"),
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
        "source": str(args.results_file),
        "definitions": {
            "D": "peak one-hour demand rate, veh/h",
            "V": "period volume, vehicles",
            "P": "congestion duration, hours; observed only, and an input to the inversion",
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
            "d_over_c": error_block(supported, "d_over_c_observed", "d_over_c_inferred"),
            "vT2_mae_mph": float(supported["vT2_error_mph"].abs().mean()),
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
