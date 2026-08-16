"""Observed against back-calculated speed on the NVTA PM links.

Two figures. The small multiples show what the curve actually does on individual
links -- the whole day, with the PM window shaded and the three anchors marked,
because the PM episode usually starts before 15:00 and clears after 19:00. The
scatter puts every PM bin on one pair of axes.

The anchors are worth looking at directly: t0, T2 and t3 are read off the
observation, so the curve is pinned at the trough and at both edges. What is
being tested is only the shape in between, which is why the residual is small
and why that smallness is not evidence of predictive skill.
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
TEAL, ORANGE, INK, SLATE = "#118b81", "#ec7541", "#10243a", "#8fa1ad"
PM_START, PM_END = 900, 1140

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.edgecolor": "#b9c5cc", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": "#5d6d78", "ytick.color": "#5d6d78", "axes.titlesize": 9.5,
    "axes.titleweight": "bold", "axes.grid": True, "grid.color": "#e6ecef",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_pm_link_speed")
    parser.add_argument("--panels", type=int, default=6)
    return parser.parse_args()


def pick(summary: pd.DataFrame, panels: int) -> list[int]:
    """The deepest episode on each corridor first, then the next deepest overall."""
    congested = summary[summary["congested"]].sort_values("vT2_mph")
    chosen = list(congested.groupby("corridor").head(1)["net_link_id"])
    for link_id in congested["net_link_id"]:
        if len(chosen) >= panels:
            break
        if link_id not in chosen:
            chosen.append(link_id)
    return chosen[:panels]


def main() -> None:
    args = parse_args()
    series = pd.read_csv(args.output_dir / "nvta_pm_link_speed_15min.csv")
    summary = pd.read_csv(args.output_dir / "nvta_pm_link_summary.csv").set_index("net_link_id")

    chosen = pick(summary.reset_index(), args.panels)
    rows = int(np.ceil(len(chosen) / 3))
    fig, axes = plt.subplots(rows, 3, figsize=(13.2, 3.5 * rows), squeeze=False)
    for ax, link_id in zip(axes.ravel(), chosen):
        g = series[series["net_link_id"] == link_id].sort_values("t_min")
        s = summary.loc[link_id]
        ax.axvspan(PM_START, PM_END, color="#f4f7f9", zorder=0)
        ax.plot(g["t_min"], g["obs_speed_mph"], color=SLATE, lw=0.9, alpha=.75,
                label="observed", zorder=2)
        ax.plot(g["t_min"], g["obs_speed_smoothed_mph"], color=INK, lw=1.6,
                label="observed, smoothed", zorder=3)
        ax.plot(g["t_min"], g["backcalc_speed_mph"], color=ORANGE, lw=2.0,
                label="back-calculated", zorder=4)
        ax.axhline(s["cutoff_mph"], color=TEAL, lw=1.0, ls="--", zorder=1)
        for t, name in [(s["t0_min"], "t0"), (s["T2_min"], "T2"), (s["t3_min"], "t3")]:
            if np.isfinite(t):
                ax.axvline(t, color=TEAL, lw=0.8, ls=":", zorder=1)
                ax.text(t, ax.get_ylim()[1], name, color=TEAL, fontsize=7.5,
                        ha="center", va="bottom")
        ax.set_xlim(360, 1425)
        ax.set_xticks(range(360, 1426, 180))
        ax.set_xticklabels([f"{h // 60:02d}:00" for h in range(360, 1426, 180)])
        ax.set_ylabel("speed (mph)")
        ax.set_title(f"{s['corridor']}  link {link_id}")
        ax.text(.015, .05,
                f"D = {s['D_veh_total']:,.0f} veh   C = {s['C_vphpl']:,.0f} veh/h/ln\n"
                f"P = {s['P_h']:.2f} h   v(T2) = {s['vT2_mph']:.1f} mph\n"
                f"MAE in episode = {s['speed_mae_episode_mph']:.2f} mph",
                transform=ax.transAxes, ha="left", va="bottom", fontsize=7.8,
                bbox=dict(boxstyle="round,pad=0.4", fc="white", ec="#cfdae1", alpha=.92))
    axes.ravel()[0].legend(frameon=False, fontsize=8, loc="upper left")
    for ax in axes.ravel()[len(chosen):]:
        ax.axis("off")
    fig.suptitle("NVTA PM: observed speed against the speed back-calculated from P, t2 and v(T2)",
                 fontweight="bold", y=1.0)
    fig.tight_layout()
    fig.savefig(FIG / "nvta_pm_link_speed_profiles.png", bbox_inches="tight")
    plt.close(fig)

    pm = series[series["in_pm_period"] & series["in_episode"]]
    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.6))
    top = max(pm["obs_speed_smoothed_mph"].max(), pm["backcalc_speed_mph"].max()) * 1.08
    left.plot([0, top], [0, top], color=INK, lw=1.2, ls="--", zorder=1)
    for corridor, g in pm.groupby("corridor"):
        left.scatter(g["obs_speed_smoothed_mph"], g["backcalc_speed_mph"], s=11, alpha=.5,
                     edgecolors="none", label=f"{corridor} (n={len(g)})", zorder=2)
    err = pm["backcalc_speed_mph"] - pm["obs_speed_smoothed_mph"]
    left.set_xlim(0, top); left.set_ylim(0, top)
    left.set_xlabel("observed speed (mph)"); left.set_ylabel("back-calculated speed (mph)")
    left.set_title("Every PM bin inside an episode")
    left.legend(frameon=False, fontsize=7.5, loc="upper left")
    left.text(.97, .05, f"n = {len(pm):,}\nMAE {err.abs().mean():.2f} mph\n"
                        f"bias {err.median():+.2f} mph",
              transform=left.transAxes, ha="right", va="bottom", fontsize=8.5,
              bbox=dict(boxstyle="round,pad=0.5", fc="#f4f7f9", ec="#cfdae1"))

    congested = summary[summary["congested"]]
    right.hist(congested["recovery_over_onset"].clip(upper=5), bins=24, color=TEAL,
               edgecolor="white", alpha=.85)
    right.axvline(1.0, color=ORANGE, lw=1.8, ls="--")
    right.text(1.06, right.get_ylim()[1] * .93, "a symmetric curve\nwould sit here",
               color=ORANGE, fontsize=8, va="top")
    right.set_xlabel("recovery width / onset width")
    right.set_ylabel("links")
    right.set_title("Why each shoulder needs its own width")
    fig.suptitle(f"{len(congested)} links with a PM episode, {series['net_link_id'].nunique()} links in total",
                 fontweight="bold", y=0.99)
    fig.tight_layout()
    fig.savefig(FIG / "nvta_pm_link_speed_scatter.png", bbox_inches="tight")
    plt.close(fig)

    print(f"panels: {chosen}")
    print(f"scatter: {len(pm):,} PM bins inside an episode, "
          f"MAE {err.abs().mean():.2f} mph, bias {err.median():+.2f} mph")
    print(f"Wrote {FIG / 'nvta_pm_link_speed_profiles.png'}")
    print(f"Wrote {FIG / 'nvta_pm_link_speed_scatter.png'}")


if __name__ == "__main__":
    main()
