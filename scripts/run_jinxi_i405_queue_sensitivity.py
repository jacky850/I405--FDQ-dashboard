"""Compare queue trajectories under observed, period-S3, and anchored-S3 inflow."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REF = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "reference_all_links.csv"
PERIOD = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_period_models.json"
ANCHOR = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_anchored_models.json"
OUT = ROOT / "outputs" / "jinxi_i405_queue_sensitivity" / "queue_sensitivity.json"
NORMAL = [("L405S-001", "1222782"), ("L405S-001", "1223027"), ("L405S-020", "1201419"), ("L405S-061", "1201350")]

sys.path.insert(0, str(ROOT / "src"))
from fdqbench.queue import fifo_waiting_time  # noqa: E402


def summarize(q: np.ndarray, baseline: np.ndarray) -> dict[str, float]:
    e = q - baseline
    return {"maxQueue": float(q.max()), "finalQueue": float(q[-1]), "maeVsObservedBaseline": float(np.mean(np.abs(e))), "rmseVsObservedBaseline": float(np.sqrt(np.mean(e ** 2)))}


def main() -> None:
    ref = pd.read_csv(REF); period = json.loads(PERIOD.read_text(encoding="utf-8")); anchor = json.loads(ANCHOR.read_text(encoding="utf-8"))
    period_by_id = {x["id"]: x for x in period["links"]}; anchor_by_id = {x["id"]: x for x in anchor["links"]}
    out = {"input": str(REF), "sameMu": True, "dtMinutes": 5, "initialQueueVeh": 0, "links": []}
    for link_id, tmc_id in NORMAL:
        key = f"{link_id}|{tmc_id}"; g = ref[(ref.link_id == link_id) & (ref.tmc_id.astype(str) == tmc_id)].copy().sort_values("time_of_day")
        mu = g.mu_ref_vehph.to_numpy(float); observed = g.flow_observed_vehph.to_numpy(float); baseline = g.queue_end_veh.to_numpy(float)
        p = period_by_id[key]; raw = np.zeros(len(g));
        for i, (_, r) in enumerate(g.iterrows()):
            m = p["models"][r.period]["parameters"]; ratio = max(m["free_speed_mph"] / max(float(r.speed_mph), 1e-9), 1.0); density = m["critical_density_vehpmipl"] * max(ratio ** (m["m"] / 2.0) - 1.0, 0.0) ** (1.0 / m["m"]); raw[i] = float(r.speed_mph * density * ({"L405S-001": 5, "L405S-020": 6, "L405S-061": 6}[link_id]))
        anchor_rows = {x["time"]: x["flow"] for x in anchor_by_id[key]["rows"]}; anchored = np.array([anchor_rows[t] for t in g.time_of_day], dtype=float)
        queues = {}
        for name, flow in [("observed", observed), ("periodS3", raw), ("anchoredS3", anchored)]:
            queues[name] = fifo_waiting_time(flow, mu, 5 / 60.0, 0.0)["queue_end_veh"].to_numpy(float)
        out["links"].append({"id": key, "linkId": link_id, "tmcId": tmc_id, "rows": [{"time": t, "observed": float(queues["observed"][i]), "periodS3": float(queues["periodS3"][i]), "anchoredS3": float(queues["anchoredS3"][i])} for i, t in enumerate(g.time_of_day)], "scenarios": {k: summarize(v, baseline) for k, v in queues.items()}})
    OUT.parent.mkdir(parents=True, exist_ok=True); OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "links": len(out["links"])}, indent=2))


if __name__ == "__main__": main()
