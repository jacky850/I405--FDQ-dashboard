"""How far can smoothing the speed take the free-flow flow error down?

The advisor's suggestion: do not invert the fundamental diagram on the raw
observed speed, invert it on the fitted QVDF speed profile -- the smooth curve
anchored at t0, T2 and t3. He expects this to reduce the free-flow error rather
than remove it, so the question is how much.

There is a reason to expect a partial win. The free-flow branch is nearly flat
in v, so dq/dv is large and any wobble in speed is amplified into a large wobble
in flow. Smoothing removes that. It cannot remove the bias, because the
diagram maps one speed to one flow no matter how cleanly that speed is measured,
and at 65 mph out of a 70 mph free-flow speed it insists on ~83% of capacity.

Variants scored against measured I-405 counts, per bin and per period:

  ``raw``          observed speed, the current baseline
  ``smooth-N``     centred rolling mean over N bins
  ``qvdf``         the model profile: free flow outside the episode, the QVDF
                   curve v_c / (1 + z(1 - tau^2)^2) inside it
  ``qvdf-blend``   as above but easing between free flow and the cut-off over
                   the half hour either side, instead of stepping
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
CUTOFF_RATIO, S3_M, MIN_EPISODE_H = 0.70, 4.0, 0.5
PERIODS = {"AM": (360, 540), "MD": (540, 900), "PM": (900, 1140), "NT": (1140, 1800)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--multiweek-file", type=Path,
                        default=ROOT / "outputs/i405_multiweek_average_holdout/weekly_average_weekday_profiles_5min.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/free_flow_error")
    return parser.parse_args()


def s3_flow(speed: np.ndarray, free_speed: float, speed_at_capacity: float,
            capacity: float) -> np.ndarray:
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    return np.minimum(k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M) * v,
                      capacity)


def episodes(below: np.ndarray, min_bins: int) -> list[tuple[int, int]]:
    """Contiguous runs below the cut-off that last at least ``min_bins``."""
    runs, start = [], None
    for i, flag in enumerate(np.append(below, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_bins:
                runs.append((start, i - 1))
            start = None
    return runs


def qvdf_profile(speed: np.ndarray, cutoff: float, free_speed: float,
                 min_bins: int, ease_bins: int = 0) -> np.ndarray:
    """The QVDF speed profile: free flow outside each episode, the curve inside.

    Inside an episode, ``v(t) = v_c / (1 + z(1 - tau^2)^2)`` with
    ``tau = 2(t - T2)/P`` and ``z = v_c/v(T2) - 1``, so the trough depth and
    position come from the data and the shape comes from the model.
    """
    out = np.full_like(speed, free_speed, dtype=float)
    for first, last in episodes(speed < cutoff, min_bins):
        window = speed[first:last + 1]
        t2 = first + int(np.argmin(window))
        half = max((last - first + 1) / 2.0, 0.5)
        z = max(cutoff / max(window.min(), 1e-6) - 1.0, 0.0)
        index = np.arange(first, last + 1)
        tau = np.clip((index - t2) / half, -1.0, 1.0)
        out[first:last + 1] = cutoff / (1.0 + z * (1.0 - tau ** 2) ** 2)
        # Optionally ease from free flow down to the cut-off either side, so the
        # profile does not step discontinuously at the episode boundary.
        for lo, hi in [(max(first - ease_bins, 0), first), (last + 1, min(last + 1 + ease_bins, len(speed)))]:
            if ease_bins and hi > lo:
                ramp = np.linspace(0.0, 1.0, hi - lo + 1)[1:] if lo < first else np.linspace(1.0, 0.0, hi - lo + 1)[:-1]
                out[lo:hi] = np.minimum(out[lo:hi], free_speed - (free_speed - cutoff) * ramp)
    return out


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    weekly = pd.read_csv(args.multiweek_file)
    step_h = 5.0 / 60.0
    min_bins = int(round(MIN_EPISODE_H / step_h))
    ease = int(round(0.5 / step_h))

    records = []
    for (link_id, week), g in weekly.groupby(["link_id", "week_start"]):
        g = g.sort_values("minute_of_day")
        speed = g["average_speed_mph"].to_numpy(float)
        flow = g["average_flow_veh_h"].to_numpy(float)
        capacity = float(np.quantile(flow, 0.995))
        speed_at_capacity = float(speed[np.argmax(flow)])
        free_speed = float(np.quantile(speed, 0.95))
        if not free_speed > speed_at_capacity > 0 or capacity <= 0:
            continue
        cutoff = CUTOFF_RATIO * free_speed
        series = pd.Series(speed)
        variants = {"raw": speed}
        for width in (3, 5, 9, 15):
            variants[f"smooth-{width}"] = series.rolling(width, center=True, min_periods=1).mean().to_numpy()
        variants["qvdf"] = qvdf_profile(speed, cutoff, free_speed, min_bins)
        variants["qvdf-blend"] = qvdf_profile(speed, cutoff, free_speed, min_bins, ease_bins=ease)

        congested = np.zeros(len(speed), dtype=bool)
        for first, last in episodes(speed < cutoff, min_bins):
            congested[first:last + 1] = True
        minute = g["minute_of_day"].to_numpy(int)
        period = np.array([next((p for p, (a, b) in PERIODS.items()
                                 if (a <= m < b if b <= 1440 else (m >= a or m < b - 1440))), "NT")
                           for m in minute])

        for name, v in variants.items():
            q_hat = s3_flow(v, free_speed, speed_at_capacity, capacity)
            records.append(pd.DataFrame({
                "link_id": link_id, "week": week, "variant": name, "period": period,
                "congested": congested, "q_hat": q_hat, "q_obs": flow,
                "V_hat": q_hat * step_h, "V_obs": flow * step_h,
            }))

    bins = pd.concat(records, ignore_index=True)
    bins = bins[bins["q_obs"] > 0]
    bins["err"] = (bins["q_hat"] - bins["q_obs"]) / bins["q_obs"] * 100
    bins.to_csv(args.output_dir / "free_flow_error_bins.csv.gz", index=False, compression="gzip")

    periods = (bins.groupby(["variant", "link_id", "week", "period"])[["V_hat", "V_obs"]]
               .sum().reset_index())
    periods["err"] = (periods["V_hat"] - periods["V_obs"]) / periods["V_obs"] * 100

    def score(frame: pd.DataFrame) -> dict:
        return {"n": int(len(frame)), "mape": round(float(frame["err"].abs().mean()), 1),
                "bias": round(float(frame["err"].median()), 1)}

    order = ["raw", "smooth-3", "smooth-5", "smooth-9", "smooth-15", "qvdf", "qvdf-blend"]
    summary = {
        name: {
            "free_flow_bins": score(bins[(bins["variant"] == name) & ~bins["congested"]]),
            "congested_bins": score(bins[(bins["variant"] == name) & bins["congested"]]),
            "period_volume_V": score(periods[periods["variant"] == name]),
        }
        for name in order
    }
    (args.output_dir / "free_flow_error.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")

    print(f"{bins['link_id'].nunique()} links x {bins['week'].nunique()} weeks, "
          f"{(bins['variant'] == 'raw').sum():,} bins per variant\n")
    print(f"{'variant':<12} | {'free-flow bins':>22} | {'congested bins':>22} | {'period V':>22}")
    print(f"{'':<12} | {'MAPE':>10} {'bias':>11} | {'MAPE':>10} {'bias':>11} | {'MAPE':>10} {'bias':>11}")
    print("-" * 88)
    for name in order:
        s = summary[name]
        print(f"{name:<12} | {s['free_flow_bins']['mape']:>9.1f}% {s['free_flow_bins']['bias']:>+10.1f}% "
              f"| {s['congested_bins']['mape']:>9.1f}% {s['congested_bins']['bias']:>+10.1f}% "
              f"| {s['period_volume_V']['mape']:>9.1f}% {s['period_volume_V']['bias']:>+10.1f}%")
    base = summary["raw"]["free_flow_bins"]["mape"]
    best = min(order, key=lambda n: summary[n]["free_flow_bins"]["mape"])
    print(f"\nbest free-flow variant: {best} "
          f"({base:.1f}% -> {summary[best]['free_flow_bins']['mape']:.1f}%, "
          f"bias {summary['raw']['free_flow_bins']['bias']:+.1f}% -> "
          f"{summary[best]['free_flow_bins']['bias']:+.1f}%)")
    print(f"\nWrote {args.output_dir}")


if __name__ == "__main__":
    main()
