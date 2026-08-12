"""Leave-one-weekday-out ground-truth validation for the closure pipeline.

S3 parameters and period service rates are estimated from the training
weekdays, then evaluated on a held-out weekday. This avoids treating the
in-sample round-trip check as predictive accuracy.
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

from fdqbench.calibrate import fit_s3_from_speed_flow
from fdqbench.closure import backward_closure, closure_speed_metrics, reconstruct_speed_from_flow


PERIODS = [("NT1", 0, 6), ("AM", 6, 10), ("MD", 10, 15), ("PM", 15, 19), ("NT2", 19, 24)]
DEFAULT_LINKS = [
    "L405S-001|1222782",
    "L405S-001|1223027",
    "L405S-020|1201419",
    "L405S-061|1201350",
]


def period_of(value: str) -> str:
    hour = int(str(value).split(":", 1)[0])
    for name, start, end in PERIODS:
        if start <= hour < end:
            return name
    return "NT2"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data/jinxi_i405_week_2025-06-16_to_22/raw_observed_fdqbench.csv",
    )
    p.add_argument("--output-dir", type=Path, default=ROOT / "outputs/i405_closure_holdout_direct4")
    p.add_argument("--links", nargs="*", default=DEFAULT_LINKS)
    return p.parse_args()


def fit_training_models(train: pd.DataFrame, key: str) -> tuple[dict, dict, float]:
    sub = train[train["key"].eq(key)]
    if sub.empty:
        raise ValueError(f"No training rows found for {key}")
    lanes = float(sub["lanes"].dropna().iloc[0])
    models = {}
    mu_by_period = {}
    model_rows = []
    for period, group in sub.groupby("period", sort=False):
        fit, info = fit_s3_from_speed_flow(group["speed_mph"], group["flow_vehph"], lanes=lanes)
        models[period] = fit
        # This is a transparent baseline service-rate estimate. The PAQ-aware
        # mu source will be added as a separate validation mode later.
        mu_by_period[period] = float(group["flow_vehph"].median())
        model_rows.append({"key": key, "period": period, "lanes": lanes, **fit.to_dict(), **{f"fit_{k}": v for k, v in info.items()}})
    return models, mu_by_period, lanes, model_rows


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.input, dtype={"link_id": str, "tmc_id": str})
    # Keep the calendar date encoded in the LA timestamp. Converting these
    # strings to UTC first would shift evening observations to the next date.
    df["local_date"] = df["timestamp_la"].str[:10]
    df["weekday"] = pd.to_datetime(df["local_date"]).dt.dayofweek < 5
    df = df[df["weekday"]].copy()
    df["key"] = df["link_id"] + "|" + df["tmc_id"]
    df["period"] = df["timestamp_la"].str[11:16].map(period_of)
    test_dates = sorted(df["local_date"].unique())
    summary_rows = []
    series_rows = []
    model_rows = []

    for test_date in test_dates:
        train = df[df["local_date"].ne(test_date)]
        test = df[df["local_date"].eq(test_date)]
        for key in args.links:
            models, mu_by_period, lanes, fitted = fit_training_models(train, key)
            model_rows.extend([{**row, "test_date": test_date, "train_dates": ";".join(sorted(train["local_date"].unique()))} for row in fitted])
            link_test = test[test["key"].eq(key)].copy()
            for period, group in link_test.groupby("period", sort=False):
                if period not in models:
                    continue
                group = group.sort_values("timestamp_la").reset_index(drop=True)
                fd = models[period]
                input_profile = group[["timestamp_la", "speed_mph", "flow_vehph", "period"]].rename(columns={"flow_vehph": "flow_observed_vehph"})
                backward, closure_summary = backward_closure(
                    input_profile,
                    fd,
                    {period: mu_by_period[period]},
                    lanes=lanes,
                    dt_minutes=5,
                )
                branches = backward["congested_by_speed"].map({True: "congested", False: "free"})
                forward = reconstruct_speed_from_flow(backward["flow_inferred_vehph"], fd, lanes=lanes, branch=branches)
                joined = backward.join(forward)
                joined["key"] = key
                joined["test_date"] = test_date
                joined["period"] = period
                joined["speed_observed_mph"] = group["speed_mph"].to_numpy()
                joined["flow_observed_vehph"] = group["flow_vehph"].to_numpy()
                joined["speed_error_mph"] = joined["speed_reconstructed_mph"] - joined["speed_observed_mph"]
                joined["flow_error_vehph"] = joined["flow_inferred_vehph"] - joined["flow_observed_vehph"]
                series_rows.append(joined)
                speed_metrics = closure_speed_metrics(joined)
                obs_vol = float((group["flow_vehph"] * 5 / 60).sum())
                inf_vol = float((joined["flow_inferred_vehph"] * 5 / 60).sum())
                summary_rows.append({
                    "test_date": test_date,
                    "key": key,
                    "link_id": key.split("|", 1)[0],
                    "tmc_id": key.split("|", 1)[1],
                    "period": period,
                    "samples": len(group),
                    "train_days": train["local_date"].nunique(),
                    "observed_volume_veh": obs_vol,
                    "inferred_volume_veh": inf_vol,
                    "volume_error_veh": inf_vol - obs_vol,
                    "volume_error_pct": 100 * (inf_vol - obs_vol) / obs_vol if obs_vol else np.nan,
                    "congestion_duration_h": closure_summary.congestion_duration_h,
                    "t2_time_of_day": group.loc[closure_summary.t2_index, "timestamp_la"] if closure_summary.t2_index is not None else "",
                    "flow_mae_vehph": float(np.mean(np.abs(joined["flow_error_vehph"]))),
                    "flow_rmse_vehph": float(np.sqrt(np.mean(joined["flow_error_vehph"] ** 2))),
                    "speed_mae_mph": speed_metrics["mae"],
                    "speed_rmse_mph": speed_metrics["rmse"],
                    "speed_r2": speed_metrics["r2"],
                    "mu_train_vehph": mu_by_period[period],
                    "validation_type": "leave_one_weekday_out",
                })

    summary = pd.DataFrame(summary_rows)
    summary.to_csv(args.output_dir / "single_link_closure_holdout_summary.csv", index=False)
    pd.concat(series_rows, ignore_index=True).to_csv(args.output_dir / "single_link_closure_holdout_timeseries.csv", index=False)
    pd.DataFrame(model_rows).to_csv(args.output_dir / "single_link_closure_holdout_models.csv", index=False)
    manifest = {"input": str(args.input), "links": args.links, "test_dates": test_dates, "dt_minutes": 5, "note": "S3 and baseline mu fit on other weekdays; no same-day fit."}
    (args.output_dir / "holdout_manifest.json").write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(summary.groupby("period").agg(samples=("samples", "sum"), mean_abs_volume_error_pct=("volume_error_pct", lambda s: s.abs().mean()), mean_flow_mae_vehph=("flow_mae_vehph", "mean"), mean_speed_mae_mph=("speed_mae_mph", "mean")).round(3).to_string())
    print(f"Wrote holdout outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
