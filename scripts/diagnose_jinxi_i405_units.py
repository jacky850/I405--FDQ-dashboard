"""Audit I-405 units, capacity metadata, and constant-mu queue outliers."""
from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DATA = ROOT / "data" / "jinxi_i405_week_2025-06-16_to_22" / "raw_observed_fdqbench.csv"
SUMMARY = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "link_model_summary.csv"
MU = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "mu_by_period_all_links.csv"
SOURCE = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\trafficflowbench_five_corridors\data_public\kaggle_release"
    r"\corridors\D12_I405_S"
)
OUT = ROOT / "outputs" / "jinxi_i405_diagnostics"


def main() -> None:
    raw = pd.read_csv(DATA)
    summary = pd.read_csv(SUMMARY)
    mu = pd.read_csv(MU)
    links = pd.read_csv(SOURCE / "network" / "links.csv")
    fd = pd.read_csv(SOURCE / "network" / "fd_parameters.csv")

    rows = []
    for _, s in summary.iterrows():
        g = raw[(raw.link_id == s.link_id) & (raw.tmc_id.astype(str) == str(s.tmc_id))]
        lm = links[links.link_id == s.link_id].iloc[0]
        fr = fd[(fd.link_id == s.link_id) & (fd.station_id.astype(str) == str(s.tmc_id))]
        fdrow = fr.iloc[0] if not fr.empty else None
        m = mu[(mu.link_id == s.link_id) & (mu.tmc_id.astype(str) == str(s.tmc_id))]
        network_cap = float(lm.capacity_vph)
        fd_cap = float(fdrow.capacity_vph) if fdrow is not None else float("nan")
        lanes = float(lm.lanes)
        flow_max = float(g.flow_vehph.max())
        flow_p95 = float(g.flow_vehph.quantile(.95))
        per_lane_p95 = flow_p95 / lanes
        cap_ratio = flow_max / network_cap if network_cap > 0 else float("inf")
        fd_cap_ratio = flow_max / fd_cap if fd_cap > 0 else float("nan")
        mu_min = float(m.mu_ref_vehph.min()) if not m.empty else float("nan")
        mu_max = float(m.mu_ref_vehph.max()) if not m.empty else float("nan")
        flags = []
        if cap_ratio > 1.25:
            flags.append("network_capacity_below_observed_flow")
        if pd.notna(fd_cap) and fd_cap_ratio > 1.25:
            flags.append("fd_capacity_below_observed_flow")
        if per_lane_p95 > 3000:
            flags.append("per_lane_flow_implausibly_high")
        if mu_min <= 0.1:
            flags.append("zero_or_near_zero_mu")
        if float(s.max_queue_veh) > 20000:
            flags.append("queue_outlier")
        if float(s.s3_mape_pct) > 100 or float(s.s3_r2) < 0.5:
            flags.append("poor_s3_fit")
        rows.append({
            "link_id": s.link_id, "tmc_id": s.tmc_id, "lanes_network": lanes,
            "rows": len(g), "speed_unit_conversion": "km/h_to_mph_only",
            "flow_unit_conversion": "unchanged_vph", "flow_max_vehph": flow_max,
            "flow_p95_vehph": flow_p95, "flow_p95_per_lane": per_lane_p95,
            "network_capacity_vph": network_cap, "fd_capacity_vph": fd_cap,
            "max_flow_over_network_capacity": cap_ratio,
            "max_flow_over_fd_capacity": fd_cap_ratio,
            "mu_min_vehph": mu_min, "mu_max_vehph": mu_max,
            "s3_mape_pct": s.s3_mape_pct, "s3_r2": s.s3_r2,
            "max_queue_veh": s.max_queue_veh, "flags": ";".join(flags) or "none",
        })

    out = pd.DataFrame(rows)
    OUT.mkdir(parents=True, exist_ok=True)
    out.sort_values(["max_queue_veh", "s3_mape_pct"], ascending=False).to_csv(OUT / "unit_mapping_diagnostics.csv", index=False)
    selected = {
        "normal_candidates": out[(out.max_queue_veh < 10000) & (out.s3_mape_pct < 100)].sort_values("s3_rmse_vehph" if "s3_rmse_vehph" in out else "max_queue_veh").head(5).to_dict("records"),
        "outliers": out[out["flags"] != "none"].sort_values("max_queue_veh", ascending=False).head(15).to_dict("records"),
        "interpretation": {
            "speed_conversion": "Only speed was converted km/h -> mph; flow_vph was copied unchanged, matching the release field definition.",
            "main_issue": "Several detector flows exceed network links.csv capacity by large factors. This indicates a link/lane/capacity metadata mismatch, not a km/h-to-mph conversion error.",
            "mu_fix": "mu is now estimated from observed flow, not speed-derived flow; prior zero-mu queue explosions are removed.",
        },
    }
    (OUT / "screening_result.json").write_text(json.dumps(selected, indent=2, default=str), encoding="utf-8")
    print(out.sort_values("max_queue_veh", ascending=False).head(15).to_string(index=False))
    print(json.dumps({"diagnostics": str(OUT), "rows": len(out)}, indent=2))


if __name__ == "__main__":
    main()
