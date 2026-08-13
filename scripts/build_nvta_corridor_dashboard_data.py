"""Build the browser payload for the I-395 NB corridor D and V dashboard."""

from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SOURCE = ROOT / "outputs/nvta_corridor_d_v_i395nb"
DESTINATION = ROOT / "dashboard/nvta_corridor_data.js"


def clean(value: object) -> object:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return None
    if isinstance(value, np.integer):
        return int(value)
    if isinstance(value, np.floating):
        return float(value)
    if isinstance(value, np.bool_):
        return bool(value)
    return value


def main() -> None:
    duration = json.loads((SOURCE / "corridor_d_v_summary.json").read_text(encoding="utf-8"))
    queue = json.loads((SOURCE / "duration_branch_vs_queue_summary.json").read_text(encoding="utf-8"))
    links = pd.read_csv(SOURCE / "duration_branch_vs_queue.csv")
    corridor = pd.read_csv(SOURCE / "corridor_queue_demand_15min.csv")

    columns = [
        "link_id", "period", "length_mi", "P_h", "vT2_mph", "vT2_predicted_mph",
        "x_hat_D_over_C", "demand_D_inferred_vph", "volume_V_inferred_veh",
        "demand_D_queue_vph", "d_over_c_queue", "queue_max_veh",
        "D_ratio_qvdf_over_queue", "episode_identified",
    ]
    rows = [
        {c: clean(r[c]) for c in columns}
        for _, r in links[links["episode_identified"]].sort_values(["period", "link_id"])[columns].iterrows()
    ]

    payload = {
        "duration": duration,
        "queue": queue,
        "links": rows,
        "corridorSeries": [
            [int(r.t_min), round(float(r.queue_veh), 2), round(float(r.demand_vph), 1), r.period]
            for r in corridor.sort_values("t_min").itertuples(index=False)
        ],
    }
    DESTINATION.write_text(
        "window.NVTA_CORRIDOR=" + json.dumps(payload, separators=(",", ":"), allow_nan=False) + ";\n",
        encoding="utf-8",
    )
    print(f"Wrote {DESTINATION} ({DESTINATION.stat().st_size / 1024:.1f} KiB, {len(rows)} link-periods)")


if __name__ == "__main__":
    main()
