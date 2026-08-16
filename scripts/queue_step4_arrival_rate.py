"""Step 4 of the single-link queue plan: the arrival rate lambda(t).

lambda is demand -- how many vehicles per hour want through -- as against mu,
what the link can pass, and `out`, what actually got through. It is never
directly observable here: in free flow it equals the flow, which is exactly
where recovering flow from speed fails, and under a queue the recoverable flow
is the discharge, which is mu.

What makes it recoverable is that the queue accumulates the gap:

    Q(t+dt) - Q(t) = [lambda(t) - out(t)] dt        ->    lambda = mu + dQ/dt

That is not used pointwise. Q is itself derived from speed, so a wobble in v
becomes a wobble in Q and differencing multiplies it. lambda is carried instead
by a cubic B-spline in time of day on 60-minute knots -- 27 coefficients against
96 bins -- fitted by running the recurrence forward and comparing the queue it
produces against the step 3 target.

The smoothness is a physical prior rather than a numerical convenience: real
demand builds over tens of minutes, it does not jump every quarter hour. This is
the same conservation equation, regularised. Pointwise it is ill-posed;
restricted to smooth solutions it is well-posed, and that is what makes a single
link tractable instead of forcing a corridor aggregate.

**The queue is produced, never read.** Q comes out of the recurrence, so it
carries Q(t-1) by construction and satisfies conservation automatically. Q_meas
is only the target, which is what makes the residual a measure of how much of
the observed speed a smooth arrival process can account for, rather than a
tautology.

Where there is no queue, Q is identically zero for *any* lambda below mu -- 800,
1500 and 1999 all give the same queue and the same speed. Those bins carry no
information and are flagged for step 5 rather than being reported as estimates.
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd
from scipy.interpolate import BSpline
from scipy.optimize import least_squares

ROOT = Path(__file__).resolve().parents[1]
DT_H = 15.0 / 60.0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--queue-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step3_queue_target_15min.csv")
    parser.add_argument("--knot-spacing-min", type=float, default=60.0)
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def run_queue(arrival_vph: np.ndarray, service_vph: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """One continuous point queue over the whole day. Nothing resets at a period."""
    n = len(arrival_vph)
    queue = np.zeros(n)
    outflow = np.zeros(n)
    for i in range(n):
        available = arrival_vph[i] + queue[i] / DT_H
        outflow[i] = min(service_vph[i], available)
        if i + 1 < n:
            queue[i + 1] = max(0.0, queue[i] + (arrival_vph[i] - outflow[i]) * DT_H)
    return queue, outflow


def spline_basis(clock: np.ndarray, knot_spacing_min: float, degree: int = 3) -> np.ndarray:
    """Cubic B-spline design matrix over the analysis clock."""
    lo, hi = float(clock[0]), float(clock[-1])
    interior = np.arange(lo + knot_spacing_min, hi, knot_spacing_min)
    knots = np.r_[[lo] * (degree + 1), interior, [hi] * (degree + 1)]
    n_basis = len(knots) - degree - 1
    columns = []
    for i in range(n_basis):
        coefficients = np.zeros(n_basis)
        coefficients[i] = 1.0
        columns.append(BSpline(knots, coefficients, degree, extrapolate=False)(clock))
    return np.nan_to_num(np.column_stack(columns))


def fit_arrival(basis: np.ndarray, service_vph: np.ndarray,
                target_veh: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray, bool]:
    """The smooth arrival profile whose recurrence best explains the speed."""

    def residual(coefficients: np.ndarray) -> np.ndarray:
        arrival = np.maximum(basis @ np.abs(coefficients), 0.0)
        queue, _ = run_queue(arrival, service_vph)
        return queue - target_veh

    start = np.full(basis.shape[1], float(service_vph.mean()))
    solution = least_squares(residual, start, method="lm", max_nfev=8000)
    arrival = np.maximum(basis @ np.abs(solution.x), 0.0)
    queue, outflow = run_queue(arrival, service_vph)

    # With lambda entirely below mu the queue is identically zero, the residual
    # stops depending on the coefficients and the search stalls on a flat plain.
    # Restart just above the service rate so a queue exists and the gradient
    # carries information again.
    restarted = False
    if queue.max() < 1.0 and target_veh.max() > 1.0:
        restarted = True
        solution = least_squares(residual, np.full(basis.shape[1], float(service_vph.mean()) * 1.05),
                                 method="lm", max_nfev=8000)
        arrival = np.maximum(basis @ np.abs(solution.x), 0.0)
        queue, outflow = run_queue(arrival, service_vph)
    return arrival, queue, outflow, restarted


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(args.queue_file).sort_values(["link_id", "t_min"])
    fitted_rows, link_rows = [], []
    n_basis = None

    for link_id, g in frame.groupby("link_id"):
        g = g.reset_index(drop=True)
        clock = g["t_min"].to_numpy(float)
        service = g["mu_vph"].to_numpy(float)
        target = g["queue_meas_veh"].to_numpy(float)
        identifiable = g["queued"].to_numpy(bool)

        basis = spline_basis(clock, args.knot_spacing_min)
        n_basis = basis.shape[1]

        if target.max() <= 1.0:
            # No queue anywhere: lambda is structurally unidentifiable on this
            # link. Reporting a fitted curve here would be inventing one.
            arrival = np.full(len(g), np.nan)
            queue = np.zeros(len(g))
            outflow = np.full(len(g), np.nan)
            restarted = False
        else:
            arrival, queue, outflow, restarted = fit_arrival(basis, service, target)

        residual = queue - target
        fitted_rows.append(pd.DataFrame({
            "link_id": link_id, "corridor": g["corridor"], "tmc_code": g["tmc_code"],
            "t_min": g["t_min"], "period": g["period"],
            "mu_vph": service, "lambda_vph": arrival,
            "queue_fitted_veh": queue, "queue_meas_veh": target,
            "outflow_vph": outflow, "residual_veh": residual,
            "lambda_identifiable": identifiable,
        }))

        has_queue = target.max() > 1.0
        link_rows.append({
            "link_id": link_id, "corridor": g["corridor"].iloc[0],
            "tmc_code": g["tmc_code"].iloc[0], "lanes": int(g["lanes"].iloc[0]),
            "has_queue": has_queue, "restarted": restarted,
            "identifiable_bins": int(identifiable.sum()),
            "unidentifiable_bins": int((~identifiable).sum()),
            "queue_peak_meas_veh": float(target.max()),
            "queue_peak_fitted_veh": float(queue.max()),
            "residual_rmse_veh": float(np.sqrt(np.mean(residual ** 2))),
            "residual_mae_veh": float(np.mean(np.abs(residual))),
            "residual_max_veh": float(np.max(np.abs(residual))),
            "lambda_mean_vph": float(np.nanmean(arrival)) if has_queue else np.nan,
            "lambda_peak_vph": float(np.nanmax(arrival)) if has_queue else np.nan,
            "lambda_over_mu_peak": float(np.nanmax(arrival / service)) if has_queue else np.nan,
            "end_of_day_queue_veh": float(queue[-1]),
        })

    fitted = pd.concat(fitted_rows, ignore_index=True)
    links = pd.DataFrame(link_rows)
    fitted.to_csv(args.output_dir / "step4_lambda_15min.csv", index=False)
    links.to_csv(args.output_dir / "step4_by_link.csv", index=False)

    q = links[links["has_queue"]]
    relative = q["residual_rmse_veh"] / q["queue_peak_meas_veh"]
    report = {
        "step": "4. Arrival rate lambda(t)",
        "parameterisation": {
            "form": "cubic B-spline in time of day",
            "knot_spacing_min": args.knot_spacing_min,
            "basis_functions": int(n_basis),
            "bins": int(frame.groupby("link_id").size().iloc[0]),
            "note": "The queue is produced only by the recurrence, so Q(t) always carries "
                    "Q(t-1). The speed-implied queue is the fitting target, which makes the "
                    "residual a measure of model adequacy rather than a tautology.",
        },
        "links": int(len(links)),
        "links_fitted": int(q.shape[0]),
        "links_without_a_queue": int((~links["has_queue"]).sum()),
        "distinct_tmcs_fitted": int(q["tmc_code"].nunique()),
        "restarts_needed": int(links["restarted"].sum()),
        "identifiability": {
            "identifiable_bins": int(fitted["lambda_identifiable"].sum()),
            "unidentifiable_bins": int((~fitted["lambda_identifiable"]).sum()),
            "share_identifiable": round(float(fitted["lambda_identifiable"].mean()), 4),
            "note": "With no queue, Q is identically zero for any lambda below mu. Those bins "
                    "are handed to step 5 rather than reported as estimates.",
        },
        "fit_quality": {
            "residual_rmse_veh_median": round(float(q["residual_rmse_veh"].median()), 2),
            "residual_rmse_over_peak_median": round(float(relative.median()), 4),
            "residual_rmse_over_peak_iqr": [round(float(relative.quantile(.25)), 4),
                                            round(float(relative.quantile(.75)), 4)],
            "peak_fitted_over_measured_median": round(
                float((q["queue_peak_fitted_veh"] / q["queue_peak_meas_veh"]).median()), 4),
        },
        "lambda": {
            "peak_vph_median": round(float(q["lambda_peak_vph"].median()), 1),
            "peak_over_mu_median": round(float(q["lambda_over_mu_peak"].median()), 3),
            "note": "lambda above mu is what builds the queue; a peak ratio below 1 would mean "
                    "the fit produced a queue without demand ever exceeding service.",
        },
        "end_of_day_queue": {
            "median_veh": round(float(q["end_of_day_queue_veh"].median()), 2),
            "links_not_clearing": int((q["end_of_day_queue_veh"] > 1.0).sum()),
        },
    }
    (args.output_dir / "step4_summary.json").write_text(json.dumps(report, indent=2), encoding="utf-8")

    p = report["parameterisation"]
    print(f"Step 4 -- arrival rate lambda(t)\n")
    print(f"  {p['basis_functions']} spline coefficients on {p['knot_spacing_min']:.0f}-min knots, "
          f"against {p['bins']} bins")
    print(f"  {report['links_fitted']} links fitted ({report['distinct_tmcs_fitted']} distinct TMCs), "
          f"{report['links_without_a_queue']} have no queue to fit against")
    i = report["identifiability"]
    print(f"  lambda identifiable on {i['share_identifiable'] * 100:.1f}% of bins "
          f"({i['identifiable_bins']:,} of {i['identifiable_bins'] + i['unidentifiable_bins']:,})")
    f = report["fit_quality"]
    print(f"\n  queue residual: RMSE {f['residual_rmse_veh_median']:.1f} veh at the median, "
          f"{f['residual_rmse_over_peak_median'] * 100:.1f}% of the peak "
          f"(IQR {f['residual_rmse_over_peak_iqr'][0] * 100:.1f}-{f['residual_rmse_over_peak_iqr'][1] * 100:.1f}%)")
    print(f"  fitted peak / measured peak: {f['peak_fitted_over_measured_median']:.3f}")
    l = report["lambda"]
    print(f"\n  lambda peak {l['peak_vph_median']:,.0f} vph at the median, "
          f"{l['peak_over_mu_median']:.2f}x mu")
    e = report["end_of_day_queue"]
    print(f"  end-of-day queue: {e['median_veh']:.2f} veh median, "
          f"{e['links_not_clearing']} links do not clear")
    if report["restarts_needed"]:
        print(f"  restarts needed on {report['restarts_needed']} links")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
