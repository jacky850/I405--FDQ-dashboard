"""D and V against measured counts across ten PeMS corridor-directions.

The first D-against-counts check had 26 AM episodes and only 4 in PM. The cause
was direction, not luck: every link available was I-405 **southbound**, which is
the Los Angeles AM commute. Its PM median speed is 66-72 mph on all 18 links, so
there was no PM congestion there to score against.

The five-corridor benchmark package carries ten corridor-directions -- both ways
on I-405, I-5, I-10, I-210 -- as daily 5-minute parquet, with lanes, free speed
and capacity in each corridor's ``network/links.csv``. That gives PM a sample.

Method is unchanged from the I-405 check so the numbers stay comparable:

  * average-weekday profile per link, weekdays only, ``is_observed == 1``
    so nothing imputed enters a comparison against measurement;
  * S3 with the standard exponent ``m = 4``, capacity from the 99.5th percentile
    of observed flow and free speed from the 95th percentile of observed speed;
  * congestion is a contiguous run below ``0.70 * v_f`` lasting at least
    ``MIN_EPISODE_H``;
  * D sums the congested bins, V sums the period.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PACKAGE = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
               r"\I210E_corridor_data_package\multicorridor_2026_pilot"
               r"\trafficflowbench_five_corridors\data_public\kaggle_release\corridors")
KM_TO_MI = 0.621371192237334
LA = "America/Los_Angeles"
PERIODS = {"AM": (360, 540), "MD": (540, 900), "PM": (900, 1140), "NT": (1140, 1800)}
CUTOFF_RATIO, S3_M, MIN_EPISODE_H, STEP_H = 0.70, 4.0, 0.5, 5.0 / 60.0
COLUMNS = ["date", "timestamp", "link_id", "speed_kmh", "flow_vph", "is_observed", "is_missing"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--package", type=Path, default=PACKAGE)
    parser.add_argument("--corridors", nargs="*", default=None,
                        help="default: every corridor directory in the package")
    parser.add_argument("--min-observations", type=int, default=10,
                        help="weekday observations a link-bin needs to enter the profile")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/pems_pm_corridors")
    return parser.parse_args()


def average_weekday(corridor_dir: Path, min_observations: int) -> pd.DataFrame:
    """Per-link, per-5-minute weekday mean of observed speed (mph) and flow."""
    files = sorted((corridor_dir / "train" / "mainline_states").rglob("*.parquet"))
    totals = None
    for path in files:
        chunk = pd.read_parquet(path, columns=COLUMNS)
        chunk = chunk[(chunk["is_observed"] == 1) & (chunk["is_missing"] == 0)]
        chunk = chunk.dropna(subset=["speed_kmh", "flow_vph"])
        if chunk.empty:
            continue
        # The timestamps carry a "Z" but are already local: each file's stamps run
        # 00:00-23:55 of its own ``date``. Converting them as UTC shifts the profile
        # seven hours and moves the PM peak into the morning, so the suffix is
        # dropped rather than honoured.
        stamp = pd.to_datetime(chunk["timestamp"].str.slice(0, 19), format="ISO8601")
        chunk = chunk.assign(minute=stamp.dt.hour * 60 + stamp.dt.minute,
                             weekday=pd.to_datetime(chunk["date"]).dt.weekday)
        chunk = chunk[chunk["weekday"] < 5]
        if chunk.empty:
            continue
        part = (chunk.groupby(["link_id", "minute"])
                .agg(speed_sum=("speed_kmh", "sum"), flow_sum=("flow_vph", "sum"),
                     n=("flow_vph", "size")))
        totals = part if totals is None else totals.add(part, fill_value=0)
    if totals is None:
        return pd.DataFrame()
    out = totals.reset_index()
    out = out[out["n"] >= min_observations]
    out["speed_mph"] = out["speed_sum"] / out["n"] * KM_TO_MI
    out["flow_vph"] = out["flow_sum"] / out["n"]
    return out[["link_id", "minute", "speed_mph", "flow_vph", "n"]]


def s3_flow(speed: np.ndarray, free_speed: float, capacity: float) -> np.ndarray:
    speed_at_capacity = free_speed * 2.0 ** (-2.0 / S3_M)
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    return np.minimum(k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M) * v,
                      capacity)


def sustained_below(below: np.ndarray, min_bins: int) -> np.ndarray:
    keep = np.zeros_like(below, dtype=bool)
    start = None
    for i, flag in enumerate(np.append(below, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_bins:
                keep[start:i] = True
            start = None
    return keep


def period_of(minute: int) -> str:
    for name, (start, end) in PERIODS.items():
        if (start <= minute < end) if end <= 1440 else (minute >= start or minute < end - 1440):
            return name
    return "NT"


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    corridors = args.corridors or sorted(d.name for d in args.package.iterdir()
                                         if d.is_dir() and (d / "network").exists())
    min_bins = int(round(MIN_EPISODE_H / STEP_H))

    profiles, rows = [], []
    for name in corridors:
        profile = average_weekday(args.package / name, args.min_observations)
        if profile.empty:
            print(f"  {name:<12} no usable observations")
            continue
        profile.insert(0, "corridor", name)
        profiles.append(profile)

        for link_id, g in profile.groupby("link_id"):
            g = g.sort_values("minute")
            speed = g["speed_mph"].to_numpy(float)
            flow = g["flow_vph"].to_numpy(float)
            if len(g) < 200 or flow.max() <= 0:
                continue
            capacity = float(np.quantile(flow, 0.995))
            free_speed = float(np.quantile(speed, 0.95))
            if not free_speed > 0 or capacity <= 0:
                continue
            q_hat = s3_flow(speed, free_speed, capacity)
            below = sustained_below(speed < CUTOFF_RATIO * free_speed, min_bins)
            period = np.array([period_of(m) for m in g["minute"]])
            for p in PERIODS:
                k = period == p
                if not k.any() or flow[k].sum() <= 0:
                    continue
                rows.append({
                    "corridor": name, "link_id": link_id, "period": p,
                    "bins": int(k.sum()), "bins_below_cutoff": int((k & below).sum()),
                    "free_speed_mph": free_speed, "capacity_vph": capacity,
                    "D_counts": float(flow[k & below].sum() * STEP_H),
                    "D_speed": float(q_hat[k & below].sum() * STEP_H),
                    "V_counts": float(flow[k].sum() * STEP_H),
                    "V_speed": float(q_hat[k].sum() * STEP_H),
                })
        done = pd.DataFrame(rows)
        done = done[done["corridor"] == name]
        print(f"  {name:<12} {profile['link_id'].nunique():>4} links, "
              f"PM episodes: {int(((done['period'] == 'PM') & (done['bins_below_cutoff'] > 0)).sum()):>4}",
              flush=True)

    pd.concat(profiles, ignore_index=True).to_csv(
        args.output_dir / "pems_average_weekday_5min.csv.gz", index=False, compression="gzip")
    frame = pd.DataFrame(rows)
    frame["V_err"] = (frame["V_speed"] - frame["V_counts"]) / frame["V_counts"] * 100
    congested = frame["bins_below_cutoff"] > 0
    frame.loc[congested, "D_err"] = ((frame.loc[congested, "D_speed"] - frame.loc[congested, "D_counts"])
                                     / frame.loc[congested, "D_counts"] * 100)
    frame.to_csv(args.output_dir / "d_v_vs_counts_by_link.csv", index=False)

    def score(s: pd.Series) -> dict:
        s = s.dropna()
        return {"n": int(len(s)), "mape": round(float(s.abs().mean()), 1),
                "bias": round(float(s.median()), 1)} if len(s) else {"n": 0}

    summary = {"corridors": corridors,
               "by_period": {p: {"D": score(frame.loc[frame["period"] == p, "D_err"]),
                                 "V": score(frame.loc[frame["period"] == p, "V_err"])}
                             for p in PERIODS},
               "PM_by_corridor": {c: score(g.loc[g["period"] == "PM", "D_err"])
                                  for c, g in frame.groupby("corridor")}}
    (args.output_dir / "d_v_vs_counts.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"\n{'period':<8} {'D n':>5} {'D MAPE':>8} {'D bias':>8} | {'V n':>5} {'V MAPE':>8} {'V bias':>8}")
    for p in PERIODS:
        d, v = summary["by_period"][p]["D"], summary["by_period"][p]["V"]
        print(f"{p:<8} {d['n']:>5} {d.get('mape', float('nan')):>7}% {d.get('bias', float('nan')):>+7}% "
              f"| {v['n']:>5} {v.get('mape', float('nan')):>7}% {v.get('bias', float('nan')):>+7}%")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
