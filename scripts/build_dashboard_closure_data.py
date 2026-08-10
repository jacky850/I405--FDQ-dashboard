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
                        observedFlow=("flow_observed_vehph", "mean")))
        profile = profile.sort_values("time")
        out.append({"key": key, "rows": profile.to_dict(orient="records")})
    args.output.write_text("window.CLOSURE_RECONSTRUCTION_DATA = " + json.dumps(out, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(f"Wrote {args.output}")


if __name__ == "__main__":
    main()
