"""Three figures for the single-link queue PM delivery.

profiles   observed speed against the queue's speed, with the assignment-only
           variant on the same axes. The third line is the point of the figure:
           it stays flat at free flow while the observation dives, which is the
           ablation drawn rather than tabulated.

episode    P, T2 and v(T2), model against observed, on 45-degree axes. These are
           outputs of the recurrence here, so the scatter is a real test.

demand     D from the assignment against the discharge the speed data already
           shows. The diagonal is where they would agree.
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
PLUM = "#8c5ba6"
PM_START, PM_END = 900, 1140
CORRIDOR_COLOR = {"I395_NB": TEAL, "I395_SB": ORANGE, "I66_EB": PLUM, "I66_WB": "#3d7fb3"}

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.edgecolor": "#b9c5cc", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": "#5d6d78", "ytick.color": "#5d6d78", "axes.titlesize": 9.5,
    "axes.titleweight": "bold", "axes.grid": True, "grid.color": "#e6ecef",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/nvta_queue_pm")
    parser.add_argument("--panels", type=int, default=6)
    return parser.parse_args()


def hour_axis(ax: plt.Axes) -> None:
    ax.set_xticks(range(360, 1141, 180))
    ax.set_xticklabels([f"{h // 60:02d}:00" for h in range(360, 1141, 180)])
    ax.set_xlim(360, 1140)


def figure_profiles(series: pd.DataFrame, summary: pd.DataFrame, panels: int) -> None:
    """Deepest observed episode on each corridor first, then the next deepest."""
    ranked = summary.sort_values("vT2_mph_obs")
    chosen = list(ranked.groupby("corridor").head(1)["net_link_id"])
    for link_id in ranked["net_link_id"]:
        if len(chosen) >= panels:
            break
        if link_id not in chosen:
            chosen.append(link_id)
    chosen = chosen[:panels]

    rows = (len(chosen) + 2) // 3
    fig, axes = plt.subplots(rows, 3, figsize=(11.0, 3.0 * rows), sharex=True)
    for ax, link_id in zip(np.ravel(axes), chosen):
        g = series[series["link_id"] == link_id].sort_values("t_min")
        row = summary[summary["net_link_id"] == link_id].iloc[0]
        t = g["t_min"].to_numpy(float)

        ax.axvspan(PM_START, PM_END, color="#f2f6f8", zorder=0)
        ax.axhline(float(g["cutoff_mph"].iloc[0]), color=SLATE, lw=0.8, ls=":", zorder=1)
        ax.plot(t, g["obs_speed_mph"], color=INK, lw=1.6, label="observed", zorder=4)
        ax.plot(t, g["model_speed_mph"], color=ORANGE, lw=1.6, label="queue model", zorder=3)
        ax.plot(t, g["assignment_only_speed_mph"], color=TEAL, lw=1.4, ls="--",
                label="assignment only", zorder=2)
        ax.set_title(f"{row['corridor']}  link {link_id}\n"
                     f"MAE {row['speed_mae_episode_mph']:.1f} mph in episode, "
                     f"D/D_obs {row['D_ratio']:.2f}")
        ax.set_ylim(0, max(float(g["free_speed_mph"].iloc[0]) * 1.12, 60))
        hour_axis(ax)
    for ax in np.ravel(axes)[len(chosen):]:
        ax.axis("off")
    for ax in np.ravel(axes)[::3]:
        ax.set_ylabel("speed (mph)")
    np.ravel(axes)[0].legend(loc="lower left", fontsize=7.5, framealpha=0.95)
    fig.suptitle("Observed speed against the queue model, whole run window "
                 "(PM shaded, dotted line is the congestion cut-off)",
                 y=1.0, fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG / "nvta_queue_pm_profiles.png", bbox_inches="tight")
    plt.close(fig)


def figure_episode(summary: pd.DataFrame) -> None:
    matched = summary.dropna(subset=["vT2_mph_model"]).copy()
    matched["T2_obs_h"] = [int(v[:2]) + int(v[3:]) / 60 for v in matched["T2_clock_obs"]]
    matched["T2_model_h"] = [int(v[:2]) + int(v[3:]) / 60 for v in matched["T2_clock_model"]]

    # P is only comparable where the model episode closed inside the run window.
    # A censored one reports the distance to midnight, so its "error" is a window
    # artefact -- the same trap step 8 guards against.
    panels = [
        ("P_h_obs", "P_h_model", "P — episode duration (h)", "h", "P_h_err"),
        ("T2_obs_h", "T2_model_h", "T2 — time of the trough (h of day)", "h", None),
        ("vT2_mph_obs", "vT2_mph_model", "v(T2) — speed at the trough (mph)", "mph", None),
    ]
    fig, axes = plt.subplots(1, 3, figsize=(11.0, 3.8))
    for ax, (xc, yc, title, unit, gate) in zip(axes, panels):
        g = matched.dropna(subset=[xc, yc] + ([gate] if gate else []))
        lo = min(g[xc].min(), g[yc].min()) * 0.9
        hi = max(g[xc].max(), g[yc].max()) * 1.05
        ax.plot([lo, hi], [lo, hi], color=SLATE, lw=1.0, ls="--", zorder=1)
        for corridor, h in g.groupby("corridor"):
            ax.scatter(h[xc], h[yc], s=26, alpha=0.85, zorder=3,
                       color=CORRIDOR_COLOR.get(corridor, INK),
                       edgecolor="white", linewidth=0.5, label=corridor)
        mae = float((g[yc] - g[xc]).abs().median())
        subtitle = f"n = {len(g)}, median |error| = {mae:.2f} {unit}"
        if gate:
            subtitle += f"\n({len(matched) - len(g)} censored at 19:00, excluded)"
        ax.set_title(f"{title}\n{subtitle}")
        ax.set_xlabel("observed")
        ax.set_ylabel("model")
        ax.set_xlim(lo, hi)
        ax.set_ylim(lo, hi)
    axes[0].legend(fontsize=7, framealpha=0.95, loc="upper left")
    fig.suptitle("Episode parameters as model outputs, not read-offs",
                 y=1.02, fontsize=10.5, fontweight="bold")
    fig.tight_layout()
    fig.savefig(FIG / "nvta_queue_pm_episode.png", bbox_inches="tight")
    plt.close(fig)


def figure_demand(summary: pd.DataFrame) -> None:
    g = summary.dropna(subset=["D_assign_vphpl", "D_obs_vphpl"])
    hi = max(g["D_assign_vphpl"].max(), g["D_obs_vphpl"].max()) * 1.08

    fig, ax = plt.subplots(figsize=(6.2, 5.4))
    ax.fill_between([0, hi], [0, 0], [0, hi], color="#fdf0e9", zorder=0)
    ax.plot([0, hi], [0, hi], color=SLATE, lw=1.1, ls="--", zorder=2)
    for corridor, h in g.groupby("corridor"):
        ax.scatter(h["D_obs_vphpl"], h["D_assign_vphpl"], s=42, alpha=0.88, zorder=3,
                   color=CORRIDOR_COLOR.get(corridor, INK),
                   edgecolor="white", linewidth=0.6, label=corridor)
    below = int((g["D_ratio"] < 1).sum())
    ax.text(hi * 0.97, hi * 0.06,
            f"{below} of {len(g)} links below the diagonal\n"
            f"median D_assign / D_obs = {g['D_ratio'].median():.2f}",
            ha="right", va="bottom", fontsize=8.5, color=INK,
            bbox=dict(boxstyle="round,pad=0.45", fc="white", ec="#d8e0e5"))
    ax.set_xlabel("D_obs — vehicles the speed data already shows discharging (vph/lane)")
    ax.set_ylabel("D_assign — vehicles the assignment places (vph/lane)")
    ax.set_title("Below the diagonal means the assignment places fewer vehicles\n"
                 "than the road is already observed to pass", fontsize=10)
    ax.set_xlim(0, hi)
    ax.set_ylim(0, hi)
    ax.legend(fontsize=8, framealpha=0.95, loc="upper left")
    fig.tight_layout()
    fig.savefig(FIG / "nvta_queue_pm_demand.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    args = parse_args()
    FIG.mkdir(parents=True, exist_ok=True)
    series = pd.read_csv(args.output_dir / "nvta_queue_pm_speed_15min.csv")
    summary = pd.read_csv(args.output_dir / "nvta_queue_pm_link_summary.csv")

    figure_profiles(series, summary, args.panels)
    figure_episode(summary)
    figure_demand(summary)
    print(f"Wrote {FIG}/nvta_queue_pm_profiles.png")
    print(f"Wrote {FIG}/nvta_queue_pm_episode.png")
    print(f"Wrote {FIG}/nvta_queue_pm_demand.png")


if __name__ == "__main__":
    main()
