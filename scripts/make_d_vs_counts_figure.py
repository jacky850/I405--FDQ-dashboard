"""D inferred from speed against D from counts, on I-405 where both exist.

The NVTA corridors have speed but no counts, so nothing there can test whether
D is trustworthy. I-405 has both on the same links at the same time, which makes
it the only place the claim can be checked.

The test isolates the flow estimate. Both columns sum over *the same* bins --
the ones whose measured speed is below the cut-off -- so what is being compared
is q(t) from the fundamental diagram against q(t) from the detector, not two
different episode detections:

    D_speed  = sum of S3(v(t)) * dt   over bins with v(t) < v_cutoff
    D_counts = sum of q_measured(t) * dt   over the same bins

V is computed the same way over every bin in the period, and drawn beside it.
The contrast is the point: D sits on the diagonal, V does not.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs/figures"
PERIODS = {"AM": (360, 540), "MD": (540, 900), "PM": (900, 1140), "NT": (1140, 1800)}
CUTOFF_RATIO = 0.70
S3_M = 4.0
# qvdf_selfdemo/config.py discards congestion episodes shorter than this as noise.
# It matters more than it looks: a brief speed dip is not necessarily congestion,
# and the fundamental diagram reads any low speed as high density regardless of
# how few vehicles were actually there.
MIN_EPISODE_H = 0.5
TEAL, ORANGE, INK, SLATE = "#118b81", "#ec7541", "#10243a", "#8fa1ad"
PERIOD_COLOUR = {"AM": TEAL, "MD": SLATE, "PM": ORANGE, "NT": INK}

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.edgecolor": "#b9c5cc", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": "#5d6d78", "ytick.color": "#5d6d78", "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.grid": True, "grid.color": "#e6ecef",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--raw-file", type=Path,
                        default=ROOT / "data/jinxi_i405_week_2025-06-16_to_22/raw_observed_fdqbench.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/d_vs_counts_i405")
    return parser.parse_args()


def sustained_below(below: np.ndarray, min_bins: int) -> np.ndarray:
    """Keep only contiguous runs below the cut-off that last long enough.

    Without this a single dipping bin counts as an episode, and those are where
    the inference fails worst -- low speed with almost no traffic behind it.
    """
    keep = np.zeros_like(below, dtype=bool)
    start = None
    for i, flag in enumerate(np.append(below, False)):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            if i - start >= min_bins:
                keep[start:i] = True
            start = None
    return keep


def s3_flow(speed: np.ndarray, free_speed: float, speed_at_capacity: float,
            capacity: float) -> np.ndarray:
    """k(v) = k_c[(v_f/v)^(m/2) - 1]^(1/m), then q = k*v. Single-valued in v."""
    k_c = capacity / speed_at_capacity
    v = np.clip(speed, 1e-6, free_speed - 1e-6)
    return np.minimum(k_c * np.maximum((free_speed / v) ** (S3_M / 2.0) - 1.0, 0.0) ** (1.0 / S3_M) * v,
                      capacity)


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    raw = pd.read_csv(args.raw_file)
    raw = raw[~raw["is_imputed"].astype(bool)].dropna(subset=["speed_mph", "flow_vehph"])
    stamp = pd.to_datetime(raw["timestamp_la"])
    raw["minute"] = stamp.dt.hour * 60 + stamp.dt.minute
    raw["date"] = stamp.dt.date.astype(str)
    raw = raw[stamp.dt.weekday < 5]
    step_h = float(np.median(np.diff(np.sort(raw["minute"].unique())))) / 60.0

    rows = []
    for link_id, link in raw.groupby("link_id"):
        # One fundamental diagram per link, fitted on that link's whole week.
        capacity = float(link["flow_vehph"].quantile(0.995))
        speed_at_capacity = float(link.loc[link["flow_vehph"].idxmax(), "speed_mph"])
        free_speed = float(link["speed_mph"].quantile(0.95))
        if not free_speed > speed_at_capacity > 0:
            continue
        cutoff = CUTOFF_RATIO * free_speed
        link = link.assign(q_speed=s3_flow(link["speed_mph"].to_numpy(float), free_speed,
                                           speed_at_capacity, capacity))
        for (date, period), g in link.groupby(
                ["date", pd.cut(link["minute"], [v for p in PERIODS.values() for v in p[:1]] + [1440],
                                labels=list(PERIODS), right=False)], observed=True):
            if len(g) < 8:
                continue
            g = g.sort_values("minute")
            raw_below = (g["speed_mph"] < cutoff).to_numpy()
            below = sustained_below(raw_below, max(1, int(round(MIN_EPISODE_H / step_h))))
            rows.append({
                "link_id": link_id, "date": date, "period": str(period),
                "bins": int(len(g)), "bins_below_cutoff": int(below.sum()),
                "bins_below_unfiltered": int(raw_below.sum()),
                "cutoff_mph": cutoff, "capacity_vph": capacity,
                "D_counts": float((g["flow_vehph"].to_numpy()[below] * step_h).sum()),
                "D_speed": float((g["q_speed"].to_numpy()[below] * step_h).sum()),
                "D_counts_unfiltered": float((g["flow_vehph"].to_numpy()[raw_below] * step_h).sum()),
                "D_speed_unfiltered": float((g["q_speed"].to_numpy()[raw_below] * step_h).sum()),
                "V_counts": float((g["flow_vehph"] * step_h).sum()),
                "V_speed": float((g["q_speed"] * step_h).sum()),
            })
    frame = pd.DataFrame(rows)
    frame = frame[frame["V_counts"] > 0]
    frame.to_csv(args.output_dir / "d_vs_counts_i405.csv", index=False)

    congested = frame[frame["bins_below_cutoff"] > 0].copy()
    congested["D_err"] = (congested["D_speed"] - congested["D_counts"]) / congested["D_counts"] * 100
    frame["V_err"] = (frame["V_speed"] - frame["V_counts"]) / frame["V_counts"] * 100

    # What the episode filter is worth, stated rather than assumed.
    unfiltered = frame[frame["bins_below_unfiltered"] > 0]
    unfiltered_err = ((unfiltered["D_speed_unfiltered"] - unfiltered["D_counts_unfiltered"])
                      / unfiltered["D_counts_unfiltered"] * 100)
    print(f"episode filter (MIN_EPISODE_H = {MIN_EPISODE_H} h):")
    print(f"  without: n={len(unfiltered):>3}  MAPE {unfiltered_err.abs().mean():>6.1f}%  "
          f"median bias {unfiltered_err.median():>+6.1f}%")
    print(f"  with:    n={len(congested):>3}  MAPE {congested['D_err'].abs().mean():>6.1f}%  "
          f"median bias {congested['D_err'].median():>+6.1f}%\n")

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.8))

    # Left: D. Short dips are drawn too, hollow, so the filter's job is visible
    # rather than hidden -- they are the points that miss the diagonal.
    blips = unfiltered[unfiltered["bins_below_cutoff"] == 0]
    top = max(congested["D_counts"].max(), congested["D_speed"].max(),
              blips["D_counts_unfiltered"].max()) * 1.06
    left.plot([0, top], [0, top], color=INK, lw=1.2, ls="--", zorder=1)
    left.scatter(blips["D_counts_unfiltered"], blips["D_speed_unfiltered"], s=30,
                 facecolors="none", edgecolors=SLATE, linewidths=.9, alpha=.7, zorder=2,
                 label=f"dips under {MIN_EPISODE_H} h, discarded (n={len(blips)})")
    for period, g in congested.groupby("period"):
        left.scatter(g["D_counts"], g["D_speed"], s=54, color=PERIOD_COLOUR.get(period, SLATE),
                     alpha=.85, edgecolors="white", linewidths=.6, zorder=3,
                     label=f"{period} (n={len(g)})")
    left.set_xlim(0, top); left.set_ylim(0, top)
    left.set_xlabel("D from measured counts (veh)")
    left.set_ylabel("D inferred from speed (veh)")
    left.set_title("D — sustained congestion episodes")
    left.legend(frameon=False, fontsize=7.5, loc="upper left")
    left.text(.97, .06,
              f"kept:      n = {len(congested)}, MAPE {congested['D_err'].abs().mean():.1f}%\n"
              f"discarded: n = {len(blips)}, MAPE {unfiltered_err[blips.index].abs().mean():.0f}%",
              transform=left.transAxes, ha="right", va="bottom", fontsize=8.5,
              bbox=dict(boxstyle="round,pad=0.5", fc="#f4f7f9", ec="#cfdae1"))

    top = max(frame["V_counts"].max(), frame["V_speed"].max()) * 1.06
    right.plot([0, top], [0, top], color=INK, lw=1.2, ls="--", zorder=1)
    for period, g in frame.groupby("period"):
        right.scatter(g["V_counts"], g["V_speed"], s=20, color=PERIOD_COLOUR.get(period, SLATE),
                      alpha=.6, edgecolors="none", zorder=2, label=f"{period} (n={len(g)})")
    right.set_xlim(0, top); right.set_ylim(0, top)
    right.set_xlabel("V from measured counts (veh)")
    right.set_ylabel("V inferred from speed (veh)")
    right.set_title("V — whole period, same links")
    right.legend(frameon=False, fontsize=8, loc="upper left")
    right.text(.97, .06,
               f"n = {len(frame)}\nMAPE {frame['V_err'].abs().mean():.1f}%\n"
               f"median bias {frame['V_err'].median():+.1f}%",
               transform=right.transAxes, ha="right", va="bottom", fontsize=8.5,
               bbox=dict(boxstyle="round,pad=0.5", fc="#f4f7f9", ec="#cfdae1"))

    fig.suptitle("I-405, where counts exist: inferred against measured",
                 fontweight="bold", y=0.99)
    fig.tight_layout()
    fig.savefig(FIG / "d_vs_counts.png", bbox_inches="tight")
    plt.close(fig)

    print(f"{frame['link_id'].nunique()} links, {frame['date'].nunique()} weekdays, "
          f"{len(frame)} link-day-periods ({len(congested)} with a congested episode)\n")
    for label, data, err in [("D (congested bins)", congested, "D_err"), ("V (whole period)", frame, "V_err")]:
        print(f"{label:<22} MAPE {data[err].abs().mean():>6.1f}%   median bias "
              f"{data[err].median():>+6.1f}%   within +-20%: {(data[err].abs() <= 20).mean()*100:>5.1f}%")
    print(f"\nWrote {args.output_dir} and docs/figures/d_vs_counts.png")


if __name__ == "__main__":
    main()
