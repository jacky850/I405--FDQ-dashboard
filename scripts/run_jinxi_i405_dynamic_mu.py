"""Evaluate a first dynamic-mu candidate using continuous period transitions."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "reference_all_links.csv"
OUT = ROOT / "outputs" / "jinxi_i405_dynamic_mu" / "dynamic_mu.json"
NORMAL = [("L405S-001", "1222782"), ("L405S-001", "1223027"), ("L405S-020", "1201419"), ("L405S-061", "1201350")]
BLEND_INTERVALS = 6  # 30 minutes on either side of a period boundary

sys.path.insert(0, str(ROOT / "src"))
from fdqbench.queue import fifo_waiting_time  # noqa: E402


def smooth_mu(labels: np.ndarray, mu_by_period: dict[str, float], intervals: int) -> np.ndarray:
    base = np.array([mu_by_period[p] for p in labels], dtype=float); out = base.copy()
    changes = np.where(np.r_[False, labels[1:] != labels[:-1]])[0]
    for i in changes:
        if i == 0: continue
        lo, hi = max(0, i - intervals), min(len(out), i + intervals + 1)
        out[lo:hi] = np.linspace(base[i - 1], base[i], hi - lo)
    return out


def main() -> None:
    ref = pd.read_csv(REF); result = {"input": str(REF), "blendIntervals": BLEND_INTERVALS, "blendMinutes": BLEND_INTERVALS * 5, "links": []}
    for link_id, tmc_id in NORMAL:
        g = ref[(ref.link_id == link_id) & (ref.tmc_id.astype(str) == tmc_id)].copy().sort_values("time_of_day")
        labels = g.period.to_numpy(str); mu_by = {p: float(g.loc[g.period == p, "mu_ref_vehph"].iloc[0]) for p in np.unique(labels)}
        mu_dynamic = smooth_mu(labels, mu_by, BLEND_INTERVALS); flow = g.flow_observed_vehph.to_numpy(float); q_const = g.queue_end_veh.to_numpy(float)
        q_dynamic = fifo_waiting_time(flow, mu_dynamic, 5 / 60.0, 0.0)["queue_end_veh"].to_numpy(float)
        result["links"].append({"id": f"{link_id}|{tmc_id}", "linkId": link_id, "tmcId": tmc_id, "muByPeriod": mu_by, "rows": [{"time": t, "muDynamic": float(mu_dynamic[i]), "queueDynamic": float(q_dynamic[i])} for i, t in enumerate(g.time_of_day)], "summary": {"constantMaxQueue": float(q_const.max()), "dynamicMaxQueue": float(q_dynamic.max()), "constantFinalQueue": float(q_const[-1]), "dynamicFinalQueue": float(q_dynamic[-1]), "queueMaeDifference": float(np.mean(np.abs(q_dynamic - q_const))), "queueRmseDifference": float(np.sqrt(np.mean((q_dynamic - q_const) ** 2)))}})
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "links": len(result["links"])}, indent=2))


if __name__ == "__main__": main()
