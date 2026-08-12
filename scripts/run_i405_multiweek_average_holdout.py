"""Leave-one-week-out QVDF validation on independent average-weekday profiles."""

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


TARGET_LINKS = [
    "L405S-012", "L405S-018", "L405S-028", "L405S-030",
    "L405S-058", "L405S-098", "L405S-115",
]
PERIODS = {"AM": (6.0, 10.0), "PM": (15.0, 19.0)}
LA = "America/Los_Angeles"
KM_TO_MI = 0.621371192237334
N_FROZEN = 1.10
S_FROZEN = 1.40
RATIO_LIMITS = (0.50, 2.00)
MAX_SPEED_ERROR_MPH = 10.0
DURATION_EXTRAPOLATION_LIMIT = 1.25
HOLIDAY_WEEKS = {"2025-06-30": "contains_2025-07-04"}
ANCHOR = pd.Timestamp("2000-01-02", tz=LA)
DEFAULT_RAW = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\pems_downloads_d12\proceed\I405\S\train_detector_states.csv"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", type=Path, default=DEFAULT_RAW)
    parser.add_argument("--start", default="2025-06-02")
    parser.add_argument("--end", default="2025-08-29")
    parser.add_argument(
        "--output-dir", type=Path,
        default=ROOT / "outputs/i405_multiweek_average_holdout",
    )
    return parser.parse_args()


def read_observations(path: Path, start: str, end: str) -> pd.DataFrame:
    parts: list[pd.DataFrame] = []
    cols = ["timestamp", "station_id", "link_id", "speed", "flow", "is_observed", "is_missing"]
    for chunk in pd.read_csv(path, usecols=cols, dtype={"link_id": str}, chunksize=500_000):
        date_text = chunk["timestamp"].astype(str).str[:10]
        mask = (
            chunk["link_id"].isin(TARGET_LINKS)
            & chunk["is_observed"].astype(int).eq(1)
            & chunk["is_missing"].astype(int).eq(0)
            & date_text.between(start, end)
        )
        chunk = chunk[mask].copy()
        if chunk.empty:
            continue
        chunk["timestamp_la"] = parse_pems_local_wall_clock(chunk["timestamp"])
        chunk["local_date"] = chunk["timestamp_la"].dt.strftime("%Y-%m-%d")
        chunk["speed_mph"] = pd.to_numeric(chunk["speed"], errors="coerce") * KM_TO_MI
        chunk["flow_veh_h"] = pd.to_numeric(chunk["flow"], errors="coerce")
        parts.append(chunk[["link_id", "station_id", "timestamp_la", "local_date", "speed_mph", "flow_veh_h"]])
    raw = pd.concat(parts, ignore_index=True)
    link = (
        raw.groupby(["link_id", "timestamp_la", "local_date"], as_index=False)
        .agg(speed_mph=("speed_mph", "mean"), flow_veh_h=("flow_veh_h", "mean"), mapped_stations=("station_id", "nunique"))
    )
    link["date_dt"] = pd.to_datetime(link["local_date"])
    link["week_start"] = (
        link["date_dt"] - pd.to_timedelta(link["date_dt"].dt.weekday, unit="D")
    ).dt.strftime("%Y-%m-%d")
    link["minute_of_day"] = link["timestamp_la"].dt.hour*60 + link["timestamp_la"].dt.minute
    return link


def build_week_profiles(observations: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    weekday = observations[observations["date_dt"].dt.weekday < 5].copy()
    completeness = (
        weekday.groupby(["link_id", "week_start"], as_index=False)
        .agg(contributing_days=("local_date", "nunique"), observed_rows=("timestamp_la", "size"))
    )
    complete = completeness[
        completeness["contributing_days"].eq(5)
        & completeness["observed_rows"].ge(5*288)
        & ~completeness["week_start"].isin(HOLIDAY_WEEKS)
    ][["link_id", "week_start"]]
    eligible = weekday.merge(complete, on=["link_id", "week_start"], how="inner")
    profile = (
        eligible.groupby(["link_id", "week_start", "minute_of_day"], as_index=False)
        .agg(
            average_speed_mph=("speed_mph", "mean"),
            average_flow_veh_h=("flow_veh_h", "mean"),
            speed_sd_mph=("speed_mph", "std"),
            flow_sd_veh_h=("flow_veh_h", "std"),
            contributing_days=("local_date", "nunique"),
        )
        .sort_values(["link_id", "week_start", "minute_of_day"])
    )
    completeness["exclusion_reason"] = np.where(
        completeness["week_start"].isin(HOLIDAY_WEEKS),
        completeness["week_start"].map(HOLIDAY_WEEKS),
        np.where(
            completeness["contributing_days"].ne(5) | completeness["observed_rows"].lt(5*288),
            "incomplete_week",
            "included",
        ),
    )
    return profile, completeness


def tiled(group: pd.DataFrame) -> pd.DataFrame:
    frames=[]
    for offset in (-1,0,1):
        frame=group.copy()
        frame["timestamp_la"] = ANCHOR + pd.Timedelta(days=offset) + pd.to_timedelta(frame["minute_of_day"], unit="m")
        frames.append(frame)
    return pd.concat(frames,ignore_index=True).sort_values("timestamp_la")


def hour(timestamp: pd.Timestamp) -> float:
    return timestamp.hour + timestamp.minute/60 + timestamp.second/3600


def detect_week_states(profile: pd.DataFrame) -> pd.DataFrame:
    cfg=EpisodeDetectionConfig()
    rows=[]
    for (link_id,week), group in profile.groupby(["link_id","week_start"],sort=True):
        free_speed=float(group["average_speed_mph"].quantile(.95))
        three=tiled(group)
        episodes,_=detect_speed_episodes(three["timestamp_la"],three["average_speed_mph"],free_speed,cfg)
        if len(episodes):
            episodes["T2_ts"]=pd.to_datetime(episodes["T2_la"],utc=True).dt.tz_convert(LA)
        for period,(start,end) in PERIODS.items():
            candidates=[]
            if len(episodes):
                candidates=episodes[
                    (episodes["T2_ts"].dt.date==ANCHOR.date())
                    & episodes["T2_ts"].map(lambda value:start<=hour(value)<end)
                ]
            period_profile=group[group["minute_of_day"].between(start*60,end*60,inclusive="left")].sort_values("minute_of_day")
            rate=period_profile["average_flow_veh_h"]
            base={
                "link_id":link_id,"period":period,"week_start":week,"period_hours":end-start,
                "free_speed_p95_mph":free_speed,
                "period_minimum_average_speed_mph":float(period_profile["average_speed_mph"].min()),
                "observed_average_period_volume_veh":float(rate.sum()*5/60),
                "observed_peak_1h_demand_veh_h":float(rate.rolling(12,min_periods=12).mean().max()),
                "capacity_proxy_week_p95_vph":float(group["average_flow_veh_h"].quantile(.95)),
                "profile_bins":len(group),"period_bins":len(period_profile),
            }
            base["period_minimum_speed_over_free_speed"] = base["period_minimum_average_speed_mph"] / free_speed
            base["k_d_observed"] = base["observed_peak_1h_demand_veh_h"]/(base["observed_average_period_volume_veh"]/base["period_hours"])
            if len(candidates):
                episode=candidates.loc[candidates["vT2_robust_mph"].idxmin()]
                base.update({
                    "episode_identified":True,"P_h":float(episode["P_h"]),
                    "vT2_mph":float(episode["vT2_robust_mph"]),
                    "cutoff_speed_vc_mph":float(episode["exit_threshold_mph"]),
                    "t0_la":episode["t0_la"],"T2_la":episode["T2_la"],"t3_la":episode["t3_la"],
                    "quality_status":episode["quality_status"],
                })
            else:
                base.update({"episode_identified":False,"quality_status":"no_canonical_episode"})
            rows.append(base)
    return pd.DataFrame(rows)


def calibrate(train_all: pd.DataFrame) -> dict[str,float]:
    train_episode=train_all[train_all["episode_identified"]].dropna(subset=["P_h","vT2_mph"])
    C=float(train_all["capacity_proxy_week_p95_vph"].median())
    kd=float(train_all["k_d_observed"].median())
    x=train_episode["observed_peak_1h_demand_veh_h"].to_numpy(float)/C
    training_max_x=float(np.max(x)) if len(x) else np.nan
    if len(train_episode) < 2:
        return {"capacity_vph":C,"k_d":kd,"f_d_h":np.nan,"f_p":np.nan,"n":N_FROZEN,"s":S_FROZEN,"training_weeks":int(train_all["week_start"].nunique()),"training_episode_weeks":int(len(train_episode)),"training_max_observed_D_over_C":training_max_x}
    fd=float(np.median(train_episode["P_h"].to_numpy(float)/np.power(x,N_FROZEN)))
    z=train_episode["cutoff_speed_vc_mph"].to_numpy(float)/train_episode["vT2_mph"].to_numpy(float)-1
    fp=float(np.median(z/np.power(train_episode["P_h"].to_numpy(float),S_FROZEN)))
    return {"capacity_vph":C,"k_d":kd,"f_d_h":fd,"f_p":fp,"n":N_FROZEN,"s":S_FROZEN,"training_weeks":int(train_all["week_start"].nunique()),"training_episode_weeks":int(len(train_episode)),"training_max_observed_D_over_C":training_max_x}


def leave_one_week_out(states: pd.DataFrame) -> pd.DataFrame:
    rows=[]
    for (link_id,period), group in states.groupby(["link_id","period"],sort=True):
        for _,test in group.iterrows():
            train=group[group["week_start"].ne(test["week_start"])]
            params=calibrate(train)
            base={**test.to_dict(),**params,"evidence_status":"holdout_week_flow_hidden_during_inference"}
            if not bool(test["episode_identified"]):
                base.update({"inverse_status":"not_identified_no_speed_episode","speed_branch_supported":False,"duration_branch_supported":False,"final_supported":False})
                rows.append(base); continue
            if params["training_episode_weeks"] < 2:
                base.update({"inverse_status":"not_identified_insufficient_training_episode_weeks","speed_branch_supported":False,"duration_branch_supported":False,"final_supported":False})
                rows.append(base); continue
            P=float(test["P_h"])
            xhat=(P/params["f_d_h"])**(1/params["n"])
            Dhat=params["capacity_vph"]*xhat
            Vhat=float(test["period_hours"])*Dhat/params["k_d"]
            zhat=params["f_p"]*P**params["s"]
            vc=float(test["cutoff_speed_vc_mph"])
            vhat=vc/(1+zhat)
            vobs=float(test["vT2_mph"])
            zobs=vc/vobs-1
            ratio=zobs/zhat if zhat>0 else np.nan
            speed_error=vhat-vobs
            speed_supported=bool(RATIO_LIMITS[0]<=ratio<=RATIO_LIMITS[1] and abs(speed_error)<=MAX_SPEED_ERROR_MPH)
            duration_extrapolation_ratio=xhat/params["training_max_observed_D_over_C"]
            duration_supported=bool(duration_extrapolation_ratio<=DURATION_EXTRAPOLATION_LIMIT)
            final_supported=bool(speed_supported and duration_supported)
            if not speed_supported:
                inverse_status="not_identified_speed_branch_failure"
            elif not duration_supported:
                inverse_status="not_identified_duration_extrapolation"
            else:
                inverse_status="identified_under_calibrated_qvdf"
            observed=float(test["observed_average_period_volume_veh"])
            base.update({
                "x_hat_D_over_C":xhat,"D_hat_veh_h":Dhat,"V_hat_veh":Vhat,
                "volume_error_veh":Vhat-observed,"absolute_percentage_error_pct":abs(Vhat-observed)/observed*100,
                "z_observed":zobs,"z_predicted":zhat,"severity_ratio":ratio,
                "vT2_predicted_mph":vhat,"vT2_error_mph":speed_error,
                "speed_branch_supported":speed_supported,
                "duration_extrapolation_ratio":duration_extrapolation_ratio,
                "duration_extrapolation_limit":DURATION_EXTRAPOLATION_LIMIT,
                "duration_branch_supported":duration_supported,
                "final_supported":final_supported,
                "inverse_status":inverse_status,
            })
            rows.append(base)
    return pd.DataFrame(rows)


def plot_results(result: pd.DataFrame, output_dir: Path) -> None:
    figures=output_dir/"figures"; figures.mkdir(parents=True,exist_ok=True)
    identified=result[result["episode_identified"]].copy()
    colors=np.where(identified["final_supported"],"#2563eb","#dc2626")
    fig,ax=plt.subplots(figsize=(8,6),constrained_layout=True)
    ax.scatter(identified["observed_average_period_volume_veh"],identified["V_hat_veh"],c=colors,s=55)
    low=min(identified["observed_average_period_volume_veh"].min(),identified["V_hat_veh"].min())
    high=max(identified["observed_average_period_volume_veh"].max(),identified["V_hat_veh"].max())
    ax.plot([low,high],[low,high],"--",color="0.35")
    ax.set(xlabel="Holdout-week observed average period volume (veh)",ylabel="Speed-only inferred volume (veh)",title="Leave-one-week-out average-weekday QVDF validation\nblue=supported, red=abstain")
    ax.grid(alpha=.2); fig.savefig(figures/"multiweek_holdout_volume_scatter.png",dpi=190); plt.close(fig)

    weeks=sorted(result["week_start"].unique())
    cases=[(link,period) for link in TARGET_LINKS for period in PERIODS]
    matrix=np.zeros((len(cases),len(weeks)))
    labels={"not_identified_no_speed_episode":0,"not_identified_insufficient_training_episode_weeks":1,"not_identified_speed_branch_failure":2,"not_identified_duration_extrapolation":3,"identified_under_calibrated_qvdf":4}
    for i,(link,period) in enumerate(cases):
        for j,week in enumerate(weeks):
            row=result[result["link_id"].eq(link)&result["period"].eq(period)&result["week_start"].eq(week)].iloc[0]
            matrix[i,j]=labels[row["inverse_status"]]
    fig,ax=plt.subplots(figsize=(13,7.5),constrained_layout=True)
    image=ax.imshow(matrix,aspect="auto",vmin=0,vmax=4,cmap=plt.matplotlib.colors.ListedColormap(["#d1d5db","#f59e0b","#dc2626","#7c3aed","#2563eb"]))
    ax.set_yticks(range(len(cases)),[f"{link} {period}" for link,period in cases]); ax.set_xticks(range(len(weeks)),weeks,rotation=45,ha="right")
    ax.set_title("Weekly inference status: gray=no episode, red=speed-gate fail, purple=duration extrapolation, blue=identified")
    fig.savefig(figures/"multiweek_coverage_matrix.png",dpi=190); plt.close(fig)


def plot_representative_episode(
    profile: pd.DataFrame, states: pd.DataFrame, output_dir: Path,
) -> None:
    """Plot one supported weekly average-speed episode used by the inverse."""
    link_id, week_start, period = "L405S-115", "2025-08-04", "AM"
    row = states[
        states["link_id"].eq(link_id)
        & states["week_start"].eq(week_start)
        & states["period"].eq(period)
    ].iloc[0]
    curve = profile[
        profile["link_id"].eq(link_id)
        & profile["week_start"].eq(week_start)
    ].sort_values("minute_of_day")

    def minute(value: str) -> float:
        timestamp = pd.to_datetime(value, format="mixed", utc=True).tz_convert(LA)
        return timestamp.hour * 60 + timestamp.minute + timestamp.second / 60

    t0, t2, t3 = minute(row["t0_la"]), minute(row["T2_la"]), minute(row["t3_la"])
    figures=output_dir/"figures"; figures.mkdir(parents=True,exist_ok=True)
    fig,ax=plt.subplots(figsize=(11,4.5),constrained_layout=True)
    ax.plot(curve["minute_of_day"]/60,curve["average_speed_mph"],color="#2563eb",lw=2,label="weekly average-weekday speed")
    ax.axhline(row["cutoff_speed_vc_mph"],color="#059669",ls="--",label=r"episode cutoff $v_c$")
    ax.axvspan(t0/60,t3/60,color="#ef4444",alpha=.16,label=r"canonical episode $[t_0,t_3]$")
    ax.axvline(t2/60,color="#dc2626",lw=1.5,label=r"$T_2$ (minimum speed)")
    ax.scatter([t2/60],[row["vT2_mph"]],color="#dc2626",zorder=3)
    ax.set(xlim=(0,24),xlabel="Los Angeles local time",ylabel="Speed (mph)",title=f"Representative speed-only episode: {link_id} {period}, week of {week_start}")
    ax.set_xticks(range(0,25,3)); ax.grid(alpha=.2); ax.legend(ncol=2,fontsize=9)
    fig.savefig(figures/"representative_weekly_speed_episode.png",dpi=190); plt.close(fig)


def metrics(result:pd.DataFrame)->pd.DataFrame:
    rows=[]
    subsets=[("all_link_periods",result)]
    subsets.extend((f"{link}_{period}",group) for (link,period),group in result.groupby(["link_id","period"]))
    for name,group in subsets:
        episode=group[group["episode_identified"]]
        supported=episode[episode["final_supported"]]
        rows.append({
            "subset":name,"eligible_weeks":len(group),"episode_weeks":len(episode),"supported_weeks":len(supported),
            "episode_coverage_pct":len(episode)/len(group)*100,
            "final_identified_coverage_pct":len(supported)/len(group)*100,
            "volume_MAPE_forced_episode_weeks_pct":episode["absolute_percentage_error_pct"].mean(),
            "volume_median_APE_forced_episode_weeks_pct":episode["absolute_percentage_error_pct"].median(),
            "volume_MAPE_supported_pct":supported["absolute_percentage_error_pct"].mean() if len(supported) else np.nan,
            "volume_median_APE_supported_pct":supported["absolute_percentage_error_pct"].median() if len(supported) else np.nan,
            "vT2_MAE_episode_weeks_mph":episode["vT2_error_mph"].abs().mean(),
        })
    return pd.DataFrame(rows)


def main()->None:
    args=parse_args(); args.output_dir.mkdir(parents=True,exist_ok=True)
    observations=read_observations(args.raw_file,args.start,args.end)
    profile,completeness=build_week_profiles(observations)
    states=detect_week_states(profile)
    result=leave_one_week_out(states)
    metric=metrics(result)
    profile.to_csv(args.output_dir/"weekly_average_weekday_profiles_5min.csv",index=False)
    completeness.to_csv(args.output_dir/"weekly_data_completeness.csv",index=False)
    states.to_csv(args.output_dir/"weekly_canonical_states_and_ground_truth.csv",index=False)
    result.to_csv(args.output_dir/"leave_one_week_out_qvdf_results.csv",index=False)
    metric.to_csv(args.output_dir/"leave_one_week_out_metrics.csv",index=False)
    result[result["final_supported"]].to_csv(args.output_dir/"supported_case_accuracy.csv",index=False)
    plot_results(result,args.output_dir)
    plot_representative_episode(profile,states,args.output_dir)
    overall=metric[metric["subset"].eq("all_link_periods")].iloc[0]
    summary={
        "calendar_weeks_found":int(completeness["week_start"].nunique()),
        "holiday_weeks_excluded":HOLIDAY_WEEKS,
        "links":len(TARGET_LINKS),
        "periods":list(PERIODS),
        "ordinary_complete_weeks_per_link_period":int(states.groupby(["link_id","period"])["week_start"].nunique().min()),
        "link_week_cases":int(len(result)),
        "episode_weeks":int(overall["episode_weeks"]),
        "supported_weeks":int(overall["supported_weeks"]),
        "no_episode_weeks":int(result["inverse_status"].eq("not_identified_no_speed_episode").sum()),
        "speed_gate_failures":int(result["inverse_status"].eq("not_identified_speed_branch_failure").sum()),
        "duration_extrapolation_gate_failures":int(result["inverse_status"].eq("not_identified_duration_extrapolation").sum()),
        "final_identified_coverage_pct":float(overall["final_identified_coverage_pct"]),
        "volume_MAPE_supported_pct":float(overall["volume_MAPE_supported_pct"]),
        "volume_median_APE_supported_pct":float(overall["volume_median_APE_supported_pct"]),
        "duration_extrapolation_limit":DURATION_EXTRAPOLATION_LIMIT,
        "protocol":"train on other weekly average-weekday profiles; hide all holdout-week flow during P/vT2 inference; score after inference",
    }
    (args.output_dir/"multiweek_holdout_summary.json").write_text(json.dumps(summary,indent=2),encoding="utf-8")
    print(json.dumps(summary,indent=2))


if __name__=="__main__":
    main()
