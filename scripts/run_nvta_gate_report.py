"""Apply the shared physical gates to every link of the NVTA full-day run.

    python scripts/run_nvta_gate_report.py

Writes one row per link with a status, a reason code, and a per-gate verdict, so
coverage and attrition can be counted rather than described. Reads only committed
outputs.

The result is not flattering, and that is the point: nothing in this run reaches
`is_physical`, because the arrival rate is a model output fitted against the same
speed the model is scored on. The gate framework says so in a field rather than
in a paragraph someone may skip.
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
from fdqbench.validation import (DischargeSource, Status, WorkloadSource,  # noqa: E402
                                 combine, gate_capacity_basis,
                                 gate_capacity_plausibility, gate_data_evidence,
                                 gate_episode_independence, gate_queue_state,
                                 gate_speed_profile)

DT_H = 0.25
BOUNDARIES = {"AM->MD 09:00": 540, "MD->PM 15:00": 900}

# lambda is a spline fitted so the recurrence reproduces the speed-implied queue,
# then scored against that same speed. That is a model output, not an independent
# workload, and it is what holds every link out of the physical chain.
WORKLOAD_SOURCE = WorkloadSource.MODEL_INFERRED
DISCHARGE_SOURCE = DischargeSource.ASSUMED_CAPACITY


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--speed-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step8_speed_variants_15min.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_gates")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    frame = pd.read_csv(args.speed_file)

    rows = []
    for (link_id, corridor), group in frame.groupby(["link_id", "corridor"], sort=True):
        group = group.sort_values("t_min")
        clock = group["t_min"].to_numpy()
        queue = group["queue_model_veh"].to_numpy(float)
        service = group["mu_vph"].to_numpy(float)
        lanes = int(group["lanes"].iloc[0])
        boundaries = [int(np.searchsorted(clock, minute)) for minute in BOUNDARIES.values()]

        # Scored on the bins where a queue makes lambda identifiable. Elsewhere
        # the model is pinned at free speed by construction and an MAE there
        # measures the pinning, not the model.
        in_episode = group["lambda_identifiable"].astype(bool).to_numpy()
        error = (group["speed_model_mph"] - group["speed_mph"]).abs().to_numpy()

        gates = [
            gate_data_evidence(detector_id=str(group["tmc_code"].iloc[0]), lanes=lanes,
                               observed_mask_available=True,
                               time_basis="America/New_York", units_declared=True),
            gate_capacity_basis(capacity_basis_declared="per_link",
                                capacity_kind="nominal_hourly"),
            gate_capacity_plausibility(capacity_vphpl=float(service[0]) / lanes),
            gate_queue_state(queue_veh=queue, period_boundary_indices=boundaries,
                             service_vph=service, dt_h=DT_H),
            gate_speed_profile(
                observed_bin_mae_mph=float(error[in_episode].mean()) if in_episode.any() else None,
                observed_bins=int(in_episode.sum()),
                imputed_bin_mae_mph=float(error[~in_episode].mean()) if (~in_episode).any() else None,
                imputed_bins=int((~in_episode).sum())),
            gate_episode_independence(workload_source=WORKLOAD_SOURCE),
        ]
        verdict = combine(gates, workload_source=WORKLOAD_SOURCE)
        rows.append({
            "link_id": link_id, "corridor": corridor, "lanes": lanes,
            "queued_bins": int(in_episode.sum()),
            "episode_mae_mph": round(float(error[in_episode].mean()), 3) if in_episode.any() else None,
            "queue_peak_veh": round(float(queue.max()), 2),
            "discharge_source": DISCHARGE_SOURCE.value,
            "episode_workload_source": WORKLOAD_SOURCE.value,
            **verdict.as_row(),
        })

    report = pd.DataFrame(rows)
    report.to_csv(args.output_dir / "nvta_gate_report.csv", index=False)

    gate_columns = [c for c in report.columns if c.startswith("gate_")]
    summary = {
        "schema_version": "0.3",
        "source": as_repo_relative(args.speed_file),
        "links": int(len(report)),
        "status": {k: int(v) for k, v in report["status"].value_counts().items()},
        "binding_reason": {k: int(v) for k, v in report["reason_code"].value_counts().items()},
        "physical": int(report["is_physical"].sum()),
        "duration_validation_status": sorted(report["duration_validation_status"].unique()),
        "by_gate": {c[5:]: {k: int(v) for k, v in report[c].value_counts().items()}
                    for c in gate_columns},
        "reading": (
            "No link reaches is_physical. lambda is fitted so the recurrence "
            "reproduces the speed-implied queue and is then scored against that "
            "same speed, so episode_workload_source is MODEL_INFERRED and every "
            "duration result is a diagnostic closure. The 176 INSUFFICIENT_DATA "
            "links carry no queued bin, so there is no observed-bin MAE to score: "
            "an abstention, not a failure."
        ),
    }
    (args.output_dir / "nvta_gate_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8")

    print(f"{summary['links']} links gated -> {as_repo_relative(args.output_dir)}\n")
    print(f"  {'status':<20}{'links':>7}")
    for status, count in sorted(summary["status"].items()):
        print(f"  {status:<20}{count:>7}")
    print(f"\n  {'binding reason':<36}{'links':>7}")
    for reason, count in sorted(summary["binding_reason"].items(), key=lambda kv: -kv[1]):
        print(f"  {reason:<36}{count:>7}")
    print(f"\n  physical: {summary['physical']} of {summary['links']}")


if __name__ == "__main__":
    main()
