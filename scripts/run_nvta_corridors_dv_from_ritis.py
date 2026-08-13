"""Period demand D and volume V for any NVTA corridor, built from RITIS speed.

The I-395 NB handoff covered one corridor. The inputs behind it are all local,
so the same quantities can be produced for every corridor without asking for
another handoff and without any calibrated QVDF parameter:

  speed        ritis_selected_corridors_5min_week_2025-10-06_to_10.csv (213 TMCs)
  geometry     corridor_tmc_mapping.csv (lanes, miles, net_link_id)
  constants    qvdf_selfdemo/config.py

Conventions are taken from that config so the output matches the pipeline that
produced the handoff:

  ``DT_MIN = 15``          5-minute RITIS is aggregated to 15-minute bins
  ``CUTOFF_RATIO = 0.70``  congestion cut-off = 0.70 x free-flow speed
  ``VT2_SMOOTH = 3``       centred 3-bin smoothing before the cut-off test
  ``USE_WEEKDAY_AVG``      one average-weekday profile per TMC
  free flow 70 mph, capacity 2200 veh/h/lane for the general-purpose freeways;
  65 mph and 1800 for the HOV corridors, per the ``CORRIDORS`` registry.

Speed at capacity follows the standard S3 exponent m = 4, which gives
``v_c = v_f / sqrt(2)`` -- 49.5 mph at a 70 mph free-flow speed, exactly the
``speed_at_capacity_uc`` in the handoff.

D and V are reported on two clocks. The *pipeline* clock is the one the handoff
uses (AM 5 h, MD 4 h, PM 6 h). The *assignment* clock is the standard four-period
split implied by ``dc_dta_vol / dc_dta_doc`` in the DTA table, which is the one
V has to be on before it can be compared against Cube or TAP-Lite.

The V caveat from the I-395 NB note applies unchanged: q(t) is inferred from
speed, so it is well posed below the cut-off and not above it. D is the
defensible column; V is an upper bound.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
NVTA = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\T2_Task_3\NVTA_internal-git"
            r"\t2_analysis\qvdf_projection_dashboard")

CUTOFF_RATIO = 0.70
DT_MIN = 15
VT2_SMOOTH = 3
S3_M = 4.0                      # standard S3 exponent; v_c = v_f * 2**(-2/m)

# free-flow speed and per-lane capacity, from the config.py CORRIDORS registry
HOV_FREE_SPEED, HOV_CAPACITY = 65.0, 1800.0
GP_FREE_SPEED, GP_CAPACITY = 70.0, 2200.0

PIPELINE_CLOCK = {"AM": (300, 600), "MD": (600, 840), "PM": (840, 1200), "NT": (1200, 1320)}
# The DTA period lengths are 3 / 6 / 4 h; those are the standard four-period splits.
ASSIGNMENT_CLOCK = {"AM": (360, 540), "MD": (540, 900), "PM": (900, 1140), "NT": (1140, 1800)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--corridors", nargs="+",
                        default=["I-66 EB", "I-66 WB", "I-395 SB", "I-395 NB"])
    parser.add_argument("--speed-file", type=Path,
                        default=NVTA / "data/ritis_selected_corridors_5min_week_2025-10-06_to_10.csv")
    parser.add_argument("--mapping-file", type=Path, default=NVTA / "data/corridor_tmc_mapping.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_corridors_dv_ritis")
    return parser.parse_args()


def s3_flow(speed: np.ndarray, free_speed: float, capacity: float) -> np.ndarray:
    """Flow implied by speed, veh/h/lane, on the congested branch of S3.

    ``v(k) = v_f / [1 + (k/k_c)^m]^(2/m)`` inverts to
    ``k(v) = k_c [ (v_f/v)^(m/2) - 1 ]^(1/m)``.
    """
    speed_at_capacity = free_speed * 2.0 ** (-2.0 / S3_M)
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    return np.minimum(k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M) * v,
                      capacity)


def average_weekday_profile(speed: pd.DataFrame) -> pd.DataFrame:
    """One 15-minute average-weekday speed profile per TMC, smoothed."""
    speed = speed.copy()
    stamp = pd.to_datetime(speed["measurement_tstamp"])
    speed = speed[stamp.dt.weekday < 5]
    minute = stamp.dt.hour * 60 + stamp.dt.minute
    speed["t_min"] = (minute // DT_MIN) * DT_MIN
    profile = (speed.groupby(["tmc_code", "t_min"], as_index=False)["speed"].mean()
               .sort_values(["tmc_code", "t_min"]))
    # Centred smoothing, matching VT2_SMOOTH in the pipeline config.
    profile["speed_smoothed"] = (
        profile.groupby("tmc_code")["speed"]
        .transform(lambda s: s.rolling(VT2_SMOOTH, center=True, min_periods=1).mean())
    )
    return profile


def summarise(frame: pd.DataFrame, clock: str) -> dict:
    """Corridor-level medians and totals for one clock."""
    out = {}
    for (corridor, period), g in frame.groupby(["corridor", "period"]):
        c = g[g["congested"]]
        out.setdefault(corridor, {})[period] = {
            "period_hours": float(g["period_hours"].iloc[0]),
            "tmcs": int(len(g)),
            "congested_tmcs": int(len(c)),
            "P_median_h": float(c["P_h"].median()) if len(c) else 0.0,
            "D_median_veh_per_lane": float(c["D_veh_per_lane"].median()) if len(c) else 0.0,
            "D_over_C_median_h": float(c["D_over_C_h"].median()) if len(c) else 0.0,
            "V_median_veh_per_lane": float(g["V_veh_per_lane"].median()),
            "D_corridor_total_veh": float(c["D_veh_total"].sum()) if len(c) else 0.0,
            "V_corridor_total_veh": float(g["V_veh_total"].sum()),
        }
    return out


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    mapping = pd.read_csv(args.mapping_file)
    mapping = mapping[mapping["corridor"].isin(args.corridors)]
    if mapping.empty:
        raise SystemExit(f"no TMCs for {args.corridors}; available: "
                         f"{sorted(pd.read_csv(args.mapping_file)['corridor'].unique())}")

    speed = pd.read_csv(args.speed_file)
    speed = speed[speed["tmc_code"].isin(set(mapping["tmc"]))]
    profile = average_weekday_profile(speed)

    geometry = mapping.set_index("tmc")[["corridor", "facility", "miles", "net_lanes", "net_link_id"]]
    profile = profile.join(geometry, on="tmc_code", how="inner")
    # HOV corridors run on their own reduced network with different constants.
    is_hov = profile["facility"].astype(str).str.upper().eq("HOV")
    profile["free_speed"] = np.where(is_hov, HOV_FREE_SPEED, GP_FREE_SPEED)
    profile["capacity_vphpl"] = np.where(is_hov, HOV_CAPACITY, GP_CAPACITY)
    profile["cutoff"] = profile["free_speed"] * CUTOFF_RATIO
    profile["q_vphpl"] = s3_flow(profile["speed_smoothed"].to_numpy(float),
                                 profile["free_speed"].to_numpy(float),
                                 profile["capacity_vphpl"].to_numpy(float))
    profile.to_csv(args.output_dir / "average_weekday_speed_flow_15min.csv", index=False)

    bin_h = DT_MIN / 60.0
    rows = []
    for clock_name, clock in [("pipeline", PIPELINE_CLOCK), ("assignment", ASSIGNMENT_CLOCK)]:
        for period, (start, end) in clock.items():
            # The night period wraps past midnight on the assignment clock.
            window = (profile["t_min"] >= start) & (profile["t_min"] < end) if end <= 1440 else \
                     (profile["t_min"] >= start) | (profile["t_min"] < end - 1440)
            for tmc, g in profile[window].groupby("tmc_code"):
                below = g["speed_smoothed"] < g["cutoff"]
                lanes = int(g["net_lanes"].iloc[0])
                capacity = float(g["capacity_vphpl"].iloc[0])
                d_lane = float((g.loc[below, "q_vphpl"] * bin_h).sum())
                v_lane = float((g["q_vphpl"] * bin_h).sum())
                rows.append({
                    "clock": clock_name, "corridor": g["corridor"].iloc[0], "tmc": tmc,
                    "net_link_id": g["net_link_id"].iloc[0], "period": period,
                    "period_hours": (end - start) / 60.0,
                    "miles": float(g["miles"].iloc[0]), "lanes": lanes,
                    "capacity_vphpl": capacity, "cutoff_mph": float(g["cutoff"].iloc[0]),
                    "bins": int(len(g)), "bins_below_cutoff": int(below.sum()),
                    "congested": bool(below.any()),
                    "min_speed_mph": float(g["speed_smoothed"].min()),
                    "P_h": float(below.sum()) * bin_h,
                    "D_veh_per_lane": d_lane, "V_veh_per_lane": v_lane,
                    "D_veh_total": d_lane * lanes, "V_veh_total": v_lane * lanes,
                    "D_over_C_h": d_lane / capacity, "V_over_C_h": v_lane / capacity,
                    "qbar_over_C_congested": (d_lane / (capacity * below.sum() * bin_h)
                                              if below.any() else np.nan),
                })
    frame = pd.DataFrame(rows).sort_values(["clock", "corridor", "period", "tmc"])
    frame.to_csv(args.output_dir / "corridor_dv_by_tmc.csv", index=False)

    summary = {
        "corridors": args.corridors,
        "method": "D = sum of q(t) for v < cutoff; V = sum of q(t) over the period; q(t) from S3(speed)",
        "conventions": {
            "source": "qvdf_selfdemo/config.py",
            "cutoff_ratio": CUTOFF_RATIO, "dt_min": DT_MIN, "smoothing_bins": VT2_SMOOTH,
            "s3_m": S3_M, "free_speed_mph": {"general": GP_FREE_SPEED, "hov": HOV_FREE_SPEED},
            "capacity_vphpl": {"general": GP_CAPACITY, "hov": HOV_CAPACITY},
            "no_calibrated_parameters_used": True,
        },
        "clocks": {"pipeline": PIPELINE_CLOCK, "assignment": ASSIGNMENT_CLOCK},
        "coverage": {
            corridor: {"tmcs": int(g["tmc"].nunique()), "miles": round(float(g.groupby("tmc")["miles"].first().sum()), 2),
                       "lanes_median": int(g["lanes"].median())}
            for corridor, g in frame[frame["clock"] == "pipeline"].groupby("corridor")
        },
        "pipeline_clock": summarise(frame[frame["clock"] == "pipeline"], "pipeline"),
        "assignment_clock": summarise(frame[frame["clock"] == "assignment"], "assignment"),
        "caveat": (
            "q(t) is inferred from speed, so D (bins below the cut-off) is well posed and V "
            "(all bins) is an upper bound. Scored against measured I-405 counts the same "
            "inversion carries 20.8% MAPE on congested bins and 171.5% on free-flow bins."
        ),
    }
    (args.output_dir / "corridor_dv_summary.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    for clock_name in ("pipeline", "assignment"):
        print(f"\n{'=' * 78}\n{clock_name.upper()} CLOCK\n{'=' * 78}")
        block = summary[f"{clock_name}_clock"]
        print(f"{'corridor':<12} {'per':<4} {'TMCs':>5} {'cong':>5} {'P med':>7} "
              f"{'D/lane':>9} {'D/C':>6} {'V/lane':>9} {'D total':>11} {'V total':>11}")
        for corridor in sorted(block):
            for period in ("AM", "MD", "PM", "NT"):
                s = block[corridor].get(period)
                if not s:
                    continue
                print(f"{corridor:<12} {period:<4} {s['tmcs']:>5} {s['congested_tmcs']:>5} "
                      f"{s['P_median_h']:>7.2f} {s['D_median_veh_per_lane']:>9,.0f} "
                      f"{s['D_over_C_median_h']:>6.2f} {s['V_median_veh_per_lane']:>9,.0f} "
                      f"{s['D_corridor_total_veh']:>11,.0f} {s['V_corridor_total_veh']:>11,.0f}")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
