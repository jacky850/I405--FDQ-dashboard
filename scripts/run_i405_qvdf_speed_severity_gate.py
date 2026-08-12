"""Held-out QVDF speed-severity branch and volume identifiability gate."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from run_i405_average_weekday_qvdf_volume import (  # noqa: E402
    LA,
    hour_of,
    period_of,
    primary_daily_episodes,
)


S_FROZEN = 1.40
SEVERITY_RATIO_LOWER = 0.50
SEVERITY_RATIO_UPPER = 2.00
MAX_SPEED_ERROR_MPH = 10.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--daily-episode-file", type=Path,
        default=ROOT / "outputs/i405_speed_only_episodes_direct7/speed_only_asymmetric_episodes.csv",
    )
    parser.add_argument(
        "--volume-dir", type=Path,
        default=ROOT / "outputs/i405_average_weekday_qvdf_volume",
    )
    parser.add_argument(
        "--average-dir", type=Path,
        default=ROOT / "outputs/i405_average_weekday_canonical_direct7",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/i405_qvdf_speed_severity_gate",
    )
    return parser.parse_args()


def observed_severity(frame: pd.DataFrame) -> pd.Series:
    return frame["exit_threshold_mph"].astype(float) / frame["vT2_robust_mph"].astype(float) - 1.0


def calibrate_fp(train: pd.DataFrame) -> float:
    z = observed_severity(train)
    return float(np.median(z / np.power(train["P_h"].astype(float), S_FROZEN)))


def evaluate_holdout(daily: pd.DataFrame, volume: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, volume_row in volume.iterrows():
        mask = (
            daily["link_id"].eq(volume_row["link_id"])
            & daily["period"].eq(volume_row["period"])
        )
        group = daily[mask]
        test = group[group["local_date"].eq(volume_row["holdout_date"])]
        train = group[group["local_date"].ne(volume_row["holdout_date"])]
        if len(test) != 1 or len(train) < 2:
            continue
        test_row = test.iloc[0]
        fp = calibrate_fp(train)
        P = float(test_row["P_h"])
        vc = float(test_row["exit_threshold_mph"])
        z_obs = float(observed_severity(test).iloc[0])
        z_hat = fp * P ** S_FROZEN
        v_hat = vc / (1.0 + z_hat)
        v_obs = float(test_row["vT2_robust_mph"])
        ratio = z_obs / z_hat if z_hat > 0 else np.nan
        speed_error = v_hat - v_obs
        ratio_pass = SEVERITY_RATIO_LOWER <= ratio <= SEVERITY_RATIO_UPPER
        speed_pass = abs(speed_error) <= MAX_SPEED_ERROR_MPH
        supported = bool(ratio_pass and speed_pass)
        rows.append({
            **volume_row.to_dict(),
            "cutoff_speed_vc_mph": vc,
            "s_frozen": S_FROZEN,
            "f_p_calibrated": fp,
            "z_observed_from_holdout_speed": z_obs,
            "z_predicted_from_holdout_P": z_hat,
            "severity_observed_over_predicted": ratio,
            "vT2_observed_mph": v_obs,
            "vT2_predicted_mph": v_hat,
            "vT2_error_mph": speed_error,
            "severity_ratio_pass": ratio_pass,
            "speed_error_pass": speed_pass,
            "speed_branch_supported": supported,
            "inverse_status": "identified_under_calibrated_qvdf" if supported else "not_identified_speed_branch_failure",
        })
    return pd.DataFrame(rows)


def evaluate_canonical(daily: pd.DataFrame, canonical_volume: pd.DataFrame, canonical_episode: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for _, volume_row in canonical_volume.iterrows():
        group = daily[
            daily["link_id"].eq(volume_row["link_id"])
            & daily["period"].eq(volume_row["period"])
        ]
        episode = canonical_episode[canonical_episode["episode_id"].eq(volume_row["episode_id"])].iloc[0]
        fp = calibrate_fp(group)
        P = float(episode["P_h"])
        vc = float(episode["exit_threshold_mph"])
        z_obs = vc / float(episode["vT2_robust_mph"]) - 1.0
        z_hat = fp * P ** S_FROZEN
        v_hat = vc / (1 + z_hat)
        v_obs = float(episode["vT2_robust_mph"])
        ratio = z_obs / z_hat if z_hat > 0 else np.nan
        speed_error = v_hat-v_obs
        supported = bool(
            SEVERITY_RATIO_LOWER <= ratio <= SEVERITY_RATIO_UPPER
            and abs(speed_error) <= MAX_SPEED_ERROR_MPH
        )
        rows.append({
            **volume_row.to_dict(), "s_frozen": S_FROZEN, "f_p_calibrated": fp,
            "z_observed": z_obs, "z_predicted": z_hat,
            "severity_observed_over_predicted": ratio,
            "vT2_observed_mph": v_obs, "vT2_predicted_mph": v_hat,
            "vT2_error_mph": speed_error, "speed_branch_supported": supported,
            "validation_scope": "daily_calibrated_to_average_profile_transfer_diagnostic_not_holdout",
        })
    return pd.DataFrame(rows)


def metrics(frame: pd.DataFrame, label: str) -> dict[str, float | int | str]:
    supported = frame[frame["speed_branch_supported"]]
    return {
        "subset": label,
        "cases": int(len(frame)),
        "supported_cases": int(len(supported)),
        "coverage_pct": float(len(supported) / len(frame) * 100) if len(frame) else 0.0,
        "vT2_MAE_mph": float(frame["vT2_error_mph"].abs().mean()),
        "volume_MAPE_all_pct": float(frame["absolute_percentage_error_pct"].mean()),
        "volume_median_APE_all_pct": float(frame["absolute_percentage_error_pct"].median()),
        "volume_MAPE_supported_pct": float(supported["absolute_percentage_error_pct"].mean()) if len(supported) else np.nan,
        "volume_median_APE_supported_pct": float(supported["absolute_percentage_error_pct"].median()) if len(supported) else np.nan,
    }


def plot_results(result: pd.DataFrame, output_dir: Path) -> None:
    figures = output_dir / "figures"; figures.mkdir(parents=True, exist_ok=True)
    colors = np.where(result["speed_branch_supported"], "#2563eb", "#dc2626")
    fig, axes = plt.subplots(1, 2, figsize=(13, 5.5), constrained_layout=True)
    axes[0].scatter(result["vT2_observed_mph"], result["vT2_predicted_mph"], c=colors, s=65)
    low = min(result["vT2_observed_mph"].min(), result["vT2_predicted_mph"].min())
    high = max(result["vT2_observed_mph"].max(), result["vT2_predicted_mph"].max())
    axes[0].plot([low, high], [low, high], "--", color="0.35")
    axes[0].set(xlabel="Observed v(T2) (mph)", ylabel="Predicted v(T2) (mph)", title="Held-out speed branch")
    axes[1].scatter(result["V_observed_veh"], result["V_hat_veh"], c=colors, s=65)
    low = min(result["V_observed_veh"].min(), result["V_hat_veh"].min())
    high = max(result["V_observed_veh"].max(), result["V_hat_veh"].max())
    axes[1].plot([low, high], [low, high], "--", color="0.35")
    axes[1].set(xlabel="Observed period volume (veh)", ylabel="Inferred period volume (veh)", title="Blue=supported, red=abstain")
    for ax in axes: ax.grid(alpha=.2)
    fig.savefig(figures / "heldout_speed_branch_and_volume_gate.png", dpi=190); plt.close(fig)


def main() -> None:
    args = parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    daily = primary_daily_episodes(args.daily_episode_file)
    volume = pd.read_csv(args.volume_dir / "daily_leave_one_out_qvdf_volume_validation.csv")
    canonical_volume = pd.read_csv(args.volume_dir / "average_weekday_canonical_qvdf_volume.csv")
    canonical_episode = pd.read_csv(args.average_dir / "canonical_average_weekday_episodes.csv")
    result = evaluate_holdout(daily, volume)
    canonical = evaluate_canonical(daily, canonical_volume, canonical_episode)
    result.to_csv(args.output_dir / "heldout_qvdf_speed_branch_gate.csv", index=False)
    canonical.to_csv(args.output_dir / "canonical_qvdf_speed_branch.csv", index=False)
    metric_rows = []
    metric_rows.append(metrics(result, "all_links"))
    for (link_id, period), group in result.groupby(["link_id", "period"]):
        metric_rows.append(metrics(group, f"{link_id}_{period}"))
    metric_frame = pd.DataFrame(metric_rows)
    metric_frame.to_csv(args.output_dir / "speed_branch_gate_metrics.csv", index=False)
    plot_results(result, args.output_dir)
    summary = {
        "speed_branch": "z=vc/vT2-1=f_p*P^s",
        "s_status": "assumed_frozen_from_mentor_gold", "s": S_FROZEN,
        "predeclared_gate": {
            "severity_ratio": [SEVERITY_RATIO_LOWER, SEVERITY_RATIO_UPPER],
            "maximum_absolute_vT2_error_mph": MAX_SPEED_ERROR_MPH,
        },
        **metrics(result, "all_links"),
        "interpretation": "failed cases are abstentions, not deleted observations; the speed branch is a consistency/identifiability gate and does not alter the mentor volume equation",
    }
    (args.output_dir / "speed_branch_gate_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
