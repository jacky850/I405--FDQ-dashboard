"""Build the static JavaScript payload for the one-link full-day dashboard."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    frame = pd.read_csv(args.input_dir / "full_day_timeseries_5min.csv")
    summary = json.loads((args.input_dir / "summary.json").read_text(encoding="utf-8"))
    episodes = pd.read_csv(args.input_dir / "congestion_episodes.csv").to_dict("records")
    timestamps = pd.to_datetime(frame["timestamp_la"])

    rows = []
    for i, row in frame.iterrows():
        rows.append(
            {
                "minute": int(timestamps.iloc[i].hour * 60 + timestamps.iloc[i].minute),
                "time": timestamps.iloc[i].strftime("%H:%M"),
                "period": row["period"],
                "episode": int(row["episode_id"]),
                "speed": round(float(row["smoothed_speed_mph"]), 3),
                "lambda_ref": round(float(row["count_reference_lambda_vph"]), 3),
                "discharge": round(float(row["observed_discharge_vph"]), 3),
                "queue_ref": round(float(row["count_reference_queue_veh"]), 3),
                "queue_speed_diagnostic": round(
                    float(row["speed_delay_diagnostic_queue_veh"]), 3
                ),
            }
        )

    payload = {"summary": summary, "episodes": episodes, "series": rows}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(
        "window.FULL_DAY_RESIDUAL = "
        + json.dumps(payload, separators=(",", ":"), allow_nan=False)
        + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {args.output} ({len(rows)} five-minute bins)")


if __name__ == "__main__":
    main()
