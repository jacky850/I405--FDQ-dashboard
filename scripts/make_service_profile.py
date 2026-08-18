"""External service profile, in the Mode A format of the validation-ladder note.

    service_profile_source = external
    interval_id, link_id, mu_veh_per_hour

That file is emitted with exactly those three columns so it can be read without
modification. The interval numbering it uses is defined separately in
time_horizon.csv rather than being implied, since interval_id on its own says
nothing about which quarter hour it is.

Also emitted is a single genuine link record for G1_1LINK_1PERIOD_EXTERNAL_MU,
plus the PM slice of its service profile, so that case can be run as it stands
once a synthetic OD and departure profile are attached.

mu is the two-regime rate from step 2: lane_capacity x lanes outside a
congestion episode, and the median speed-implied flow inside one. It is defined
on all 96 intervals of all 252 links.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
QUEUE = ROOT / "outputs/nvta_queue"
DT_MIN = 15
PERIOD_WINDOWS = [("AM", 360, 540), ("MD", 540, 900), ("PM", 900, 1140)]
# I-395 SB, four lanes. Chosen for G1 because its assigned volume agrees with the
# observed discharge (ratio 1.02), its episode opens and closes inside the run
# window, and its capacity drop is an unremarkable 8%.
G1_LINK = 26776
G1_PERIOD = "PM"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-dir", type=Path, default=QUEUE)
    parser.add_argument("--g1-link", type=int, default=G1_LINK)
    parser.add_argument("--g1-period", default=G1_PERIOD)
    parser.add_argument("--output-dir", type=Path,
                        default=ROOT / "outputs/nvta_service_profile")
    return parser.parse_args()


def clock(minute: int) -> str:
    return f"{minute // 60:02d}:{minute % 60:02d}"


def period_of(minute: int) -> str:
    for name, start, end in PERIOD_WINDOWS:
        if start <= minute < end:
            return name
    return "NT"


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    q = args.queue_dir

    frame = pd.read_csv(q / "step3_queue_target_15min.csv",
                        usecols=["link_id", "t_min", "mu_vph", "queued", "episode_id"])
    frame = frame.sort_values(["link_id", "t_min"])

    # interval_id counts quarter hours from midnight, 1-based: 1 is 00:00-00:15.
    minutes = sorted(frame["t_min"].unique())
    interval_of = {m: i + 1 for i, m in enumerate(minutes)}
    frame["interval_id"] = frame["t_min"].map(interval_of)

    horizon = pd.DataFrame({"interval_id": [interval_of[m] for m in minutes],
                            "start_time": [clock(int(m)) for m in minutes],
                            "end_time": [clock(int(m) + DT_MIN) for m in minutes],
                            "start_minute": [int(m) for m in minutes],
                            "interval_minutes": DT_MIN,
                            "period": [period_of(int(m)) for m in minutes]})
    horizon.to_csv(args.output_dir / "time_horizon.csv", index=False)

    profile = frame[["interval_id", "link_id", "mu_vph"]].rename(
        columns={"mu_vph": "mu_veh_per_hour"})
    profile["mu_veh_per_hour"] = profile["mu_veh_per_hour"].round(2)
    profile = profile[["interval_id", "link_id", "mu_veh_per_hour"]]
    profile.to_csv(args.output_dir / "service_profile.csv", index=False)

    # ---- the G1 case -------------------------------------------------------
    window = next(w for w in PERIOD_WINDOWS if w[0] == args.g1_period)
    g1_rows = frame[(frame["link_id"] == args.g1_link)
                    & (frame["t_min"] >= window[1]) & (frame["t_min"] < window[2])]
    if g1_rows.empty:
        raise SystemExit(f"link {args.g1_link} has no {args.g1_period} intervals")
    g1_profile = (g1_rows[["interval_id", "link_id", "mu_vph"]]
                  .rename(columns={"mu_vph": "mu_veh_per_hour"}))
    g1_profile["mu_veh_per_hour"] = g1_profile["mu_veh_per_hour"].round(2)
    g1_profile.to_csv(args.output_dir / "g1_service_profile.csv", index=False)

    period_table = pd.read_csv(ROOT / "outputs/nvta_odme/odme_link_period.csv")
    record = period_table[(period_table["link_id"] == args.g1_link)
                          & (period_table["period"] == args.g1_period)]
    run = pd.read_csv(q / "step6_by_link.csv",
                      usecols=["link_id", "queue_peak_model_veh", "queue_peak_meas_veh",
                               "storage_veh"])
    record = record.merge(run, on="link_id", how="left")
    record.insert(0, "case", "G1_1LINK_1PERIOD_EXTERNAL_MU")
    record["first_interval_id"] = int(g1_profile["interval_id"].min())
    record["last_interval_id"] = int(g1_profile["interval_id"].max())
    record.to_csv(args.output_dir / "g1_link_record.csv", index=False)

    r = record.iloc[0]
    print(f"service_profile.csv   {len(profile):,} rows "
          f"({frame['link_id'].nunique()} links x {len(minutes)} intervals)")
    print(f"time_horizon.csv      {len(horizon)} rows, "
          f"{DT_MIN} min from {horizon['start_time'].iloc[0]}")
    print(f"\nG1 case: link {args.g1_link}, {args.g1_period}, "
          f"intervals {r['first_interval_id']}-{r['last_interval_id']}")
    print(f"  {int(r['lanes'])} lanes, {r['length_mi']:.2f} mi, "
          f"free speed {r['free_speed_obs_p95_mph']:.2f} mph")
    print(f"  mu_free {r['mu_free_vph']:.0f} vph, mu_queued {r['mu_queued_vph']:.0f} vph "
          f"(drop {r['capacity_drop'] * 100:.1f}%)")
    print(f"  V_assign {r['V_assign_veh']:,.0f} veh vs observed discharge "
          f"{r['V_throughput_obs_veh']:,.0f} (ratio {r['D_ratio']:.2f})")
    print(f"  observed episode P {r['P_h_obs']:.2f} h, v(T2) {r['vT2_mph_obs']:.1f} mph")
    print(f"  expected queue peak {r['queue_peak_model_veh']:.0f} veh "
          f"against {r['storage_veh']:.0f} of storage")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
