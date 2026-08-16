"""Free-flow speed for the four corridors, computed from the TMC readings directly.

The free-flow speed sets the cut-off at 0.70 v_f, which decides which bins are
congested, which sets D, the episode extent, and the queue. The plan records it
as the choice that dominates everything downstream, so it is worth deriving
rather than accepting.

Five independent routes are compared, four from the observations and one from
INRIX itself:

  p95 per TMC           each segment's own 95th percentile
  p95 per corridor      one value for the whole corridor-direction
  night median          median speed 00:00-05:00, when nothing is queueing
  observed maximum      the highest speed ever recorded on the segment
  INRIX reference       the `reference_speed` field, INRIX's own free-flow value

They disagree in ways that matter. The observed maximum is the hard ceiling: a
free-flow speed above it is impossible, and the assignment's flat 75 mph on I-66
breaks that test on links whose highest speed all day is 55.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SHARED = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\link-queue-simulation"
              r"\link-queue-simulation")
CORRIDORS = ["I395_NB", "I395_SB", "I66_EB", "I66_WB"]
NIGHT_START, NIGHT_END = 0, 300          # 00:00-05:00


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared", type=Path, default=SHARED)
    parser.add_argument("--corridors", nargs="+", default=CORRIDORS)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frames = []
    for name in args.corridors:
        chunk = pd.read_csv(args.shared / "tmc-15min-speed" / name / "Readings.csv",
                            usecols=["tmc_code", "measurement_tstamp", "speed",
                                     "reference_speed", "historical_average_speed"])
        stamp = pd.to_datetime(chunk["measurement_tstamp"])
        chunk = chunk.assign(corridor=name, weekday=stamp.dt.weekday,
                             t_min=stamp.dt.hour * 60 + stamp.dt.minute)
        frames.append(chunk[chunk["weekday"] < 5].dropna(subset=["speed"]))
    speed = pd.concat(frames, ignore_index=True)

    night = speed[(speed["t_min"] >= NIGHT_START) & (speed["t_min"] < NIGHT_END)]
    per_tmc = speed.groupby(["corridor", "tmc_code"]).agg(
        n=("speed", "size"),
        p85=("speed", lambda s: s.quantile(0.85)),
        p95=("speed", lambda s: s.quantile(0.95)),
        p99=("speed", lambda s: s.quantile(0.99)),
        observed_max=("speed", "max"),
        inrix_reference=("reference_speed", "median"),
    )
    per_tmc["night_median"] = night.groupby(["corridor", "tmc_code"])["speed"].median()
    per_tmc = per_tmc.reset_index()

    # One value per corridor-direction, which is how the reference pipeline does it.
    per_corridor = speed.groupby("corridor")["speed"].quantile(0.95).rename("corridor_p95")
    per_tmc = per_tmc.join(per_corridor, on="corridor")

    # What the assignment assigns, for comparison.
    mapping = pd.read_csv(args.shared / "tmc-matching/canonical_node_pair_tmc-1v1.csv",
                          usecols=["tmc", "link_id", "from_node_id", "to_node_id"])
    performance = pd.read_csv(args.shared / "TAPLite-model-input-output-subset/pm/link_performance.csv",
                              usecols=["link_id", "from_node_id", "to_node_id", "free_speed_mph"])
    assigned = (mapping.merge(performance, on=["link_id", "from_node_id", "to_node_id"])
                .groupby("tmc")["free_speed_mph"].median().rename("assignment_model"))
    per_tmc = per_tmc.join(assigned, on="tmc_code")

    per_tmc["p95_over_observed_max"] = per_tmc["p95"] / per_tmc["observed_max"]
    per_tmc["assignment_over_observed_max"] = per_tmc["assignment_model"] / per_tmc["observed_max"]
    per_tmc.to_csv(args.output_dir / "free_speed_audit_by_tmc.csv", index=False)

    routes = ["p95", "corridor_p95", "night_median", "observed_max", "inrix_reference",
              "assignment_model"]
    table = per_tmc.groupby("corridor")[routes].median().round(2)
    table.insert(0, "tmcs", per_tmc.groupby("corridor").size())

    impossible = per_tmc.groupby("corridor").apply(
        lambda g: pd.Series({
            "assignment_above_observed_max": int((g["assignment_model"] > g["observed_max"]).sum()),
            "p95_above_observed_max": int((g["p95"] > g["observed_max"]).sum()),
        }), include_groups=False)

    report = {
        "step": "free-flow speed audit",
        "weekdays": int(pd.to_datetime(speed["measurement_tstamp"]).dt.date.nunique()),
        "routes": {
            "p95": "95th percentile of that TMC's own weekday observations",
            "corridor_p95": "95th percentile pooled over the whole corridor-direction",
            "night_median": "median speed 00:00-05:00, when nothing is queueing",
            "observed_max": "highest speed ever recorded -- a hard ceiling on any v_f",
            "inrix_reference": "INRIX's own reference_speed field, an independent estimate",
            "assignment_model": "free_speed_mph from the TAPLite link performance table",
        },
        "by_corridor": {c: {k: float(v) for k, v in row.items()}
                        for c, row in table.iterrows()},
        "impossible_values": impossible.to_dict("index"),
        "spread_within_corridor": {
            c: {"p95_min": round(float(g["p95"].min()), 1),
                "p95_max": round(float(g["p95"].max()), 1),
                "p95_range_mph": round(float(g["p95"].max() - g["p95"].min()), 1)}
            for c, g in per_tmc.groupby("corridor")
        },
    }
    (args.output_dir / "free_speed_audit.json").write_text(json.dumps(report, indent=2),
                                                           encoding="utf-8")

    print(f"Free-flow speed, {report['weekdays']} weekdays, computed from the TMC readings\n")
    print(table.to_string())
    print("\nvalues above the highest speed ever observed on the segment (impossible):")
    print(impossible.to_string())
    print("\nspread of the per-TMC p95 within each corridor:")
    for c, s in report["spread_within_corridor"].items():
        print(f"  {c:<9} {s['p95_min']:>5.1f} to {s['p95_max']:>5.1f} mph  "
              f"(range {s['p95_range_mph']:.1f})")
    print(f"\nWrote {args.output_dir / 'free_speed_audit_by_tmc.csv'}")


if __name__ == "__main__":
    main()
