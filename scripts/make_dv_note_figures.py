"""Figures for the I-395 NB D and V note.

Three panels, one per step of the argument:
  1. D built forward from q(t) against D from inverting the duration branch --
     they agree, and where they don't, flow during the episode explains it;
  2. flow against speed in both datasets, which is why V cannot be trusted --
     one dataset carries flow information outside congestion, the other does not;
  3. the size of that error, scored against measured counts on I-405.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs/figures"
ORANGE, TEAL, RED, BLUE, SLATE, INK = "#ec7541", "#118b81", "#d6534c", "#3278bc", "#8fa1ad", "#10243a"

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.edgecolor": "#b9c5cc", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": "#5d6d78", "ytick.color": "#5d6d78", "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.grid": True, "grid.color": "#e6ecef",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def figure_branch_agreement() -> None:
    """Forward D against inverted D, and the flow ratio that explains the gap."""
    f = pd.read_csv(ROOT / "outputs/nvta_corridor_dv_forward_i395nb/corridor_dv_forward.csv")
    f = f[f["D_over_C_duration_branch"].notna()]
    fig, (left, right) = plt.subplots(1, 2, figsize=(9.6, 3.9))

    for period, colour in [("AM", TEAL), ("PM", ORANGE)]:
        g = f[f["period"] == period]
        left.scatter(g["D_over_C_h"], g["D_over_C_duration_branch"], s=34, color=colour,
                     alpha=.85, edgecolors="none", label=f"{period}  (n={len(g)})")
        right.scatter(g["qbar_over_C_congested"], g["D_over_C_branch_ape_pct"], s=34,
                      color=colour, alpha=.85, edgecolors="none", label=period)
    lims = [0, 6]
    left.plot(lims, lims, color=INK, lw=1.1, ls="--")
    left.set_xlim(*lims); left.set_ylim(*lims)
    left.set_xlabel("D/C from $\\sum q(t)$, $v < v_{cutoff}$  (h)")
    left.set_ylabel("D/C from $(P/f_d)^{1/n}$  (h)")
    left.set_title("The two routes to D agree")
    left.legend(frameon=False, loc="upper left", fontsize=8.5)
    # Episodes that fill the whole period share one P, so they stack at one height.
    censored = f[f["P_h_below_cutoff"] >= f["period_hours"] - 1e-9]
    if len(censored):
        counts = censored["period"].value_counts()
        left.annotate(f"{len(censored)} episodes ({', '.join(f'{v} {k}' for k, v in counts.items())})"
                      "\nfill the whole window: P is censored",
                      xy=(censored["D_over_C_h"].min(), censored["D_over_C_duration_branch"].max()),
                      xytext=(0.55, 4.55), fontsize=8, color=RED,
                      arrowprops=dict(arrowstyle="->", color=RED, lw=1.0))
    am, pm = f[f["period"] == "AM"], f[f["period"] == "PM"]
    left.text(.97, .05,
              f"AM  MAPE {am['D_over_C_branch_ape_pct'].mean():.1f}%   r = {am['D_over_C_h'].corr(am['D_over_C_duration_branch']):.2f}\n"
              f"PM  MAPE {pm['D_over_C_branch_ape_pct'].mean():.1f}%   r = {pm['D_over_C_h'].corr(pm['D_over_C_duration_branch']):.2f}",
              transform=left.transAxes, ha="right", va="bottom", fontsize=8.5,
              bbox=dict(boxstyle="round,pad=0.45", fc="#f4f7f9", ec="#cfdae1"))

    right.set_xlabel("Mean flow during the episode, $\\bar q / C$")
    right.set_ylabel("Duration-branch error (%)")
    right.set_title("The gap is flow, not duration")
    right.text(.04, .93,
               f"corr = {f['qbar_over_C_congested'].corr(f['D_over_C_branch_ape_pct']):.2f}\n"
               "the branch assumes flow holds near\ncapacity; where it drops, D is overstated",
               transform=right.transAxes, va="top", fontsize=8.5,
               bbox=dict(boxstyle="round,pad=0.45", fc="#fff3ec", ec="#f0cdb8"))

    fig.tight_layout()
    fig.savefig(FIG / "branch_agreement.png", bbox_inches="tight")
    plt.close(fig)


BAND = (60.0, 65.0)   # a free-flow speed slice both datasets populate well


def figure_flow_information() -> None:
    """Hold speed fixed and ask what flow was: a wide answer, or a single one.

    The scatter alone leaves the reader to find the vertical spread, so one
    free-flow speed slice is drawn out of both panels and put side by side.
    """
    i405 = pd.read_csv(ROOT / "outputs/i405_average_weekday_canonical_direct7/average_weekday_speed_flow_5min.csv")
    i405 = i405.rename(columns={"average_observed_flow_veh_h": "q", "average_speed_mph": "v"})
    nvta = pd.read_csv(ROOT / "data/nvta_i395nb_handoff/handoff_avgweekday_timedependent.csv")
    nvta["q"] = nvta["count_total_15min"] / 0.25
    nvta["v"] = nvta["speed_smoothed"]
    for frame in (i405, nvta):
        frame["norm"] = frame["q"] / frame.groupby("link_id")["q"].transform("max")

    fig, axes = plt.subplots(1, 3, figsize=(12.4, 4.0), sharey=True,
                             gridspec_kw={"width_ratios": [1, 1, 0.62]})
    panels = [(axes[0], i405, "I-405: measured detector flow", BLUE),
              (axes[1], nvta, "I-395 NB handoff: count_total_15min", ORANGE)]

    for ax, frame, title, colour in panels:
        inside = frame["v"].between(*BAND)
        ax.scatter(frame.loc[~inside, "v"], frame.loc[~inside, "norm"], s=7,
                   color="#c8d3da", alpha=.55, edgecolors="none")
        ax.scatter(frame.loc[inside, "v"], frame.loc[inside, "norm"], s=9,
                   color=colour, alpha=.75, edgecolors="none")
        ax.axvspan(*BAND, color=colour, alpha=.09)
        ax.set_xlabel("Speed (mph)")
        ax.set_title(title)
        ax.set_ylim(-0.02, 1.08)

    # Name the two extremes of the I-405 slice: same speed, opposite traffic.
    slice_405 = i405[i405["v"].between(*BAND)]
    for row, offset, note in [(slice_405.loc[slice_405["norm"].idxmax()], (14, -6), "busiest"),
                              (slice_405.loc[slice_405["norm"].idxmin()], (14, 10), "quietest")]:
        axes[0].annotate(f"{note}  {int(row['minute_of_day'])//60:02d}:{int(row['minute_of_day'])%60:02d}",
                         xy=(row["v"], row["norm"]), xytext=offset, textcoords="offset points",
                         fontsize=8, color=INK, fontweight="bold",
                         arrowprops=dict(arrowstyle="-", color=INK, lw=.9))

    # The slice itself, side by side. This is the whole argument.
    strip = axes[2]
    for i, (frame, colour, label) in enumerate([(i405, BLUE, "I-405\nmeasured"),
                                                (nvta, ORANGE, "I-395 NB\nhandoff")]):
        values = frame.loc[frame["v"].between(*BAND), "norm"].to_numpy()
        jitter = np.random.default_rng(0).normal(i, .085, len(values))
        strip.scatter(jitter, values, s=11, color=colour, alpha=.45, edgecolors="none")
        strip.plot([i - .28, i + .28], [values.min()] * 2, color=colour, lw=2.2)
        strip.plot([i - .28, i + .28], [values.max()] * 2, color=colour, lw=2.2)
        strip.annotate("", xy=(i + .36, values.min()), xytext=(i + .36, values.max()),
                       arrowprops=dict(arrowstyle="<->", color=colour, lw=1.6))
        strip.text(i + .44, (values.min() + values.max()) / 2,
                   f"{values.max()/values.min():.1f}×" if values.min() > 0 else "",
                   color=colour, fontweight="bold", fontsize=11, va="center")
        strip.text(i, 1.045, f"n={len(values):,}", ha="center", fontsize=8, color="#5d6d78")
    strip.set_xticks([0, 1]); strip.set_xticklabels(["I-405\nmeasured", "I-395 NB\nhandoff"], fontsize=9)
    strip.set_xlim(-.55, 1.9)
    strip.set_title(f"Flow at {BAND[0]:.0f}–{BAND[1]:.0f} mph")
    strip.grid(axis="x", visible=False)

    axes[0].set_ylabel("Flow ÷ that link's daily peak flow")
    fig.suptitle("Hold the speed fixed. How many flows are consistent with it?",
                 fontweight="bold", y=1.02)
    fig.tight_layout()
    fig.savefig(FIG / "flow_information.png", bbox_inches="tight")
    plt.close(fig)


def figure_volume_error() -> None:
    """Speed-only period volume against measured counts, I-405."""
    v = pd.read_csv(ROOT / "outputs/qt_information_content/i405_speed_only_volume_error.csv")
    order = ["AM", "MD", "PM", "NT", "FULL DAY"]
    bias = [v[v["period"] == p]["error_pct"].median() for p in order]

    fig, ax = plt.subplots(figsize=(7.4, 3.4))
    bars = ax.bar(order, bias, color=[TEAL, SLATE, ORANGE, RED, INK], width=.6)
    for bar, value in zip(bars, bias):
        ax.text(bar.get_x() + bar.get_width() / 2, value + 1.4, f"+{value:.0f}%",
                ha="center", fontweight="bold", fontsize=10)
    for period, colour in zip(order, [TEAL, SLATE, ORANGE, RED, INK]):
        g = v[v["period"] == period]["error_pct"]
        ax.scatter([period] * len(g), g, s=18, color=colour, alpha=.5,
                   edgecolors="white", linewidths=.5, zorder=3)
    ax.axhline(0, color=INK, lw=1.1)
    ax.set_ylabel("Volume error (%)")
    ax.set_ylim(-5, 100)
    ax.set_title("Volume inferred from speed alone, scored against measured counts (I-405, 7 links)")
    ax.grid(axis="x", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "volume_error.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    # Figures supporting the retracted unit reading are removed rather than left
    # orphaned next to the corrected note.
    for stale in ("calibration_inputs.png", "accumulation_test.png", "pems_vs_baselines.png"):
        (FIG / stale).unlink(missing_ok=True)
    figure_branch_agreement()
    figure_flow_information()
    figure_volume_error()
    for path in sorted(FIG.glob("*.png")):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
