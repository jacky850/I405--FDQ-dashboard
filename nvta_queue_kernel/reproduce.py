"""Reproduce the published NVTA queue and speed for one I-395 and one I-66 link.

    python nvta_queue_kernel/reproduce.py

Reads lambda and mu from `data/`, runs the kernel, and compares every interval
against the published `expected_output.csv`, which was cut from
`outputs/nvta_queue/step8_speed_variants_15min.csv` without modification.

Exit code is 0 only if every value matches to within 1e-9.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parent))
from kernel import run_link  # noqa: E402

HERE = Path(__file__).resolve().parent
DT_H = 15.0 / 60.0
INITIAL_QUEUE_VEH = 0.0        # Q(06:00) = 0, an empty link before the AM build-up
TOLERANCE = 1e-9

CASES = [
    ("I-395 NB", "link_26469_i395nb.csv"),
    ("I-66 EB", "link_31804_i66eb.csv"),
]

COMPARED = ["outflow_vph", "queue_model_veh", "delay_h", "travel_time_h", "speed_model_mph"]


def hhmm(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def run_case(path: Path, expected: pd.DataFrame, show_rows: int) -> float:
    frame = pd.read_csv(path).sort_values("t_min").reset_index(drop=True)
    link_id = int(frame["link_id"].iloc[0])
    length_mi = float(frame["length_mi"].iloc[0])
    free_speed = float(frame["free_speed_mph"].iloc[0])

    result = run_link(
        arrival_vph=frame["lambda_anchored_vph"].to_numpy(float),
        service_vph=frame["mu_vph"].to_numpy(float),
        dt_h=DT_H,
        length_mi=length_mi,
        free_speed_mph=free_speed,
        initial_queue_veh=INITIAL_QUEUE_VEH,
    )

    print(f"  link {link_id}  {frame['corridor'].iloc[0]}  TMC {frame['tmc_code'].iloc[0]}")
    print(f"  {len(frame)} intervals of {int(DT_H * 60)} min, "
          f"{hhmm(int(frame.t_min.min()))}-{hhmm(int(frame.t_min.max()) + int(DT_H * 60))}, "
          f"L = {length_mi} mi, v_f = {free_speed:.2f} mph, "
          f"{int(frame.lanes.iloc[0])} lanes, Q(start) = {INITIAL_QUEUE_VEH:.1f} veh")

    want = expected[expected["link_id"] == link_id].sort_values("t_min").reset_index(drop=True)
    worst = 0.0
    for column in COMPARED:
        difference = float(np.max(np.abs(result[column] - want[column].to_numpy(float))))
        worst = max(worst, difference)
        status = "ok" if difference <= TOLERANCE else "MISMATCH"
        print(f"    {column:<20} max |computed - published| = {difference:.3e}  {status}")

    peak = int(np.argmax(result["queue_model_veh"]))
    window = range(max(0, peak - show_rows // 2), min(len(frame), peak + show_rows // 2 + 1))
    print(f"\n    around the queue peak ({hhmm(int(frame.t_min[peak]))}):")
    print(f"    {'time':>6} {'period':>7} {'lambda':>9} {'mu':>9} {'out':>9} "
          f"{'Q':>8} {'TT_min':>8} {'v_model':>8} {'v_obs':>8}")
    for i in window:
        print(f"    {hhmm(int(frame.t_min[i])):>6} {frame.anchor_period[i]:>7} "
              f"{frame.lambda_anchored_vph[i]:>9.1f} {frame.mu_vph[i]:>9.1f} "
              f"{result['outflow_vph'][i]:>9.1f} {result['queue_model_veh'][i]:>8.1f} "
              f"{result['travel_time_h'][i] * 60:>8.2f} "
              f"{result['speed_model_mph'][i]:>8.2f} {frame.speed_mph[i]:>8.2f}")
    print(f"\n    queue left at the end of the run: {result['final_queue_veh']:.1f} veh")
    return worst


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--rows", type=int, default=8,
                        help="intervals to print either side of the queue peak")
    args = parser.parse_args()

    expected = pd.read_csv(HERE / "data/expected_output.csv")
    print("NVTA single-link queue kernel: lambda, mu -> Q, travel time, speed\n")

    worst = 0.0
    for label, filename in CASES:
        print(f"{label}")
        worst = max(worst, run_case(HERE / "data" / filename, expected, args.rows))
        print()

    if worst <= TOLERANCE:
        print(f"All values reproduce the published output "
              f"(worst difference {worst:.3e}, tolerance {TOLERANCE:.0e}).")
        return 0
    print(f"FAILED: worst difference {worst:.3e} exceeds {TOLERANCE:.0e}.")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
