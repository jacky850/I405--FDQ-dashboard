"""Time handling for the PeMS-derived TrafficFlowBench CSV files."""

from __future__ import annotations

import pandas as pd


PEMS_TIMEZONE = "America/Los_Angeles"


def parse_pems_local_wall_clock(values: pd.Series) -> pd.Series:
    """Parse CSV timestamps whose trailing Z was appended without UTC conversion.

    The source builder reads PeMS Station 5-Minute local timestamps as naive
    datetimes and serializes them with a literal ``Z``. Therefore the clock
    fields are Pacific local wall-clock values, not UTC instants.
    """

    clock = values.astype(str).str.replace(r"Z$", "", regex=True)
    parsed = pd.to_datetime(clock, errors="raise", format="mixed")
    return parsed.dt.tz_localize(
        PEMS_TIMEZONE,
        ambiguous="NaT",
        nonexistent="shift_forward",
    )
