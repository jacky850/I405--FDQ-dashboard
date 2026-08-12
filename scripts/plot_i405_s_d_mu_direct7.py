"""Plot D(t) and period-level mu for the strict seven-link I-405 S test set."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd


PERIOD_ORDER = ["NT1", "AM", "MD", "PM", "NT2"]
PERIOD_HOURS = {"NT1": (0, 6), "AM": (6, 10), "MD": (10, 15), "PM": (15, 19), "NT2": (19, 24)}


def hour_value(value: str) -> float:
    hour, minute = str(value).split(":")[:2]
    return int(hour) + int(minute) / 60.0


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--profile", type=Path, required=True)
    ap.add_argument("--summary", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    profile = pd.read_csv(args.profile)
    summary = pd.read_csv(args.summary)
    profile["hour"] = profile["time_la"].map(hour_value)
    summary["period"] = pd.Categorical(summary["period"], PERIOD_ORDER, ordered=True)

    for link_id, g in profile.groupby("link_id", sort=True):
        s = summary[summary["link_id"] == link_id].sort_values("period")
        fig, (ax_d, ax_mu) = plt.subplots(2, 1, figsize=(12, 7), constrained_layout=True)

        ax_d.plot(g["hour"], g["D_vph"], color="#1769aa", linewidth=1.4, label="D(t): upstream + on-ramp")
        ax_d.set_title(f"I-405 South {link_id}: demand D(t) and discharge μ")
        ax_d.set_ylabel("D (veh/h)")
        ax_d.set_xlim(0, 24)
        ax_d.set_xticks([0, 6, 10, 15, 19, 24])
        ax_d.set_xticklabels(["00:00", "06:00", "10:00", "15:00", "19:00", "24:00"])
        ax_d.grid(True, alpha=0.25)
        ax_d.legend(loc="upper right")

        colors = ["#d95f02" if "congested" in str(x) else "#8c8c8c" for x in s["mu_source"]]
        bars = ax_mu.bar(s["period"].astype(str), s["mu_vph"], color=colors, alpha=0.9)
        ax_mu.plot(s["period"].astype(str), s["capacity_vph_effective"], color="#222222", marker="_", linewidth=1.2, label="effective capacity")
        ax_mu.set_ylabel("μ (veh/h)")
        ax_mu.set_xlabel("LA time period")
        ax_mu.grid(True, axis="y", alpha=0.25)
        ax_mu.legend(loc="upper right")
        for bar, row in zip(bars, s.itertuples()):
            label = "congested" if "congested" in str(row.mu_source) else "fallback"
            ax_mu.text(bar.get_x() + bar.get_width() / 2, bar.get_height(), f"{row.mu_vph:.0f}\n{label}", ha="center", va="bottom", fontsize=8)

        fig.savefig(args.output_dir / f"{link_id}_d_mu_diagnostic.png", dpi=160)
        plt.close(fig)

    # Compact overview for comparing all seven links.
    fig, ax = plt.subplots(figsize=(12, 6), constrained_layout=True)
    for link_id, g in summary.groupby("link_id", sort=True):
        g = g.sort_values("period")
        ax.plot(g["period"].astype(str), g["mu_vph"], marker="o", linewidth=1.5, label=link_id)
    ax.set_title("I-405 South strict seven-link μ comparison")
    ax.set_xlabel("LA time period")
    ax.set_ylabel("μ (veh/h)")
    ax.grid(True, alpha=0.25)
    ax.legend(ncol=2, fontsize=8)
    fig.savefig(args.output_dir / "i405_s_direct7_mu_overview.png", dpi=160)
    plt.close(fig)

    print(f"Wrote {summary['link_id'].nunique()} link diagnostic plots to {args.output_dir}")


if __name__ == "__main__":
    main()
