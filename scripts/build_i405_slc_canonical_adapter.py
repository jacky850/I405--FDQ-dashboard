"""Map the I-405 PeMS ground-truth subset to the mentor SLC contract.

This adapter does not calibrate QVDF parameters.  It preserves observations,
adds versioned network/sensor metadata, and derives auditable daily-period
states needed by the later forward/backward closure comparison.
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
DEFAULT_CORRIDOR_ROOT = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\trafficflowbench_five_corridors\data_public\kaggle_release"
    r"\corridors\D12_I405_S"
)
DEFAULT_KEYS = [
    "L405S-001|1222782",
    "L405S-001|1223027",
    "L405S-020|1201419",
    "L405S-061|1201350",
]
PERIODS = [
    ("NT1", 0, 6),
    ("AM", 6, 10),
    ("MD", 10, 15),
    ("PM", 15, 19),
    ("NT2", 19, 24),
]
PERIOD_HOURS = {name: float(end - start) for name, start, end in PERIODS}
KM_TO_MI = 0.621371192237334


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--observations",
        type=Path,
        default=ROOT / "data/jinxi_i405_week_2025-06-16_to_22/raw_observed_fdqbench.csv",
    )
    parser.add_argument("--corridor-root", type=Path, default=DEFAULT_CORRIDOR_ROOT)
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/i405_slc_canonical_direct4",
    )
    parser.add_argument("--keys", nargs="*", default=DEFAULT_KEYS)
    return parser.parse_args()


def sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def period_of_timestamp(timestamp_la: str) -> str:
    hour = int(str(timestamp_la)[11:13])
    for name, start, end in PERIODS:
        if start <= hour < end:
            return name
    raise ValueError(f"Hour outside the period contract: {timestamp_la}")


def rolling_peak_hour(flow: pd.Series, interval_min: int = 5) -> float:
    window = int(round(60 / interval_min))
    values = pd.to_numeric(flow, errors="coerce")
    rolled = values.rolling(window, min_periods=window).mean()
    return float(rolled.max()) if rolled.notna().any() else float(values.max())


def interpolate_crossing_time(
    t_left: float,
    v_left: float,
    t_right: float,
    v_right: float,
    cutoff: float,
) -> float:
    if not all(np.isfinite([t_left, v_left, t_right, v_right, cutoff])) or v_right == v_left:
        return float(t_right)
    fraction = (cutoff - v_left) / (v_right - v_left)
    return float(t_left + np.clip(fraction, 0.0, 1.0) * (t_right - t_left))


def extract_speed_state(group: pd.DataFrame, cutoff_speed_mph: float) -> dict[str, object]:
    """Extract the cutoff-bounded episode containing the minimum speed."""

    g = group.sort_values("timestamp_la").reset_index(drop=True)
    speed = g["speed_mph"].to_numpy(dtype=float)
    minute = (
        pd.to_datetime(g["timestamp_la"].str[:19])
        - pd.to_datetime(g["timestamp_la"].str[:19]).dt.normalize()
    ).dt.total_seconds().to_numpy() / 60.0
    if len(g) == 0 or not np.isfinite(speed).any():
        return {
            "T2_timestamp_la": "",
            "vT2_observed_mph": np.nan,
            "t0_clock_h": np.nan,
            "t3_clock_h": np.nan,
            "P_observed_h": np.nan,
            "speed_state_quality": "missing_speed",
        }

    t2 = int(np.nanargmin(speed))
    queued = np.isfinite(speed) & (speed <= float(cutoff_speed_mph))
    if not queued[t2]:
        return {
            "T2_timestamp_la": str(g.loc[t2, "timestamp_la"]),
            "vT2_observed_mph": float(speed[t2]),
            "t0_clock_h": np.nan,
            "t3_clock_h": np.nan,
            "P_observed_h": 0.0,
            "speed_state_quality": "no_cutoff_crossing",
        }

    left = t2
    right = t2
    while left > 0 and queued[left - 1]:
        left -= 1
    while right + 1 < len(g) and queued[right + 1]:
        right += 1

    if left > 0:
        t0_min = interpolate_crossing_time(
            minute[left - 1], speed[left - 1], minute[left], speed[left], cutoff_speed_mph
        )
        onset_status = "interpolated"
    else:
        t0_min = float(minute[left])
        onset_status = "left_censored"
    if right + 1 < len(g):
        t3_min = interpolate_crossing_time(
            minute[right], speed[right], minute[right + 1], speed[right + 1], cutoff_speed_mph
        )
        recovery_status = "interpolated"
    else:
        t3_min = float(minute[right] + 5.0)
        recovery_status = "right_censored"

    return {
        "T2_timestamp_la": str(g.loc[t2, "timestamp_la"]),
        "vT2_observed_mph": float(speed[t2]),
        "t0_clock_h": t0_min / 60.0,
        "t3_clock_h": t3_min / 60.0,
        "P_observed_h": max(0.0, (t3_min - t0_min) / 60.0),
        "speed_state_quality": f"{onset_status};{recovery_status}",
    }


def load_metadata(corridor_root: Path, keys: list[str]) -> tuple[pd.DataFrame, pd.DataFrame]:
    network = corridor_root / "network"
    links = pd.read_csv(network / "links.csv", dtype={"link_id": str})
    fd = pd.read_csv(network / "fd_parameters.csv", dtype={"link_id": str, "station_id": str})
    mapping = pd.read_csv(network / "station_to_link.csv", dtype={"link_id": str, "station_id": str})
    topology = pd.read_csv(network / "lwr_mainline_topology.csv", dtype={"link_id": str})

    requested = pd.DataFrame(
        [key.split("|", 1) for key in keys], columns=["model_link_id", "tmc_id"]
    )
    requested = requested.merge(
        mapping.rename(columns={"link_id": "model_link_id", "station_id": "tmc_id"}),
        on=["model_link_id", "tmc_id"],
        how="left",
        validate="one_to_one",
        indicator=True,
    )
    if not requested["_merge"].eq("both").all():
        missing = requested.loc[requested["_merge"].ne("both"), ["model_link_id", "tmc_id"]]
        raise ValueError(f"Missing station-to-link mappings: {missing.to_dict('records')}")
    # The mapping file also carries corridor_id.  Mapping validation only
    # needs the stable link/sensor key; network attributes are sourced from
    # links.csv below to avoid duplicate/suffixed metadata columns.
    requested = requested[["model_link_id", "tmc_id"]].copy()

    link_cols = [
        "corridor_id",
        "link_id",
        "from_node_id",
        "to_node_id",
        "length_km",
        "lanes",
        "free_speed_kmh",
        "capacity_vph",
        "link_type",
        "road_name",
        "direction",
        "asset_type",
    ]
    meta = requested.merge(
        links[link_cols].rename(columns={"link_id": "model_link_id"}),
        on="model_link_id",
        how="left",
        validate="many_to_one",
    )
    fd_selected = fd.rename(columns={"link_id": "model_link_id", "station_id": "tmc_id"})[
        ["model_link_id", "tmc_id", "free_speed_kmh", "capacity_vph", "v_cut"]
    ].rename(
        columns={
            "free_speed_kmh": "detector_free_speed_kmh",
            "capacity_vph": "detector_capacity_vph",
            "v_cut": "cutoff_speed_kmh",
        }
    )
    meta = meta.merge(fd_selected, on=["model_link_id", "tmc_id"], how="left", validate="one_to_one")
    order = topology[["link_id", "order_index"]].rename(columns={"link_id": "model_link_id"})
    meta = meta.merge(order, on="model_link_id", how="left", validate="many_to_one")
    meta["length_mi"] = meta["length_km"].astype(float) * KM_TO_MI
    meta["free_speed_mph"] = meta["detector_free_speed_kmh"].fillna(meta["free_speed_kmh"]).astype(float) * KM_TO_MI
    meta["cutoff_speed_mph"] = meta["cutoff_speed_kmh"].astype(float) * KM_TO_MI
    meta["nominal_capacity_vph"] = meta["detector_capacity_vph"].fillna(meta["capacity_vph"]).astype(float)
    meta["capacity_basis"] = np.where(
        meta["detector_capacity_vph"].notna(), "fd_parameters_detector_all_lanes", "links_csv_all_lanes"
    )
    meta["metadata_status"] = "observed_network_metadata"

    map_out = requested.copy()
    map_out["mapping_method"] = "published_station_to_link"
    map_out["direction_match"] = True
    map_out["distance_error_m"] = np.nan
    map_out["confidence"] = "published_mapping"
    map_out["effective_date"] = "2025-06-16"
    map_out["mapping_version"] = "trafficflowbench_public_2026_pilot"
    return meta, map_out


def build_observations(raw: pd.DataFrame, keys: list[str]) -> pd.DataFrame:
    d = raw.copy()
    d["key"] = d["link_id"].astype(str) + "|" + d["tmc_id"].astype(str)
    d = d[d["key"].isin(keys)].copy()
    d["day_id"] = d["timestamp_la"].str[:10]
    d["day_type"] = np.where(pd.to_datetime(d["day_id"]).dt.dayofweek < 5, "weekday", "weekend")
    d = d[d["day_type"].eq("weekday")].copy()
    d["period_id"] = d["timestamp_la"].map(period_of_timestamp)
    d["interval_min"] = 5
    d["interval_volume_veh"] = d["flow_vehph"].astype(float) * 5.0 / 60.0
    d["occupancy"] = np.nan
    d["sample_count"] = np.where(d["pct_observed"].notna(), 1, 0)
    d["coverage_ratio"] = d["pct_observed"].astype(float) / 100.0
    d["quality_flag"] = np.where(d["is_imputed"].astype(int).eq(0), "observed_complete", "imputed")
    d["observed_or_inferred"] = "observed"
    d["model_link_id"] = d["link_id"].astype(str)
    d["flow_rate_vph"] = d["flow_vehph"].astype(float)
    columns = [
        "model_link_id",
        "tmc_id",
        "timestamp_la",
        "timestamp",
        "interval_min",
        "day_id",
        "day_type",
        "period_id",
        "speed_mph",
        "flow_rate_vph",
        "interval_volume_veh",
        "occupancy",
        "sample_count",
        "coverage_ratio",
        "lanes",
        "source_corridor",
        "quality_flag",
        "observed_or_inferred",
    ]
    out = d[columns].sort_values(["model_link_id", "tmc_id", "timestamp_la"]).reset_index(drop=True)
    duplicates = out.duplicated(["model_link_id", "tmc_id", "timestamp_la"])
    if duplicates.any():
        raise ValueError(f"Canonical observations contain {int(duplicates.sum())} duplicate timestamps")
    return out


def build_period_states(observations: pd.DataFrame, metadata: pd.DataFrame) -> pd.DataFrame:
    meta = metadata.set_index(["model_link_id", "tmc_id"])
    rows: list[dict[str, object]] = []
    group_cols = ["model_link_id", "tmc_id", "day_id", "period_id"]
    for keys, group in observations.groupby(group_cols, sort=True):
        link_id, tmc_id, day_id, period = keys
        m = meta.loc[(link_id, tmc_id)]
        period_h = PERIOD_HOURS[str(period)]
        volume = float(group["interval_volume_veh"].sum())
        average_rate = volume / period_h
        peak = rolling_peak_hour(group.sort_values("timestamp_la")["flow_rate_vph"])
        kd = peak / average_rate if average_rate > 0 else np.nan
        state = extract_speed_state(group, float(m["cutoff_speed_mph"]))
        rows.append(
            {
                "model_link_id": link_id,
                "tmc_id": tmc_id,
                "day_id": day_id,
                "period_id": period,
                "period_hours": period_h,
                "samples": int(len(group)),
                "observed_volume_veh": volume,
                "average_flow_rate_vph": average_rate,
                "D_peak_1h_vph": peak,
                "k_d_daily_derived": kd,
                "D_status": "derived_from_observed_rolling_1h_peak",
                "nominal_capacity_vph": float(m["nominal_capacity_vph"]),
                "capacity_basis": str(m["capacity_basis"]),
                "cutoff_speed_mph": float(m["cutoff_speed_mph"]),
                "k_mu": np.nan,
                "mu_vph": np.nan,
                "mu_status": "not_identified_by_adapter_requires_discharge_evidence",
                **state,
                "volume_status": "observed_integrated_5min_flow_rate",
            }
        )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(args.observations, dtype={"link_id": str, "tmc_id": str})
    metadata, mapping = load_metadata(args.corridor_root, args.keys)
    observations = build_observations(raw, args.keys)
    states = build_period_states(observations, metadata)

    metadata_out = metadata[
        [
            "model_link_id",
            "tmc_id",
            "corridor_id",
            "direction",
            "order_index",
            "from_node_id",
            "to_node_id",
            "length_mi",
            "lanes",
            "free_speed_mph",
            "cutoff_speed_mph",
            "nominal_capacity_vph",
            "capacity_basis",
            "link_type",
            "asset_type",
            "metadata_status",
        ]
    ].copy()
    observation_path = args.output_dir / "canonical_observations_5min.csv"
    metadata_path = args.output_dir / "canonical_link_sensor_metadata.csv"
    mapping_path = args.output_dir / "canonical_sensor_to_link_mapping.csv"
    state_path = args.output_dir / "canonical_daily_period_states.csv"
    observations.to_csv(observation_path, index=False)
    metadata_out.to_csv(metadata_path, index=False)
    mapping.to_csv(mapping_path, index=False)
    states.to_csv(state_path, index=False)

    manifest = {
        "adapter": "scripts/build_i405_slc_canonical_adapter.py",
        "source_observations": str(args.observations),
        "source_observations_sha256": sha256(args.observations),
        "corridor_root": str(args.corridor_root),
        "keys": args.keys,
        "timezone": "America/Los_Angeles",
        "interval_min": 5,
        "weekday_only": True,
        "observation_rows": int(len(observations)),
        "period_state_rows": int(len(states)),
        "important_limit": "The adapter does not identify k_mu, f_d, n, f_p, or s.",
        "outputs": {
            path.name: sha256(path)
            for path in [observation_path, metadata_path, mapping_path, state_path]
        },
    }
    (args.output_dir / "adapter_manifest.json").write_text(
        json.dumps(manifest, indent=2), encoding="utf-8"
    )
    print(f"Wrote {len(observations):,} canonical observations and {len(states):,} period states")
    print(f"Output directory: {args.output_dir}")


if __name__ == "__main__":
    main()
