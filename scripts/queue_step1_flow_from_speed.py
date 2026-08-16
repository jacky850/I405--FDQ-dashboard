"""Step 1 of the single-link queue plan: flow from speed, on the TAPLite link basis.

    q(t) = S3(v(t)),  m = 4

Everything is read from the shared `link-queue-simulation` package, which is the
authoritative copy:

  observed speed    tmc-15min-speed/<CORRIDOR>/Readings.csv
  link attributes   TAPLite-model-input-output-subset/pm/link_performance.csv
  join key          tmc-matching/canonical_node_pair_tmc-1v1.csv

Two things differ from what the plan assumed, both settled in step 0.

**15-minute bins over 23 weekdays, not 5-minute over 5.** Step 2 has to estimate
the pre-breakdown peak on each individual day and take the median of those, so
the number of days matters more than the resolution within a day.

**One TMC covers several TAPLite links, not the other way round.** The earlier
link definition had up to four TMCs on one network link and needed a
length-weighted harmonic mean of their speeds. Here 21 TMCs map onto 31 links,
so the observed speed is broadcast rather than combined -- and the links sharing
a TMC also share one observation, which is carried as `tmcs_links_sharing` so
that later steps do not treat them as independent evidence.

The free-flow speed is the one input with two defensible sources, and the plan
records it as the choice that dominates everything downstream, so both are
carried: the model's `free_speed_mph` and the 95th percentile of each TMC's own
observed profile. `q` is produced against each.
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

S3_M = 4.0
CUTOFF_RATIO = 0.70
DT_MIN = 15
PERIOD_WINDOWS = [("AM", 360, 540), ("MD", 540, 900), ("PM", 900, 1140), ("NT", 1140, 1800)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--shared", type=Path, default=SHARED)
    parser.add_argument("--corridors", nargs="+", default=CORRIDORS)
    parser.add_argument("--period", default="pm", choices=["am", "md", "pm"])
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def s3_flow(speed: np.ndarray, free_speed: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    """Flow implied by speed, veh/h/lane, on the congested branch of S3.

    ``v(k) = v_f / [1 + (k/k_c)^m]^(2/m)`` inverts to
    ``k(v) = k_c [ (v_f/v)^(m/2) - 1 ]^(1/m)``, and ``q = k v``.
    """
    speed_at_capacity = free_speed * 2.0 ** (-2.0 / S3_M)
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    return np.minimum(
        k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M) * v,
        capacity)


def period_of(minute: int) -> str:
    for name, start, end in PERIOD_WINDOWS:
        if start <= minute < end if end <= 1440 else (minute >= start or minute < end - 1440):
            return name
    return "NT"


def read_speed(shared: Path, corridors: list[str]) -> pd.DataFrame:
    """Observed TMC speed, weekdays only, on a minute-of-day clock."""
    frames = []
    for name in corridors:
        path = shared / "tmc-15min-speed" / name / "Readings.csv"
        chunk = pd.read_csv(path, usecols=["tmc_code", "measurement_tstamp", "speed"])
        stamp = pd.to_datetime(chunk["measurement_tstamp"])
        chunk = chunk.assign(corridor=name, date=stamp.dt.date,
                             weekday=stamp.dt.weekday,
                             t_min=stamp.dt.hour * 60 + stamp.dt.minute)
        frames.append(chunk[chunk["weekday"] < 5].drop(columns=["measurement_tstamp", "weekday"]))
    return pd.concat(frames, ignore_index=True).dropna(subset=["speed"])


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    speed = read_speed(args.shared, args.corridors)

    mapping = pd.read_csv(args.shared / "tmc-matching/canonical_node_pair_tmc-1v1.csv",
                          usecols=["tmc", "road", "direction", "link_id", "from_node_id",
                                   "to_node_id", "length_mi", "lanes", "match_status"])
    performance = pd.read_csv(
        args.shared / f"TAPLite-model-input-output-subset/{args.period}/link_performance.csv",
        usecols=["link_id", "from_node_id", "to_node_id", "volume", "lane_capacity",
                 "link_capacity", "free_speed_mph", "cutoff_speed_mph", "D", "doc",
                 "P", "t0", "t2", "t3", "vt2_mph", "mu", "qvdf_profile_status"])

    links = (mapping.merge(performance, on=["link_id", "from_node_id", "to_node_id"], how="inner")
             .query("qvdf_profile_status == 'generated_model'"))
    links = links[links["tmc"].isin(set(speed["tmc_code"]))].copy()
    links["links_sharing_this_tmc"] = links.groupby("tmc")["link_id"].transform("size")

    # The observed free-flow speed is a property of the TMC, since that is what
    # was measured; it is then broadcast with the speed onto each link.
    observed_free = speed.groupby("tmc_code")["speed"].quantile(0.95).rename("free_speed_observed_mph")

    # Average weekday profile per TMC, and the per-day series step 2 needs.
    daily = (speed.groupby(["corridor", "tmc_code", "date", "t_min"], as_index=False)["speed"].mean())
    average = (daily.groupby(["corridor", "tmc_code", "t_min"], as_index=False)
               .agg(speed=("speed", "mean"), days=("speed", "size")))

    attributes = links[["tmc", "link_id", "from_node_id", "to_node_id", "road", "direction",
                        "length_mi", "lanes", "match_status", "links_sharing_this_tmc",
                        "volume", "lane_capacity", "link_capacity", "free_speed_mph",
                        "cutoff_speed_mph", "D", "doc", "P", "t0", "t2", "t3", "vt2_mph", "mu"]]
    attributes = attributes.join(observed_free, on="tmc")

    def attach(frame: pd.DataFrame) -> pd.DataFrame:
        out = frame.merge(attributes, left_on="tmc_code", right_on="tmc", how="inner")
        for source, suffix in [("free_speed_mph", "model"), ("free_speed_observed_mph", "observed")]:
            free = out[source].to_numpy(float)
            out[f"cutoff_{suffix}_mph"] = free * CUTOFF_RATIO
            out[f"q_{suffix}_vphpl"] = s3_flow(out["speed"].to_numpy(float), free,
                                               out["lane_capacity"].to_numpy(float))
            out[f"below_cutoff_{suffix}"] = out["speed"].to_numpy(float) < free * CUTOFF_RATIO
        out["period"] = [period_of(m) for m in out["t_min"]]
        return out.drop(columns=["tmc"])

    average_out = attach(average)
    daily_out = attach(daily)

    average_out.to_csv(args.output_dir / "step1_flow_average_weekday_15min.csv", index=False)
    daily_out.to_csv(args.output_dir / "step1_flow_by_day_15min.csv.gz", index=False,
                     compression="gzip")

    disagreement = (attributes["free_speed_observed_mph"] - attributes["free_speed_mph"])
    report = {
        "step": "1. Flow from speed, q(t) = S3(v(t)), m = 4",
        "source": "shared link-queue-simulation package",
        "period_table": args.period,
        "resolution_min": DT_MIN,
        "weekdays": int(speed["date"].nunique()),
        "date_range": [str(speed["date"].min()), str(speed["date"].max())],
        "tmcs_with_speed": int(speed["tmc_code"].nunique()),
        "links": int(len(attributes)),
        "links_by_corridor": average_out.groupby("corridor")["link_id"].nunique().to_dict(),
        "match_status": attributes["match_status"].value_counts().to_dict(),
        "links_sharing_one_tmc": {
            "max": int(attributes["links_sharing_this_tmc"].max()),
            "median": float(attributes["links_sharing_this_tmc"].median()),
            "links_not_uniquely_observed": int((attributes["links_sharing_this_tmc"] > 1).sum()),
        },
        "free_speed_sources": {
            "model_median_mph": round(float(attributes["free_speed_mph"].median()), 2),
            "observed_p95_median_mph": round(float(attributes["free_speed_observed_mph"].median()), 2),
            "median_difference_mph": round(float(disagreement.median()), 2),
            "mae_mph": round(float(disagreement.abs().mean()), 2),
            "note": "Carried side by side. The plan records the free-speed source as the choice "
                    "that dominates everything downstream, so it stays a column rather than a "
                    "constant until step 9 measures what it is worth.",
        },
        "capacity": {
            "lane_capacity_median_vphpl": round(float(attributes["lane_capacity"].median()), 1),
            "note": "From the assignment, replacing the 2200/1800 constants used earlier.",
        },
        "model_t2_is_pinned": {
            "fraction_at_the_period_midpoint": round(float((attributes["t2"].round(6) == 17.0).mean()), 4),
            "note": "The model puts T2 at 17:00, the midpoint of the 15:00-19:00 PM window, on "
                    "most links. Observed T2 is what step 8 has to compare it against.",
        },
    }
    (args.output_dir / "step1_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Step 1 -- flow from speed, {args.period.upper()} link table\n")
    print(f"  {report['weekdays']} weekdays {report['date_range'][0]} to {report['date_range'][1]}, "
          f"{DT_MIN}-minute bins")
    print(f"  {report['tmcs_with_speed']} TMCs with speed -> {report['links']} links")
    for corridor, n in report["links_by_corridor"].items():
        print(f"      {corridor:<10} {n:>4} links")
    print(f"\n  links sharing a TMC with another link: "
          f"{report['links_sharing_one_tmc']['links_not_uniquely_observed']} of {report['links']} "
          f"(max {report['links_sharing_one_tmc']['max']} on one TMC)")
    f = report["free_speed_sources"]
    print(f"\n  free speed   model {f['model_median_mph']:.1f} mph vs observed p95 "
          f"{f['observed_p95_median_mph']:.1f} mph, MAE {f['mae_mph']:.2f} mph")
    print(f"  lane capacity {report['capacity']['lane_capacity_median_vphpl']:.0f} vphpl (median)")
    print(f"  model T2 pinned at the period midpoint on "
          f"{report['model_t2_is_pinned']['fraction_at_the_period_midpoint'] * 100:.0f}% of links")
    for label, frame in [("average weekday", average_out), ("by day", daily_out)]:
        below = frame["below_cutoff_model"].mean() * 100
        print(f"\n  {label:<16} {len(frame):>8,} rows, {below:>5.1f}% of bins below the model cut-off")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
