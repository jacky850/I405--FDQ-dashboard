"""Create period-volume-anchored period-specific S3 candidates."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "jinxi_i405_week_2025-06-16_to_22" / "average_weekday_fdqbench.csv"
PERIOD_MODELS = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_period_models.json"
OUT = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_anchored_models.json"
PERIODS = ["NT1", "AM", "MD", "PM", "NT2"]
NORMAL = [("L405S-001", "1222782"), ("L405S-001", "1223027"), ("L405S-020", "1201419"), ("L405S-061", "1201350")]


def metric(obs: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    e = pred - obs
    ss = np.sum((obs - obs.mean()) ** 2)
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))), "r2": float(1 - np.sum(e ** 2) / ss) if ss else float("nan"), "bias": float(np.mean(e))}


def assign_period(t: str) -> str:
    h, m = map(int, str(t).split(":")[:2]); x = h * 60 + m
    if x < 360: return "NT1"
    if x < 600: return "AM"
    if x < 900: return "MD"
    if x < 1140: return "PM"
    return "NT2"


def main() -> None:
    df = pd.read_csv(INPUT); df["period"] = df.time_of_day.map(assign_period)
    period_models = json.loads(PERIOD_MODELS.read_text(encoding="utf-8")); by_id = {x["id"]: x for x in period_models["links"]}
    out = {"input": str(INPUT), "method": "period-specific S3 shape anchored to observed period volume", "links": []}
    for link_id, tmc_id in NORMAL:
        g = df[(df.link_id == link_id) & (df.tmc_id.astype(str) == tmc_id)].copy().sort_values("time_of_day")
        lanes = float({"L405S-001": 5, "L405S-020": 6, "L405S-061": 6}[link_id])
        pm = by_id[f"{link_id}|{tmc_id}"]; raw = np.full(len(g), np.nan); anchored = np.full(len(g), np.nan); factors = {}
        for period in PERIODS:
            mask = g.period.to_numpy() == period; model = pm["models"][period]["parameters"]
            speed = g.loc[mask, "speed_mph"].to_numpy(float); obs = g.loc[mask, "flow_vehph"].to_numpy(float)
            ratio = np.maximum(model["free_speed_mph"] / np.maximum(speed, 1e-9), 1.0)
            density = model["critical_density_vehpmipl"] * np.maximum(ratio ** (model["m"] / 2.0) - 1.0, 0.0) ** (1.0 / model["m"])
            rp = speed * density * lanes; raw[mask] = rp
            factor = float(obs.sum() / rp.sum()) if rp.sum() > 1e-9 else 1.0; factors[period] = factor; anchored[mask] = rp * factor
        obs_all = g.flow_vehph.to_numpy(float); period_metrics = {}
        for period in PERIODS:
            mask = g.period.to_numpy() == period; period_metrics[period] = metric(obs_all[mask], anchored[mask])
        out["links"].append({"id": f"{link_id}|{tmc_id}", "linkId": link_id, "tmcId": tmc_id, "factors": factors, "overall": metric(obs_all, anchored), "periodMetrics": period_metrics, "rows": [{"time": t, "flow": float(q)} for t, q in zip(g.time_of_day, anchored)]})
    OUT.write_text(json.dumps(out, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "links": len(out["links"])}, indent=2))


if __name__ == "__main__": main()
