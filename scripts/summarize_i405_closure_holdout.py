"""Summarize and plot I-405 leave-one-weekday-out closure validation."""

from __future__ import annotations

import argparse
from pathlib import Path

import matplotlib.pyplot as plt
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PERIOD_ORDER = ["NT1", "AM", "MD", "PM", "NT2"]


def parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser()
    p.add_argument("--input-dir", type=Path, default=ROOT / "outputs/i405_closure_holdout_direct4")
    p.add_argument("--output-dir", type=Path, default=ROOT / "outputs/i405_closure_holdout_direct4/figures")
    return p.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    summary = pd.read_csv(args.input_dir / "single_link_closure_holdout_summary.csv")
    series = pd.read_csv(args.input_dir / "single_link_closure_holdout_timeseries.csv")
    summary["period"] = pd.Categorical(summary["period"], PERIOD_ORDER, ordered=True)
    series["period"] = pd.Categorical(series["period"], PERIOD_ORDER, ordered=True)

    period = (summary.groupby("period", observed=False)
              .agg(mean_abs_volume_error_pct=("volume_error_pct", lambda s: s.abs().mean()),
                   mean_flow_mae_vehph=("flow_mae_vehph", "mean"),
                   mean_speed_mae_mph=("speed_mae_mph", "mean"))
              .reindex(PERIOD_ORDER).reset_index())
    link = (summary.groupby("key", as_index=False)
            .agg(mean_abs_volume_error_pct=("volume_error_pct", lambda s: s.abs().mean()),
                 mean_flow_mae_vehph=("flow_mae_vehph", "mean")))
    link["label"] = link["key"].str.replace("|", "\n", regex=False)
    link = link.sort_values("mean_abs_volume_error_pct")

    period.to_csv(args.output_dir.parent / "single_link_closure_holdout_period_summary.csv", index=False)
    link.to_csv(args.output_dir.parent / "single_link_closure_holdout_link_summary.csv", index=False)

    fig, axes = plt.subplots(2, 2, figsize=(13, 9), constrained_layout=True)
    ax = axes[0, 0]
    ax.bar(period["period"], period["mean_abs_volume_error_pct"], color="#2563eb")
    ax.set_title("Holdout volume error by period")
    ax.set_ylabel("Mean absolute volume error (%)")
    ax.set_xlabel("Period")
    ax.grid(axis="y", alpha=0.25)

    ax = axes[0, 1]
    colors = {"NT1": "#2563eb", "AM": "#059669", "MD": "#d97706", "PM": "#dc2626", "NT2": "#7c3aed"}
    for period_name in PERIOD_ORDER:
        g = summary[summary["period"].eq(period_name)]
        ax.scatter(g["observed_volume_veh"], g["inferred_volume_veh"], alpha=0.8, label=period_name, color=colors[period_name])
    lo = min(summary["observed_volume_veh"].min(), summary["inferred_volume_veh"].min())
    hi = max(summary["observed_volume_veh"].max(), summary["inferred_volume_veh"].max())
    ax.plot([lo, hi], [lo, hi], "--", color="#6b7280", linewidth=1)
    ax.set_title("Observed vs. inferred period volume")
    ax.set_xlabel("Observed volume (veh)")
    ax.set_ylabel("Inferred volume (veh)")
    ax.legend(title="Period", fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1, 0]
    for period_name in PERIOD_ORDER:
        g = series[series["period"].eq(period_name)]
        ax.scatter(g["flow_observed_vehph"], g["flow_inferred_vehph"], s=7, alpha=0.25, label=period_name, color=colors[period_name])
    lo = min(series["flow_observed_vehph"].min(), series["flow_inferred_vehph"].min())
    hi = max(series["flow_observed_vehph"].max(), series["flow_inferred_vehph"].max())
    ax.plot([lo, hi], [lo, hi], "--", color="#6b7280", linewidth=1)
    ax.set_title("Holdout flow: observed vs. inferred")
    ax.set_xlabel("Observed flow (veh/h)")
    ax.set_ylabel("Inferred flow (veh/h)")
    ax.legend(title="Period", fontsize=8)
    ax.grid(alpha=0.25)

    ax = axes[1, 1]
    ax.barh(link["label"], link["mean_abs_volume_error_pct"], color="#9333ea")
    ax.set_title("Mean absolute volume error by link")
    ax.set_xlabel("Mean absolute volume error (%)")
    ax.grid(axis="x", alpha=0.25)

    fig.suptitle("I-405 Single-Link Closure: leave-one-weekday-out validation", fontsize=14)
    fig.savefig(args.output_dir / "i405_closure_holdout_overview.png", dpi=180)
    plt.close(fig)
    print(f"Wrote summaries and figure to {args.output_dir}")


if __name__ == "__main__":
    main()
