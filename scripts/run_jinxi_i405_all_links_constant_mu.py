"""Calibrate all complete I-405 link/TMC profiles with constant-mu queues.

Stage 1 only.  S3 and triangular FD models are fitted link-by-link.  The
queue reference uses observed flow as lambda and one constant mu per period;
queues are never reset at period boundaries.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.calibrate import fit_models  # noqa: E402
from fdqbench.fd import S3FD, TriangularFD  # noqa: E402
from fdqbench.io import write_json  # noqa: E402
from fdqbench.metrics import period_volume_closure, queue_qaqc, regression_metrics  # noqa: E402
from fdqbench.reference import build_reference_day  # noqa: E402


DEFAULT_AVERAGE = ROOT / "data" / "jinxi_i405_week_2025-06-16_to_22" / "average_weekday_fdqbench.csv"
DEFAULT_SOURCE = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\IEEE Big Data"
    r"\I210E_corridor_data_package\multicorridor_2026_pilot"
    r"\trafficflowbench_five_corridors\data_public\kaggle_release"
    r"\corridors\D12_I405_S"
)


def args_parse() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--average", type=Path, default=DEFAULT_AVERAGE)
    p.add_argument("--source", type=Path, default=DEFAULT_SOURCE)
    p.add_argument("--output", type=Path, default=ROOT / "outputs" / "jinxi_i405_all_links_constant_mu")
    return p.parse_args()


def metadata(source: Path) -> tuple[pd.DataFrame, pd.DataFrame]:
    links = pd.read_csv(source / "network" / "links.csv")
    fd = pd.read_csv(source / "network" / "fd_parameters.csv")
    return links, fd


def link_meta(links: pd.DataFrame, fd: pd.DataFrame, link_id: str, tmc_id: str) -> dict:
    row = links[links.link_id.astype(str).eq(str(link_id))]
    if row.empty:
        raise ValueError(f"Missing link metadata: {link_id}")
    r = row.iloc[0]
    lanes = float(r.lanes)
    fdr = fd[fd.link_id.astype(str).eq(str(link_id)) & fd.station_id.astype(str).eq(str(tmc_id))]
    out = {
        "link_id": str(link_id),
        "tmc_id": str(tmc_id),
        "lanes": lanes,
        "length_mi": float(r.length_km) * 0.621371192237334,
        "free_speed_mph": float(r.free_speed_kmh) * 0.621371192237334,
        "capacity_vehphpl": float(r.capacity_vph) / lanes,
    }
    if not fdr.empty:
        out["cutoff_speed_mph"] = float(fdr.iloc[0].v_cut) * 0.621371192237334
    return out


def triangular_speed_prediction(speed: pd.Series, params: dict) -> np.ndarray:
    """Full-range triangular speed envelope for diagnostics only.

    Congested speeds use the exact congested-branch inverse.  Free-flow speeds
    use the capacity envelope because speed alone does not identify free-flow
    volume under a triangular FD.
    """
    fd = TriangularFD(**params)
    v = np.asarray(speed, dtype=float)
    return np.where(v < fd.cutoff_speed_mph, [fd.congested_flow_from_speed(x) for x in v], fd.capacity_vehphpl)


def main() -> None:
    a = args_parse()
    avg = pd.read_csv(a.average)
    links, fd = metadata(a.source)
    periods = [
        {"name": "NT1", "start": "00:00", "end": "06:00"},
        {"name": "AM", "start": "06:00", "end": "10:00"},
        {"name": "MD", "start": "10:00", "end": "15:00"},
        {"name": "PM", "start": "15:00", "end": "19:00"},
        {"name": "NT2", "start": "19:00", "end": "23:59"},
    ]
    a.output.mkdir(parents=True, exist_ok=True)

    summaries = []
    all_refs = []
    all_mu = []
    all_models = {}
    skipped = []

    for (link_id, tmc_id), g in avg.groupby(["link_id", "tmc_id"], sort=True):
        g = g.sort_values("time_of_day").reset_index(drop=True)
        if len(g) != 288:
            skipped.append({"link_id": str(link_id), "tmc_id": str(tmc_id), "rows": int(len(g))})
            continue
        meta = link_meta(links, fd, str(link_id), str(tmc_id))
        models = fit_models(g, "speed_mph", "flow_vehph", lanes=meta["lanes"])
        s3 = S3FD(**models["s3"]["parameters"])
        q_s3 = s3.flow_from_speed(g.speed_mph.to_numpy()) * meta["lanes"]
        q_tri = triangular_speed_prediction(g.speed_mph, models["triangular"]["parameters"]) * meta["lanes"]
        s3_metrics = regression_metrics(g.flow_vehph, q_s3)
        tri_metrics = regression_metrics(g.flow_vehph, q_tri)

        g = g.copy()
        g["arrival_vehph"] = g["flow_vehph"]
        ref, mu = build_reference_day(
            g,
            meta,
            periods,
            {"name": "s3", "parameters": models["s3"]["parameters"], "period_volume_anchor": "observed"},
            {"mode": "post_t2_median", "flow_col": "flow_observed_vehph", "blend_intervals": 0,
             "t2_by_period": {"AM": "08:15", "MD": "13:00", "PM": "17:15"}},
            dt_minutes=5,
            initial_queue_veh=0.0,
        )
        ref["link_id"] = str(link_id)
        ref["tmc_id"] = str(tmc_id)
        all_refs.append(ref)
        all_mu.extend({"link_id": str(link_id), "tmc_id": str(tmc_id), "period": p, "mu_ref_vehph": v} for p, v in mu.items())
        all_models[f"{link_id}|{tmc_id}"] = {"metadata": meta, "models": models}
        summaries.append({
            "link_id": str(link_id), "tmc_id": str(tmc_id), "lanes": meta["lanes"],
            "n_rows": len(g), "s3_mae_vehph": s3_metrics.get("mae"),
            "s3_rmse_vehph": s3_metrics.get("rmse"), "s3_mape_pct": s3_metrics.get("mape_pct"),
            "s3_r2": s3_metrics.get("r2"), "tri_mae_vehph": tri_metrics.get("mae"),
            "tri_rmse_vehph": tri_metrics.get("rmse"), "tri_mape_pct": tri_metrics.get("mape_pct"),
            "tri_r2": tri_metrics.get("r2"), "max_queue_veh": float(ref.queue_end_veh.max()),
            "queue_end_veh": float(ref.queue_end_veh.iloc[-1]),
        })

    summary = pd.DataFrame(summaries).sort_values("s3_rmse_vehph")
    summary.to_csv(a.output / "link_model_summary.csv", index=False)
    pd.concat(all_refs, ignore_index=True).to_csv(a.output / "reference_all_links.csv", index=False)
    pd.DataFrame(all_mu).to_csv(a.output / "mu_by_period_all_links.csv", index=False)
    write_json(all_models, a.output / "fitted_models_all.json")
    write_json({"n_complete_profiles": len(summaries), "skipped": skipped}, a.output / "run_manifest.json")
    print(summary.to_string(index=False))
    print(json.dumps({"output": str(a.output), "complete_profiles": len(summaries), "skipped": skipped}, indent=2))


if __name__ == "__main__":
    main()
