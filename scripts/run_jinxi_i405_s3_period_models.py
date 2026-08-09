"""Evaluate period-specific direct-flow S3 models on the LA weekday profile."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
INPUT = ROOT / "data" / "jinxi_i405_week_2025-06-16_to_22" / "average_weekday_fdqbench.csv"
OUT = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_period_models.json"
NORMAL = [("L405S-001", "1222782"), ("L405S-001", "1223027"), ("L405S-020", "1201419"), ("L405S-061", "1201350")]
PERIODS = ["NT1", "AM", "MD", "PM", "NT2"]

import sys
sys.path.insert(0, str(ROOT / "src"))
from fdqbench.calibrate import fit_s3_from_speed_flow  # noqa: E402
from fdqbench.fd import S3FD  # noqa: E402


def assign_period(t: str) -> str:
    h, m = map(int, str(t).split(":")[:2])
    x = h * 60 + m
    if x < 360: return "NT1"
    if x < 600: return "AM"
    if x < 900: return "MD"
    if x < 1140: return "PM"
    return "NT2"


def metric(obs: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    e = pred - obs
    ss = np.sum((obs - obs.mean()) ** 2)
    return {"mae": float(np.mean(np.abs(e))), "rmse": float(np.sqrt(np.mean(e ** 2))), "r2": float(1 - np.sum(e ** 2) / ss) if ss else float("nan"), "bias": float(np.mean(e)), "observedMean": float(np.mean(obs)), "predictedMean": float(np.mean(pred))}


def main() -> None:
    df = pd.read_csv(INPUT)
    df["period"] = df["time_of_day"].map(assign_period)
    payload = {"input": str(INPUT), "fit_target": "direct speed-to-flow", "links": []}
    for link_id, tmc_id in NORMAL:
        g = df[(df.link_id == link_id) & (df.tmc_id.astype(str) == tmc_id)].copy().sort_values("time_of_day")
        lanes = float({"L405S-001": 5, "L405S-020": 6, "L405S-061": 6}[link_id])
        pred = np.full(len(g), np.nan)
        models = {}
        for period in PERIODS:
            idx = g.index[g.period == period]
            sub = g.loc[idx]
            if len(sub) < 10:
                continue
            fd, info = fit_s3_from_speed_flow(sub.speed_mph, sub.flow_vehph, lanes=lanes)
            models[period] = {"parameters": fd.to_dict(), "fit": info, "n": int(len(sub))}
            pred[g.index.get_indexer(idx)] = fd.flow_from_speed(sub.speed_mph.to_numpy()) * lanes
        obs = g.flow_vehph.to_numpy(float)
        valid = np.isfinite(pred)
        period_metrics = {p: metric(g.loc[g.period == p, "flow_vehph"].to_numpy(float), pred[g.period.to_numpy() == p]) for p in PERIODS if p in models}
        payload["links"].append({"id": f"{link_id}|{tmc_id}", "linkId": link_id, "tmcId": tmc_id, "models": models, "overall": metric(obs[valid], pred[valid]), "periodMetrics": period_metrics})
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(payload, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "links": len(payload["links"])}, indent=2))


if __name__ == "__main__":
    main()
