"""Run the first real-data Single-Link Closure validation on four I-405 links.

This is an initial round-trip diagnostic. It uses the processed average-weekday
PeMS profile, fits a period-specific S3 model on the selected link, estimates a
period service rate from observed flow, runs the backward queue calculation,
and reconstructs speed from inferred flow using the observed S3 branch.

Because the S3 fit and branch labels are obtained from the same profile, this
script is a closure/implementation check, not a held-out accuracy experiment.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.calibrate import fit_s3_from_speed_flow
from fdqbench.closure import backward_closure, closure_speed_metrics, reconstruct_speed_from_flow
from fdqbench.fd import S3FD
from fdqbench.reference import clock_minutes


PERIODS = [("NT1", 0, 6), ("AM", 6, 10), ("MD", 10, 15), ("PM", 15, 19), ("NT2", 19, 24)]
DEFAULT_LINKS = {
    "L405S-001|1222782",
    "L405S-001|1223027",
    "L405S-020|1201419",
    "L405S-061|1201350",
}


def period_of(value: str) -> str:
    hour = int(str(value).split(":", 1)[0])
    for name, start, end in PERIODS:
        if start <= hour < end:
            return name
    return "NT2"


def dashboard_link_metadata(path: Path) -> dict[str, dict]:
    text = path.read_text(encoding="utf-8")
    payload = text.split("window.DASHBOARD_DATA = ", 1)[1].rsplit(";", 1)[0]
    data = json.loads(payload)
    out = {}
    for item in data["links"]:
        key = f"{item['linkId']}|{item['tmcId']}"
        out[key] = {
            "lanes": float(item.get("lanes", 1.0)),
            "link_id": str(item["linkId"]),
            "tmc_id": str(item["tmcId"]),
        }
    return out


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument(
        "--input",
        type=Path,
        default=ROOT / "data/jinxi_i405_week_2025-06-16_to_22/average_weekday_fdqbench.csv",
    )
    p.add_argument("--dashboard-data", type=Path, default=ROOT / "data.js")
    p.add_argument("--output-dir", type=Path, default=ROOT / "outputs/i405_closure_validation_direct4")
    p.add_argument("--links", nargs="*", default=sorted(DEFAULT_LINKS))
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    df = pd.read_csv(args.input, dtype={"link_id": str, "tmc_id": str})
    meta = dashboard_link_metadata(args.dashboard_data)
    df["key"] = df["link_id"].astype(str) + "|" + df["tmc_id"].astype(str)
    df["period"] = df["time_of_day"].map(period_of)

    summaries = []
    timeseries = []
    model_rows = []
    for key in args.links:
        if key not in meta:
            raise ValueError(f"No lane metadata in dashboard data for {key}")
        sub = df[df["key"].eq(key)].copy().sort_values("time_of_day")
        if sub.empty:
            raise ValueError(f"No average-weekday rows found for {key}")
        lanes = meta[key]["lanes"]
        # Fit one S3 model per period to match the current period-S3 dashboard
        # candidate. This is intentionally an in-sample closure check.
        sub_models = {}
        for period, group in sub.groupby("period", sort=False):
            fit, info = fit_s3_from_speed_flow(group["speed_mph"], group["flow_vehph"], lanes=lanes)
            sub_models[period] = fit
            model_rows.append({"key": key, "period": period, **fit.to_dict(), **{f"fit_{k}": v for k, v in info.items()}})

        parts = []
        for period, group in sub.groupby("period", sort=False):
            group = group.copy().reset_index(drop=True)
            fd = sub_models[period]
            group["flow_model_vehph"] = fd.flow_from_speed(group["speed_mph"].to_numpy()) * lanes
            group["speed_branch"] = np.where(group["speed_mph"] < fd.critical_speed_mph, "congested", "free")
            group["mu_period_vehph"] = group["flow_vehph"].median()
            # Run backward for the period, retaining observed flow for volume QA.
            backward, closure_summary = backward_closure(
                group.rename(columns={"flow_vehph": "flow_observed_vehph"}),
                fd,
                {period: float(group["mu_period_vehph"].iloc[0])},
                lanes=lanes,
                dt_minutes=5,
            )
            forward = reconstruct_speed_from_flow(
                backward["flow_inferred_vehph"], fd, lanes=lanes, branch=backward["congested_by_speed"].map({True: "congested", False: "free"})
            )
            backward = backward.join(forward)
            backward["key"] = key
            backward["period"] = period
            backward["speed_observed_mph"] = group["speed_mph"].to_numpy()
            backward["flow_observed_vehph"] = group["flow_vehph"].to_numpy()
            backward["speed_error_mph"] = backward["speed_reconstructed_mph"] - backward["speed_observed_mph"]
            backward["flow_error_vehph"] = backward["flow_inferred_vehph"] - backward["flow_observed_vehph"]
            timeseries.append(backward)
            speed_metrics = closure_speed_metrics(backward)
            observed_volume = float((group["flow_vehph"] * 5.0 / 60.0).sum())
            inferred_volume = float((backward["flow_inferred_vehph"] * 5.0 / 60.0).sum())
            summaries.append({
                "key": key,
                "link_id": meta[key]["link_id"],
                "tmc_id": meta[key]["tmc_id"],
                "lanes": lanes,
                "period": period,
                "samples": len(group),
                "observed_volume_veh": observed_volume,
                "inferred_volume_veh": inferred_volume,
                "volume_error_veh": inferred_volume - observed_volume,
                "volume_error_pct": 100.0 * (inferred_volume - observed_volume) / observed_volume if observed_volume else np.nan,
                "congestion_duration_h": closure_summary.congestion_duration_h,
                "t2_time_of_day": group.loc[closure_summary.t2_index, "time_of_day"] if closure_summary.t2_index is not None else "",
                "speed_mae_mph": speed_metrics["mae"],
                "speed_rmse_mph": speed_metrics["rmse"],
                "speed_r2": speed_metrics["r2"],
                "flow_mae_vehph": float(np.mean(np.abs(backward["flow_error_vehph"]))),
                "flow_rmse_vehph": float(np.sqrt(np.mean(backward["flow_error_vehph"] ** 2))),
                "mu_period_vehph": float(group["mu_period_vehph"].iloc[0]),
                "closure_note": "in_sample_period_s3_round_trip",
            })

    pd.DataFrame(summaries).to_csv(args.output_dir / "single_link_closure_period_summary.csv", index=False)
    pd.concat(timeseries, ignore_index=True).to_csv(args.output_dir / "single_link_closure_timeseries.csv", index=False)
    pd.DataFrame(model_rows).to_csv(args.output_dir / "single_link_closure_s3_models.csv", index=False)
    print(pd.DataFrame(summaries).to_string(index=False))
    print(f"Wrote closure outputs to {args.output_dir}")


if __name__ == "__main__":
    main()
