"""Create visual QA figures for the speed-only asymmetric episode detector."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.dates as mdates
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--input-dir",
        type=Path,
        default=ROOT / "outputs/i405_speed_only_episodes_direct7",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    figure_dir = args.input_dir / "figures"
    figure_dir.mkdir(parents=True, exist_ok=True)
    process = pd.read_csv(args.input_dir / "speed_only_episode_process_5min.csv")
    episodes = pd.read_csv(args.input_dir / "speed_only_asymmetric_episodes.csv")
    comparison = pd.read_csv(args.input_dir / "speed_only_vs_paq_reference.csv")
    process["timestamp_la"] = pd.to_datetime(process["timestamp_la"], utc=True).dt.tz_convert(
        "America/Los_Angeles"
    )
    for column in ["t0_la", "T2_la", "t3_la"]:
        episodes[column] = pd.to_datetime(episodes[column], utc=True, format="mixed").dt.tz_convert(
            "America/Los_Angeles"
        )
    for column in ["paq_t0_la", "paq_t3_la"]:
        comparison[column] = pd.to_datetime(
            comparison[column], utc=True, errors="coerce", format="mixed"
        ).dt.tz_convert(
            "America/Los_Angeles"
        )

    for link_id in sorted(process["link_id"].unique()):
        link_process = process[process["link_id"].eq(link_id)]
        dates = sorted(link_process["local_date"].unique())
        fig, axes = plt.subplots(len(dates), 1, figsize=(13, 2.35 * len(dates)), sharex=False, sharey=True)
        axes = np.atleast_1d(axes)
        for ax, date in zip(axes, dates):
            day = link_process[link_process["local_date"].eq(date)].sort_values("timestamp_la")
            ax.plot(day["timestamp_la"], day["speed_raw_mph"], color="#9bbcf3", lw=0.8, label="raw speed")
            ax.plot(day["timestamp_la"], day["speed_smoothed_mph"], color="#1456b8", lw=1.5, label="3-bin median")
            ax.plot(day["timestamp_la"], day["enter_threshold_mph"], "--", color="#d97706", lw=1.0, label="entry threshold")
            ax.plot(day["timestamp_la"], day["exit_threshold_mph"], ":", color="#059669", lw=1.0, label="exit threshold")
            detected = episodes[episodes["link_id"].eq(link_id) & episodes["local_date"].eq(date)]
            for _, row in detected.iterrows():
                ax.axvspan(row["t0_la"], row["t3_la"], color="#ef4444", alpha=0.14)
                ax.axvline(row["T2_la"], color="#b91c1c", lw=1.0)
            day_start = pd.Timestamp(date, tz="America/Los_Angeles")
            ax.set_xlim(day_start, day_start + pd.Timedelta(days=1))
            ax.set_ylabel("mph")
            ax.set_title(f"{date} | detected={len(detected)}", loc="left", fontsize=10)
            ax.grid(alpha=0.18)
            ax.xaxis.set_major_locator(mdates.HourLocator(byhour=[0, 6, 12, 18]))
            ax.xaxis.set_major_formatter(mdates.DateFormatter("%H:%M", tz=day["timestamp_la"].dt.tz))
        axes[0].legend(loc="upper center", ncol=4, frameon=False, fontsize=8)
        fig.suptitle(
            f"{link_id}: speed-only asymmetric congestion episodes (red)",
            y=0.998,
        )
        fig.tight_layout(rect=(0, 0, 1, 0.975))
        fig.savefig(figure_dir / f"{link_id}_speed_episode_diagnostic.png", dpi=180)
        plt.close(fig)

    matched = comparison[comparison["match_status"].eq("matched")].copy()
    fig, axes = plt.subplots(1, 3, figsize=(13, 4.1))
    axes[0].scatter(matched["paq_P_h"] * 60, matched["speed_P_h"] * 60, color="#2563eb")
    bound = max(1.0, float(np.nanmax(np.r_[matched["paq_P_h"], matched["speed_P_h"]]) * 60))
    axes[0].plot([0, bound], [0, bound], "--", color="0.35")
    axes[0].set(xlabel="PAQ duration (min)", ylabel="Speed-only duration (min)", title="Duration agreement")
    axes[1].scatter(np.arange(len(matched)), matched["delta_t0_min"], color="#d97706", label="t0")
    axes[1].scatter(np.arange(len(matched)), matched["delta_t3_min"], color="#059669", label="t3")
    axes[1].axhline(0, color="0.35", lw=0.8)
    axes[1].set(xlabel="Matched episode", ylabel="Speed-only minus PAQ (min)", title="Boundary differences")
    axes[1].legend(frameon=False)
    axes[2].scatter(np.arange(len(matched)), matched["delta_T2_min"], color="#7c3aed")
    axes[2].axhline(0, color="0.35", lw=0.8)
    axes[2].set(xlabel="Matched episode", ylabel="Difference (min)", title="T2 within PAQ window")
    for ax in axes:
        ax.grid(alpha=0.2)
    fig.tight_layout()
    fig.savefig(figure_dir / "speed_only_vs_paq_summary.png", dpi=200)
    plt.close(fig)
    print(f"Wrote episode QA figures to {figure_dir}")


if __name__ == "__main__":
    main()
