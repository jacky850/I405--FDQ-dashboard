"""Forward-project the inferred QVDF state into a 5-minute speed profile.

The holdout inversion stops at scalars: D/C, D, V, and the single speed v(T2).
This script closes the loop the other way. It takes the inferred state back
through the QVDF speed map, produces a speed value for every 5-minute bin of
the period, and scores it against the observed holdout profile.

What is actually being predicted
--------------------------------
The duration branch round-trips exactly. ``x_hat`` was obtained by inverting
``P = f_d * x^n``, so pushing ``x_hat`` forward through the same branch returns
the observed P by construction. It carries no independent information and is
reported only as a closure check.

The forward projection therefore tests two things that were *not* fitted on the
holdout week:

  1. the severity branch ``z = f_p * P^s``, frozen on the training weeks, and
  2. the QVDF episode shape ``v(t) = vc / (1 + z * (1 - tau^2)^2)``.

Two model variants separate them:

  ``forward``     z from the frozen severity branch. The genuine prediction.
  ``shape_only``  z from the observed v(T2). Isolates shape error by handing
                  the model the correct depth.

A constant free-flow speed is scored alongside as the null baseline. Without
it, a speed MAE in mph is not interpretable: most bins of an AM period are
uncongested, and predicting "free flow everywhere" already scores well.

Windows
-------
``model_window``      where QVDF claims congestion, |tau| <= 1
``observed_episode``  where congestion was actually detected, [t0, t3]
``period``            the whole reporting period, free-flow speed outside the
                      episode. This is the only window with full coverage.
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

PERIODS = {"AM": (6.0, 9.0), "PM": (15.0, 19.0)}
VARIANTS = ("forward", "shape_only", "free_flow_baseline")
WINDOWS = ("model_window", "observed_episode", "period")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--results-file", type=Path,
        default=ROOT / "outputs/i405_multiweek_average_holdout/leave_one_week_out_qvdf_results.csv",
    )
    parser.add_argument(
        "--profile-file", type=Path,
        default=ROOT / "outputs/i405_multiweek_average_holdout/weekly_average_weekday_profiles_5min.csv",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/i405_multiweek_average_holdout",
    )
    return parser.parse_args()


def minute_of_day(stamp: str) -> float:
    """Minutes past local midnight from an anchored ISO timestamp."""
    parsed = pd.Timestamp(stamp)
    return parsed.hour * 60.0 + parsed.minute + parsed.second / 60.0


def qvdf_speed(clock_h: np.ndarray, T2_h: float, P_h: float, vc: float,
               z: float, free_speed: float) -> tuple[np.ndarray, np.ndarray]:
    """QVDF episode speed over a clock, free-flow outside the episode."""
    tau = 2.0 * (clock_h - T2_h) / P_h
    inside = np.abs(tau) <= 1.0
    shape = np.where(inside, (1.0 - np.clip(tau, -1.0, 1.0) ** 2) ** 2, 0.0)
    speed = np.where(inside, vc / (1.0 + z * shape), free_speed)
    return speed, inside


def score(observed: np.ndarray, predicted: np.ndarray, baseline: np.ndarray) -> dict:
    if observed.size == 0:
        return {"bins": 0}
    error = predicted - observed
    baseline_mse = float(((baseline - observed) ** 2).mean())
    model_mse = float((error ** 2).mean())
    return {
        "bins": int(observed.size),
        "mae_mph": float(np.abs(error).mean()),
        "rmse_mph": float(np.sqrt(model_mse)),
        "bias_mph": float(error.mean()),
        "max_abs_error_mph": float(np.abs(error).max()),
        "mape_pct": float((np.abs(error) / observed).mean() * 100.0),
        # Fraction of the free-flow baseline's squared error removed. Negative
        # means the model is worse than assuming free flow everywhere.
        "skill_vs_free_flow": float(1.0 - model_mse / baseline_mse) if baseline_mse > 0 else np.nan,
    }


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    results = pd.read_csv(args.results_file)
    profiles = pd.read_csv(args.profile_file)

    cases = results[results["episode_identified"].astype(bool)].copy()
    cases = cases.dropna(subset=["z_predicted", "P_h", "T2_la", "cutoff_speed_vc_mph"])

    bin_rows: list[pd.DataFrame] = []
    metric_rows: list[dict] = []

    for _, case in cases.iterrows():
        start_h, end_h = PERIODS[case["period"]]
        profile = profiles[
            profiles["link_id"].eq(case["link_id"])
            & profiles["week_start"].eq(case["week_start"])
            & profiles["minute_of_day"].between(start_h * 60, end_h * 60, inclusive="left")
        ].sort_values("minute_of_day")
        if profile.empty:
            continue

        clock_h = profile["minute_of_day"].to_numpy(float) / 60.0
        observed = profile["average_speed_mph"].to_numpy(float)
        vc = float(case["cutoff_speed_vc_mph"])
        free_speed = float(case["free_speed_p95_mph"])
        P_h = float(case["P_h"])
        T2_h = minute_of_day(case["T2_la"]) / 60.0
        t0_h = minute_of_day(case["t0_la"]) / 60.0
        t3_h = minute_of_day(case["t3_la"]) / 60.0

        forward, in_model = qvdf_speed(clock_h, T2_h, P_h, vc, float(case["z_predicted"]), free_speed)
        shape_only, _ = qvdf_speed(clock_h, T2_h, P_h, vc, float(case["z_observed"]), free_speed)
        baseline = np.full_like(observed, free_speed)
        in_episode = (clock_h >= t0_h) & (clock_h <= t3_h)

        bin_rows.append(pd.DataFrame({
            "link_id": case["link_id"], "period": case["period"],
            "holdout_week": case["week_start"], "final_supported": bool(case["final_supported"]),
            "minute_of_day": profile["minute_of_day"].to_numpy(),
            "observed_speed_mph": observed,
            "forward_speed_mph": forward,
            "shape_only_speed_mph": shape_only,
            "free_flow_baseline_mph": baseline,
            "inside_model_window": in_model,
            "inside_observed_episode": in_episode,
        }))

        masks = {
            "model_window": in_model,
            "observed_episode": in_episode,
            "period": np.ones_like(observed, dtype=bool),
        }
        predictions = {
            "forward": forward,
            "shape_only": shape_only,
            "free_flow_baseline": baseline,
        }
        for window, mask in masks.items():
            for variant, prediction in predictions.items():
                metric_rows.append({
                    "link_id": case["link_id"], "period": case["period"],
                    "holdout_week": case["week_start"],
                    "final_supported": bool(case["final_supported"]),
                    "inverse_status": case["inverse_status"],
                    "window": window, "variant": variant,
                    # The model episode is symmetric about T2; the detected one
                    # need not be. This is a forward-projection error source.
                    "T2_minus_episode_midpoint_min": (T2_h - (t0_h + t3_h) / 2.0) * 60.0,
                    "P_h": P_h, "vc_mph": vc, "free_speed_p95_mph": free_speed,
                    "z_used": {"forward": float(case["z_predicted"]),
                               "shape_only": float(case["z_observed"]),
                               "free_flow_baseline": np.nan}[variant],
                    **score(observed[mask], prediction[mask], baseline[mask]),
                })

    bins = pd.concat(bin_rows, ignore_index=True)
    metrics = pd.DataFrame(metric_rows)
    metrics.to_csv(args.output_dir / "forward_projection_speed_metrics.csv", index=False)

    def aggregate(frame: pd.DataFrame) -> dict:
        out: dict = {}
        for window in WINDOWS:
            out[window] = {}
            for variant in VARIANTS:
                subset = frame[frame["window"].eq(window) & frame["variant"].eq(variant)]
                subset = subset[subset["bins"] > 0]
                if subset.empty:
                    out[window][variant] = {"cases": 0}
                    continue
                out[window][variant] = {
                    "cases": int(len(subset)),
                    "mean_bins_per_case": float(subset["bins"].mean()),
                    "mae_mph": float(subset["mae_mph"].mean()),
                    "rmse_mph": float(np.sqrt((subset["rmse_mph"] ** 2).mean())),
                    "bias_mph": float(subset["bias_mph"].mean()),
                    "max_abs_error_mph": float(subset["max_abs_error_mph"].max()),
                    "mape_pct": float(subset["mape_pct"].mean()),
                    "skill_vs_free_flow": float(subset["skill_vs_free_flow"].mean()),
                }
        return out

    def decompose(frame: pd.DataFrame) -> dict:
        """Split the period error into the model's congested and free-flow halves.

        The QVDF episode is a boxcar: inside the window it models a speed dip,
        outside it asserts free flow. Splitting the squared error at that edge
        shows which of the two assumptions the period-level error comes from.
        """
        error = frame["forward_speed_mph"] - frame["observed_speed_mph"]
        inside = frame["inside_model_window"].astype(bool)
        total_sse = float((error ** 2).sum())
        block = {}
        for label, mask in [("inside_model_window", inside), ("outside_model_window", ~inside)]:
            part = error[mask]
            block[label] = {
                "bins": int(mask.sum()),
                "bin_share_pct": float(100.0 * mask.mean()),
                "sse_share_pct": float(100.0 * (part ** 2).sum() / total_sse) if total_sse > 0 else np.nan,
                "mae_mph": float(part.abs().mean()) if len(part) else np.nan,
                "bias_mph": float(part.mean()) if len(part) else np.nan,
            }
        outside = frame[~inside]
        block["outside_window_reality_check"] = {
            "bins_below_cutoff_speed_pct": float(100.0 * (outside["observed_speed_mph"] < outside["vc_mph"]).mean()),
            "bins_below_90pct_free_speed_pct": float(
                100.0 * (outside["observed_speed_mph"] < 0.9 * outside["free_flow_baseline_mph"]).mean()),
            "note": (
                "Bins the model calls free-flow that are in fact still slow. A one-sided "
                "positive bias here means the model ends the episode too early or starts it "
                "too late, not that it mis-sizes the dip."
            ),
        }
        block["period_congestion_coverage"] = {
            "period_bins_below_cutoff_speed_pct": float(
                100.0 * (frame["observed_speed_mph"] < frame["vc_mph"]).mean()),
            "model_window_share_of_period_pct": float(100.0 * inside.mean()),
        }
        return block

    supported = metrics[metrics["final_supported"]]
    asymmetry = metrics.drop_duplicates(["link_id", "period", "holdout_week"])
    cutoff = metrics.drop_duplicates(["link_id", "period", "holdout_week"]).set_index(
        ["link_id", "period", "holdout_week"])["vc_mph"]
    bins["vc_mph"] = bins.set_index(["link_id", "period", "holdout_week"]).index.map(cutoff)
    bins.to_csv(args.output_dir / "forward_projection_speed_5min.csv", index=False)
    summary = {
        "source": {"results": str(args.results_file), "profiles": str(args.profile_file)},
        "what_is_predicted": (
            "The duration branch round-trips by construction: x_hat was inverted from the "
            "observed P, so forward-projecting it returns P exactly. The forward projection "
            "tests the frozen severity branch z = f_p * P^s and the QVDF episode shape "
            "v(t) = vc / (1 + z (1 - tau^2)^2). P, T2 and vc are read from the holdout speed "
            "profile and handed to the model."
        ),
        "variants": {
            "forward": "z from the frozen severity branch; the genuine prediction",
            "shape_only": "z from the observed v(T2); isolates shape error",
            "free_flow_baseline": "constant free-flow speed; the null model",
        },
        "coverage": {
            "episode_cases_scored": int(metrics["holdout_week"].groupby(
                [metrics["link_id"], metrics["period"], metrics["holdout_week"]]).ngroup().nunique()),
            "supported_cases": int(len(supported.drop_duplicates(["link_id", "period", "holdout_week"]))),
        },
        "episode_alignment": {
            "T2_minus_episode_midpoint_min_mean": float(asymmetry["T2_minus_episode_midpoint_min"].mean()),
            "T2_minus_episode_midpoint_min_abs_max": float(asymmetry["T2_minus_episode_midpoint_min"].abs().max()),
            "note": (
                "The QVDF episode is symmetric about T2. The detected episode is not, so the "
                "model congestion window is shifted relative to the observed one."
            ),
        },
        "supported_cases": aggregate(supported),
        "all_episode_cases": aggregate(metrics),
        "period_error_decomposition_supported": decompose(bins[bins["final_supported"].astype(bool)]),
    }
    (args.output_dir / "forward_projection_speed_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )

    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
