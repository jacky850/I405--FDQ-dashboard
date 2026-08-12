"""Detect asymmetric I-405 episodes from speed only and audit against PAQ.

The detector consumes only link ID, local date/time, and speed.  Flow-related
columns in the source process table are intentionally not read.  Existing PAQ
objects are used after detection as external spatial/temporal reference only.
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

from fdqbench.episodes import EpisodeDetectionConfig, detect_speed_episodes  # noqa: E402
from fdqbench.time_utils import parse_pems_local_wall_clock  # noqa: E402


TARGETS = [
    "L405S-012",
    "L405S-018",
    "L405S-028",
    "L405S-030",
    "L405S-058",
    "L405S-098",
    "L405S-115",
]
KM_TO_MI = 0.621371192237334
DEFAULT_RAW_SPEED_FILE = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\pems_downloads_d12\proceed\I405\S\train_detector_states.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--speed-file",
        type=Path,
        default=DEFAULT_RAW_SPEED_FILE,
    )
    parser.add_argument(
        "--paq-file",
        type=Path,
        default=ROOT
        / "outputs/i405_s_paq_aware_direct7/i405_s_paq_objects_week_2025-06-02_to_2025-06-06.csv",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/i405_speed_only_episodes_direct7",
    )
    parser.add_argument("--links", nargs="*", default=TARGETS)
    parser.add_argument("--enter-ratio", type=float, default=0.70)
    parser.add_argument("--exit-ratio", type=float, default=0.75)
    parser.add_argument("--persistence-bins", type=int, default=3)
    parser.add_argument("--minimum-duration-min", type=float, default=20.0)
    parser.add_argument("--minimum-depth-mph", type=float, default=3.0)
    return parser.parse_args()


def read_local_speed(path: Path, links: list[str]) -> pd.DataFrame:
    """Read target-link speed and derive the full LA date from UTC timestamp."""

    pieces: list[pd.DataFrame] = []
    usecols = ["timestamp", "link_id", "speed", "is_observed", "is_missing"]
    for chunk in pd.read_csv(path, usecols=usecols, dtype={"link_id": str}, chunksize=500_000):
        chunk = chunk[
            chunk["link_id"].isin(links)
            & chunk["is_observed"].astype(int).eq(1)
            & chunk["is_missing"].astype(int).eq(0)
            & chunk["timestamp"].astype(str).str[:10].between("2025-06-02", "2025-06-06")
        ].copy()
        if chunk.empty:
            continue
        chunk["timestamp_la"] = parse_pems_local_wall_clock(chunk["timestamp"])
        chunk["date"] = chunk["timestamp_la"].dt.strftime("%Y-%m-%d")
        pieces.append(chunk[["link_id", "timestamp_la", "date", "speed"]])
    if not pieces:
        raise ValueError(f"No observed target-link speed rows found in {path}")
    raw = pd.concat(pieces, ignore_index=True)
    return (
        raw.groupby(["link_id", "timestamp_la", "date"], as_index=False)
        .agg(speed_kmh=("speed", "mean"))
        .sort_values(["link_id", "timestamp_la"])
    )


def paq_reference_local(paq: pd.DataFrame) -> pd.DataFrame:
    """Attach Pacific-local timezone to legacy PAQ wall-clock minutes."""

    out = paq.copy()
    local_day = pd.to_datetime(out["date"], errors="raise").dt.tz_localize("America/Los_Angeles")
    out["paq_t0_la"] = local_day + pd.to_timedelta(out["T0_min"], unit="m")
    out["paq_t3_la"] = local_day + pd.to_timedelta(out["T3_min"], unit="m")
    out["paq_P_h"] = (out["paq_t3_la"] - out["paq_t0_la"]).dt.total_seconds() / 3600.0
    return out


def overlap_seconds(a0: pd.Timestamp, a3: pd.Timestamp, b0: pd.Timestamp, b3: pd.Timestamp) -> float:
    return max(0.0, (min(a3, b3) - max(a0, b0)).total_seconds())


def reference_t2(
    process: pd.DataFrame,
    link_id: str,
    t0: pd.Timestamp,
    t3: pd.Timestamp,
) -> tuple[pd.Timestamp | pd.NaT, float]:
    subset = process[
        process["link_id"].eq(link_id)
        & process["timestamp_la"].between(t0, t3, inclusive="both")
    ]
    subset = subset.dropna(subset=["speed_smoothed_mph"])
    if subset.empty:
        return pd.NaT, np.nan
    index = subset["speed_smoothed_mph"].idxmin()
    return pd.Timestamp(subset.loc[index, "timestamp_la"]), float(subset.loc[index, "speed_smoothed_mph"])


def match_paq(
    episodes: pd.DataFrame,
    process: pd.DataFrame,
    paq: pd.DataFrame,
    links: list[str],
) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for link_id in links:
        speed = episodes[episodes["link_id"].eq(link_id)].copy()
        references = paq[
            paq["range_link_ids"].fillna("").str.split(";").map(lambda values: link_id in values)
        ].copy()
        pairs: list[tuple[float, int, int, float]] = []
        for speed_index, speed_row in speed.iterrows():
            s0 = pd.Timestamp(speed_row["t0_la"])
            s3 = pd.Timestamp(speed_row["t3_la"])
            for paq_index, paq_row in references.iterrows():
                p0 = pd.Timestamp(paq_row["paq_t0_la"])
                p3 = pd.Timestamp(paq_row["paq_t3_la"])
                overlap = overlap_seconds(s0, s3, p0, p3)
                if overlap <= 0:
                    continue
                union = (max(s3, p3) - min(s0, p0)).total_seconds()
                pairs.append((overlap / union if union > 0 else 0.0, speed_index, paq_index, overlap))
        matched_speed: set[int] = set()
        matched_paq: set[int] = set()
        for iou, speed_index, paq_index, overlap in sorted(pairs, reverse=True):
            if speed_index in matched_speed or paq_index in matched_paq:
                continue
            matched_speed.add(speed_index)
            matched_paq.add(paq_index)
            speed_row = speed.loc[speed_index]
            paq_row = references.loc[paq_index]
            s0, s2, s3 = map(pd.Timestamp, [speed_row["t0_la"], speed_row["T2_la"], speed_row["t3_la"]])
            p0, p3 = pd.Timestamp(paq_row["paq_t0_la"]), pd.Timestamp(paq_row["paq_t3_la"])
            p2, p2_speed = reference_t2(process, link_id, p0, p3)
            rows.append(
                {
                    "link_id": link_id,
                    "speed_episode_id": speed_row["episode_id"],
                    "paq_object": paq_row["object"],
                    "match_status": "matched",
                    "overlap_iou": iou,
                    "overlap_min": overlap / 60.0,
                    "speed_t0_la": s0.isoformat(),
                    "speed_T2_la": s2.isoformat(),
                    "speed_t3_la": s3.isoformat(),
                    "speed_P_h": float(speed_row["P_h"]),
                    "paq_t0_la": p0.isoformat(),
                    "paq_T2_target_speed_la": p2.isoformat() if pd.notna(p2) else "",
                    "paq_t3_la": p3.isoformat(),
                    "paq_P_h": float(paq_row["paq_P_h"]),
                    "paq_target_vT2_mph": p2_speed,
                    "delta_t0_min": (s0 - p0).total_seconds() / 60.0,
                    "delta_T2_min": (s2 - p2).total_seconds() / 60.0 if pd.notna(p2) else np.nan,
                    "delta_t3_min": (s3 - p3).total_seconds() / 60.0,
                    "delta_P_min": (float(speed_row["P_h"]) - float(paq_row["paq_P_h"])) * 60.0,
                    "paq_xstar_link_id": paq_row["xstar_link_id"],
                    "paq_range_link_ids": paq_row["range_link_ids"],
                }
            )
        for speed_index, speed_row in speed.iterrows():
            if speed_index in matched_speed:
                continue
            rows.append(
                {
                    "link_id": link_id,
                    "speed_episode_id": speed_row["episode_id"],
                    "paq_object": "",
                    "match_status": "speed_only",
                    "speed_t0_la": speed_row["t0_la"],
                    "speed_T2_la": speed_row["T2_la"],
                    "speed_t3_la": speed_row["t3_la"],
                    "speed_P_h": speed_row["P_h"],
                }
            )
        for paq_index, paq_row in references.iterrows():
            if paq_index in matched_paq:
                continue
            p0, p3 = pd.Timestamp(paq_row["paq_t0_la"]), pd.Timestamp(paq_row["paq_t3_la"])
            p2, p2_speed = reference_t2(process, link_id, p0, p3)
            rows.append(
                {
                    "link_id": link_id,
                    "speed_episode_id": "",
                    "paq_object": paq_row["object"],
                    "match_status": "paq_only",
                    "paq_t0_la": p0.isoformat(),
                    "paq_T2_target_speed_la": p2.isoformat() if pd.notna(p2) else "",
                    "paq_t3_la": p3.isoformat(),
                    "paq_P_h": float(paq_row["paq_P_h"]),
                    "paq_target_vT2_mph": p2_speed,
                    "paq_xstar_link_id": paq_row["xstar_link_id"],
                    "paq_range_link_ids": paq_row["range_link_ids"],
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    config = EpisodeDetectionConfig(
        enter_ratio=args.enter_ratio,
        exit_ratio=args.exit_ratio,
        enter_persistence_bins=args.persistence_bins,
        exit_persistence_bins=args.persistence_bins,
        minimum_duration_min=args.minimum_duration_min,
        minimum_depth_mph=args.minimum_depth_mph,
    )
    # Deliberately exclude every flow, demand, service, and queue column.
    speed = read_local_speed(args.speed_file, args.links)
    speed["speed_mph"] = speed["speed_kmh"].astype(float) * KM_TO_MI
    free_speed = speed.groupby("link_id")["speed_mph"].quantile(0.95).to_dict()

    episode_frames: list[pd.DataFrame] = []
    process_frames: list[pd.DataFrame] = []
    day_rows: list[dict[str, object]] = []
    local_dates = sorted(speed["date"].unique())
    for link_id, group in speed.groupby("link_id", sort=True):
        episodes, process = detect_speed_episodes(
            group["timestamp_la"], group["speed_mph"], free_speed[link_id], config
        )
        process["link_id"] = link_id
        process["local_date"] = process["timestamp_la"].dt.strftime("%Y-%m-%d")
        process_frames.append(process)
        if not episodes.empty:
            episodes.insert(0, "local_date", pd.to_datetime(episodes["T2_la"]).dt.strftime("%Y-%m-%d"))
            episodes.insert(0, "link_id", link_id)
            episodes["episode_id"] = [
                f"{link_id}-{date}-E{number}"
                for date, number in zip(
                    episodes["local_date"],
                    episodes.groupby("local_date").cumcount() + 1,
                )
            ]
            episode_count_by_day = episodes.groupby("local_date")["episode_id"].transform("size")
            episodes["multiple_episode_day"] = episode_count_by_day > 1
            episode_frames.append(episodes)
        counts = episodes["local_date"].value_counts().to_dict() if not episodes.empty else {}
        samples_by_day = group.groupby("date")["speed_mph"].count().to_dict()
        for date in local_dates:
            count = int(counts.get(date, 0))
            day_rows.append(
                {
                    "link_id": link_id,
                    "local_date": date,
                    "episode_count": count,
                    "day_status": "episode_detected" if count else "no_congestion_not_identifiable",
                    "free_speed_p95_mph": free_speed[link_id],
                    "input_samples": int(samples_by_day.get(date, 0)),
                }
            )

    episodes = pd.concat(episode_frames, ignore_index=True) if episode_frames else pd.DataFrame()
    process = pd.concat(process_frames, ignore_index=True)
    day_status = pd.DataFrame(day_rows)
    paq = paq_reference_local(pd.read_csv(args.paq_file))
    comparison = match_paq(episodes, process, paq, args.links)

    episode_path = args.output_dir / "speed_only_asymmetric_episodes.csv"
    process_path = args.output_dir / "speed_only_episode_process_5min.csv"
    day_path = args.output_dir / "speed_only_day_status.csv"
    comparison_path = args.output_dir / "speed_only_vs_paq_reference.csv"
    candidate_path = args.output_dir / "qvdf_episode_candidates_strict_v1.csv"
    episodes.to_csv(episode_path, index=False)
    process.to_csv(process_path, index=False)
    day_status.to_csv(day_path, index=False)
    comparison.to_csv(comparison_path, index=False)

    matched = comparison[comparison["match_status"].eq("matched")]
    candidate_match = matched[
        ["speed_episode_id", "paq_object", "overlap_iou", "paq_xstar_link_id"]
    ].copy()
    candidates = episodes.merge(
        candidate_match,
        left_on="episode_id",
        right_on="speed_episode_id",
        how="left",
    )
    candidates["strict_candidate_v1"] = (
        candidates["quality_status"].eq("accepted")
        & candidates["overlap_iou"].ge(0.50)
    )
    candidates = candidates[candidates["strict_candidate_v1"]].drop(columns="speed_episode_id")
    candidates.to_csv(candidate_path, index=False)
    summary = {
        "algorithm": "speed_only_asymmetric_v1",
        "timezone": "America/Los_Angeles",
        "links": args.links,
        "days": int(day_status["local_date"].nunique()),
        "episodes": int(len(episodes)),
        "days_without_identifiable_episode": int(day_status["episode_count"].eq(0).sum()),
        "matched_to_paq": int(len(matched)),
        "speed_only_unmatched": int(comparison["match_status"].eq("speed_only").sum()),
        "paq_only_unmatched": int(comparison["match_status"].eq("paq_only").sum()),
        "strict_qvdf_episode_candidates_v1": int(len(candidates)),
        "matched_median_abs_delta_t0_min": float(matched["delta_t0_min"].abs().median()) if len(matched) else None,
        "matched_median_abs_delta_T2_min": float(matched["delta_T2_min"].abs().median()) if len(matched) else None,
        "matched_median_abs_delta_t3_min": float(matched["delta_t3_min"].abs().median()) if len(matched) else None,
        "matched_median_abs_delta_P_min": float(matched["delta_P_min"].abs().median()) if len(matched) else None,
        "config": config.__dict__,
        "input_contract": "speed-only: PeMS local wall-clock timestamp (literal Z is not UTC), link_id, speed_kmh, observation-quality flags",
        "paq_time_correction": "legacy PAQ date + local wall-clock minutes localized explicitly to America/Los_Angeles",
        "T2_validation_note": "PAQ does not independently publish T2; the PAQ-window T2 diagnostic is derived from the same target-link speed and is not an external T2 accuracy test.",
    }
    (args.output_dir / "episode_detection_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
