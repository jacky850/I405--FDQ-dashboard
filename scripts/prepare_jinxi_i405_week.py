"""Extract one I-405 PeMS week into the FDQBench input contract.

The public corridor release contains processed 5-minute Parquet files.  This
adapter keeps only non-imputed mainline observations by default, converts
speed from km/h to mph, and maps each detector station to the link metadata
needed by FDQBench.
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

import pandas as pd


DEFAULT_SOURCE = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\trafficflowbench_five_corridors\data_public\kaggle_release"
    r"\corridors\D12_I405_S"
)
DEFAULT_START = "2025-06-16"
DEFAULT_END = "2025-06-22"
DEFAULT_OUTPUT = Path(__file__).resolve().parents[1] / "data" / "jinxi_i405_week_2025-06-16_to_22"
LOCAL_TIMEZONE = "America/Los_Angeles"


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--start", default=DEFAULT_START, help="Inclusive ISO date")
    p.add_argument("--end", default=DEFAULT_END, help="Inclusive ISO date")
    p.add_argument("--output", type=Path, default=DEFAULT_OUTPUT)
    p.add_argument(
        "--include-imputed",
        action="store_true",
        help="Keep imputed values. Default is observed-only for calibration ground truth.",
    )
    return p.parse_args()


def load_week(source: Path, start: str, end: str, include_imputed: bool) -> pd.DataFrame:
    start_ts = pd.Timestamp(start)
    end_ts = pd.Timestamp(end)
    # Include the next UTC date because the requested LA day ends during it.
    read_end = end_ts + pd.Timedelta(days=1)
    files = sorted((source / "train" / "mainline_states").glob("year_month=*/*.parquet"))
    if not files:
        raise FileNotFoundError(f"No mainline Parquet files found under {source}")

    chunks: list[pd.DataFrame] = []
    for file in files:
        # The partition filename is enough to avoid reading unrelated months.
        date_text = file.stem[-10:].replace("_", "-")
        file_date = pd.Timestamp(date_text)
        if file_date < start_ts or file_date > read_end:
            continue
        df = pd.read_parquet(file)
        # The release timestamp is UTC ISO-8601.  Date filtering is completed
        # after conversion to local time so a weekday profile follows LA clock.
        ts_local = pd.to_datetime(df["timestamp"], utc=True).dt.tz_convert(LOCAL_TIMEZONE)
        local_dates = ts_local.dt.date
        df["date"] = pd.to_datetime(df["date"]).dt.date
        df = df[(local_dates >= start_ts.date()) & (local_dates <= end_ts.date())]
        if not include_imputed:
            df = df[df["is_imputed"].eq(0)]
        chunks.append(df)

    if not chunks:
        raise ValueError(f"No rows found between {start} and {end}")
    return pd.concat(chunks, ignore_index=True)


def convert(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame, dict]:
    source = args.source.resolve()
    df = load_week(source, args.start, args.end, args.include_imputed)

    links = pd.read_csv(source / "network" / "links.csv")
    required_link_cols = {"link_id", "lanes"}
    missing = required_link_cols - set(links.columns)
    if missing:
        raise ValueError(f"links.csv is missing columns: {sorted(missing)}")
    link_meta = links[["link_id", "lanes"]].drop_duplicates("link_id")

    out = pd.DataFrame(
        {
            "timestamp": df["timestamp"].astype(str),
            "link_id": df["link_id"].astype(str),
            # FDQBench calls this field tmc_id; the release calls it station_id.
            "tmc_id": df["station_id"].astype(str),
            "speed_mph": df["speed_kmh"].astype(float) * 0.621371192237334,
            "flow_vehph": df["flow_vph"].astype(float),
            "pct_observed": df["pct_observed"].astype(float),
            "is_imputed": df["is_imputed"].astype(int),
            "source_date": df["date"].astype(str),
            "source_corridor": df["corridor_id"].astype(str),
        }
    )
    out = out.merge(link_meta, on="link_id", how="left", validate="many_to_one")
    if out["lanes"].isna().any():
        missing_links = sorted(out.loc[out["lanes"].isna(), "link_id"].unique())
        raise ValueError(f"No lane metadata for links: {missing_links[:10]}")
    out["lanes"] = out["lanes"].astype(int)
    out = out.sort_values(["link_id", "timestamp", "tmc_id"]).reset_index(drop=True)

    ts_utc = pd.to_datetime(out["timestamp"], utc=True)
    ts_local = ts_utc.dt.tz_convert(LOCAL_TIMEZONE)
    out["timestamp_la"] = ts_local.astype(str)
    weekday = out.loc[ts_local.dt.dayofweek < 5].copy()
    weekday["time_of_day"] = ts_local.loc[weekday.index].dt.floor("5min").dt.strftime("%H:%M")
    average_weekday = (
        weekday.groupby(["link_id", "tmc_id", "time_of_day"], as_index=False)
        .agg(speed_mph=("speed_mph", "mean"), flow_vehph=("flow_vehph", "mean"))
        .sort_values(["link_id", "tmc_id", "time_of_day"])
        .reset_index(drop=True)
    )

    manifest = {
        "source": str(source),
        "corridor": "D12_I405_S",
        "start_date": args.start,
        "end_date": args.end,
        "include_imputed": bool(args.include_imputed),
        "observed_only": not args.include_imputed,
        "rows": int(len(out)),
        "average_weekday_rows": int(len(average_weekday)),
        "links": int(out["link_id"].nunique()),
        "stations": int(out["tmc_id"].nunique()),
        "dates": int(out["source_date"].nunique()),
        "speed_conversion": "speed_mph = speed_kmh * 0.621371192237334",
        "flow_units": "veh/hour; copied from flow_vph",
        "local_timezone": LOCAL_TIMEZONE,
        "timestamp_contract": "UTC ISO-8601 source timestamp retained; weekday grouping and time_of_day use America/Los_Angeles",
        "note": "This is a processed 5-minute public release; observed-only output excludes is_imputed == 1.",
    }
    return out, average_weekday, manifest


def main() -> None:
    args = parse_args()
    out, average_weekday, manifest = convert(args)
    args.output.mkdir(parents=True, exist_ok=True)
    csv_path = args.output / "raw_observed_fdqbench.csv"
    average_path = args.output / "average_weekday_fdqbench.csv"
    manifest_path = args.output / "selection_manifest.json"
    out.to_csv(csv_path, index=False)
    average_weekday.to_csv(average_path, index=False)
    manifest_path.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"raw_csv": str(csv_path), "average_weekday_csv": str(average_path), "manifest": str(manifest_path), **manifest}, indent=2))


if __name__ == "__main__":
    main()
