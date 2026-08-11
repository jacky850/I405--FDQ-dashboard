"""Build the compact browser payload for the multiweek QVDF dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/i405_multiweek_average_holdout"
DESTINATION = ROOT / "dashboard/qvdf_multiweek_data.js"


def clean(value: object) -> object:
    if value is None or (isinstance(value, float) and np.isnan(value)):
        return None
    if isinstance(value, (np.integer,)):
        return int(value)
    if isinstance(value, (np.floating,)):
        return float(value)
    if isinstance(value, (np.bool_,)):
        return bool(value)
    return value


def records(frame: pd.DataFrame, columns: list[str]) -> list[dict[str, object]]:
    return [
        {column: clean(row[column]) for column in columns}
        for _, row in frame[columns].iterrows()
    ]


def main() -> None:
    results = pd.read_csv(SOURCE / "leave_one_week_out_qvdf_results.csv")
    profiles = pd.read_csv(SOURCE / "weekly_average_weekday_profiles_5min.csv")
    summary = json.loads((SOURCE / "multiweek_holdout_summary.json").read_text(encoding="utf-8"))

    case_columns = [
        "link_id", "period", "week_start", "episode_identified", "P_h",
        "vT2_mph", "cutoff_speed_vc_mph", "t0_la", "T2_la", "t3_la",
        "observed_average_period_volume_veh", "V_hat_veh",
        "absolute_percentage_error_pct", "capacity_vph", "k_d", "f_d_h",
        "f_p", "n", "s", "training_episode_weeks",
        "training_max_observed_D_over_C", "x_hat_D_over_C", "z_observed",
        "z_predicted", "severity_ratio", "vT2_predicted_mph",
        "vT2_error_mph", "speed_branch_supported",
        "duration_extrapolation_ratio", "duration_branch_supported",
        "final_supported", "inverse_status", "observed_peak_1h_demand_veh_h",
    ]

    profile_payload: dict[str, list[list[float]]] = {}
    for (link_id, week_start), group in profiles.groupby(["link_id", "week_start"]):
        profile_payload[f"{link_id}|{week_start}"] = [
            [int(row.minute_of_day), round(float(row.average_speed_mph), 3), round(float(row.average_flow_veh_h), 3)]
            for row in group.itertuples(index=False)
        ]

    payload = {
        "summary": summary,
        "weeks": sorted(results["week_start"].unique().tolist()),
        "links": sorted(results["link_id"].unique().tolist()),
        "cases": records(results.sort_values(["link_id", "period", "week_start"]), case_columns),
        "profiles": profile_payload,
    }
    DESTINATION.parent.mkdir(parents=True, exist_ok=True)
    DESTINATION.write_text(
        "window.QVDF_MULTI=" + json.dumps(payload, separators=(",", ":"), allow_nan=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {DESTINATION} ({DESTINATION.stat().st_size / 1024:.1f} KiB)")


if __name__ == "__main__":
    main()
