"""Predeclared robustness tests for I-405 speed-only congestion episodes.

The baseline detector is perturbed along four axes without inspecting the
result first: entry threshold, persistence duration, sampling interval, and
additive speed noise.  Baseline free speeds remain frozen in every run.
"""

from __future__ import annotations

import argparse
import json
import math
import sys
from dataclasses import asdict
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
DEFAULT_RAW = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\pems_downloads_d12\proceed\I405\S\train_detector_states.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed-file", type=Path, default=DEFAULT_RAW)
    parser.add_argument(
        "--baseline-dir", type=Path,
        default=ROOT / "outputs/i405_speed_only_episodes_direct7",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/i405_episode_sensitivity_direct7",
    )
    parser.add_argument("--noise-replicates", type=int, default=10)
    parser.add_argument("--seed", type=int, default=20260810)
    return parser.parse_args()


def read_speed(path: Path) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    cols = ["timestamp", "link_id", "speed", "is_observed", "is_missing"]
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
        parts.append(chunk[["link_id", "timestamp_la", "speed"]])
    data = pd.concat(parts, ignore_index=True)
    data["speed_mph"] = pd.to_numeric(data["speed"], errors="coerce") * KM_TO_MI
    return (
        data.groupby(["link_id", "timestamp_la"], as_index=False)["speed_mph"]
        .mean().sort_values(["link_id", "timestamp_la"])
    )


def variant_grid(noise_replicates: int, seed: int) -> list[dict[str, object]]:
    variants: list[dict[str, object]] = []
    for ratio in (0.65, 0.70, 0.75):
        for persistence in (10, 15, 20):
            if ratio == 0.70 and persistence == 15:
                continue
            variants.append({
                "variant_id": f"threshold_r{ratio:.2f}_p{persistence}",
                "category": "threshold_persistence", "sample_min": 5,
                "enter_ratio": ratio, "persistence_min": persistence,
                "noise_sigma_mph": 0.0, "noise_seed": None,
            })
    for sample_min in (10, 15):
        variants.append({
            "variant_id": f"sampling_{sample_min}min", "category": "sampling",
            "sample_min": sample_min, "enter_ratio": 0.70,
            "persistence_min": 15, "noise_sigma_mph": 0.0, "noise_seed": None,
        })
    seed_sequence = np.random.SeedSequence(seed).spawn(3 * noise_replicates)
    k = 0
    for sigma in (1.0, 3.0, 5.0):
        for replicate in range(1, noise_replicates + 1):
            child_seed = int(seed_sequence[k].generate_state(1)[0]); k += 1
            variants.append({
                "variant_id": f"noise_s{sigma:g}_r{replicate:02d}", "category": "noise",
                "sample_min": 5, "enter_ratio": 0.70, "persistence_min": 15,
                "noise_sigma_mph": sigma, "noise_seed": child_seed,
            })
    return variants


def config_for(variant: dict[str, object]) -> EpisodeDetectionConfig:
    sample = int(variant["sample_min"])
    persistence = int(variant["persistence_min"])
    return EpisodeDetectionConfig(
        interval_min=sample,
        smoothing_bins=max(1, round(15 / sample)),
        enter_ratio=float(variant["enter_ratio"]),
        exit_ratio=float(variant["enter_ratio"]) + 0.05,
        enter_persistence_bins=max(1, math.ceil(persistence / sample)),
        exit_persistence_bins=max(1, math.ceil(persistence / sample)),
        max_interpolation_gap_bins=max(1, math.ceil(10 / sample)),
        minimum_duration_min=20.0,
        minimum_depth_mph=3.0,
    )


def run_variant(
    speed: pd.DataFrame, free_speed: dict[str, float], variant: dict[str, object]
) -> pd.DataFrame:
    cfg = config_for(variant)
    frames: list[pd.DataFrame] = []
    rng = np.random.default_rng(variant["noise_seed"])
    for link_id, group in speed.groupby("link_id", sort=True):
        series = group.set_index("timestamp_la")["speed_mph"].sort_index()
        if cfg.interval_min > 5:
            series = series.resample(f"{cfg.interval_min}min").mean()
        sigma = float(variant["noise_sigma_mph"])
        values = series.to_numpy(copy=True)
        if sigma:
            finite = np.isfinite(values)
            values[finite] += rng.normal(0.0, sigma, finite.sum())
        episodes, _ = detect_speed_episodes(series.index, values, free_speed[link_id], cfg)
        if episodes.empty:
            continue
        episodes.insert(0, "link_id", link_id)
        episodes["variant_episode_id"] = [f"{variant['variant_id']}:{link_id}:E{i}" for i in range(1, len(episodes) + 1)]
        frames.append(episodes)
    return pd.concat(frames, ignore_index=True) if frames else pd.DataFrame()


def interval_iou(a0: pd.Timestamp, a3: pd.Timestamp, b0: pd.Timestamp, b3: pd.Timestamp) -> float:
    overlap = max(0.0, (min(a3, b3) - max(a0, b0)).total_seconds())
    union = (max(a3, b3) - min(a0, b0)).total_seconds()
    return overlap / union if union > 0 else 0.0


def match_baseline(baseline: pd.DataFrame, candidate: pd.DataFrame, variant: dict[str, object]) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for link_id, base_link in baseline.groupby("link_id", sort=True):
        cand_link = candidate[candidate["link_id"].eq(link_id)] if not candidate.empty else candidate
        pairs: list[tuple[float, int, int]] = []
        for bi, b in base_link.iterrows():
            b0, b3 = pd.Timestamp(b["t0_la"]), pd.Timestamp(b["t3_la"])
            for ci, c in cand_link.iterrows():
                iou = interval_iou(b0, b3, pd.Timestamp(c["t0_la"]), pd.Timestamp(c["t3_la"]))
                if iou > 0:
                    pairs.append((iou, bi, ci))
        matched_b: dict[int, tuple[int, float]] = {}
        used_c: set[int] = set()
        for iou, bi, ci in sorted(pairs, reverse=True):
            if bi not in matched_b and ci not in used_c:
                matched_b[bi] = (ci, iou); used_c.add(ci)
        for bi, b in base_link.iterrows():
            common = {**variant, "baseline_episode_id": b["episode_id"], "link_id": link_id}
            if bi not in matched_b:
                rows.append({**common, "matched": False, "iou": 0.0})
                continue
            ci, iou = matched_b[bi]; c = cand_link.loc[ci]
            b0, b2, b3 = map(pd.Timestamp, [b["t0_la"], b["T2_la"], b["t3_la"]])
            c0, c2, c3 = map(pd.Timestamp, [c["t0_la"], c["T2_la"], c["t3_la"]])
            rows.append({
                **common, "matched": True, "iou": iou,
                "variant_episode_id": c["variant_episode_id"],
                "delta_t0_min": (c0 - b0).total_seconds() / 60,
                "delta_T2_min": (c2 - b2).total_seconds() / 60,
                "delta_t3_min": (c3 - b3).total_seconds() / 60,
                "delta_P_min": float(c["P_h"] - b["P_h"]) * 60,
            })
    return pd.DataFrame(rows)


def aggregate_stability(baseline: pd.DataFrame, matches: pd.DataFrame) -> pd.DataFrame:
    rows: list[dict[str, object]] = []
    for _, b in baseline.iterrows():
        subset = matches[matches["baseline_episode_id"].eq(b["episode_id"])]
        deterministic = subset[subset["category"].isin(["threshold_persistence", "sampling"])]
        noise = subset[subset["category"].eq("noise")]
        sampling = subset[subset["category"].eq("sampling")]
        det_matched = deterministic[deterministic["matched"]]
        noise_matched = noise[noise["matched"]]
        sample_good = sampling["matched"] & sampling["iou"].ge(0.50)
        row = {
            "episode_id": b["episode_id"], "link_id": b["link_id"],
            "t0_la": b["t0_la"], "T2_la": b["T2_la"], "t3_la": b["t3_la"],
            "P_h": b["P_h"], "quality_status": b["quality_status"],
            "deterministic_match_rate": deterministic["matched"].mean(),
            "deterministic_median_iou": det_matched["iou"].median(),
            "deterministic_median_abs_t0_min": det_matched["delta_t0_min"].abs().median(),
            "deterministic_median_abs_T2_min": det_matched["delta_T2_min"].abs().median(),
            "deterministic_median_abs_t3_min": det_matched["delta_t3_min"].abs().median(),
            "deterministic_median_abs_P_min": det_matched["delta_P_min"].abs().median(),
            "sampling_pass_rate": sample_good.mean(),
            "noise_match_rate": noise["matched"].mean(),
            "noise_median_iou": noise_matched["iou"].median(),
            "noise_median_abs_P_min": noise_matched["delta_P_min"].abs().median(),
        }
        row["stable_speed_only_v1"] = bool(
            b["quality_status"] == "accepted"
            and row["deterministic_match_rate"] >= 0.80
            and row["deterministic_median_iou"] >= 0.50
            and row["sampling_pass_rate"] == 1.0
            and row["noise_match_rate"] >= 0.80
            and row["noise_median_iou"] >= 0.50
        )
        rows.append(row)
    return pd.DataFrame(rows)


def plot_results(stability: pd.DataFrame, matches: pd.DataFrame, figure_dir: Path) -> None:
    figure_dir.mkdir(parents=True, exist_ok=True)
    ordered = stability.sort_values(["link_id", "T2_la"]).reset_index(drop=True)
    x = np.arange(len(ordered))
    fig, axes = plt.subplots(3, 1, figsize=(15, 10), sharex=True, constrained_layout=True)
    axes[0].plot(x, ordered["deterministic_match_rate"], "o-", label="threshold/persistence/sampling")
    axes[0].plot(x, ordered["noise_match_rate"], "s-", label="noise")
    axes[0].axhline(0.8, color="black", ls="--", lw=1); axes[0].set_ylabel("match rate"); axes[0].legend()
    axes[1].plot(x, ordered["deterministic_median_iou"], "o-", label="deterministic")
    axes[1].plot(x, ordered["noise_median_iou"], "s-", label="noise")
    axes[1].axhline(0.5, color="black", ls="--", lw=1); axes[1].set_ylabel("median IoU"); axes[1].legend()
    axes[2].bar(x - .2, ordered["deterministic_median_abs_t0_min"], .4, label="|Δt0|")
    axes[2].bar(x + .2, ordered["deterministic_median_abs_t3_min"], .4, label="|Δt3|")
    axes[2].set_ylabel("median minutes"); axes[2].legend()
    axes[2].set_xticks(x, ordered["episode_id"], rotation=80, ha="right", fontsize=7)
    fig.suptitle("I-405 speed-only episode robustness (predeclared perturbations)")
    fig.savefig(figure_dir / "episode_stability_overview.png", dpi=180); plt.close(fig)

    deterministic = matches[matches["category"].isin(["threshold_persistence", "sampling"])]
    matrix = deterministic.pivot(index="variant_id", columns="baseline_episode_id", values="iou")
    matrix = matrix.reindex(columns=ordered["episode_id"])
    fig, ax = plt.subplots(figsize=(16, 5), constrained_layout=True)
    image = ax.imshow(matrix.to_numpy(), aspect="auto", vmin=0, vmax=1, cmap="viridis")
    ax.set_yticks(range(len(matrix.index)), matrix.index, fontsize=8)
    ax.set_xticks(range(len(matrix.columns)), matrix.columns, rotation=80, ha="right", fontsize=7)
    ax.set_title("Temporal IoU with baseline episode"); fig.colorbar(image, ax=ax, label="IoU")
    fig.savefig(figure_dir / "episode_variant_iou_heatmap.png", dpi=180); plt.close(fig)


def main() -> None:
    args = parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    speed = read_speed(args.speed_file)
    free_speed = speed.groupby("link_id")["speed_mph"].quantile(0.95).to_dict()
    baseline = pd.read_csv(args.baseline_dir / "speed_only_asymmetric_episodes.csv")
    variants = variant_grid(args.noise_replicates, args.seed)
    match_frames: list[pd.DataFrame] = []
    run_rows: list[dict[str, object]] = []
    for number, variant in enumerate(variants, 1):
        candidate = run_variant(speed, free_speed, variant)
        match_frames.append(match_baseline(baseline, candidate, variant))
        cfg = config_for(variant)
        run_rows.append({**variant, **{f"config_{k}": v for k, v in asdict(cfg).items()}, "detected_episodes": len(candidate)})
        print(f"[{number:02d}/{len(variants)}] {variant['variant_id']}: {len(candidate)} episodes")
    matches = pd.concat(match_frames, ignore_index=True)
    stability = aggregate_stability(baseline, matches)
    stable = baseline.merge(stability[["episode_id", "stable_speed_only_v1"]], on="episode_id")
    stable = stable[stable["stable_speed_only_v1"]]
    strict = pd.read_csv(args.baseline_dir / "qvdf_episode_candidates_strict_v1.csv")
    stable_paq = strict.merge(stability, on=["episode_id", "link_id"], suffixes=("", "_stability"))
    stable_paq = stable_paq[stable_paq["stable_speed_only_v1"]]

    matches.to_csv(args.output_dir / "episode_variant_matches.csv", index=False)
    stability.to_csv(args.output_dir / "episode_stability_summary.csv", index=False)
    stable.to_csv(args.output_dir / "stable_speed_only_episodes.csv", index=False)
    stable_paq.to_csv(args.output_dir / "stable_paq_qvdf_candidates.csv", index=False)
    pd.DataFrame(run_rows).to_csv(args.output_dir / "variant_run_summary.csv", index=False)
    plot_results(stability, matches, args.output_dir / "figures")
    summary = {
        "stage": "C_predeclared_episode_sensitivity_v1",
        "baseline_episodes": len(baseline), "variants": len(variants),
        "deterministic_variants": sum(v["category"] != "noise" for v in variants),
        "noise_variants": sum(v["category"] == "noise" for v in variants),
        "stable_speed_only_episodes": len(stable),
        "baseline_strict_paq_candidates": len(strict),
        "stable_paq_qvdf_candidates": len(stable_paq),
        "stable_rule": "quality=accepted; deterministic match>=0.8 and median IoU>=0.5; both 10/15-min sampling IoU>=0.5; noise match>=0.8 and median IoU>=0.5",
        "free_speed_policy": "link p95 frozen from unperturbed 5-min observations",
        "seed": args.seed,
    }
    (args.output_dir / "sensitivity_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
