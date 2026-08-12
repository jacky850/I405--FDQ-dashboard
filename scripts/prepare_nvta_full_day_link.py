"""Stage 1 of the NVTA speed-only full-day queue case.

Extracts one INRIX/RITIS TMC for one real weekday onto the mentor's continuous
whole-day clock (``whole_day_DTA/docs/03``): the day is anchored at minute 360
(06:00) and runs to minute 1800 (30:00 = 06:00 the following morning), so the
NT period never wraps at midnight and no period boundary resets state.

The stage writes a minimal reproducible input plus a characterisation of what
the day actually looks like.  It performs no queue computation.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from fdqbench.episodes import EpisodeDetectionConfig, detect_speed_episodes  # noqa: E402


TIMEZONE = "America/New_York"
INTERVAL_MIN = 5
DAY_START_MIN = 360  # 06:00, the mentor's whole-day anchor
DAY_END_MIN = 1800  # 30:00 == 06:00 next day
BINS = (DAY_END_MIN - DAY_START_MIN) // INTERVAL_MIN  # 288

# whole_day_DTA/docs/03: reporting boundaries only, never physical boundaries.
PERIOD_WINDOWS = [
    ("AM", 360, 540),
    ("MD", 540, 900),
    ("PM", 900, 1140),
    ("NT", 1140, 1800),
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed-file", type=Path, required=True)
    parser.add_argument("--tmc", default="110-04178")
    parser.add_argument("--date", default="2025-10-08")
    parser.add_argument("--mapping-file", type=Path, required=True)
    parser.add_argument("--qvdf-file", type=Path, required=True)
    parser.add_argument("--data-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--free-speed-percentile", type=float, default=95.0)
    return parser.parse_args()


def period_of(clock_min: float) -> str:
    for label, start, end in PERIOD_WINDOWS:
        if start <= clock_min < end:
            return label
    return "OUT"


def load_day(speed_file: Path, tmc: str, date: str) -> pd.DataFrame:
    """Return the 288-bin window running 06:00 on ``date`` to 06:00 the next day."""
    frame = pd.read_csv(
        speed_file,
        usecols=["tmc_code", "measurement_tstamp", "speed", "reference_speed", "date", "tod_min"],
    )
    frame = frame.loc[frame["tmc_code"].eq(tmc)].copy()
    if frame.empty:
        raise ValueError(f"TMC {tmc} is absent from {speed_file}")

    anchor = pd.Timestamp(date)
    next_day = (anchor + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    head = frame.loc[frame["date"].eq(date) & frame["tod_min"].ge(DAY_START_MIN)].copy()
    tail = frame.loc[frame["date"].eq(next_day) & frame["tod_min"].lt(DAY_START_MIN)].copy()
    head["clock_min"] = head["tod_min"]
    tail["clock_min"] = tail["tod_min"] + 1440  # continuous clock: no midnight reset

    day = pd.concat([head, tail]).sort_values("clock_min").reset_index(drop=True)
    day["timestamp"] = pd.to_datetime(day["measurement_tstamp"]).dt.tz_localize(TIMEZONE)
    day["period"] = day["clock_min"].map(period_of)
    day["wall_clock"] = day["clock_min"].map(
        lambda m: f"{int(m // 60):02d}:{int(m % 60):02d}"
    )
    return day


def link_attributes(mapping_file: Path, qvdf_file: Path, tmc: str, speed: np.ndarray,
                    reference_speed: float, free_speed_percentile: float) -> dict:
    mapping = pd.read_csv(mapping_file)
    row = mapping.loc[mapping["tmc"].eq(tmc)]
    if row.empty:
        raise ValueError(f"TMC {tmc} is absent from the corridor mapping")
    row = row.iloc[0]

    qvdf = pd.read_csv(qvdf_file)
    qvdf_rows = qvdf.loc[qvdf["tmc"].eq(tmc)]

    observed_free_speed = float(np.nanpercentile(speed, free_speed_percentile))

    attributes = {
        "tmc": tmc,
        "net_link_id": int(row["net_link_id"]),
        "corridor": str(row["corridor"]),
        "direction": str(row["direction"]),
        "facility": str(row["facility"]),
        "county": str(row["county"]),
        "length_mi": float(row["miles"]),
        "lanes": int(row["net_lanes"]),
        # Three independent free-speed claims are kept side by side on purpose;
        # they disagree and the disagreement is a reportable input uncertainty.
        "free_speed_mph": {
            "observed_p95": observed_free_speed,
            "inrix_reference": reference_speed,
            "network_attribute": float(row["net_free_speed_mph"]),
            "qvdf_calibration_constant": (
                float(qvdf_rows["vf"].iloc[0]) if not qvdf_rows.empty else None
            ),
        },
        "capacity_vphpl": {
            "network_attribute": float(row["net_capacity_raw"]),
            "qvdf_calibration_constant": (
                float(qvdf_rows["cap"].iloc[0]) if not qvdf_rows.empty else None
            ),
        },
        "qvdf_cutoff_mph": (
            float(qvdf_rows["cutoff"].iloc[0]) if not qvdf_rows.empty else None
        ),
        "qvdf_periods": {
            str(r["period"]): {
                key: (None if pd.isna(r[key]) else float(r[key]))
                for key in ["P", "demand", "DC", "v_t2", "t2", "t0", "t3", "qdf", "m"]
            }
            for _, r in qvdf_rows.iterrows()
        },
        "qvdf_provenance": (
            "observed_t2_dataset week average (date='SelectedWeekAverage', "
            "2025-10-06..10); capacity and free speed are hardcoded constants "
            "(1800/2200 vphpl by HOV flag) and demand is S3-inverted from speed, "
            "not observed"
        ),
    }
    return attributes


def main() -> None:
    args = parse_args()
    args.data_dir.mkdir(parents=True, exist_ok=True)
    args.output_dir.mkdir(parents=True, exist_ok=True)

    day = load_day(args.speed_file, args.tmc, args.date)
    speed = day["speed"].to_numpy(float)
    reference_speed = float(day["reference_speed"].mode().iloc[0])

    attributes = link_attributes(
        args.mapping_file, args.qvdf_file, args.tmc, speed, reference_speed,
        args.free_speed_percentile,
    )

    # Episode detection reuses the PeMS-side speed-only detector.  It expects a
    # calendar-day grid, so both calendar days are passed and the results are
    # then restricted to the 360-1800 analysis window.
    full = pd.read_csv(
        args.speed_file,
        usecols=["tmc_code", "measurement_tstamp", "speed", "date"],
    )
    next_day = (pd.Timestamp(args.date) + pd.Timedelta(days=1)).strftime("%Y-%m-%d")
    full = full.loc[full["tmc_code"].eq(args.tmc) & full["date"].isin([args.date, next_day])]
    stamps = pd.to_datetime(full["measurement_tstamp"]).dt.tz_localize(TIMEZONE)

    free_speed = attributes["free_speed_mph"]["observed_p95"]
    episodes, process = detect_speed_episodes(
        stamps, full["speed"].to_numpy(float), free_speed, EpisodeDetectionConfig(),
    )
    if not episodes.empty:
        t2 = pd.to_datetime(episodes["T2_la"])
        anchor = pd.Timestamp(args.date, tz=TIMEZONE)
        clock = (t2 - anchor).dt.total_seconds() / 60.0
        episodes = episodes.assign(
            T2_clock_min=clock,
            T2_period=[period_of(c) for c in clock],
        )
        episodes = episodes.loc[clock.between(DAY_START_MIN, DAY_END_MIN)].reset_index(drop=True)

    day.to_csv(args.data_dir / "speed_5min.csv", index=False)
    (args.data_dir / "link.json").write_text(
        json.dumps(attributes, indent=2), encoding="utf-8"
    )
    episodes.to_csv(args.output_dir / "speed_episodes.csv", index=False)

    cutoff = attributes["qvdf_cutoff_mph"]
    by_period = {}
    for label, start, end in PERIOD_WINDOWS:
        mask = day["clock_min"].between(start, end - 1)
        segment = day.loc[mask, "speed"].to_numpy(float)
        by_period[label] = {
            "bins": int(mask.sum()),
            "mean_speed_mph": float(np.nanmean(segment)),
            "min_speed_mph": float(np.nanmin(segment)),
            "bins_below_cutoff": int(np.nansum(segment < cutoff)),
        }

    characterisation = {
        "case_id": f"nvta_{attributes['net_link_id']}_{args.date}",
        "tmc": args.tmc,
        "date": args.date,
        "timezone": TIMEZONE,
        "clock": {
            "convention": "continuous minutes, anchored 360 (06:00), no midnight reset",
            "start_min": DAY_START_MIN,
            "end_min": DAY_END_MIN,
            "bins": BINS,
            "source": "whole_day_DTA/docs/03_PERIOD_HANDLING_AM_MD_PM_NT.md",
        },
        "data_completeness": {
            "bins_present": int(len(day)),
            "bins_expected": BINS,
            "missing_speed_bins": int(np.isnan(speed).sum()),
        },
        "link": attributes,
        "by_period": by_period,
        "episodes_detected": int(len(episodes)),
        "stage": "1_input_preparation_only_no_queue_computed",
    }
    (args.output_dir / "day_characterization.json").write_text(
        json.dumps(characterisation, indent=2), encoding="utf-8"
    )
    print(json.dumps(characterisation, indent=2))
    if not episodes.empty:
        columns = [
            "episode_id", "t0_la", "T2_la", "t3_la", "P_h", "vT2_robust_mph",
            "asymmetry_ratio", "T2_period", "cross_period", "quality_flags",
        ]
        print("\n" + episodes[columns].to_string(index=False))


if __name__ == "__main__":
    main()
