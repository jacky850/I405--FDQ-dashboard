"""D and V inferred from speed against the same quantities from counts.

Reads what ``build_pems_pm_corridors.py`` scored: ten PeMS corridor-directions
(both ways on I-405, I-5, I-10, I-210), average-weekday profiles, D restricted to
congestion episodes of at least half an hour.

Also prints the split that says what *kind* of error each one carries. Comparing
`|bias|` against MAPE separates a consistent lean from scatter, and the two
behave differently: per bin the error is nearly all scatter, and summing a period
cancels most of it, so what is left is mostly direction.
"""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
FIG = ROOT / "docs/figures"
PERIODS = ["AM", "MD", "PM", "NT"]
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
    parser.add_argument("--scored-file", type=Path,
                        default=ROOT / "outputs/pems_pm_corridors/d_v_vs_counts_by_link.csv")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    frame = pd.read_csv(args.scored_file)
    congested = frame[frame["bins_below_cutoff"] > 0].dropna(subset=["D_err"])

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.8))
    for ax, data, xcol, ycol, err, title in [
        (left, congested, "D_counts", "D_speed", "D_err", "D — congestion episodes of at least 0.5 h"),
        (right, frame, "V_counts", "V_speed", "V_err", "V — whole period, same links"),
    ]:
        top = max(data[xcol].quantile(.98), data[ycol].quantile(.98)) * 1.10
        outside = int(((data[xcol] > top) | (data[ycol] > top)).sum())
        ax.plot([0, top], [0, top], color=INK, lw=1.2, ls="--", zorder=1)
        for period in PERIODS:
            g = data[data["period"] == period]
            if g.empty:
                continue
            ax.scatter(g[xcol].clip(upper=top), g[ycol].clip(upper=top), s=13,
                       color=PERIOD_COLOUR[period], alpha=.55, edgecolors="none", zorder=2,
                       label=f"{period} (n={len(g)})")
        ax.set_xlim(0, top); ax.set_ylim(0, top)
        ax.set_xlabel(f"{xcol[0]} from measured counts (veh)")
        ax.set_ylabel(f"{xcol[0]} inferred from speed (veh)")
        ax.set_title(title)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        ax.text(.97, .06,
                f"n = {len(data)}\nMAPE {data[err].abs().mean():.1f}%\n"
                f"median bias {data[err].median():+.1f}%\n"
                f"within ±20%: {(data[err].abs() <= 20).mean()*100:.0f}%"
                + (f"\n{outside} beyond the axis, drawn at the edge" if outside else ""),
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.5", fc="#f4f7f9", ec="#cfdae1"))

    fig.suptitle(f"{frame['corridor'].nunique()} PeMS corridor-directions, "
                 f"{frame['link_id'].nunique()} links: inferred against measured",
                 fontweight="bold", y=0.99)
    fig.tight_layout()
    fig.savefig(FIG / "d_vs_counts.png", bbox_inches="tight")
    plt.close(fig)

    print(f"{frame['corridor'].nunique()} corridor-directions, {frame['link_id'].nunique()} links\n")
    print(f"{'':<16} {'n':>5} {'MAPE':>8} {'bias':>8} {'|bias|/MAPE':>13}")
    for label, data, err in [("D", congested, "D_err"), ("V", frame, "V_err")]:
        for period in PERIODS:
            g = data[data["period"] == period][err].dropna()
            if g.empty:
                continue
            mape = g.abs().mean()
            print(f"{label + ' ' + period:<16} {len(g):>5} {mape:>7.1f}% {g.median():>+7.1f}% "
                  f"{abs(g.median())/mape:>13.2f}")
    print(f"\nWrote {FIG / 'd_vs_counts.png'}")


if __name__ == "__main__":
    main()
