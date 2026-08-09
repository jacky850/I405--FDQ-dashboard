"""Run a mentor-equation FD comparison on the same LA-time PeMS links.

This mirrors the FD equations in the mentor's FDQ_LA_q_only_v1.py and
FDQ_LA_q_only_v2.py while keeping the mentor source files unchanged. The
mentor workbook convention is retained: speed in mph, flow in veh/h/lane,
and density in veh/mi/lane.
"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.optimize import curve_fit

ROOT = Path(__file__).resolve().parents[1]
REFERENCE = ROOT / "outputs" / "jinxi_i405_all_links_constant_mu" / "reference_all_links.csv"
OUT = ROOT / "outputs" / "jinxi_i405_mentor_comparison" / "mentor_triangular_comparison.json"
NORMAL = [("L405S-001", "1222782"), ("L405S-001", "1223027"), ("L405S-020", "1201419"), ("L405S-061", "1201350")]


def mentor_triangular(k: np.ndarray, k_c: float, k_jam: float, v_f: float) -> np.ndarray:
    """Same piecewise equation used by mentor FDQ_LA_q_only_v1.py."""
    q = np.zeros_like(k, dtype=float)
    free = (0 <= k) & (k < k_c)
    cong = (k_c <= k) & (k < k_jam)
    q[free] = v_f * k[free]
    q[cong] = v_f * k_c * (k_jam - k[cong]) / (k_jam - k_c)
    return q


def mentor_fdq_drop(k: np.ndarray, k_c: float, k_jam: float, maximum_capacity: float, cap: float, min_flow: float) -> np.ndarray:
    """Same capacity-drop equation used by mentor FDQ_LA_q_only_v2.py."""
    q = np.zeros_like(k, dtype=float)
    free = (0 <= k) & (k < k_c)
    cong = (k_c < k) & (k <= k_jam)
    q[free] = min_flow + (maximum_capacity - min_flow) * (k[free] / k_c)
    q[k == k_c] = cap
    q[cong] = cap - (cap - min_flow) * ((k[cong] - k_c) / (k_jam - k_c))
    return q


def metrics(obs: np.ndarray, pred: np.ndarray) -> dict[str, float]:
    e = pred - obs
    ss = np.sum((obs - obs.mean()) ** 2)
    return {
        "mae_vehph_total": float(np.mean(np.abs(e))),
        "rmse_vehph_total": float(np.sqrt(np.mean(e**2))),
        "r2": float(1 - np.sum(e**2) / ss) if ss else float("nan"),
    }


def main() -> None:
    ref = pd.read_csv(REFERENCE)
    result = {
        "input": str(REFERENCE),
        "model": "mentor_fdq_only_equations_v1_v2",
        "unit_contract": {
            "speed": "mph (as used by mentor workbook)",
            "flow_fit": "veh/h/lane",
            "density_fit": "veh/mi/lane",
            "reported_flow": "veh/h total link",
            "time": "LA local weekday profile",
        },
        "links": [],
    }

    for link_id, tmc_id in NORMAL:
        g = ref[(ref.link_id == link_id) & (ref.tmc_id.astype(str) == tmc_id)].copy()
        lanes = float(g["lanes"].iloc[0]) if "lanes" in g else float({"L405S-001": 5, "L405S-020": 6, "L405S-061": 6}[link_id])
        flow_total = g["flow_observed_vehph"].to_numpy(float)
        flow_lane = flow_total / lanes
        speed_mph = g["speed_mph"].to_numpy(float)
        density = flow_lane / np.maximum(speed_mph, 1e-6)
        order = np.argsort(density)
        k_fit, q_fit = density[order], flow_lane[order]
        v1_params, _ = curve_fit(mentor_triangular, k_fit, q_fit, p0=[3.0, 10.0, 2.0], maxfev=20000)
        v1_pred_total = mentor_triangular(density, *v1_params) * lanes
        maximum_capacity = float(q_fit.max())
        approx_k_c = float(k_fit[np.argmax(q_fit)])
        cap = 0.85 * maximum_capacity
        min_flow = 0.1 * maximum_capacity
        p0 = [approx_k_c, 150.0, maximum_capacity, cap, min_flow]
        bounds = ([approx_k_c * 0.8, 100.0, maximum_capacity * 0.95, cap * 0.8, min_flow * 0.8],
                  [approx_k_c * 1.2, 200.0, maximum_capacity * 1.05, cap * 1.2, min_flow * 1.2])
        v2_params, _ = curve_fit(mentor_fdq_drop, k_fit, q_fit, p0=p0, bounds=bounds, maxfev=50000)
        v2_pred_total = mentor_fdq_drop(density, *v2_params) * lanes
        k_curve = np.linspace(0, max(120.0, float(density.max()) * 1.05), 160)
        v1_curve_total = mentor_triangular(k_curve, *v1_params) * lanes
        v2_curve_total = mentor_fdq_drop(k_curve, *v2_params) * lanes
        result["links"].append({
            "id": f"{link_id}|{tmc_id}", "linkId": link_id, "tmcId": tmc_id, "lanes": lanes,
            "parameters": {"critical_density_vehpipl": float(v2_params[0]), "jam_density_vehpipl": float(v2_params[1]), "maximum_capacity_vehphpl": float(v2_params[2]), "capacity_drop_vehphpl": float(v2_params[3]), "minimum_flow_vehphpl": float(v2_params[4])},
            "metrics": metrics(flow_total, v2_pred_total),
            "variants": {
                "v1_triangular": {"parameters": {"critical_density_vehpipl": float(v1_params[0]), "jam_density_vehpipl": float(v1_params[1]), "free_speed_mph": float(v1_params[2])}, "metrics": metrics(flow_total, v1_pred_total)},
                "v2_capacity_drop": {"parameters": {"critical_density_vehpipl": float(v2_params[0]), "jam_density_vehpipl": float(v2_params[1]), "maximum_capacity_vehphpl": float(v2_params[2]), "capacity_drop_vehphpl": float(v2_params[3]), "minimum_flow_vehphpl": float(v2_params[4])}, "metrics": metrics(flow_total, v2_pred_total)},
            },
            "points": [{"density": float(k), "flow": float(q)} for k, q in zip(density, flow_total)],
            "curve": [{"density": float(k), "flow": float(q)} for k, q in zip(k_curve, v2_curve_total)],
            "curveV1": [{"density": float(k), "flow": float(q)} for k, q in zip(k_curve, v1_curve_total)],
        })

    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text(json.dumps(result, indent=2), encoding="utf-8")
    print(json.dumps({"output": str(OUT), "links": len(result["links"])}, indent=2))


if __name__ == "__main__":
    main()
