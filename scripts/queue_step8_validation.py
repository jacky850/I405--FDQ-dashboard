"""Step 8 of the single-link queue plan: validation.

The comparison the advisor asked for: model speed(t) against observed speed(t),
and P, v(T2) and T2 against their observed counterparts, on the link basis.

**Scored against two baselines, because the headline MAE on its own cannot say
what earned it.** The plan asserts that timing is not a real test -- the shape
came from speed -- while depth is, because it comes from the queue and the queue
from the assignment's level. In this implementation that split is not so clean:
lambda inside an episode is the step 4 fit, which was fitted to the queue implied
by the observed speed, so depth partly inherits the observation too.

Three arrival profiles are therefore run through the same recurrence and the
same queue-to-speed map:

  free_flow     lambda so low no queue ever forms, i.e. v_hat = v_f throughout.
                The null. Most bins are uncongested, so predicting free flow
                everywhere already scores well and any MAE has to beat it.

  assignment    lambda = V_assign / period_hours, flat within each period. No
                speed information of any kind -- this is what the static
                assignment on its own implies.

  anchored      the delivered model: pinned by the queue where step 4 could
                identify lambda, levelled by V_assign where it could not.

The gap between `assignment` and `anchored` is what the speed data contributed.
The gap between `free_flow` and `assignment` is what the assignment contributed.
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
sys.path.insert(0, str(ROOT / "src"))

from queue_step4_arrival_rate import run_queue  # noqa: E402
from queue_step7_queue_to_speed import detect, period_of  # noqa: E402

DT_H = 15.0 / 60.0
PERIOD_HOURS = {"AM": 3.0, "MD": 6.0, "PM": 4.0}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--speed-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step7_speed_model_15min.csv")
    parser.add_argument("--observed-episodes", type=Path,
                        default=ROOT / "outputs/nvta_queue/step2_episodes.csv")
    parser.add_argument("--model-episodes", type=Path,
                        default=ROOT / "outputs/nvta_queue/step7_model_episodes.csv")
    parser.add_argument("--anchor-file", type=Path,
                        default=ROOT / "outputs/nvta_queue/step5_volume_anchor_by_link.csv")
    parser.add_argument("--period", default="PM")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue")
    return parser.parse_args()


def speed_from_queue(queue: np.ndarray, mu: np.ndarray, length: float,
                     free_speed: float) -> np.ndarray:
    return length / (length / free_speed + queue / np.maximum(mu, 1e-6))


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    frame = pd.read_csv(args.speed_file).sort_values(["link_id", "t_min"])
    all_anchors = pd.read_csv(args.anchor_file)
    anchor = all_anchors[all_anchors["period"] == args.period].set_index("link_id")

    # V_assign per link and period, for the assignment-only variant. It is not
    # carried on the step 7 series, and silently reading a missing column would
    # run that variant at lambda = 0 and make it indistinguishable from the null.
    v_assign = (all_anchors.set_index(["link_id", "period"])["V_assign_veh"]
                .unstack("period"))
    missing = [p for p in PERIOD_HOURS if p not in v_assign.columns]
    if missing:
        raise SystemExit(f"anchor file has no V_assign for {missing}; rerun step 5 over all periods")

    rows, series_rows = [], []
    for link_id, g in frame.groupby("link_id"):
        g = g.sort_values("t_min").reset_index(drop=True)
        length = float(g["length_mi"].iloc[0])
        free_speed = float(g["free_speed_mph"].iloc[0])
        mu = g["mu_vph"].to_numpy(float)
        t = g["t_min"].to_numpy(float)

        # Variant: the assignment on its own, flat within each period.
        if link_id not in v_assign.index:
            continue
        flat = np.zeros(len(g))
        for period, hours in PERIOD_HOURS.items():
            mask = g["anchor_period"].to_numpy() == period
            total = v_assign.loc[link_id, period]
            if not mask.any() or not np.isfinite(total):
                continue
            flat[mask] = float(total) / hours
        queue_flat, _ = run_queue(flat, mu)
        speed_flat = speed_from_queue(queue_flat, mu, length, free_speed)

        g["speed_assignment_only_mph"] = speed_flat
        g["speed_free_flow_mph"] = free_speed
        series_rows.append(g)

        window = g["anchor_period"].to_numpy() == args.period
        queued = g["lambda_identifiable"].to_numpy(bool) & window
        if not window.any():
            continue
        observed = g["speed_mph"].to_numpy(float)
        for name, model in [("free_flow", np.full(len(g), free_speed)),
                            ("assignment", speed_flat),
                            ("anchored", g["speed_model_mph"].to_numpy(float))]:
            err = model - observed
            rows.append({
                "link_id": link_id, "corridor": g["corridor"].iloc[0],
                "tmc_code": g["tmc_code"].iloc[0], "variant": name,
                "mae_period_mph": float(np.abs(err[window]).mean()),
                "rmse_period_mph": float(np.sqrt((err[window] ** 2).mean())),
                "mae_episode_mph": float(np.abs(err[queued]).mean()) if queued.any() else np.nan,
                "bias_episode_mph": float(np.median(err[queued])) if queued.any() else np.nan,
                "episode_bins": int(queued.sum()),
            })

    series = pd.concat(series_rows, ignore_index=True)
    scores = pd.DataFrame(rows)
    series.to_csv(args.output_dir / "step8_speed_variants_15min.csv", index=False)
    scores.to_csv(args.output_dir / "step8_speed_scores_by_link.csv", index=False)

    # P, v(T2) and T2: model against observed, matched on the period's episode.
    obs = pd.read_csv(args.observed_episodes)
    mod = pd.read_csv(args.model_episodes)
    obs = (obs[obs["period_by_T2"] == args.period]
           .sort_values("P_h", ascending=False).groupby("link_id").first())
    censored = mod.groupby("link_id")["right_censored"].any()
    mod = (mod[mod["period_by_T2"] == args.period]
           .sort_values("P_h", ascending=False).groupby("link_id").first())
    paired = obs[["corridor", "P_h", "T2_min", "vT2_mph", "t0_min", "t3_min"]].join(
        mod[["P_h", "T2_min", "vT2_mph", "t0_min", "t3_min"]],
        lsuffix="_obs", rsuffix="_model", how="inner")
    for column in ["P_h", "T2_min", "vT2_mph", "t0_min", "t3_min"]:
        paired[f"{column}_err"] = paired[f"{column}_model"] - paired[f"{column}_obs"]
    paired = paired.join(anchor[["inside_window", "below_lower", "above_upper"]], how="left")
    # P is only comparable where the model episode actually closed inside the run
    # window; a censored one reports the distance to midnight, not a duration.
    paired["right_censored"] = paired.index.map(censored).fillna(False)
    paired.loc[paired["right_censored"], ["P_h_err", "t3_min_err"]] = np.nan
    paired.to_csv(args.output_dir / "step8_episode_comparison.csv")

    def score(variant: str) -> dict:
        g = scores[scores["variant"] == variant]
        e = g.dropna(subset=["mae_episode_mph"])
        return {
            "links": int(len(g)),
            "mae_period_mph": round(float(g["mae_period_mph"].median()), 3),
            "links_with_episode": int(len(e)),
            "mae_episode_mph": round(float(e["mae_episode_mph"].median()), 3),
            "bias_episode_mph": round(float(e["bias_episode_mph"].median()), 3),
        }

    detected = {
        "observed_episodes": int(len(obs)), "model_episodes": int(len(mod)),
        "matched": int(len(paired)),
        "model_missed": int(len(obs) - len(paired)),
        "model_invented": int(len(mod) - len(paired)),
    }
    report = {
        "step": "8. Validation",
        "period": args.period,
        "speed": {v: score(v) for v in ["free_flow", "assignment", "anchored"]},
        "what_each_ingredient_earns": {
            "assignment_over_null_mph": round(
                score("free_flow")["mae_episode_mph"] - score("assignment")["mae_episode_mph"], 3),
            "speed_over_assignment_mph": round(
                score("assignment")["mae_episode_mph"] - score("anchored")["mae_episode_mph"], 3),
            "note": "The null is free flow everywhere. Beating it is the minimum bar; most bins "
                    "are uncongested, so it scores well on its own.",
        },
        "episode_detection": detected,
        "episode_parameters": {
            column: {
                "n": int(paired[f"{column}_err"].notna().sum()),
                "median_error": round(float(paired[f"{column}_err"].median()), 3),
                "mae": round(float(paired[f"{column}_err"].abs().median()), 3),
                "within_one_bin" if column in ("T2_min", "t0_min", "t3_min") else "within_20pct":
                    round(float((paired[f"{column}_err"].abs() <= 15).mean()), 3)
                    if column in ("T2_min", "t0_min", "t3_min")
                    else round(float((paired[f"{column}_err"].abs()
                                      / paired[f"{column}_obs"] <= 0.2).mean()), 3),
            }
            for column in ["P_h", "T2_min", "vT2_mph", "t0_min", "t3_min"]
        },
        "by_anchor_status": {
            str(status): {
                "links": int(len(g)),
                "vT2_mae_mph": round(float(g["vT2_mph_err"].abs().median()), 2),
                "P_mae_h": round(float(g["P_h_err"].abs().median()), 2),
            }
            for status, g in paired.groupby(paired["inside_window"].fillna(False))
        },
    }
    (args.output_dir / "step8_summary.json").write_text(json.dumps(report, indent=2),
                                                        encoding="utf-8")

    print(f"Step 8 -- validation, {args.period}\n")
    print(f"  {'variant':<12} {'MAE period':>11} {'MAE episode':>12} {'bias':>8}")
    for v in ["free_flow", "assignment", "anchored"]:
        s = report["speed"][v]
        print(f"  {v:<12} {s['mae_period_mph']:>10.2f}  {s['mae_episode_mph']:>11.2f} "
              f"{s['bias_episode_mph']:>+8.2f}")
    w = report["what_each_ingredient_earns"]
    print(f"\n  assignment over the null : {w['assignment_over_null_mph']:+.2f} mph")
    print(f"  speed over the assignment: {w['speed_over_assignment_mph']:+.2f} mph")
    d = report["episode_detection"]
    print(f"\n  episodes: {d['observed_episodes']} observed, {d['model_episodes']} modelled, "
          f"{d['matched']} matched ({d['model_missed']} missed, {d['model_invented']} invented)")
    print(f"\n  {'quantity':<10} {'n':>4} {'median err':>11} {'MAE':>8}")
    for column in ["P_h", "T2_min", "vT2_mph"]:
        p = report["episode_parameters"][column]
        print(f"  {column:<10} {p['n']:>4} {p['median_error']:>+11.2f} {p['mae']:>8.2f}")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
