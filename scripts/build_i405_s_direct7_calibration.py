"""Build episode-level and link-period calibration tables for seven I-405 S links.

This is a transparent first implementation of the report's episode workflow:
the 70% free-speed cutoff identifies queued samples, t0 is onset, t2 is the
minimum-speed sample, and t3 is recovery after two consecutive uncongested
samples. Formal mu_e is only reported for cleared episodes; fallback estimates
remain separate and are never silently used as formal discharge.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PERIODS = [("NT1", 0, 6), ("AM", 6, 10), ("MD", 10, 15), ("PM", 15, 19), ("NT2", 19, 24)]
LINKS = ["L405S-012", "L405S-018", "L405S-028", "L405S-030", "L405S-058", "L405S-098", "L405S-115"]


def period_of(value: str) -> str:
    hour = int(str(value).split(":", 1)[0])
    for name, start, end in PERIODS:
        if start <= hour < end:
            return name
    return "NT2"


def split_ids(value: object) -> list[str]:
    if pd.isna(value) or not str(value):
        return []
    return [x for x in str(value).split(";") if x]


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--test-file", type=Path, required=True)
    ap.add_argument("--raw-file", type=Path, required=True, help="Original PeMS mainline CSV containing milepost.")
    ap.add_argument("--corridor-root", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--paq-file", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_rows = pd.read_csv(args.test_file)
    target = all_rows[all_rows["link_id"].isin(LINKS)].copy()
    target = target[target["valid_link_test"]].copy()
    target["period"] = target["time_la"].map(period_of)
    target["timestamp_dt"] = pd.to_datetime(target["timestamp"], utc=True)

    links = pd.read_csv(args.corridor_root / "network" / "links.csv")
    target = target.merge(links[["link_id", "free_speed_kmh"]], on="link_id", how="left")
    topo = pd.read_csv(args.corridor_root / "network" / "lwr_mainline_topology.csv").set_index("link_id")
    observed = set(all_rows["link_id"].astype(str))
    flow_by_link_time = all_rows.groupby(["link_id", "date", "time_la"])["flow_vph"].mean()
    raw_milepost = pd.read_csv(args.raw_file, usecols=["link_id", "milepost"])
    target_pm = raw_milepost[raw_milepost["link_id"].isin(LINKS)].groupby("link_id")["milepost"].median().to_dict()
    paq = pd.read_csv(args.paq_file)
    paq["T0_min"] = paq["T0_min"].astype(float)
    paq["T3_min"] = paq["T3_min"].astype(float)

    # Reconstruct the direct demand inflow at each target link and time.
    d_rows = []
    for row in target.itertuples(index=False):
        incoming_col = "incoming_link_ids" if "incoming_link_ids" in topo.columns else "upstream_mainline_link_ids"
        incoming = [x for x in split_ids(topo.loc[row.link_id, incoming_col]) if x in observed]
        vals = [flow_by_link_time.get((x, row.date, row.time_la), np.nan) for x in incoming]
        vals = [float(x) for x in vals if pd.notna(x)]
        upstream = float(np.mean(vals)) if vals else np.nan
        source = "observed_upstream_mainline" if vals else "no_direct_upstream"
        d_rows.append({
            "link_id": row.link_id, "date": row.date, "time_la": row.time_la,
            "period": row.period, "timestamp_dt": row.timestamp_dt,
            "speed_kmh": row.speed_kmh, "flow_vph": row.flow_vph,
            "free_speed_kmh": row.free_speed_kmh,
            "mainline_inflow_vph": upstream,
            "on_ramp_flow_vph": row.on_ramp_flow_vph_used,
            "D_vph": upstream + float(row.on_ramp_flow_vph_used) if pd.notna(upstream) else np.nan,
            "D_source": source,
        })
    data = pd.DataFrame(d_rows).sort_values(["link_id", "date", "period", "timestamp_dt"])
    data["congested"] = data["speed_kmh"] <= 0.70 * data["free_speed_kmh"]

    episodes = []
    for (link_id, date, period), g in data.groupby(["link_id", "date", "period"], sort=True):
        g = g.reset_index(drop=True)
        flags = g["congested"].to_numpy(dtype=bool)
        i = 0
        episode_no = 0
        while i < len(g):
            if not flags[i]:
                i += 1
                continue
            start = i
            while i + 1 < len(g) and flags[i + 1]:
                i += 1
            end = i
            i += 1
            if end - start + 1 < 3:
                continue
            queued = g.iloc[start : end + 1]
            t2_idx = queued["speed_kmh"].idxmin()
            t2_pos = int(t2_idx)
            recovery_pos = None
            for j in range(max(t2_pos + 1, start), len(g) - 1):
                if (not bool(g.loc[j, "congested"])) and (not bool(g.loc[j + 1, "congested"])):
                    recovery_pos = j
                    break
            episode_no += 1
            t0 = g.loc[start, "timestamp_dt"]
            t2 = g.loc[t2_pos, "timestamp_dt"]
            t3 = g.loc[recovery_pos, "timestamp_dt"] if recovery_pos is not None else pd.NaT
            interval_end = recovery_pos if recovery_pos is not None else end
            # Report Eq. (49)-(50): episode-average discharge integrates over
            # the complete cleared episode t0--t3. t2 identifies the
            # minimum-speed state but is not the lower integration bound.
            interval = g.loc[start:interval_end]
            cleared = recovery_pos is not None and len(interval) >= 2
            duration_h = (t3 - t0).total_seconds() / 3600.0 if cleared else np.nan
            # PAQ was run from the original UTC timestamp/date fields. Match
            # its clock using timestamp_dt; flow extraction below still uses
            # the same row membership and LA display time.
            t0_min = int(g.loc[start, "timestamp_dt"].hour) * 60 + int(g.loc[start, "timestamp_dt"].minute)
            t3_min = int(g.loc[interval_end, "timestamp_dt"].hour) * 60 + int(g.loc[interval_end, "timestamp_dt"].minute)
            candidates = paq[(paq["date"].astype(str) == str(date))
                             & (paq["pm_lo"] <= target_pm.get(link_id, np.nan))
                             & (paq["pm_hi"] >= target_pm.get(link_id, np.nan))
                             & (paq["T3_min"] >= t0_min)
                             & (paq["T0_min"] <= t3_min)].copy()
            if not candidates.empty:
                candidates["overlap_min"] = candidates.apply(
                    lambda r: max(0.0, min(t3_min, r["T3_min"]) - max(t0_min, r["T0_min"])), axis=1
                )
                paq_match = candidates.sort_values(["overlap_min", "n_segments"], ascending=False).iloc[0]
                mu_flow_link_id = str(paq_match["xstar_link_id"])
                source = "paq_xstar_observed_flow"
                object_id = str(paq_match["object"])
                xstar_pm = float(paq_match["xstar_pm"])
            else:
                mu_flow_link_id = str(link_id)
                source = "target_flow_no_paq_match"
                object_id = ""
                xstar_pm = np.nan
            source_rows = all_rows[(all_rows["link_id"].astype(str) == mu_flow_link_id)
                                   & (all_rows["date"].astype(str) == str(date))
                                   & (all_rows["time_la"].isin(interval["time_la"]))]
            mu_e = float(source_rows["flow_vph"].mean()) if cleared and not source_rows.empty else np.nan
            dq = float(g.loc[start:interval_end, "D_vph"].sum() * 5.0 / 60.0) if cleared else np.nan
            mu_p = float(mu_e * duration_h) if cleared else np.nan
            episodes.append({
                "link_id": link_id, "date": date, "period": period,
                "episode_no": episode_no, "t0": t0.isoformat(), "t2": t2.isoformat(),
                "t3": t3.isoformat() if cleared else "",
                "duration_h": duration_h, "min_speed_kmh": float(queued["speed_kmh"].min()),
                "mu_e_vph": mu_e, "DQ_arrival_veh": dq, "mu_e_times_P_veh": mu_p,
                "conservation_residual_veh": dq - mu_p if cleared else np.nan,
                "mu_flow_link_id": mu_flow_link_id if cleared else "",
                "paq_object": object_id if cleared else "",
                "paq_xstar_pm": xstar_pm if cleared else np.nan,
                "mu_source": source if cleared else "not_identified_no_recovery",
                "quality_status": "episode_cleared" if cleared else "limited_no_recovery",
                "queued_sample_n": len(queued),
            })
    episode = pd.DataFrame(episodes)
    episode.to_csv(args.output_dir / "i405_s_congestion_episode_summary_direct7.csv", index=False)

    base = pd.read_csv(args.summary)
    ep = (episode.groupby(["link_id", "period"], as_index=False)
          .agg(episode_count=("episode_no", "size"),
               cleared_episode_count=("duration_h", lambda s: int(s.notna().sum())),
               mu_e_vph=("mu_e_vph", "median"),
               mu_flow_link_id=("mu_flow_link_id", lambda s: ";".join(sorted(set(str(x) for x in s.dropna() if str(x))))),
               episode_mu_source=("mu_source", lambda s: ";".join(sorted(set(str(x) for x in s.dropna() if str(x))))),
               duration_h_median=("duration_h", "median"),
               DQ_arrival_veh_median=("DQ_arrival_veh", "median"),
               conservation_residual_veh_median=("conservation_residual_veh", "median")))
    final = base.merge(ep, on=["link_id", "period"], how="left")
    final["mu_e_source"] = np.where(final["cleared_episode_count"].fillna(0) > 0, final["episode_mu_source"], "limited_identification")
    final["k_mu"] = final["mu_e_vph"] / final["capacity_vph_effective"]
    final["D_peak_over_C"] = final["D_peak_1h_vph"] / final["capacity_vph_effective"]
    final["D_peak_over_mu_e"] = final["D_peak_1h_vph"] / final["mu_e_vph"]
    final["quality_status"] = np.where(final["cleared_episode_count"].fillna(0) > 0, "episode_based_preliminary", "limited_identification")
    final.to_csv(args.output_dir / "i405_s_calibration_link_period_direct7.csv", index=False)
    data.to_csv(args.output_dir / "i405_s_d_mu_profile_5min_direct7.csv", index=False)
    print(f"Wrote {len(episode)} episode rows and {len(final)} link-period calibration rows")


if __name__ == "__main__":
    main()
