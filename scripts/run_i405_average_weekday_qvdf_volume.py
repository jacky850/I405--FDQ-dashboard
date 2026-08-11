"""Mentor-aligned QVDF duration-to-volume calibration and holdout validation."""

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

from fdqbench.time_utils import parse_pems_local_wall_clock  # noqa: E402


TARGETS = ["L405S-012", "L405S-018", "L405S-115"]
LA = "America/Los_Angeles"
N_FROZEN = 1.10
PERIODS = {"AM": (6.0, 10.0), "MD": (10.0, 15.0), "PM": (15.0, 19.0)}
DEFAULT_RAW = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\pems_downloads_d12\proceed\I405\S\train_detector_states.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", type=Path, default=DEFAULT_RAW)
    parser.add_argument(
        "--average-dir", type=Path,
        default=ROOT / "outputs/i405_average_weekday_canonical_direct7",
    )
    parser.add_argument(
        "--daily-episode-file", type=Path,
        default=ROOT / "outputs/i405_speed_only_episodes_direct7/speed_only_asymmetric_episodes.csv",
    )
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/i405_average_weekday_qvdf_volume",
    )
    return parser.parse_args()


def read_flow(path: Path) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    cols = ["timestamp", "station_id", "link_id", "flow", "is_observed", "is_missing"]
    for chunk in pd.read_csv(path, usecols=cols, dtype={"link_id": str}, chunksize=500_000):
        mask = (
            chunk["link_id"].isin(TARGETS)
            & chunk["is_observed"].astype(int).eq(1)
            & chunk["is_missing"].astype(int).eq(0)
            & chunk["timestamp"].astype(str).str[:10].between("2025-06-02", "2025-06-06")
        )
        chunk = chunk[mask].copy()
        if chunk.empty:
            continue
        chunk["timestamp_la"] = parse_pems_local_wall_clock(chunk["timestamp"])
        chunk["local_date"] = chunk["timestamp_la"].dt.strftime("%Y-%m-%d")
        chunk["flow_veh_h"] = pd.to_numeric(chunk["flow"], errors="coerce")
        parts.append(chunk[["link_id", "station_id", "timestamp_la", "local_date", "flow_veh_h"]])
    raw = pd.concat(parts, ignore_index=True)
    return (
        raw.groupby(["link_id", "timestamp_la", "local_date"], as_index=False)
        .agg(flow_veh_h=("flow_veh_h", "mean"), mapped_station_count=("station_id", "nunique"))
        .sort_values(["link_id", "timestamp_la"])
    )


def hour_of(timestamp: pd.Timestamp) -> float:
    return timestamp.hour + timestamp.minute / 60 + timestamp.second / 3600


def period_of(hour: float) -> str | None:
    for name, (start, end) in PERIODS.items():
        if start <= hour < end:
            return name
    return None


def daily_period_ground_truth(flow: pd.DataFrame, link_id: str, period: str) -> pd.DataFrame:
    start, end = PERIODS[period]
    group = flow[flow["link_id"].eq(link_id)].copy()
    group["clock_h"] = group["timestamp_la"].map(hour_of)
    group = group[group["clock_h"].between(start, end, inclusive="left")]
    rows = []
    for date, day in group.groupby("local_date", sort=True):
        rate = day.sort_values("timestamp_la")["flow_veh_h"]
        rows.append({
            "link_id": link_id, "period": period, "local_date": date,
            "period_hours": end-start,
            "observed_period_volume_veh": float(rate.sum() * 5 / 60),
            "observed_mean_flow_veh_h": float(rate.mean()),
            "observed_peak_1h_demand_veh_h": float(rate.rolling(12, min_periods=12).mean().max()),
            "period_bins": int(len(rate)),
        })
    result = pd.DataFrame(rows)
    result["k_d_observed"] = result["observed_peak_1h_demand_veh_h"] / (
        result["observed_period_volume_veh"] / result["period_hours"]
    )
    return result


def primary_daily_episodes(path: Path) -> pd.DataFrame:
    episodes = pd.read_csv(path)
    for col in ["t0_la", "T2_la", "t3_la"]:
        episodes[col] = pd.to_datetime(episodes[col], utc=True, format="mixed").dt.tz_convert(LA)
    episodes["period"] = episodes["T2_la"].map(lambda value: period_of(hour_of(value)))
    episodes = episodes[episodes["period"].notna()].copy()
    # QVDF carries one deepest-queue state per link/day/period.
    index = episodes.groupby(["link_id", "local_date", "period"])["vT2_robust_mph"].idxmin()
    return episodes.loc[index].copy()


def capacity_from_days(flow: pd.DataFrame, link_id: str, dates: set[str]) -> float:
    sample = flow[flow["link_id"].eq(link_id) & flow["local_date"].isin(dates)]["flow_veh_h"]
    return float(sample.quantile(0.95))


def calibrate_duration(rows: pd.DataFrame, capacity: float, n: float = N_FROZEN) -> dict[str, float]:
    x = rows["observed_peak_1h_demand_veh_h"].to_numpy(float) / capacity
    p = rows["P_h"].to_numpy(float)
    fd_samples = p / np.power(x, n)
    return {
        "capacity_vph": capacity,
        "k_d": float(rows["k_d_observed"].median()),
        "f_d_h": float(np.median(fd_samples)),
        "n": n,
        "calibration_episode_count": int(len(rows)),
    }


def inverse_volume(P_h: float, period_hours: float, params: dict[str, float]) -> dict[str, float]:
    x_hat = (P_h / params["f_d_h"]) ** (1 / params["n"])
    D_hat = params["capacity_vph"] * x_hat
    V_hat = period_hours * D_hat / params["k_d"]
    return {"x_hat_D_over_C": x_hat, "D_hat_veh_h": D_hat, "V_hat_veh": V_hat}


def holdout_validation(flow: pd.DataFrame, events: pd.DataFrame) -> pd.DataFrame:
    rows = []
    for (link_id, period), event_group in events.groupby(["link_id", "period"], sort=True):
        truth = daily_period_ground_truth(flow, link_id, period)
        joined = event_group.merge(truth, on=["link_id", "period", "local_date"], validate="one_to_one")
        for _, test in joined.iterrows():
            train = joined[joined["local_date"].ne(test["local_date"])]
            training_dates = set(truth[truth["local_date"].ne(test["local_date"])] ["local_date"])
            if len(train) < 2:
                continue
            params = calibrate_duration(train, capacity_from_days(flow, link_id, training_dates))
            inverse = inverse_volume(float(test["P_h"]), float(test["period_hours"]), params)
            observed = float(test["observed_period_volume_veh"])
            rows.append({
                "link_id": link_id, "period": period, "holdout_date": test["local_date"],
                "P_observed_from_speed_h": test["P_h"], "vT2_observed_mph": test["vT2_robust_mph"],
                **params, **inverse,
                "V_observed_veh": observed,
                "volume_error_veh": inverse["V_hat_veh"]-observed,
                "absolute_percentage_error_pct": abs(inverse["V_hat_veh"]-observed)/observed*100,
                "evidence_status": "held_out_day_speed_duration_to_volume",
            })
    return pd.DataFrame(rows)


def canonical_inverse(
    flow: pd.DataFrame, events: pd.DataFrame, canonical: pd.DataFrame, average_profile: pd.DataFrame
) -> pd.DataFrame:
    rows = []
    all_dates = set(flow["local_date"].unique())
    for _, episode in canonical.iterrows():
        link_id = episode["link_id"]
        period = period_of(hour_of(pd.Timestamp(episode["T2_la"])))
        truth = daily_period_ground_truth(flow, link_id, period)
        event_train = events[(events["link_id"].eq(link_id)) & (events["period"].eq(period))]
        training = event_train.merge(truth, on=["link_id", "period", "local_date"], validate="one_to_one")
        params = calibrate_duration(training, capacity_from_days(flow, link_id, all_dates))
        inverse = inverse_volume(float(episode["P_h"]), float(truth["period_hours"].iloc[0]), params)
        observed = float(truth["observed_period_volume_veh"].mean())
        t2, t3 = pd.Timestamp(episode["T2_la"]), pd.Timestamp(episode["t3_la"])
        start_min, end_min = hour_of(t2)*60, hour_of(t3)*60
        profile_window = average_profile[
            average_profile["link_id"].eq(link_id)
            & average_profile["minute_of_day"].between(start_min, end_min, inclusive="both")
        ]
        mu = float(profile_window["average_observed_flow_veh_h"].median())
        rows.append({
            "episode_id": episode["episode_id"], "link_id": link_id, "period": period,
            "t0_clock_la": episode["t0_clock_la"], "T2_clock_la": episode["T2_clock_la"],
            "t3_clock_la": episode["t3_clock_la"], "P_h": episode["P_h"],
            "vT2_mph": episode["vT2_robust_mph"], **params, **inverse,
            "V_average_weekday_observed_veh": observed,
            "volume_error_veh": inverse["V_hat_veh"]-observed,
            "absolute_percentage_error_pct": abs(inverse["V_hat_veh"]-observed)/observed*100,
            "mu_observed_recovery_median_veh_h": mu,
            "k_mu_observed": mu/params["capacity_vph"],
            "volume_evidence_status": "in_sample_average_weekday_canonical",
            "mu_evidence_status": "observed_flow_derived_not_speed_identified",
        })
    return pd.DataFrame(rows)


def plot_results(holdout: pd.DataFrame, canonical: pd.DataFrame, output_dir: Path) -> None:
    figures = output_dir / "figures"; figures.mkdir(parents=True, exist_ok=True)
    fig, ax = plt.subplots(figsize=(7, 6), constrained_layout=True)
    for link_id, group in holdout.groupby("link_id"):
        ax.scatter(group["V_observed_veh"], group["V_hat_veh"], s=55, label=link_id)
    low = min(holdout["V_observed_veh"].min(), holdout["V_hat_veh"].min())
    high = max(holdout["V_observed_veh"].max(), holdout["V_hat_veh"].max())
    ax.plot([low, high], [low, high], "--", color="0.3", label="1:1")
    ax.set(xlabel="Observed period volume (veh)", ylabel="Speed-duration inferred volume (veh)",
           title="Leave-one-weekday-out QVDF volume validation")
    ax.grid(alpha=.2); ax.legend(frameon=False)
    fig.savefig(figures / "holdout_volume_observed_vs_inferred.png", dpi=190); plt.close(fig)

    x = np.arange(len(canonical)); width=.36
    fig, ax = plt.subplots(figsize=(9, 5), constrained_layout=True)
    ax.bar(x-width/2, canonical["V_average_weekday_observed_veh"], width, label="observed")
    ax.bar(x+width/2, canonical["V_hat_veh"], width, label="QVDF inferred")
    ax.set_xticks(x, canonical["episode_id"], rotation=15, ha="right")
    ax.set(ylabel="period volume (veh)", title="Average-weekday canonical period volume")
    ax.grid(axis="y", alpha=.2); ax.legend(frameon=False)
    fig.savefig(figures / "canonical_average_weekday_volume.png", dpi=190); plt.close(fig)


def main() -> None:
    args = parse_args(); args.output_dir.mkdir(parents=True, exist_ok=True)
    flow = read_flow(args.raw_file)
    daily = primary_daily_episodes(args.daily_episode_file)
    canonical = pd.read_csv(args.average_dir / "canonical_average_weekday_episodes.csv")
    for col in ["t0_la", "T2_la", "t3_la"]:
        canonical[col] = pd.to_datetime(canonical[col], utc=True, format="mixed").dt.tz_convert(LA)
    average_profile = pd.read_csv(args.average_dir / "average_weekday_speed_flow_5min.csv")
    holdout = holdout_validation(flow, daily[daily["link_id"].isin(TARGETS)])
    canonical_result = canonical_inverse(flow, daily, canonical, average_profile)
    holdout["structural_audit_flag"] = np.where(
        holdout["absolute_percentage_error_pct"].gt(100),
        "duration_volume_relation_failure_gt100pct",
        "none",
    )
    by_link = (
        holdout.groupby(["link_id", "period"], as_index=False)
        .agg(
            holdout_cases=("holdout_date", "size"),
            MAE_veh=("volume_error_veh", lambda values: values.abs().mean()),
            MAPE_pct=("absolute_percentage_error_pct", "mean"),
            median_APE_pct=("absolute_percentage_error_pct", "median"),
            max_APE_pct=("absolute_percentage_error_pct", "max"),
        )
    )
    holdout.to_csv(args.output_dir / "daily_leave_one_out_qvdf_volume_validation.csv", index=False)
    by_link.to_csv(args.output_dir / "daily_leave_one_out_metrics_by_link.csv", index=False)
    canonical_result.to_csv(args.output_dir / "average_weekday_canonical_qvdf_volume.csv", index=False)
    plot_results(holdout, canonical_result, args.output_dir)
    summary = {
        "formula": "P=f_d*(D/C)^n; D=k_d*V/Tp; inverse V=Tp*C*(P/f_d)^(1/n)/k_d",
        "stress_basis": "D_over_C", "n_status": "assumed_frozen_from_mentor_gold", "n": N_FROZEN,
        "holdout_cases": len(holdout),
        "holdout_MAE_veh": float(holdout["volume_error_veh"].abs().mean()),
        "holdout_MAPE_pct": float(holdout["absolute_percentage_error_pct"].mean()),
        "holdout_median_APE_pct": float(holdout["absolute_percentage_error_pct"].median()),
        "holdout_structural_failure_cases_gt100pct": int(holdout["structural_audit_flag"].ne("none").sum()),
        "canonical_cases": len(canonical_result),
        "canonical_MAE_veh": float(canonical_result["volume_error_veh"].abs().mean()),
        "canonical_MAPE_pct": float(canonical_result["absolute_percentage_error_pct"].mean()),
        "identifiability_note": "C, k_d, and f_d are calibrated from observed flow; mu is observed-flow-derived. Neither is identified from speed alone.",
        "decision": "average-weekday in-sample closure passes provisionally, but held-out volume transfer fails and must be improved before release",
    }
    (args.output_dir / "qvdf_volume_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
