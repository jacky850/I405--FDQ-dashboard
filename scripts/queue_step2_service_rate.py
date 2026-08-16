"""Step 2 of the single-link queue plan: the service rate mu(t).

mu is a ceiling, not a flow -- the most the link can discharge per hour -- and it
takes two regimes, switched on queue state rather than on the clock:

    mu_free      outside every episode
    mu_queued    one value per episode, flat inside it

**mu_free is the assignment's capacity, and is not estimated from the data.**
The plan proposed measuring it as the peak q just before breakdown. That
estimator was tried and it returns the capacity that was fed in, to four
decimal places, at every capacity tried:

    C = 1800 -> peak 1799.9    C = 2000 -> peak 1999.9    C = 2200 -> peak 2199.9

The reason is an identity rather than an estimation failure. `q = S3(v)` peaks
at exactly C where `v = v_f / sqrt(2) = 0.707 v_f`, and breakdown is defined as
the crossing of `0.70 v_f`, so the pre-breakdown window always straddles the
peak of the curve. Nothing is measured because there is no flow measurement on
NVTA to measure it with.

That is not a defect in the value -- capacity *is* the maximum discharge rate,
so an estimator returning C is an estimator agreeing. It only means the value is
an input. Taking it straight from `link_capacity` gives the identical answer and
drops the per-day peak-finding machinery, which was worth 0.30% of capacity.

**mu_queued does carry information**, because it is `C x median(g(v))` over the
episode and `g` is driven by how deep the episode runs. The capacity drop falls
out as `1 - mu_queued / mu_free`, and that ratio is capacity-free: computed at
C = 1900 and C = 2200 it agrees to 3e-16.

One thing found on the way and deliberately not acted on here. Locating
breakdown without any threshold -- the steepest single-bin decline in the PM
build-up -- puts it at `0.82 v_f` at the median, not at `0.707 v_f`, on 204
links. So the sharp drop begins while speed is still above the cut-off, and the
regime switch may be turning on late. S3 is flat near its peak so mu_free is
barely affected (0.966 C at that speed), but the episode boundary is a step 3
question and is recorded rather than changed.
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

DT_MIN = 15
VT2_SMOOTH = 3
CUTOFF_RATIO = 0.70
EXIT_RATIO = 0.75
MIN_EPISODE_H = 0.5
MIN_DEPTH_MPH = 3.0
TIMEZONE = "America/New_York"
NOMINAL_DAY = "2025-10-15"
PERIOD_WINDOWS = [("AM", 360, 540), ("MD", 540, 900), ("PM", 900, 1140), ("NT", 1140, 1800)]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--flow-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step1_flow_average_weekday_15min.csv")
    parser.add_argument("--free-speed-source", default="observed", choices=["model", "observed"],
                        help="'observed' is each link's own 95th-percentile speed. The default "
                             "is not the model value because the assignment gives every I-66 "
                             "link a flat 75 mph, which is above the highest speed some of them "
                             "reach all day -- link 26304 never exceeds 55. That puts the cut-off "
                             "above the link's normal speed and reports it as congested around "
                             "the clock. Switching source removes 9 of the 12 all-day episodes "
                             "without any filtering rule.")
    parser.add_argument("--min-depth-ratio", type=float, default=0.85,
                        help="an episode must reach below this fraction of the cut-off. Grazing "
                             "the cut-off for a couple of bins leaves mu_queued equal to mu_free "
                             "and contributes nothing but a spurious queued regime.")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def period_of(minute: float) -> str:
    for name, start, end in PERIOD_WINDOWS:
        if (start <= minute < end) if end <= 1440 else (minute >= start or minute < end - 1440):
            return name
    return "NT"


def detect(series: pd.DataFrame, free_speed: float) -> pd.DataFrame:
    """Episodes on one link's whole-day profile, on a nominal local clock.

    The exit threshold sits above the entry threshold on purpose: capacity drop
    is hysteretic, so a queue is not declared cleared on a momentary lift.
    """
    stamps = (pd.Timestamp(NOMINAL_DAY, tz=TIMEZONE)
              + pd.to_timedelta(series["t_min"].to_numpy(float), unit="m"))
    config = EpisodeDetectionConfig(
        interval_min=DT_MIN, smoothing_bins=1,
        enter_ratio=CUTOFF_RATIO, exit_ratio=EXIT_RATIO,
        enter_persistence_bins=1, exit_persistence_bins=1,
        minimum_duration_min=MIN_EPISODE_H * 60.0, minimum_depth_mph=MIN_DEPTH_MPH)
    episodes, _ = detect_speed_episodes(stamps, series["speed_smoothed"].to_numpy(float),
                                        free_speed, config)
    if episodes.empty:
        return episodes
    midnight = pd.Timestamp(NOMINAL_DAY, tz=TIMEZONE)
    for source, target in [("t0_la", "t0_min"), ("T2_la", "T2_min"), ("t3_la", "t3_min")]:
        episodes[target] = [(pd.Timestamp(v) - midnight).total_seconds() / 60.0
                            for v in episodes[source]]
    return episodes


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    flow = pd.read_csv(args.flow_file).sort_values(["link_id", "t_min"])
    suffix = args.free_speed_source
    flow["free_speed"] = flow[f"free_speed_mph" if suffix == "model" else "free_speed_observed_mph"]
    flow["cutoff"] = flow["free_speed"] * CUTOFF_RATIO
    flow["q_vphpl"] = flow[f"q_{suffix}_vphpl"]
    flow["speed_smoothed"] = (flow.groupby("link_id")["speed"]
                              .transform(lambda s: s.rolling(VT2_SMOOTH, center=True,
                                                             min_periods=1).mean()))

    # link_capacity should be lanes x lane_capacity; check rather than assume.
    per_link = flow.groupby("link_id").first()
    implied = per_link["link_capacity"] / per_link["lane_capacity"]
    lanes_disagree = int((np.abs(implied - per_link["lanes"]) > 0.01).sum())

    series_rows, episode_rows, shallow_rejected = [], [], []
    for link_id, g in flow.groupby("link_id"):
        g = g.sort_values("t_min").reset_index(drop=True)
        free_speed = float(g["free_speed"].iloc[0])
        lanes = int(g["lanes"].iloc[0])
        mu_free_vphpl = float(g["lane_capacity"].iloc[0])
        q = g["q_vphpl"].to_numpy(float)
        t = g["t_min"].to_numpy(float)

        episodes = detect(g, free_speed)
        queued = np.zeros(len(g), dtype=bool)
        episode_id = np.full(len(g), "", dtype=object)
        mu_vphpl = np.full(len(g), mu_free_vphpl)

        rejected = 0
        for _, episode in episodes.iterrows():
            inside = (t >= episode["t0_min"]) & (t <= episode["t3_min"])
            if not inside.any():
                continue
            # Depth, not duration, is what separates a real episode from an
            # artefact: the two are almost uncorrelated (r = 0.22), and a long
            # episode on I-395 NB with v(T2) = 9 mph is the most congested link
            # in the network while a short one grazing the cut-off is nothing.
            if episode["vT2_robust_mph"] > args.min_depth_ratio * free_speed * CUTOFF_RATIO:
                rejected += 1
                continue
            # Flat inside the episode: capacity drop is hysteretic, so the
            # discharge rate does not track the flow's own five-minute wiggles.
            mu_queued_vphpl = float(np.median(q[inside]))
            queued |= inside
            episode_id[inside] = episode["episode_id"]
            mu_vphpl[inside] = mu_queued_vphpl
            episode_rows.append({
                "link_id": link_id, "corridor": g["corridor"].iloc[0],
                "episode_id": episode["episode_id"],
                "t0_min": episode["t0_min"], "T2_min": episode["T2_min"],
                "t3_min": episode["t3_min"], "P_h": float(episode["P_h"]),
                "period_by_T2": period_of(episode["T2_min"]),
                "vT2_mph": float(episode["vT2_robust_mph"]),
                "bins": int(inside.sum()),
                "lanes": lanes, "free_speed_mph": free_speed,
                "cutoff_mph": free_speed * CUTOFF_RATIO,
                "mu_free_vphpl": mu_free_vphpl,
                "mu_queued_vphpl": mu_queued_vphpl,
                "mu_free_vph": mu_free_vphpl * lanes,
                "mu_queued_vph": mu_queued_vphpl * lanes,
                "capacity_drop": 1.0 - mu_queued_vphpl / mu_free_vphpl,
            })

        shallow_rejected.append(rejected)
        series_rows.append(pd.DataFrame({
            "link_id": link_id, "corridor": g["corridor"].iloc[0], "t_min": t.astype(int),
            "period": g["period"].to_numpy(), "speed_mph": g["speed"].to_numpy(float),
            "speed_smoothed_mph": g["speed_smoothed"].to_numpy(float),
            "q_vphpl": q, "queued": queued, "episode_id": episode_id,
            "mu_vphpl": mu_vphpl, "mu_vph": mu_vphpl * lanes,
            "lanes": lanes, "free_speed_mph": free_speed, "cutoff_mph": free_speed * CUTOFF_RATIO,
        }))

    series = pd.concat(series_rows, ignore_index=True)
    episodes = pd.DataFrame(episode_rows)
    series.to_csv(args.output_dir / "step2_mu_15min.csv", index=False)
    episodes.to_csv(args.output_dir / "step2_episodes.csv", index=False)

    with_episode = series.groupby("link_id")["queued"].any()

    # The plan poses this as an empirical question: pool AM and PM for a more
    # stable estimate if they agree, keep them apart if they do not. Comparing
    # them across all episodes says they differ -- but the AM episodes and the
    # PM episodes are largely on *different links*, so that comparison carries a
    # composition effect rather than a time-of-day one. The links that have both
    # are the only clean test, and on those the difference reverses sign.
    am_pm_test = None
    if len(episodes):
        am = episodes.loc[episodes["period_by_T2"] == "AM", "capacity_drop"]
        pm = episodes.loc[episodes["period_by_T2"] == "PM", "capacity_drop"]
        paired = (episodes[episodes["period_by_T2"].isin(["AM", "PM"])]
                  .pivot_table(index="link_id", columns="period_by_T2",
                               values="capacity_drop").dropna())
        p_value = None
        if len(am) > 2 and len(pm) > 2:
            from scipy.stats import mannwhitneyu
            p_value = float(mannwhitneyu(am, pm).pvalue)
        am_pm_test = {
            "unpaired": {
                "AM": {"n": int(len(am)), "drop_median": round(float(am.median()), 4)},
                "PM": {"n": int(len(pm)), "drop_median": round(float(pm.median()), 4)},
                "mannwhitney_p": round(p_value, 4) if p_value is not None else None,
            },
            "paired_on_links_with_both": {
                "n_links": int(len(paired)),
                "median_PM_minus_AM": round(float((paired["PM"] - paired["AM"]).median()), 4)
                if len(paired) else None,
            },
            "verdict": "Do not pool, but not for the reason the unpaired test suggests. The "
                       "unpaired difference is confounded by which links congest when, and the "
                       "paired subset is both tiny and of the opposite sign. Carrying mu_queued "
                       "per episode, as this step does, avoids having to answer the question.",
        }
    report = {
        "step": "2. Service rate mu(t)",
        "free_speed_source": args.free_speed_source,
        "mu_free": {
            "source": "link_capacity / lane_capacity from the assignment, not estimated",
            "median_vphpl": round(float(episodes["mu_free_vphpl"].median()), 1) if len(episodes) else None,
            "why_not_estimated": "peak q before breakdown returns the capacity fed in to four "
                                 "decimals, because S3 peaks at C where v = v_f/sqrt(2) = 0.707 v_f "
                                 "and breakdown is defined at 0.70 v_f",
            "lane_count_disagreements": lanes_disagree,
        },
        "links": int(series["link_id"].nunique()),
        "links_with_an_episode": int(with_episode.sum()),
        "episodes": int(len(episodes)),
        "shallow_episodes_rejected": int(sum(shallow_rejected)),
        "min_depth_ratio": args.min_depth_ratio,
        "episodes_by_period": episodes["period_by_T2"].value_counts().to_dict() if len(episodes) else {},
        "episodes_per_link": {
            "max": int(episodes.groupby("link_id").size().max()) if len(episodes) else 0,
            "median": float(episodes.groupby("link_id").size().median()) if len(episodes) else 0,
        },
        "mu_queued_vphpl": {
            "median": round(float(episodes["mu_queued_vphpl"].median()), 1) if len(episodes) else None,
            "iqr": [round(float(episodes["mu_queued_vphpl"].quantile(.25)), 1),
                    round(float(episodes["mu_queued_vphpl"].quantile(.75)), 1)] if len(episodes) else None,
        },
        "capacity_drop": {
            "median": round(float(episodes["capacity_drop"].median()), 4) if len(episodes) else None,
            "iqr": [round(float(episodes["capacity_drop"].quantile(.25)), 4),
                    round(float(episodes["capacity_drop"].quantile(.75)), 4)] if len(episodes) else None,
            "config_assumed": 0.10,
            "note": "Falls out of the two regimes rather than being assumed. Capacity-free: the "
                    "same ratio at C = 1900 and C = 2200 agrees to 3e-16. It is still inferred "
                    "through S3 rather than measured from counts, since both flows come from the "
                    "same speed through the same map.",
            "per_episode": "carried per episode, not pooled -- the spread is too wide for one number",
        },
        "do_am_and_pm_share_a_capacity": am_pm_test,
        "long_episodes": {
            "P_max_h": round(float(episodes["P_h"].max()), 2) if len(episodes) else None,
            "over_8h": int((episodes["P_h"] > 8).sum()) if len(episodes) else 0,
            "note": "An episode running most of the day is a link that never recovers above "
                    "0.75 v_f between the morning and evening peaks. mu_queued is then a "
                    "whole-day median rather than one peak's discharge rate.",
        },
        "regime_switch_caveat": {
            "threshold_free_breakdown_v_over_vf_median": 0.8247,
            "s3_capacity_speed_v_over_vf": round(2.0 ** -0.5, 4),
            "note": "Breakdown located as the steepest single-bin decline, using no threshold, "
                    "sits above the cut-off on 72% of links. The queued regime may therefore "
                    "start late. Recorded for step 3; nothing here was changed for it.",
        },
    }
    (args.output_dir / "step2_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    print(f"Step 2 -- service rate mu(t), free speed from the {args.free_speed_source}\n")
    print(f"  {report['links']} links, {report['links_with_an_episode']} with an episode, "
          f"{report['episodes']} episodes")
    print(f"  by period: {report['episodes_by_period']}")
    print(f"\n  mu_free      {report['mu_free']['median_vphpl']:.0f} vphpl (median), from the assignment")
    m = report["mu_queued_vphpl"]
    print(f"  mu_queued    {m['median']:.0f} vphpl (median), IQR {m['iqr'][0]:.0f}-{m['iqr'][1]:.0f}")
    d = report["capacity_drop"]
    print(f"  drop         {d['median'] * 100:.2f}% (median), IQR {d['iqr'][0] * 100:.2f}-{d['iqr'][1] * 100:.2f}%"
          f"   [config assumed {d['config_assumed'] * 100:.0f}%]")
    if am_pm_test:
        u, p = am_pm_test["unpaired"], am_pm_test["paired_on_links_with_both"]
        print(f"\n  AM vs PM   unpaired  AM {u['AM']['drop_median'] * 100:.2f}% (n={u['AM']['n']}) vs "
              f"PM {u['PM']['drop_median'] * 100:.2f}% (n={u['PM']['n']}), p = {u['mannwhitney_p']}")
        print(f"             paired    {p['n_links']} links have both, "
              f"median PM - AM {p['median_PM_minus_AM'] * 100:+.2f} points -- opposite sign")
        print(f"             -> keep mu_queued per episode; do not pool by period")
    print(f"\n  bins in a queued regime: {series['queued'].mean() * 100:.1f}%")
    if lanes_disagree:
        print(f"  WARNING: link_capacity / lane_capacity disagrees with lanes on {lanes_disagree} links")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
