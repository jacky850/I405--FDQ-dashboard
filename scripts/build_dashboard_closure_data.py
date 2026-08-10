"""Build compact browser data for the holdout closure speed comparison."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]


def main() -> None:
    p = argparse.ArgumentParser()
    p.add_argument("--input", type=Path, default=ROOT / "outputs/i405_closure_holdout_direct4/single_link_closure_holdout_timeseries.csv")
    p.add_argument("--output", type=Path, default=ROOT / "dashboard/closure_reconstruction_data.js")
    args = p.parse_args()
    df = pd.read_csv(args.input)
    df["time"] = df["timestamp_la"].str[11:16]
    out = []
    for key, group in df.groupby("key", sort=True):
        profile = (group.groupby("time", as_index=False)
                   .agg(observedSpeed=("speed_observed_mph", "mean"),
                        reconstructedSpeed=("speed_reconstructed_mph", "mean"),
                        inferredFlow=("flow_inferred_vehph", "mean"),
                        observedFlow=("flow_observed_vehph", "mean"),
                        lambdaFlow=("lambda_speed_vehph", "mean"),
                        muFlow=("mu_vehph", "mean"),
                        queue=("queue_end_veh", "mean")))
        profile = profile.sort_values("time")
        out.append({"key": key, "rows": profile.to_dict(orient="records")})
    args.output.write_text("window.CLOSURE_RECONSTRUCTION_DATA = " + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")

    summary_path = args.input.parent / "single_link_closure_holdout_summary.csv"
    summary = pd.read_csv(summary_path)
    summary["t2Time"] = summary["t2_time_of_day"].astype(str).str[11:16]
    summary_out = (summary.groupby(["key", "period"], as_index=False)
                   .agg(observedVolume=("observed_volume_veh", "mean"),
                        inferredVolume=("inferred_volume_veh", "mean"),
                        volumeErrorPct=("volume_error_pct", "mean"),
                        flowMae=("flow_mae_vehph", "mean"),
                        flowRmse=("flow_rmse_vehph", "mean"),
                        speedMae=("speed_mae_mph", "mean"),
                        speedR2=("speed_r2", "mean"),
                        durationH=("congestion_duration_h", "mean"),
                        muTrain=("mu_train_vehph", "mean"),
                        t2Time=("t2Time", "first")))
    summary_js = summary_out.to_dict(orient="records")
    holdout_path = args.output.parent.parent / "dashboard" / "closure_holdout_data.js"
    holdout_path.write_text("window.CLOSURE_HOLDOUT_DATA = " + json.dumps(summary_js, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {holdout_path}")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
