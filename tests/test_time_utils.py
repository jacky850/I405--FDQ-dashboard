from __future__ import annotations

import pandas as pd

from fdqbench.time_utils import parse_pems_local_wall_clock


def test_literal_z_is_treated_as_pems_local_wall_clock() -> None:
    parsed = parse_pems_local_wall_clock(pd.Series(["2025-06-02T08:00:00Z"]))
    assert parsed.iloc[0].strftime("%Y-%m-%d %H:%M %z") == "2025-06-02 08:00 -0700"
