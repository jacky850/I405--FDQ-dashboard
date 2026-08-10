"""Diagnostic D/mu estimates on the I-405 South valid link test set.

This is intentionally conservative and transparent:
* D(t) = observed upstream mainline flow + observed on-ramp flow;
* at a boundary/no-upstream link, current observed mainline flow is used as a
  boundary-demand proxy and labelled accordingly;
* mu is the median mainline outflow after the minimum-speed point in each
  period, restricted to speeds <= 70% of network free speed when possible;
* if a period has no congested observations, a period-flow fallback is used and
  labelled.  Such rows need mentor review before deployment.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import numpy as np
import pandas as pd


PERIODS = [("NT1", 0, 6), ("AM", 6, 10), ("MD", 10, 15), ("PM", 15, 19), ("NT2", 19, 24)]


def period_of(time_la: str) -> str:
    hour = int(str(time_la).split(":", 1)[0])
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
    ap.add_argument("--corridor-root", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    ap.add_argument(
        "--link-ids",
        nargs="*",
        default=None,
        help="Optional explicit target link IDs. If omitted, use all fully eligible links.",
    )
    ap.add_argument(
        "--output-stem",
        default="test",
        help="Suffix used for generated output files, e.g. direct7.",
    )
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    all_mainline = pd.read_csv(args.test_file)
    fully_eligible = all_mainline.groupby("link_id")["valid_link_test"].all()
    fully_eligible = set(fully_eligible[fully_eligible].index.astype(str))
    if args.link_ids:
        requested = {str(x) for x in args.link_ids}
        target_links = fully_eligible.intersection(requested)
        missing = sorted(requested - target_links)
        if missing:
            raise ValueError(f"Requested link IDs are not fully eligible: {', '.join(missing)}")
    else:
        target_links = fully_eligible
    raw = all_mainline[all_mainline["valid_link_test"] & all_mainline["link_id"].astype(str).isin(target_links)].copy()
    links = pd.read_csv(args.corridor_root / "network" / "links.csv")
    fd_path = args.corridor_root / "network" / "fd_parameters.csv"
    fd = pd.read_csv(fd_path) if fd_path.exists() else pd.DataFrame()
    topo = pd.read_csv(args.corridor_root / "network" / "lwr_mainline_topology.csv")
    # Upstream mainline flow may come from any of the 44 observed mainline
    # links. Only the target link's ramp completeness is restricted to the
    # 27-link valid test set.
    observed_links = set(all_mainline["link_id"].astype(str))

    # Work at the average-weekday LA-time profile, one row per link/time.
    raw["period"] = raw["time_la"].map(period_of)
    prof = (raw.groupby(["link_id", "time_la", "period"], as_index=False)
            .agg(speed_kmh=("speed_kmh", "mean"),
                 flow_vph=("flow_vph", "mean"),
                 on_ramp_flow_vph=("on_ramp_flow_vph_used", "mean"),
                 off_ramp_flow_vph=("off_ramp_flow_vph_used", "mean"),
                 weekday_count=("date", "nunique")))
    prof = prof.merge(links[["link_id", "free_speed_kmh", "capacity_vph", "lanes"]], on="link_id", how="left")
    if not fd.empty and "capacity_vph" in fd.columns:
        fd_cap = fd.groupby("link_id", as_index=False)["capacity_vph"].median().rename(
            columns={"capacity_vph": "fd_capacity_vph"}
        )
        prof = prof.merge(fd_cap, on="link_id", how="left")
    else:
        prof["fd_capacity_vph"] = np.nan
    prof["capacity_vph_effective"] = prof["fd_capacity_vph"].fillna(prof["capacity_vph"])
    prof["capacity_source"] = np.where(
        prof["fd_capacity_vph"].notna(), "fd_parameters_link_median", "links_csv_network_capacity"
    )
    prof["speed_mph"] = prof["speed_kmh"] * 0.621371192237334
    prof["free_speed_mph"] = prof["free_speed_kmh"] * 0.621371192237334

    # Use an observed upstream sensor when the topology exposes one. If the
    # upstream is only a connection/out-of-network node, preserve the link's
    # own observed flow as a boundary-demand proxy.
    flow_by_link_time = (all_mainline.groupby(["link_id", "time_la"], as_index=True)["flow_vph"].mean())
    topo_by_link = topo.set_index("link_id")
    d_rows = []
    for row in prof.itertuples(index=False):
        t = (str(row.link_id), str(row.time_la))
        upstream = [x for x in split_ids(topo_by_link.loc[row.link_id, "incoming_link_ids"] if "incoming_link_ids" in topo_by_link.columns else topo_by_link.loc[row.link_id, "upstream_mainline_link_ids"]) if x in observed_links]
        upstream_values = [flow_by_link_time.get((x, row.time_la), np.nan) for x in upstream]
        upstream_values = [float(x) for x in upstream_values if pd.notna(x)]
        if upstream_values:
            mainline_in = float(np.mean(upstream_values))
            source = "observed_upstream_mainline"
        else:
            mainline_in = float(row.flow_vph)
            source = "boundary_or_unobserved_upstream_proxy"
        d_rows.append({
            "link_id": row.link_id, "time_la": row.time_la, "period": row.period,
            "flow_observed_vph": row.flow_vph, "mainline_inflow_vph": mainline_in,
            "on_ramp_flow_vph": row.on_ramp_flow_vph,
            "D_vph": mainline_in + float(row.on_ramp_flow_vph),
            "D_source": source,
        })
    dprof = pd.DataFrame(d_rows)
    prof = prof.merge(dprof, on=["link_id", "time_la", "period"], how="left")

    # Estimate mu separately for each weekday, then aggregate across weekdays.
    # This preserves congestion episodes that disappear after averaging days.
    daily = raw.copy()
    daily["period"] = daily["time_la"].map(period_of)
    daily = daily.merge(links[["link_id", "free_speed_kmh", "capacity_vph", "lanes"]], on="link_id", how="left")
    daily["speed_mph"] = daily["speed_kmh"] * 0.621371192237334
    daily["free_speed_mph"] = daily["free_speed_kmh"] * 0.621371192237334
    daily = daily.merge(prof[["link_id", "fd_capacity_vph", "capacity_vph_effective", "capacity_source"]].drop_duplicates("link_id"), on="link_id", how="left")
    daily_mu_rows = []
    for (link_id, date, period), g in daily.groupby(["link_id", "date", "period"], sort=True):
        g = g.sort_values("time_la").copy()
        min_idx = g["speed_mph"].idxmin()
        min_time = g.loc[min_idx, "time_la"]
        after_min = g[g["time_la"] >= min_time]
        congested = after_min[after_min["speed_mph"] <= 0.70 * after_min["free_speed_mph"]]
        candidate = congested["flow_vph"].dropna()
        capacity = float(g["capacity_vph_effective"].iloc[0]) if pd.notna(g["capacity_vph_effective"].iloc[0]) else np.nan
        if len(candidate) >= 2:
            mu_value = float(candidate.median())
            source = "daily_post_min_speed_congested_median"
        else:
            mu_value = float(g["flow_vph"].median())
            source = "daily_period_flow_median_fallback_no_congestion"
        if pd.notna(capacity):
            mu_value = min(mu_value, capacity)
        daily_mu_rows.append({
            "link_id": link_id, "date": date, "period": period, "mu_daily_vph": mu_value,
            "mu_daily_source": source, "congested_candidate_n_daily": int(len(candidate)),
            "period_sample_n_daily": int(len(g)), "capacity_vph_effective": capacity,
            "capacity_source": str(g["capacity_source"].iloc[0]),
        })
    daily_mu = pd.DataFrame(daily_mu_rows)
    daily_mu.to_csv(args.output_dir / f"i405_s_mu_daily_{args.output_stem}.csv", index=False)
    mu = (daily_mu.groupby(["link_id", "period"], as_index=False)
          .agg(mu_vph=("mu_daily_vph", "median"),
               congested_days=("mu_daily_source", lambda s: int(s.eq("daily_post_min_speed_congested_median").sum())),
               days_observed=("date", "nunique"),
               congested_candidate_n=("congested_candidate_n_daily", "sum"),
               period_sample_n=("period_sample_n_daily", "sum"),
               capacity_vph_effective=("capacity_vph_effective", "first"),
               capacity_source=("capacity_source", "first")))
    mu["mu_source"] = np.where(mu["congested_days"] > 0, "daily_congested_median_across_weekdays", "daily_period_median_fallback_no_congestion")
    dprof = dprof.merge(mu[["link_id", "period", "mu_vph", "mu_source"]], on=["link_id", "period"], how="left")

    # The report distinguishes the instantaneous inflow diagnostic from the
    # assignment demand rate D. For directly observed upstream demand, use a
    # declared one-hour rolling window and take its peak within each period.
    # Keep D_mean_vph below for traceability, but expose the report-aligned
    # peak demand estimate explicitly.
    dprof = dprof.sort_values(["link_id", "period", "time_la"]).copy()
    dprof["D_rolling_1h_vph"] = (
        dprof.groupby(["link_id", "period"], sort=False)["D_vph"]
        .transform(lambda s: s.rolling(window=12, min_periods=12).mean())
    )
    d_peak = (dprof.groupby(["link_id", "period"], as_index=False)
              .agg(D_peak_1h_vph=("D_rolling_1h_vph", "max"),
                   D_reference_window=("D_rolling_1h_vph", lambda s: "1h_rolling_peak" if s.notna().any() else "period_mean_fallback")))
    dprof = dprof.merge(d_peak, on=["link_id", "period"], how="left")
    dprof.to_csv(args.output_dir / f"i405_s_d_mu_profile_{args.output_stem}.csv", index=False)

    summary = (dprof.groupby(["link_id", "period", "D_source", "mu_source"], as_index=False)
               .agg(D_mean_vph=("D_vph", "mean"), D_p95_vph=("D_vph", lambda s: float(s.quantile(.95))),
                    D_peak_1h_vph=("D_peak_1h_vph", "first"),
                    D_reference_window=("D_reference_window", "first"),
                    mu_vph=("mu_vph", "first"), congested_candidate_n=("mu_source", "size"),
                    samples=("D_vph", "size")))
    # Replace the count above with the actual candidate count from the mu table.
    summary = summary.drop(columns=["congested_candidate_n"]).merge(
        mu[["link_id", "period", "congested_days", "days_observed", "congested_candidate_n", "period_sample_n", "capacity_vph_effective", "capacity_source"]],
        on=["link_id", "period"], how="left")
    summary.to_csv(args.output_dir / f"i405_s_d_mu_summary_{args.output_stem}.csv", index=False)
    print(summary.to_string(index=False))
    print(f"Wrote {len(summary)} link-period estimates to {args.output_dir}")


if __name__ == "__main__":
    main()
