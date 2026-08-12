"""Build the static JavaScript payload for the NVTA speed-only queue dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    series = pd.read_csv(args.input_dir / "full_day_queue_5min.csv")
    envelope = pd.read_csv(args.input_dir / "queue_envelope.csv")
    sweep = pd.read_csv(args.input_dir / "branch_a_capacity_sweep.csv")
    episodes = pd.read_csv(args.input_dir / "speed_episodes.csv")
    summary = json.loads((args.input_dir / "queue_summary.json").read_text(encoding="utf-8"))
    gates = json.loads((args.input_dir / "gate_report.json").read_text(encoding="utf-8"))
    link = json.loads((args.data_dir / "link.json").read_text(encoding="utf-8"))

    merged = series.merge(envelope, on="clock_min", how="left")
    rows = [
        {
            "clock": int(row["clock_min"]),
            "time": row["wall_clock"],
            "period": row["period"],
            "speedRaw": round(float(row["speed_raw_mph"]), 2),
            "speed": round(float(row["speed_mph"]), 2),
            "queued": bool(row["queued_regime"]),
            "mu": round(float(row["mu_vph"]), 1),
            "lambdaB": round(float(row["lambda_b_vph"]), 1),
            "queue": round(float(row["queue_b_recurrence_veh"]), 2),
            "queueMeasured": round(float(row["queue_b_measurement_veh"]), 2),
            "queueLow": round(float(row["queue_min_veh"]), 2),
            "queueHigh": round(float(row["queue_max_veh"]), 2),
            "queueA": round(float(row["queue_a_veh"]), 2),
        }
        for _, row in merged.iterrows()
    ]

    episode_rows = [
        {
            "id": row["episode_id"],
            "t0": row["t0_la"],
            "t2": row["T2_la"],
            "t3": row["t3_la"],
            "P": round(float(row["P_h"]), 2),
            "vT2": round(float(row["vT2_robust_mph"]), 1),
            "asymmetry": round(float(row["asymmetry_ratio"]), 2),
            "period": row["T2_period"],
        }
        for _, row in episodes.iterrows()
    ]

    payload = {
        "link": {
            "tmc": link["tmc"],
            "netLinkId": link["net_link_id"],
            "corridor": link["corridor"],
            "county": link["county"],
            "lengthMi": link["length_mi"],
            "lanes": link["lanes"],
            "date": gates["date"],
        },
        "summary": summary,
        "gates": gates,
        "episodes": episode_rows,
        "series": rows,
        "sweep": sweep.to_dict("records"),
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "window.NVTA_FULL_DAY = "
        + json.dumps(payload, separators=(",", ":"), allow_nan=False)
        + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} ({len(rows)} five-minute bins)")


if __name__ == "__main__":
    main()
