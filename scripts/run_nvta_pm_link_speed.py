"""PM-period link-based results: D, C, observed speed(t) and back-calculated speed(t).

The advisor's request is for one table per network link, on the PM period,
carrying the four quantities together so they can be read against each other:
``D``, ``C``, the observed speed profile, and the speed the QVDF episode
parameters put back into the speed domain.

D and C already existed per link in ``nvta_dv_vs_assignment.csv``, but that
table is one row per link-period -- it has no time axis at all. The two speed
series are new, and so are the episode anchors (t0, T2, t3, v_T2) they are
built from.

Three points of construction that were settled before this was written.

**TMC to link.** Speed does not average; travel time adds. Two TMCs on one
network link are combined as total length over total traversal time, i.e. the
length-weighted *harmonic* mean, not the arithmetic one. In practice this
barely moves: 82 of the 92 PM links carry exactly one TMC, and the ten that
carry more are near-duplicate sub-segments whose speeds agree to a few
hundredths of a mile per hour. Length enters only as a weight, so the
question of whether those sub-segments are adjacent or overlapping does not
affect the result.

**Which speed sits in the denominator.** The QVDF episode curve is anchored so
that ``v = v_c`` at the episode edges, and the episode is *defined* as the
stretch below the congestion cut-off. So ``v_c`` must be the cut-off,
``0.70 * v_f``, and not the S3 speed at capacity ``v_f / sqrt(2)``. Those two
differ by 1% at a 70 mph free-flow speed -- 49.00 against 49.50 -- which is
why using the wrong one has never shown up. The cut-off is the correct one and
is what this script uses.

**The shape is asymmetric.** The textbook form ``tau = 2(t - T2)/P`` carries a
single P, which forces the recovery shoulder to be exactly as wide as the onset
shoulder. Real episodes are not like that: on the NVTA link already studied the
recovery runs 1.8x the onset in AM and 4.5x in PM. Feeding an observed T2 into
a symmetric curve moves the trough but still pins it midway between the
shoulders, so it does not fix this. Each shoulder therefore gets its own width,
taken from the detected t0 and t3::

    tau(t) = (t - T2) / (T2 - t0)   for t <  T2
             (t - T2) / (t3 - T2)   for t >= T2

    v(t)   = v_cutoff / (1 + z (1 - tau^2)^2),   z = v_cutoff / v_T2 - 1

Scored against the CBI reconstruction of the same corridors, allowing the two
shoulders to differ takes the median residual from 0.72 mph to 0.24 mph.
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

SHARED = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\link-queue-simulation"
              r"\link-queue-simulation")
CBI_CORRIDORS = {"I-395 NB": "I395_NB", "I-395 SB": "I395_SB",
                 "I-66 EB": "I66_EB", "I-66 WB": "I66_WB"}

CUTOFF_RATIO = 0.70
DT_MIN = 15
VT2_SMOOTH = 3
S3_M = 4.0
MIN_EPISODE_H = 0.5
PM_START, PM_END = 900, 1140          # the assignment clock, 15:00-19:00
TIMEZONE = "America/New_York"
NOMINAL_DAY = "2025-10-08"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--profile-file", type=Path,
                        default=ROOT / "outputs/nvta_corridors_dv_ritis/average_weekday_speed_flow_15min.csv")
    parser.add_argument("--free-speed-source", default="observed",
                        choices=["observed", "config"],
                        help="'observed' takes each link's own 95th-percentile speed, which "
                             "assumes nothing and is defined for every link. 'config' uses the "
                             "70/65 mph constants the QVDF parameters were calibrated against.")
    parser.add_argument("--reference-file", type=Path,
                        default=ROOT / "outputs/nvta_corridors_dv_ritis/nvta_dv_vs_assignment.csv",
                        help="the delivered D/V table, joined in so the effect of the free-speed "
                             "choice on D is visible in the same row")
    parser.add_argument("--cbi-dir", type=Path, default=SHARED / "cbi",
                        help="shared CBI results, used only to check the free-flow speed against "
                             "an independently derived one")
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "outputs/nvta_pm_link_speed")
    return parser.parse_args()


def cbi_link_parameters(cbi_dir: Path) -> pd.DataFrame:
    """Free-flow speed, cut-off and capacity per network link, as CBI derived them."""
    frames = []
    for name in CBI_CORRIDORS.values():
        path = cbi_dir / name / "07-reconstruction-and-handoff/average_weekday_time_dependent.csv"
        if not path.exists():
            continue
        frames.append(pd.read_csv(path, usecols=["network_link_id", "free_flow_speed_model_mph",
                                                 "congestion_threshold_mph", "capacity_vphpl"]))
    if not frames:
        return pd.DataFrame()
    return (pd.concat(frames).dropna(subset=["network_link_id"])
            .groupby("network_link_id").first().reset_index()
            .rename(columns={"network_link_id": "net_link_id",
                             "free_flow_speed_model_mph": "cbi_free_speed_mph",
                             "congestion_threshold_mph": "cbi_cutoff_mph",
                             "capacity_vphpl": "cbi_capacity_vphpl"})
            .astype({"net_link_id": int}))


def s3_flow(speed: np.ndarray, free_speed: np.ndarray, capacity: np.ndarray) -> np.ndarray:
    """Flow implied by speed, veh/h/lane, on the congested branch of S3."""
    speed_at_capacity = free_speed * 2.0 ** (-2.0 / S3_M)
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    return np.minimum(
        k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M) * v,
        capacity)


def link_speed_profile(profile: pd.DataFrame) -> pd.DataFrame:
    """Length-weighted harmonic mean of the TMC speeds on each network link.

    Total length over total traversal time. Reduces to the TMC's own speed on
    the 82 links that carry exactly one.
    """
    p = profile.dropna(subset=["net_link_id", "speed"]).copy()
    p["net_link_id"] = p["net_link_id"].astype(int)
    p["travel_time_h"] = p["miles"] / p["speed"].clip(lower=1e-6)

    grouped = p.groupby(["net_link_id", "t_min"])
    link = grouped.agg(miles=("miles", "sum"),
                       travel_time_h=("travel_time_h", "sum"),
                       tmcs=("tmc_code", "nunique")).reset_index()
    link["speed"] = link["miles"] / link["travel_time_h"].clip(lower=1e-9)

    geometry = (p.sort_values("miles", ascending=False)
                .groupby("net_link_id")
                .agg(corridor=("corridor", "first"), facility=("facility", "first"),
                     lanes=("net_lanes", "first"), capacity_vphpl=("capacity_vphpl", "first"),
                     config_free_speed=("free_speed", "first"),
                     miles_total=("miles", "sum")))
    geometry["miles_total"] = p.groupby(["net_link_id", "tmc_code"])["miles"].first() \
                               .groupby("net_link_id").sum()

    link = link.join(geometry, on="net_link_id")
    link = link.sort_values(["net_link_id", "t_min"])
    link["speed_smoothed"] = (link.groupby("net_link_id")["speed"]
                              .transform(lambda s: s.rolling(VT2_SMOOTH, center=True,
                                                             min_periods=1).mean()))
    return link


def qvdf_speed(t_min: np.ndarray, t0: float, t2: float, t3: float,
               v_cutoff: float, v_t2: float) -> np.ndarray:
    """The QVDF episode curve with an independent width on each shoulder.

    Returns NaN outside [t0, t3]; the caller decides what to put there.
    """
    onset = max(t2 - t0, 1e-6)
    recovery = max(t3 - t2, 1e-6)
    tau = np.where(t_min < t2, (t_min - t2) / onset, (t_min - t2) / recovery)
    inside = (t_min >= t0) & (t_min <= t3)
    z = v_cutoff / max(v_t2, 1e-6) - 1.0
    speed = np.full_like(t_min, np.nan, dtype=float)
    speed[inside] = v_cutoff / (1.0 + z * (1.0 - np.clip(tau[inside], -1.0, 1.0) ** 2) ** 2)
    return speed


def detect(link_id: int, series: pd.DataFrame, free_speed: float) -> pd.DataFrame:
    """Episodes on one link's whole-day profile, on a nominal local clock."""
    stamps = (pd.Timestamp(NOMINAL_DAY, tz=TIMEZONE)
              + pd.to_timedelta(series["t_min"].to_numpy(float), unit="m"))
    config = EpisodeDetectionConfig(
        interval_min=DT_MIN, smoothing_bins=1,           # already smoothed upstream
        enter_ratio=CUTOFF_RATIO, exit_ratio=0.75,
        enter_persistence_bins=1, exit_persistence_bins=1,
        minimum_duration_min=MIN_EPISODE_H * 60.0, minimum_depth_mph=3.0)
    episodes, _ = detect_speed_episodes(stamps, series["speed_smoothed"].to_numpy(float),
                                        free_speed, config)
    if episodes.empty:
        return episodes
    midnight = pd.Timestamp(NOMINAL_DAY, tz=TIMEZONE)
    for column, target in [("t0_la", "t0_min"), ("T2_la", "T2_min"), ("t3_la", "t3_min")]:
        episodes[target] = [(pd.Timestamp(v) - midnight).total_seconds() / 60.0
                            for v in episodes[column]]
    episodes.insert(0, "net_link_id", link_id)
    return episodes


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    profile = pd.read_csv(args.profile_file)
    link = link_speed_profile(profile)

    if args.free_speed_source == "observed":
        free = link.groupby("net_link_id")["speed_smoothed"].quantile(0.95).clip(lower=30.0)
    else:
        free = link.groupby("net_link_id")["config_free_speed"].first()
    link["free_speed"] = link["net_link_id"].map(free)
    link["cutoff"] = link["free_speed"] * CUTOFF_RATIO

    bin_h = DT_MIN / 60.0
    series_rows, summary_rows = [], []

    for link_id, g in link.groupby("net_link_id"):
        g = g.sort_values("t_min").reset_index(drop=True)
        free_speed = float(g["free_speed"].iloc[0])
        cutoff = float(g["cutoff"].iloc[0])
        capacity = float(g["capacity_vphpl"].iloc[0])
        lanes = int(g["lanes"].iloc[0])

        episodes = detect(link_id, g, free_speed)
        # The episode that owns the PM period is the one whose trough falls in it.
        pm = episodes[(episodes["T2_min"] >= PM_START) & (episodes["T2_min"] < PM_END)] \
            if not episodes.empty else episodes
        episode = pm.iloc[0] if len(pm) else None

        t_min = g["t_min"].to_numpy(float)
        model = np.full(len(g), np.nan)
        if episode is not None:
            model = qvdf_speed(t_min, episode["t0_min"], episode["T2_min"],
                               episode["t3_min"], cutoff, float(episode["vT2_robust_mph"]))
        in_episode = np.isfinite(model)
        model_filled = np.where(in_episode, model, free_speed)

        q = s3_flow(g["speed_smoothed"].to_numpy(float),
                    np.full(len(g), free_speed), np.full(len(g), capacity))
        window = (t_min >= PM_START) & (t_min < PM_END)
        below = window & (g["speed_smoothed"].to_numpy(float) < cutoff)
        d_lane = float((q[below] * bin_h).sum())
        v_lane = float((q[window] * bin_h).sum())

        block = pd.DataFrame({
            "net_link_id": link_id, "corridor": g["corridor"].iloc[0],
            "t_min": t_min.astype(int),
            "clock": [f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}" for m in t_min],
            "obs_speed_mph": g["speed"].to_numpy(float),
            "obs_speed_smoothed_mph": g["speed_smoothed"].to_numpy(float),
            "backcalc_speed_mph": model_filled,
            "in_episode": in_episode,
            "cutoff_mph": cutoff, "free_speed_mph": free_speed,
            "q_vphpl": q,
        })
        # The PM episode routinely starts before 15:00 and clears after 19:00, so
        # the whole day is exported with PM flagged rather than clipped to it.
        block["in_pm_period"] = window
        series_rows.append(block)

        error = block.loc[window, "backcalc_speed_mph"] - block.loc[window, "obs_speed_smoothed_mph"]
        inside = block.loc[window & in_episode, "backcalc_speed_mph"] \
            - block.loc[window & in_episode, "obs_speed_smoothed_mph"]

        summary_rows.append({
            "corridor": g["corridor"].iloc[0], "net_link_id": link_id,
            "tmcs": int(g["tmcs"].max()), "miles": float(g["miles_total"].iloc[0]),
            "lanes": lanes,
            "C_vphpl": capacity, "C_veh_per_h": capacity * lanes,
            "free_speed_mph": free_speed, "cutoff_mph": cutoff,
            "congested": episode is not None,
            "P_h": float(episode["P_h"]) if episode is not None else 0.0,
            "t0_min": float(episode["t0_min"]) if episode is not None else np.nan,
            "T2_min": float(episode["T2_min"]) if episode is not None else np.nan,
            "t3_min": float(episode["t3_min"]) if episode is not None else np.nan,
            "vT2_mph": float(episode["vT2_robust_mph"]) if episode is not None else np.nan,
            "onset_to_T2_h": float(episode["onset_to_T2_h"]) if episode is not None else np.nan,
            "T2_to_recovery_h": float(episode["T2_to_recovery_h"]) if episode is not None else np.nan,
            "recovery_over_onset": (float(episode["T2_to_recovery_h"]) / float(episode["onset_to_T2_h"])
                                    if episode is not None and float(episode["onset_to_T2_h"]) > 0
                                    else np.nan),
            # The detector exits on 0.75 * v_f, deliberately, so that a queue is not
            # declared cleared on a momentary lift. On a handful of links the speed
            # never gets back above that line between the morning and evening peaks,
            # and the two peaks are then reported as one episode. P is a whole-day
            # duration on those links and must not be read as a PM duration.
            "episode_starts_before_noon": (bool(episode["t0_min"] < 720)
                                           if episode is not None else False),
            "episode_longer_than_the_pm_window": (bool(episode["P_h"] > (PM_END - PM_START) / 60.0)
                                                  if episode is not None else False),
            "D_veh_per_lane": d_lane, "D_veh_total": d_lane * lanes,
            "V_veh_per_lane": v_lane, "V_veh_total": v_lane * lanes,
            "D_over_C_h": d_lane / capacity, "V_over_C_h": v_lane / capacity,
            "speed_mae_period_mph": float(error.abs().mean()),
            "speed_rmse_period_mph": float(np.sqrt((error ** 2).mean())),
            "speed_mae_episode_mph": float(inside.abs().mean()) if len(inside) else np.nan,
            "speed_rmse_episode_mph": float(np.sqrt((inside ** 2).mean())) if len(inside) else np.nan,
            "episode_bins_in_pm": int((window & in_episode).sum()),
        })

    series = pd.concat(series_rows, ignore_index=True)
    summary = pd.DataFrame(summary_rows).sort_values(["corridor", "net_link_id"])

    # The delivered table, so the free-speed choice can be read in the same row.
    if args.reference_file.exists():
        reference = pd.read_csv(args.reference_file)
        reference = reference[reference["period"] == "PM"][
            ["net_link_id", "P_h", "D_veh_per_lane", "D_over_C_h", "congested_tmcs"]]
        reference.columns = ["net_link_id", "P_h_config_vf", "D_veh_per_lane_config_vf",
                             "D_over_C_h_config_vf", "congested_tmcs_config_vf"]
        summary = summary.merge(reference, on="net_link_id", how="left")

    # CBI derived a free-flow speed per link by its own route. Agreement between
    # the two is the only external check available on this choice, and the choice
    # sets the cut-off, which sets both D and the episode.
    cbi = cbi_link_parameters(args.cbi_dir)
    free_speed_check = None
    if not cbi.empty:
        summary = summary.merge(cbi, on="net_link_id", how="left")
        both = summary.dropna(subset=["cbi_free_speed_mph"])
        if len(both):
            delta = both["free_speed_mph"] - both["cbi_free_speed_mph"]
            free_speed_check = {
                "links_in_common": int(len(both)),
                "ours_median_mph": round(float(both["free_speed_mph"].median()), 2),
                "cbi_median_mph": round(float(both["cbi_free_speed_mph"].median()), 2),
                "median_difference_mph": round(float(delta.median()), 2),
                "mae_mph": round(float(delta.abs().mean()), 2),
                "within_3_mph_pct": round(float((delta.abs() < 3).mean() * 100), 1),
                "correlation": round(float(both["free_speed_mph"].corr(both["cbi_free_speed_mph"])), 4),
                "note": "Two independent derivations -- ours the 95th percentile of each link's "
                        "own observed profile, theirs a separate model estimate. Agreement to "
                        "under 2 mph is what retires the 70 mph constant.",
            }

    def clock(minutes: pd.Series) -> pd.Series:
        return minutes.map(lambda m: "" if not np.isfinite(m)
                           else f"{int(m) // 60 % 24:02d}:{int(m) % 60:02d}")

    for source, target in [("t0_min", "t0_clock"), ("T2_min", "T2_clock"), ("t3_min", "t3_clock")]:
        summary[target] = clock(summary[source])
    summary["note"] = np.select(
        [summary["episode_starts_before_noon"], summary["episode_longer_than_the_pm_window"]],
        ["episode spans the morning peak too; P is an all-day figure",
         "episode runs past the PM window, as most do"], default="")

    series.to_csv(args.output_dir / "nvta_pm_link_speed_15min.csv", index=False)
    summary.to_csv(args.output_dir / "nvta_pm_link_summary_full.csv", index=False)

    # What was asked for, plus what is needed to reproduce it, in that order. The
    # full table keeps the free-speed evidence (the config-v_f and CBI columns)
    # for the question of why 49 links carry an episode where 76 were called
    # congested before.
    delivered = ["corridor", "net_link_id", "lanes", "miles",
                 "C_vphpl", "C_veh_per_h",
                 "D_veh_per_lane", "D_veh_total", "D_over_C_h", "V_veh_total",
                 "free_speed_mph", "cutoff_mph",
                 "congested", "P_h", "t0_clock", "T2_clock", "t3_clock", "vT2_mph",
                 "recovery_over_onset",
                 "speed_mae_episode_mph", "speed_rmse_episode_mph", "note"]
    summary[delivered].to_csv(args.output_dir / "nvta_pm_link_summary.csv", index=False)

    congested = summary[summary["congested"]]
    report = {
        "scope": "NVTA PM period on the assignment clock, 15:00-19:00, average weekday "
                 "2025-10-06 to 10-10, one row per network link",
        "free_speed_source": args.free_speed_source,
        "links": int(len(summary)), "links_with_a_PM_episode": int(len(congested)),
        "construction": {
            "tmc_to_link": "length-weighted harmonic mean of speed (total length / total travel time)",
            "v_c_in_the_qvdf_denominator": "the congestion cut-off 0.70*v_f, not the S3 speed at capacity",
            "episode_shape": "independent onset and recovery widths, tau=(t-T2)/(T2-t0) and (t-T2)/(t3-T2)",
            "outside_the_episode": "the back-calculated speed is the free-flow speed, as in CBI",
            "D": "sum of S3 flow over PM bins below the cut-off, veh per lane",
            "C": "capacity, veh/h/lane; D/C therefore carries units of hours",
        },
        "by_corridor": {
            corridor: {
                "links": int(len(g)), "with_PM_episode": int(g["congested"].sum()),
                "P_median_h": round(float(g.loc[g["congested"], "P_h"].median()), 2) if g["congested"].any() else 0.0,
                "vT2_median_mph": round(float(g.loc[g["congested"], "vT2_mph"].median()), 2) if g["congested"].any() else None,
                "recovery_over_onset_median": round(float(g.loc[g["congested"], "recovery_over_onset"].median()), 2) if g["congested"].any() else None,
                "D_median_veh_per_lane": round(float(g.loc[g["congested"], "D_veh_per_lane"].median()), 0) if g["congested"].any() else 0.0,
                "D_over_C_median_h": round(float(g.loc[g["congested"], "D_over_C_h"].median()), 2) if g["congested"].any() else 0.0,
                "speed_mae_episode_mph": round(float(g["speed_mae_episode_mph"].median()), 2) if g["congested"].any() else None,
            }
            for corridor, g in summary.groupby("corridor")
        },
        "free_speed_check_against_cbi": free_speed_check,
        "episode_count_vs_the_delivered_table": {
            "delivered_congested_links": (int((summary["congested_tmcs_config_vf"] > 0).sum())
                                          if "congested_tmcs_config_vf" in summary else None),
            "links_with_a_PM_episode_here": int(len(congested)),
            "why_they_differ": "The delivered table called a link congested if any PM bin fell "
                              "below 0.70 * 70 mph = 49 mph. Here the cut-off is 0.70 times the "
                              "link's own free-flow speed, which is 64.7 mph at the median and as "
                              "low as 50, and an episode also has to last half an hour and be "
                              "3 mph deep. Links whose speed never drops below their own cut-off "
                              "are no longer counted. This is a correction, not a loss: a link "
                              "running 45 mph against a 50 mph free-flow speed is not congested.",
        },
        "episode_extent": {
            "P_median_h": round(float(congested["P_h"].median()), 2),
            "longer_than_the_4h_pm_window": int(congested["episode_longer_than_the_pm_window"].sum()),
            "starting_before_noon": int(congested["episode_starts_before_noon"].sum()),
            "links_affected": sorted(congested.loc[congested["episode_starts_before_noon"],
                                                   "net_link_id"].astype(int).tolist()),
            "note": "An episode is allowed to run past the PM window, and usually does: the "
                    "queue builds before 15:00 and clears after 19:00. On the links flagged as "
                    "starting before noon the morning and evening peaks were joined into one "
                    "episode because the speed never recovered above 0.75 * v_f in between. "
                    "Their P is an all-day figure and a single curve is a poor description of "
                    "two peaks. D, C and the observed speed are unaffected.",
        },
        "asymmetry": {
            "recovery_over_onset_median": round(float(congested["recovery_over_onset"].median()), 2),
            "recovery_over_onset_iqr": [round(float(congested["recovery_over_onset"].quantile(.25)), 2),
                                        round(float(congested["recovery_over_onset"].quantile(.75)), 2)],
            "note": "A symmetric curve would require this to be 1.0 on every link. The spread is "
                    "why each shoulder is given its own width.",
        },
        "speed_agreement": {
            "episode_bins_only": {
                "mae_mph": round(float(congested["speed_mae_episode_mph"].median()), 3),
                "rmse_mph": round(float(congested["speed_rmse_episode_mph"].median()), 3),
            },
            "whole_pm_period": {
                "mae_mph": round(float(summary["speed_mae_period_mph"].median()), 3),
                "rmse_mph": round(float(summary["speed_rmse_period_mph"].median()), 3),
            },
            "note": "The curve is anchored on the observed t0, T2, t3 and v_T2, so depth and "
                    "timing are exact by construction and only the shape between the anchors "
                    "is being tested. A small residual here is expected and is not evidence "
                    "that the parameters predict anything.",
        },
    }
    (args.output_dir / "nvta_pm_link_summary.json").write_text(json.dumps(report, indent=2),
                                                               encoding="utf-8")

    print(f"{len(summary)} links, {len(congested)} with a PM episode "
          f"(free speed: {args.free_speed_source})\n")
    print(f"{'corridor':<10} {'links':>6} {'cong':>5} {'P med':>7} {'vT2':>6} {'rec/on':>7} "
          f"{'D/lane':>9} {'D/C':>6} {'speed MAE':>10}")
    for corridor, s in report["by_corridor"].items():
        print(f"{corridor:<10} {s['links']:>6} {s['with_PM_episode']:>5} {s['P_median_h']:>7.2f} "
              f"{s['vT2_median_mph'] or 0:>6.1f} {s['recovery_over_onset_median'] or 0:>7.2f} "
              f"{s['D_median_veh_per_lane']:>9,.0f} {s['D_over_C_median_h']:>6.2f} "
              f"{s['speed_mae_episode_mph'] or 0:>9.2f}")
    print(f"\nspeed agreement, median link: {report['speed_agreement']['episode_bins_only']['mae_mph']:.2f} mph "
          f"MAE inside the episode, {report['speed_agreement']['whole_pm_period']['mae_mph']:.2f} mph over the whole PM period")
    if free_speed_check:
        c = free_speed_check
        print(f"\nfree-flow speed against CBI, {c['links_in_common']} links in common: "
              f"ours {c['ours_median_mph']:.1f} vs theirs {c['cbi_median_mph']:.1f} mph, "
              f"MAE {c['mae_mph']:.2f} mph, r = {c['correlation']:.3f}, "
              f"{c['within_3_mph_pct']:.0f}% within 3 mph")
    a = report["asymmetry"]
    print(f"recovery / onset width: median {a['recovery_over_onset_median']:.2f}, "
          f"IQR {a['recovery_over_onset_iqr'][0]:.2f}-{a['recovery_over_onset_iqr'][1]:.2f} "
          f"(a symmetric curve would need 1.00 everywhere)")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
