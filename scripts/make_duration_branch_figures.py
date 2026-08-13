"""Figures for the duration-branch identifiability note.

Three panels, each carrying one step of the argument:
  1. the two calibration datasets, side by side, showing why neither identifies
     the branch — one is circular, the other barely varies;
  2. the accumulation test, which needs no model at all;
  3. the I-405 result against its baselines, so the reported error is readable.
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
NVTA_QVDF = Path(
    r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu\T2_Task_3\NVTA_internal-git"
    r"\t2_analysis\qvdf_projection_dashboard\outputs\pabc_link_level_week.csv"
)
ORANGE, TEAL, RED, BLUE, SLATE, INK = "#ec7541", "#118b81", "#d6534c", "#3278bc", "#8fa1ad", "#10243a"

plt.rcParams.update({
    "figure.dpi": 160, "savefig.dpi": 160, "font.size": 9,
    "axes.edgecolor": "#b9c5cc", "axes.labelcolor": INK, "text.color": INK,
    "xtick.color": "#5d6d78", "ytick.color": "#5d6d78", "axes.titlesize": 10.5,
    "axes.titleweight": "bold", "axes.grid": True, "grid.color": "#e6ecef",
    "figure.facecolor": "white", "axes.facecolor": "white",
})


def figure_calibration_inputs() -> None:
    """Why neither dataset identifies the branch: circular vs. barely varying."""
    fig, (left, right) = plt.subplots(1, 2, figsize=(9.6, 3.9))

    nvta = pd.read_csv(NVTA_QVDF)
    nvta = nvta[nvta["corridor"].str.contains("I-66|I-395")].dropna(subset=["P_A", "DC_obs"])
    slope, intercept = np.polyfit(nvta["P_A"], nvta["DC_obs"], 1)
    r2 = nvta["P_A"].corr(nvta["DC_obs"]) ** 2
    left.scatter(nvta["P_A"], nvta["DC_obs"], s=16, color=ORANGE, alpha=.65, edgecolors="none")
    grid = np.linspace(nvta["P_A"].min(), nvta["P_A"].max(), 50)
    left.plot(grid, slope * grid + intercept, color=RED, lw=1.8)
    left.set_title("NVTA calibration input: D/C is built from P")
    left.set_xlabel("Congestion duration P (h)")
    left.set_ylabel("D/C in the calibration table")
    left.text(.04, .93, f"D/C = {slope:.2f}·P + {intercept:.2f}\n$R^2$ = {r2:.3f}   n = {len(nvta)}",
              transform=left.transAxes, va="top", fontsize=8.5,
              bbox=dict(boxstyle="round,pad=0.45", fc="#fff3ec", ec="#f0cdb8"))

    pems = pd.read_csv(ROOT / "outputs/i405_multiweek_average_holdout/leave_one_week_out_qvdf_results.csv")
    pems = pems[pems["episode_identified"]].dropna(subset=["P_h", "observed_peak_1h_demand_veh_h"])
    dc = pems["observed_peak_1h_demand_veh_h"] / pems["capacity_proxy_week_p95_vph"]
    right.scatter(pems["P_h"], dc, s=22, color=TEAL, alpha=.75, edgecolors="none")
    right.axhline(1.0, color=INK, lw=1.1, ls="--")
    right.set_ylim(0.0, 4.8)
    right.set_title("I-405 calibration input: D/C is measured, and barely moves")
    right.set_xlabel("Congestion duration P (h)")
    right.set_ylabel("D/C from measured flow")
    right.text(.04, .93,
               f"D/C spans {dc.min():.2f}–{dc.max():.2f}  (1.7×)\n"
               f"P spans {pems['P_h'].min():.2f}–{pems['P_h'].max():.2f} h  (12×)\n"
               f"corr(P, D/C) = {pems['P_h'].corr(dc):.2f}   n = {len(pems)}",
               transform=right.transAxes, va="top", fontsize=8.5,
               bbox=dict(boxstyle="round,pad=0.45", fc="#e9f4f2", ec="#b5d8d2"))

    fig.tight_layout()
    fig.savefig(FIG / "calibration_inputs.png", bbox_inches="tight")
    plt.close(fig)


def figure_accumulation() -> None:
    """The model-free check: the implied queue has nowhere to go."""
    summary = json.loads(
        (ROOT / "outputs/nvta_corridor_d_v_i395nb/duration_branch_vs_queue_summary.json")
        .read_text(encoding="utf-8")
    )
    f = summary["falsification_by_accumulation"]
    labels = ["Delay queue implied\nby observed speed", "Corridor storage\nat jam density",
              "AM: implied by\nduration branch", "PM: implied by\nduration branch"]
    values = [f["observed_delay_queue_max_veh"], f["storage_at_jam_density_veh"],
              f["AM"]["implied_queue_accumulation_veh"], f["PM"]["implied_queue_accumulation_veh"]]
    colours = [TEAL, SLATE, ORANGE, RED]

    fig, ax = plt.subplots(figsize=(9.0, 3.2))
    y = np.arange(len(values))[::-1]
    ax.barh(y, values, color=colours, height=.6)
    ax.set_xscale("log")
    ax.set_xlim(100, 90000)
    ax.axvspan(f["storage_at_jam_density_veh"], 90000, color=RED, alpha=.06)
    ax.axvline(f["storage_at_jam_density_veh"], color=RED, lw=1.5, ls="--")
    ax.text(f["storage_at_jam_density_veh"] * 1.15, y[0] + .42,
            "beyond here the vehicles do not fit on the road",
            color=RED, fontsize=8, va="bottom")
    for yi, v, c in zip(y, values, colours):
        ax.text(v * 1.12, yi, f"{v:,.0f}", va="center", color=c, fontweight="bold", fontsize=9)
    ax.set_yticks(y); ax.set_yticklabels(labels, fontsize=8.5)
    ax.set_xlabel("Vehicles accumulated (log scale)")
    ax.set_title("I-395 NB: where would the implied vehicles go?")
    ax.grid(axis="y", visible=False)
    fig.tight_layout()
    fig.savefig(FIG / "accumulation_test.png", bbox_inches="tight")
    plt.close(fig)


def figure_pems_result() -> None:
    """The I-405 result read against its baselines, and against the truth."""
    pems = pd.read_csv(ROOT / "outputs/i405_multiweek_average_holdout/leave_one_week_out_qvdf_results.csv")
    s = pems[pems["final_supported"]].copy()
    s["dc_true"] = s["observed_peak_1h_demand_veh_h"] / s["capacity_vph"]

    fig, (left, right) = plt.subplots(1, 2, figsize=(9.6, 3.9))

    left.scatter(s["dc_true"], s["x_hat_D_over_C"], s=30, color=BLUE, alpha=.8, edgecolors="none")
    lims = [0.4, 1.5]
    left.plot(lims, lims, color=INK, lw=1.1, ls="--")
    left.set_xlim(*lims); left.set_ylim(*lims)
    left.set_xlabel("Measured D/C"); left.set_ylabel("Inferred D/C from the duration branch")
    left.set_title("I-405: the inference does not track the truth")
    left.text(.04, .93,
              f"corr = {s['x_hat_D_over_C'].corr(s['dc_true']):.2f}\n"
              f"measured sd = {s['dc_true'].std():.3f}\ninferred sd = {s['x_hat_D_over_C'].std():.3f}",
              transform=left.transAxes, va="top", fontsize=8.5,
              bbox=dict(boxstyle="round,pad=0.45", fc="#eaf1f8", ec="#bfd4e8"))

    names = ["Duration\nbranch", "Assume\nD = capacity", "Average the\nother weeks"]
    scores = [16.88, 7.08, 5.21]
    bars = right.bar(names, scores, color=[ORANGE, TEAL, SLATE], width=.55)
    for bar, v in zip(bars, scores):
        right.text(bar.get_x() + bar.get_width() / 2, v + .4, f"{v:.2f}%",
                   ha="center", fontweight="bold", fontsize=9.5)
    right.set_ylabel("Period-volume MAPE (%)")
    right.set_ylim(0, 20)
    right.set_title("I-405: worse than doing nothing")
    right.grid(axis="x", visible=False)

    fig.tight_layout()
    fig.savefig(FIG / "pems_vs_baselines.png", bbox_inches="tight")
    plt.close(fig)


def main() -> None:
    FIG.mkdir(parents=True, exist_ok=True)
    figure_calibration_inputs()
    figure_accumulation()
    figure_pems_result()
    for path in sorted(FIG.glob("*.png")):
        print(f"{path.relative_to(ROOT)}  {path.stat().st_size / 1024:.0f} KiB")


if __name__ == "__main__":
    main()
