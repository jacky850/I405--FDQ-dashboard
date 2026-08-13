"""One results figure for the four-corridor D and V note.

Left: D/C by corridor and period, which is the headline number.
Right: how much of the period volume V sits above the cut-off, which is the
part of V the speed-to-flow inversion cannot resolve.
"""

from __future__ import annotations

import json
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs/figures"
CORRIDORS = ["I-395 NB", "I-395 SB", "I-66 EB", "I-66 WB"]
PERIODS = ["AM", "MD", "PM", "NT"]
COLOURS = {"AM": "#118b81", "MD": "#8fa1ad", "PM": "#ec7541", "NT": "#10243a"}
INK = "#10243a"

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.edgecolor": "#b9c5cc", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": "#5d6d78", "ytick.color": "#5d6d78", "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.grid": True, "grid.color": "#e6ecef",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    summary = json.loads((ROOT / "outputs/nvta_corridors_dv_ritis/corridor_dv_summary.json")
                         .read_text(encoding="utf-8"))["pipeline_clock"]
    frame = pd.read_csv(ROOT / "outputs/nvta_corridors_dv_ritis/corridor_dv_by_tmc.csv")
    frame = frame[frame["clock"] == "pipeline"]

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.2, 3.8))
    x = np.arange(len(CORRIDORS))
    width = 0.2

    for i, period in enumerate(PERIODS):
        values = [summary[c][period]["D_over_C_median_h"] for c in CORRIDORS]
        bars = left.bar(x + (i - 1.5) * width, values, width, color=COLOURS[period], label=period)
        for bar, v in zip(bars, values):
            left.text(bar.get_x() + bar.get_width() / 2, v + .07, f"{v:.1f}",
                      ha="center", fontsize=7.5, color=COLOURS[period], fontweight="bold")
    left.set_xticks(x); left.set_xticklabels(CORRIDORS, fontsize=8.5)
    left.set_ylabel("D / C   (h)")
    left.set_title("Demand over capacity, median link")
    left.legend(frameon=False, ncol=4, fontsize=8.5, loc="upper center", bbox_to_anchor=(.5, 1.0))
    left.set_ylim(0, 5.2)
    left.grid(axis="x", visible=False)

    # The share of V that comes from bins above the cut-off is the share the
    # inversion cannot resolve; it is what makes V an upper bound.
    for i, period in enumerate(PERIODS):
        shares = []
        for corridor in CORRIDORS:
            g = frame[(frame["corridor"] == corridor) & (frame["period"] == period)]
            shares.append(100.0 * (1.0 - g["D_veh_total"].sum() / g["V_veh_total"].sum()))
        bars = right.bar(x + (i - 1.5) * width, shares, width, color=COLOURS[period], label=period)
        for bar, v in zip(bars, shares):
            right.text(bar.get_x() + bar.get_width() / 2, v + 1.6, f"{v:.0f}",
                       ha="center", fontsize=7.5, color=COLOURS[period], fontweight="bold")
    right.set_xticks(x); right.set_xticklabels(CORRIDORS, fontsize=8.5)
    right.set_ylabel("% of V from free-flow bins")
    right.set_title("The part of V the speed inversion cannot resolve")
    right.set_ylim(0, 105)
    right.grid(axis="x", visible=False)

    fig.tight_layout()
    fig.savefig(FIG / "corridor_dv_results.png", bbox_inches="tight")
    plt.close(fig)
    print(f"docs/figures/corridor_dv_results.png  {(FIG / 'corridor_dv_results.png').stat().st_size/1024:.0f} KiB")


if __name__ == "__main__":
    main()
