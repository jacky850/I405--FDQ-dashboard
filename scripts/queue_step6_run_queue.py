"""Step 6 of the single-link queue plan: run the queue.

    out(t) = min( mu(t), lambda(t) + Q(t)/dt )
    Q(t+dt) = max( 0, Q(t) + [lambda(t) - out(t)] dt )

**One continuous recurrence from 06:00 to 19:00.** AM, MD and PM are labels on
the anchor, not boundaries in the model: nothing resets at 09:00 or 15:00, so a
queue standing at the start of PM is carried in rather than created there. That
is the whole reason step 5 was run over three periods instead of PM alone.

Q(06:00) = 0 is the initial condition -- an empty link in the early morning,
before the AM build-up.

lambda is the anchored arrival from step 5: pinned by the queue on the bins step
4 could identify, and levelled by V_assign on the 94% it could not. mu is the
two-regime service rate from step 2.

Nothing here is fitted. Step 4 already chose the arrival coefficients; this runs
the same recurrence forward with the anchored lambda and records what comes out,
which is what step 7 converts back into a speed.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "scripts"))

from queue_step4_arrival_rate import run_queue  # noqa: E402

DT_H = 15.0 / 60.0
DAY_START, DAY_END = 360, 1140          # 06:00 to 19:00
JAM_DENSITY_VEHPMIPL = 200.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--anchored-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step5_lambda_anchored_15min.csv")
    parser.add_argument("--queue-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step3_queue_target_15min.csv")
    parser.add_argument("--jam-density", type=float, default=JAM_DENSITY_VEHPMIPL)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    anchored = pd.read_csv(args.anchored_file)
    # queue_meas_veh is already carried by the anchored file; taking it from both
    # sides would only produce a suffixed duplicate.
    geometry = pd.read_csv(args.queue_file,
                           usecols=["link_id", "t_min", "length_mi", "free_speed_mph",
                                    "cutoff_mph", "storage_veh", "period"])
    frame = (anchored.merge(geometry, on=["link_id", "t_min"], how="left")
             .sort_values(["link_id", "t_min"]))
    frame = frame[(frame["t_min"] >= DAY_START) & (frame["t_min"] < DAY_END)]

    series_rows, link_rows = [], []
    for link_id, g in frame.groupby("link_id"):
        g = g.sort_values("t_min").reset_index(drop=True)
        arrival = g["lambda_anchored_vph"].to_numpy(float)
        service = g["mu_vph"].to_numpy(float)
        queue, outflow = run_queue(arrival, service)

        g = g.assign(queue_model_veh=queue, outflow_vph=outflow,
                     unmet_vph=np.maximum(arrival - outflow, 0.0))
        series_rows.append(g)

        target = g["queue_meas_veh"].to_numpy(float)
        queued = g["lambda_identifiable"].to_numpy(bool)
        storage = float(g["storage_veh"].iloc[0])
        boundaries = {label: float(queue[np.argmax(g["t_min"].to_numpy() >= minute)])
                      for label, minute in [("AM->MD 09:00", 540), ("MD->PM 15:00", 900)]}
        link_rows.append({
            "link_id": link_id, "corridor": g["corridor"].iloc[0],
            "tmc_code": g["tmc_code"].iloc[0], "lanes": int(g["lanes"].iloc[0]),
            "queue_peak_model_veh": float(queue.max()),
            "queue_peak_meas_veh": float(target.max()),
            "peak_ratio": float(queue.max() / target.max()) if target.max() > 0 else np.nan,
            "queue_at_AM_MD_boundary_veh": boundaries["AM->MD 09:00"],
            "queue_at_MD_PM_boundary_veh": boundaries["MD->PM 15:00"],
            "end_of_run_queue_veh": float(queue[-1]),
            "storage_veh": storage,
            "peak_over_storage": float(queue.max() / storage) if storage > 0 else np.nan,
            "bins_over_storage": int((queue > storage).sum()),
            "bins_at_capacity": int((outflow >= service - 1e-6).sum()),
            "unmet_demand_veh": float((np.maximum(arrival - outflow, 0.0) * DT_H).sum()),
            "residual_rmse_veh": float(np.sqrt(np.mean((queue - target) ** 2))),
            "residual_rmse_in_episode_veh": float(np.sqrt(np.mean((queue[queued] - target[queued]) ** 2)))
            if queued.any() else np.nan,
            "has_queue": bool(target.max() > 1.0),
        })

    series = pd.concat(series_rows, ignore_index=True)
    links = pd.DataFrame(link_rows)
    series.to_csv(args.output_dir / "step6_queue_run_15min.csv", index=False)
    links.to_csv(args.output_dir / "step6_by_link.csv", index=False)

    q = links[links["has_queue"]]
    carried = q[q["queue_at_MD_PM_boundary_veh"] > 1.0]
    report = {
        "step": "6. Run the queue",
        "recurrence": "out = min(mu, lambda + Q/dt); Q(t+dt) = max(0, Q + (lambda - out) dt)",
        "window": "06:00 to 19:00, one continuous run, Q(06:00) = 0",
        "bins": int(frame.groupby("link_id").size().iloc[0]),
        "links": int(len(links)),
        "links_with_a_queue": int(len(q)),
        "continuity": {
            "links_carrying_a_queue_into_PM": int(len(carried)),
            "median_carried_veh": round(float(carried["queue_at_MD_PM_boundary_veh"].median()), 1)
            if len(carried) else 0.0,
            "max_carried_veh": round(float(q["queue_at_MD_PM_boundary_veh"].max()), 1),
            "note": "These are the vehicles a PM-only run starting from an empty link would have "
                    "thrown away. Nothing resets at 09:00 or 15:00.",
        },
        "queue_peaks": {
            "model_median_veh": round(float(q["queue_peak_model_veh"].median()), 1),
            "measured_median_veh": round(float(q["queue_peak_meas_veh"].median()), 1),
            "peak_ratio_median": round(float(q["peak_ratio"].median()), 3),
        },
        "residual_vs_target": {
            "rmse_median_veh": round(float(q["residual_rmse_veh"].median()), 2),
            "rmse_in_episode_median_veh": round(float(q["residual_rmse_in_episode_veh"].median()), 2),
        },
        "physical_checks": {
            "bins_over_storage": int(links["bins_over_storage"].sum()),
            "links_over_storage": int((links["bins_over_storage"] > 0).sum()),
            "peak_over_storage_max": round(float(links["peak_over_storage"].max()), 3),
            "links_not_clearing_by_19:00": int((links["end_of_run_queue_veh"] > 1.0).sum()),
            "unmet_demand_total_veh": round(float(links["unmet_demand_veh"].sum()), 0),
        },
    }
    (args.output_dir / "step6_summary.json").write_text(json.dumps(report, indent=2),
                                                        encoding="utf-8")

    print("Step 6 -- run the queue\n")
    print(f"  {report['window']}, {report['bins']} bins per link")
    print(f"  {report['links']} links, {report['links_with_a_queue']} carry a queue")
    c = report["continuity"]
    print(f"\n  continuity: {c['links_carrying_a_queue_into_PM']} links arrive at 15:00 with a "
          f"queue already standing")
    print(f"    median {c['median_carried_veh']:.0f} veh, max {c['max_carried_veh']:.0f} -- "
          f"a PM-only run would have discarded these")
    p = report["queue_peaks"]
    print(f"\n  queue peak: model {p['model_median_veh']:.0f} veh vs target "
          f"{p['measured_median_veh']:.0f}, ratio {p['peak_ratio_median']:.3f}")
    r = report["residual_vs_target"]
    print(f"  residual: RMSE {r['rmse_median_veh']:.1f} veh over the run, "
          f"{r['rmse_in_episode_median_veh']:.1f} inside episodes")
    f = report["physical_checks"]
    print(f"\n  storage: {f['bins_over_storage']} bins over, worst peak/storage "
          f"{f['peak_over_storage_max']:.2f}")
    print(f"  links still queued at 19:00: {f['links_not_clearing_by_19:00']}")
    print(f"  unmet demand across all links: {f['unmet_demand_total_veh']:,.0f} veh")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
