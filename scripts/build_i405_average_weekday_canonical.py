"""Build average-weekday I-405 profiles and canonical speed episodes."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.episodes import EpisodeDetectionConfig, detect_speed_episodes  # noqa: E402
from fdqbench.time_utils import parse_pems_local_wall_clock  # noqa: E402


TARGETS = [
    "L405S-012", "L405S-018", "L405S-028", "L405S-030",
    "L405S-058", "L405S-098", "L405S-115",
]
KM_TO_MI = 0.621371192237334
LA = "America/Los_Angeles"
ANCHOR = pd.Timestamp("2000-01-02", tz=LA)
DEFAULT_RAW = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\pems_downloads_d12\proceed\I405\S\train_detector_states.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", type=Path, default=DEFAULT_RAW)
    parser.add_argument(
        "--daily-episode-file", type=Path,
        default=ROOT / "outputs/i405_speed_only_episodes_direct7/speed_only_asymmetric_episodes.csv",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/i405_average_weekday_canonical_direct7",
    )
    return parser.parse_args()


def read_link_observations(path: Path) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    cols = ["timestamp", "station_id", "link_id", "speed", "flow", "is_observed", "is_missing"]
    for chunk in pd.read_csv(path, usecols=cols, dtype={"link_id": str}, chunksize=500_000):
        chunk = chunk[
            chunk["link_id"].isin(TARGETS)
            & chunk["is_observed"].astype(int).eq(1)
            & chunk["is_missing"].astype(int).eq(0)
            & chunk["timestamp"].astype(str).str[:10].between("2025-06-02", "2025-06-06")
        ].copy()
        if chunk.empty:
            continue
        chunk["timestamp_la"] = parse_pems_local_wall_clock(chunk["timestamp"])
        chunk["local_date"] = chunk["timestamp_la"].dt.strftime("%Y-%m-%d")
        parts.append(chunk[["link_id", "station_id", "timestamp_la", "local_date", "speed", "flow"]])
    raw = pd.concat(parts, ignore_index=True)
    raw["speed_mph"] = pd.to_numeric(raw["speed"], errors="coerce") * KM_TO_MI
    raw["flow_veh_h"] = pd.to_numeric(raw["flow"], errors="coerce")
    # Multiple stations mapped to one link are parallel measurements of the
    # same network link. Collapse them before averaging across weekdays.
    return (
        raw.groupby(["link_id", "timestamp_la", "local_date"], as_index=False)
        .agg(
            speed_mph=("speed_mph", "mean"),
            flow_veh_h=("flow_veh_h", "mean"),
            mapped_station_count=("station_id", "nunique"),
        )
        .sort_values(["link_id", "timestamp_la"])
    )


def average_weekday(observations: pd.DataFrame) -> pd.DataFrame:
    data = observations.copy()
    data["minute_of_day"] = data["timestamp_la"].dt.hour * 60 + data["timestamp_la"].dt.minute
    profile = (
        data.groupby(["link_id", "minute_of_day"], as_index=False)
        .agg(
            average_speed_mph=("speed_mph", "mean"),
            speed_std_across_days_mph=("speed_mph", "std"),
            average_observed_flow_veh_h=("flow_veh_h", "mean"),
            flow_std_across_days_veh_h=("flow_veh_h", "std"),
            contributing_weekdays=("local_date", "nunique"),
            max_mapped_station_count=("mapped_station_count", "max"),
        )
        .sort_values(["link_id", "minute_of_day"])
    )
    profile["clock_la"] = profile["minute_of_day"].map(
        lambda minute: f"{int(minute)//60:02d}:{int(minute)%60:02d}"
    )
    return profile


def tile_profile(group: pd.DataFrame) -> pd.DataFrame:
    frames = []
    for offset in (-1, 0, 1):
        frame = group.copy()
        frame["timestamp_la"] = ANCHOR + pd.Timedelta(days=offset) + pd.to_timedelta(
            frame["minute_of_day"], unit="m"
        )
        frames.append(frame)
    return pd.concat(frames, ignore_index=True).sort_values("timestamp_la")


def canonical_clock(timestamp: pd.Timestamp) -> str:
    delta_min = int(round((timestamp - ANCHOR).total_seconds() / 60))
    day_offset, minute = divmod(delta_min, 1440)
    prefix = "" if day_offset == 0 else f"D{day_offset:+d} "
    return f"{prefix}{minute // 60:02d}:{minute % 60:02d}"


def detect_canonical(profile: pd.DataFrame) -> pd.DataFrame:
    frames: list[pd.DataFrame] = []
    cfg = EpisodeDetectionConfig()
    for link_id, group in profile.groupby("link_id", sort=True):
        tiled = tile_profile(group)
        free_speed = float(group["average_speed_mph"].quantile(0.95))
        episodes, _ = detect_speed_episodes(
            tiled["timestamp_la"], tiled["average_speed_mph"], free_speed, cfg
        )
        if episodes.empty:
            continue
        episodes["T2_timestamp"] = pd.to_datetime(episodes["T2_la"], utc=True).dt.tz_convert(LA)
        episodes = episodes[episodes["T2_timestamp"].dt.date == ANCHOR.date()].copy()
        if episodes.empty:
            continue
        episodes.insert(0, "link_id", link_id)
        episodes["episode_id"] = [f"{link_id}-AVG-E{i}" for i in range(1, len(episodes) + 1)]
        for source, target in [("t0_la", "t0_clock_la"), ("T2_la", "T2_clock_la"), ("t3_la", "t3_clock_la")]:
            timestamps = pd.to_datetime(episodes[source], utc=True).dt.tz_convert(LA)
            episodes[target] = timestamps.map(canonical_clock)
        episodes["canonical_profile"] = "Mon-Fri mean at each 5-min LA-time bin"
        frames.append(episodes.drop(columns="T2_timestamp"))
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def map_daily_to_anchor(row: pd.Series) -> tuple[pd.Timestamp, pd.Timestamp, pd.Timestamp]:
    t0, t2, t3 = map(pd.Timestamp, [row["t0_la"], row["T2_la"], row["t3_la"]])
    anchor_t2 = ANCHOR + pd.Timedelta(hours=t2.hour, minutes=t2.minute, seconds=t2.second)
    return anchor_t2 + (t0 - t2), anchor_t2, anchor_t2 + (t3 - t2)


def iou(a0: pd.Timestamp, a3: pd.Timestamp, b0: pd.Timestamp, b3: pd.Timestamp) -> float:
    overlap = max(0.0, (min(a3, b3) - max(a0, b0)).total_seconds())
    union = (max(a3, b3) - min(a0, b0)).total_seconds()
    return overlap / union if union > 0 else 0.0


def compare_daily(canonical: pd.DataFrame, daily_file: Path) -> pd.DataFrame:
    daily = pd.read_csv(daily_file)
    for column in ["t0_la", "T2_la", "t3_la"]:
        daily[column] = pd.to_datetime(daily[column], utc=True, format="mixed").dt.tz_convert(LA)
    rows: list[dict[str, object]] = []
    for _, c in canonical.iterrows():
        c0, c2, c3 = map(pd.Timestamp, [c["t0_la"], c["T2_la"], c["t3_la"]])
        candidates = daily[daily["link_id"].eq(c["link_id"])]
        matches = []
        for date, day in candidates.groupby("local_date"):
            best = None
            for _, d in day.iterrows():
                d0, d2, d3 = map_daily_to_anchor(d)
                score = iou(c0, c3, d0, d3)
                if best is None or score > best[0]:
                    best = (score, d, d0, d2, d3)
            if best and best[0] > 0:
                score, d, d0, d2, d3 = best
                matches.append({
                    "date": date, "iou": score, "P_h": d["P_h"],
                    "dt0": (d0-c0).total_seconds()/60,
                    "dT2": (d2-c2).total_seconds()/60,
                    "dt3": (d3-c3).total_seconds()/60,
                })
        m = pd.DataFrame(matches)
        rows.append({
            "canonical_episode_id": c["episode_id"], "link_id": c["link_id"],
            "canonical_t0_clock_la": c["t0_clock_la"], "canonical_T2_clock_la": c["T2_clock_la"],
            "canonical_t3_clock_la": c["t3_clock_la"], "canonical_P_h": c["P_h"],
            "matched_weekdays": len(m), "weekday_recurrence_rate": len(m) / 5.0,
            "median_daily_iou": m["iou"].median() if len(m) else np.nan,
            "median_daily_P_h": m["P_h"].median() if len(m) else np.nan,
            "median_abs_delta_t0_min": m["dt0"].abs().median() if len(m) else np.nan,
            "median_abs_delta_T2_min": m["dT2"].abs().median() if len(m) else np.nan,
            "median_abs_delta_t3_min": m["dt3"].abs().median() if len(m) else np.nan,
        })
    return pd.DataFrame(rows)


def shade_canonical(ax: plt.Axes, row: pd.Series) -> None:
    t0, t3 = pd.Timestamp(row["t0_la"]), pd.Timestamp(row["t3_la"])
    start = max(t0, ANCHOR); end = min(t3, ANCHOR + pd.Timedelta(days=1))
    if start < end:
        ax.axvspan((start-ANCHOR).total_seconds()/60, (end-ANCHOR).total_seconds()/60, color="#ef4444", alpha=.14)


def plot_profiles(profile: pd.DataFrame, episodes: pd.DataFrame, output_dir: Path) -> None:
    figures = output_dir / "figures"; figures.mkdir(parents=True, exist_ok=True)
    for link_id, group in profile.groupby("link_id", sort=True):
        eps = episodes[episodes["link_id"].eq(link_id)]
        fig, axes = plt.subplots(2, 1, figsize=(12, 6.5), sharex=True, constrained_layout=True)
        axes[0].plot(group["minute_of_day"], group["average_speed_mph"], color="#1456b8", lw=1.7)
        axes[0].fill_between(
            group["minute_of_day"],
            group["average_speed_mph"]-group["speed_std_across_days_mph"],
            group["average_speed_mph"]+group["speed_std_across_days_mph"],
            color="#93c5fd", alpha=.28, label="±1 weekday SD",
        )
        for _, row in eps.iterrows():
            shade_canonical(axes[0], row)
            t2 = pd.Timestamp(row["T2_la"]); axes[0].axvline((t2-ANCHOR).total_seconds()/60, color="#b91c1c", lw=1)
        axes[0].set(ylabel="speed (mph)", title=f"{link_id}: average-weekday speed and canonical episodes")
        axes[0].legend(frameon=False)
        axes[1].plot(group["minute_of_day"], group["average_observed_flow_veh_h"], color="#0f766e", lw=1.7)
        axes[1].fill_between(
            group["minute_of_day"],
            group["average_observed_flow_veh_h"]-group["flow_std_across_days_veh_h"],
            group["average_observed_flow_veh_h"]+group["flow_std_across_days_veh_h"],
            color="#99f6e4", alpha=.25,
        )
        axes[1].set(ylabel="observed flow (veh/h)", xlabel="LA time")
        for ax in axes:
            ax.grid(alpha=.2); ax.set_xlim(0, 1440)
        ticks = [0, 360, 720, 1080, 1440]
        axes[1].set_xticks(ticks, ["00:00", "06:00", "12:00", "18:00", "24:00"])
        fig.savefig(figures / f"{link_id}_average_weekday_canonical.png", dpi=180); plt.close(fig)


def main() -> None:
    args = parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    observations = read_link_observations(args.raw_file)
    profile = average_weekday(observations)
    canonical = detect_canonical(profile)
    daily_comparison = compare_daily(canonical, args.daily_episode_file)
    profile.to_csv(args.output_dir / "average_weekday_speed_flow_5min.csv", index=False)
    canonical.to_csv(args.output_dir / "canonical_average_weekday_episodes.csv", index=False)
    daily_comparison.to_csv(args.output_dir / "canonical_vs_daily_episode_summary.csv", index=False)
    plot_profiles(profile, canonical, args.output_dir)
    summary = {
        "profile": "Monday-Friday mean by link and 5-minute LA-time bin",
        "links": int(profile["link_id"].nunique()),
        "bins_per_link": int(profile.groupby("link_id").size().median()),
        "minimum_contributing_weekdays": int(profile["contributing_weekdays"].min()),
        "canonical_episodes": len(canonical),
        "links_with_canonical_episode": int(canonical["link_id"].nunique()) if len(canonical) else 0,
        "daily_role": "robustness and day-to-day uncertainty; not the primary average-weekday calibration target",
        "station_aggregation": "mean across stations mapped to the same link/timestamp before weekday averaging",
    }
    (args.output_dir / "average_weekday_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
