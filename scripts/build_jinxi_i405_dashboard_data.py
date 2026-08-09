"""Build a self-contained data.js file for the first I-405 dashboard."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "dashboard" / "data.js"
REFERENCE = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "reference_all_links.csv"
SUMMARY = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "link_model_summary.csv"
MODELS = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "fitted_models_all.json"
MENTOR = ROOT / "outputs" / "jinxi_i405_mentor_comparison" / "mentor_triangular_comparison.json"
PERIOD_MODELS = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_period_models.json"
ANCHORED_MODELS = ROOT / "outputs" / "jinxi_i405_s3_period_models" / "s3_anchored_models.json"
QUEUE_SENSITIVITY = ROOT / "outputs" / "jinxi_i405_queue_sensitivity" / "queue_sensitivity.json"
DYNAMIC_MU = ROOT / "outputs" / "jinxi_i405_dynamic_mu" / "dynamic_mu.json"
NORMAL = [("L405S-001", "1222782"), ("L405S-001", "1223027"), ("L405S-020", "1201419"), ("L405S-061", "1201350")]


def main() -> None:
    ref = pd.read_csv(REFERENCE)
    summary = pd.read_csv(SUMMARY)
    models = json.loads(MODELS.read_text(encoding="utf-8"))
    mentor = json.loads(MENTOR.read_text(encoding="utf-8"))
    mentor_by_id = {x["id"]: x for x in mentor["links"]}
    period_models = json.loads(PERIOD_MODELS.read_text(encoding="utf-8"))
    period_by_id = {x["id"]: x for x in period_models["links"]}
    anchored = json.loads(ANCHORED_MODELS.read_text(encoding="utf-8"))
    anchored_by_id = {x["id"]: x for x in anchored["links"]}
    queue_sensitivity = json.loads(QUEUE_SENSITIVITY.read_text(encoding="utf-8"))
    queue_by_id = {x["id"]: x for x in queue_sensitivity["links"]}
    dynamic_mu = json.loads(DYNAMIC_MU.read_text(encoding="utf-8"))
    dynamic_by_id = {x["id"]: x for x in dynamic_mu["links"]}
    links = []

    for link_id, tmc_id in NORMAL:
        g = ref[(ref.link_id == link_id) & (ref.tmc_id.astype(str) == tmc_id)].copy()
        s = summary[(summary.link_id == link_id) & (summary.tmc_id.astype(str) == tmc_id)].iloc[0]
        model = models[f"{link_id}|{tmc_id}"]
        mentor_model = mentor_by_id[f"{link_id}|{tmc_id}"]
        period_model = period_by_id[f"{link_id}|{tmc_id}"]
        anchored_model = anchored_by_id[f"{link_id}|{tmc_id}"]
        queue_model = queue_by_id[f"{link_id}|{tmc_id}"]
        dynamic_model = dynamic_by_id[f"{link_id}|{tmc_id}"]
        anchored_by_time = {x["time"]: x["flow"] for x in anchored_model["rows"]}
        queue_by_time = {x["time"]: x for x in queue_model["rows"]}
        dynamic_by_time = {x["time"]: x for x in dynamic_model["rows"]}
        params = model["models"]["s3"]["parameters"]
        lanes = float(s.lanes)
        g["density_vehpmipl"] = (g["flow_observed_vehph"] / lanes) / g["speed_mph"].clip(lower=1e-6)
        k = np.linspace(0, max(80.0, float(g.density_vehpmipl.max()) * 1.1), 120)
        s3 = params["free_speed_mph"] / (1 + (k / params["critical_density_vehpmipl"]) ** params["m"]) ** (2 / params["m"])
        curve = [{"density": float(x), "flow": float(x * y * lanes)} for x, y in zip(k, s3)]
        rows = []
        for _, r in g.sort_values("time_of_day").iterrows():
            pp = period_model["models"][r.period]["parameters"]
            ratio = max(float(pp["free_speed_mph"]) / max(float(r.speed_mph), 1e-9), 1.0)
            dens = float(pp["critical_density_vehpmipl"]) * max(ratio ** (float(pp["m"]) / 2.0) - 1.0, 0.0) ** (1.0 / float(pp["m"]))
            rows.append({
                "time": r.time_of_day, "speed": float(r.speed_mph),
                "observedFlow": float(r.flow_observed_vehph), "inferredFlow": float(r.flow_speed_only_vehph),
                "lambda": float(r.lambda_ref_vehph), "mu": float(r.mu_ref_vehph), "queue": float(r.queue_end_veh),
                "density": float(r.density_vehpmipl), "period": r.period, "flowSource": r.lambda_ref_source,
                "periodInferredFlow": float(r.speed_mph * dens * lanes),
                "anchoredInferredFlow": float(anchored_by_time[r.time_of_day]),
                "queueObserved": float(queue_by_time[r.time_of_day]["observed"]), "queuePeriodS3": float(queue_by_time[r.time_of_day]["periodS3"]), "queueAnchoredS3": float(queue_by_time[r.time_of_day]["anchoredS3"]),
                "muDynamic": float(dynamic_by_time[r.time_of_day]["muDynamic"]), "queueDynamic": float(dynamic_by_time[r.time_of_day]["queueDynamic"]),
            })
        errors = g["flow_speed_only_vehph"] - g["flow_observed_vehph"]
        period_stats = []
        for period in ["NT1", "AM", "MD", "PM", "NT2"]:
            pg = g[g["period"] == period]
            if pg.empty or period not in period_model["periodMetrics"]:
                continue
            pm = period_model["periodMetrics"][period]
            period_stats.append({"period": period, "n": int(len(pg)), "mae": pm["mae"], "rmse": pm["rmse"], "bias": pm["bias"], "observedMean": pm["observedMean"], "predictedMean": pm["predictedMean"]})
        links.append({
            "id": f"{link_id}|{tmc_id}", "linkId": link_id, "tmcId": tmc_id, "lanes": lanes,
            "rows": rows, "fdCurve": curve, "s3": params, "s3R2": float(s.s3_r2),
            "s3Mae": float(s.s3_mae_vehph), "s3Rmse": float(s.s3_rmse_vehph),
            "s3Mape": float(s.s3_mape_pct), "maxQueue": float(s.max_queue_veh),
            "queueEnd": float(s.queue_end_veh), "periodStats": period_stats,
            "mentorCurve": mentor_model["curve"], "mentorMetrics": mentor_model["metrics"],
            "mentorParameters": mentor_model["parameters"],
            "periodS3Overall": period_model["overall"], "periodS3Metrics": period_model["periodMetrics"],
            "anchoredS3Overall": anchored_model["overall"], "anchoredS3Metrics": anchored_model["periodMetrics"],
            "queueScenarios": queue_model["scenarios"],
            "dynamicMuSummary": dynamic_model["summary"], "dynamicMuByPeriod": dynamic_model["muByPeriod"],
        })

    payload = {
        "generatedFrom": str(REFERENCE),
        "timestampContract": "UTC ISO-8601 source timestamps retained; weekday profile and dashboard clock labels use America/Los_Angeles",
        "displayTimezone": "America/Los_Angeles",
        "links": links,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text("window.DASHBOARD_DATA = " + json.dumps(payload, separators=(",", ":")) + ";\n", encoding="utf-8")
    print(json.dumps({"output": str(OUT), "links": len(links)}, indent=2))


if __name__ == "__main__":
    main()
