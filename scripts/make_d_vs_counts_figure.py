"""D inferred from speed against D from counts, on I-405 where both exist.

The NVTA corridors have speed but no counts, so nothing there can test whether
D is trustworthy. I-405 has both on the same links at the same time, which makes
it the only place the claim can be checked.

The test isolates the flow estimate. Both columns sum over *the same* bins, so
what is compared is q(t) from the fundamental diagram against q(t) from the
detector, not two different episode detections:

    D_speed  = sum of S3(v(t)) * dt   over the congested bins
    D_counts = sum of q_measured(t) * dt   over the same bins

Congested bins are contiguous runs below the cut-off lasting at least
``MIN_EPISODE_H``, which is the rule in ``qvdf_selfdemo/config.py``. Shorter
dips are not congestion, and the diagram misreads them badly -- it takes any low
speed as high density however few vehicles are actually behind it.

Two sources are pooled to get a usable sample, both weekday-only:

  ``multiweek``  7 links x 12 weekly average-weekday profiles
  ``daily``      18 links x 5 individual weekdays

V is computed the same way over every bin in the period and drawn beside D. The
contrast is the point: D sits on the diagonal, V sits above it.
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
    parser.add_argument("--multiweek-file", type=Path,
                        default=ROOT / "outputs/i405_multiweek_average_holdout/weekly_average_weekday_profiles_5min.csv")
    parser.add_argument("--daily-file", type=Path,
                        default=ROOT / "data/jinxi_i405_week_2025-06-16_to_22/raw_observed_fdqbench.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/d_vs_counts_i405")
    return parser.parse_args()


def load_sources(multiweek_file: Path, daily_file: Path) -> pd.DataFrame:
    """Both datasets in one tidy shape: unit, link, minute, speed, flow."""
    frames = []

    weekly = pd.read_csv(multiweek_file)
    frames.append(pd.DataFrame({
        "source": "multiweek", "link_id": weekly["link_id"],
        "unit": "wk " + weekly["week_start"].astype(str),
        "minute": weekly["minute_of_day"].astype(int),
        "speed": weekly["average_speed_mph"], "flow": weekly["average_flow_veh_h"],
    }))

    daily = pd.read_csv(daily_file)
    daily = daily[~daily["is_imputed"].astype(bool)]
    stamp = pd.to_datetime(daily["timestamp_la"])
    daily = daily.assign(minute=stamp.dt.hour * 60 + stamp.dt.minute,
                         day=stamp.dt.date.astype(str), weekday=stamp.dt.weekday)
    daily = daily[daily["weekday"] < 5]
    frames.append(pd.DataFrame({
        "source": "daily", "link_id": daily["link_id"], "unit": daily["day"],
        "minute": daily["minute"].astype(int),
        "speed": daily["speed_mph"], "flow": daily["flow_vehph"],
    }))

    return pd.concat(frames, ignore_index=True).dropna(subset=["speed", "flow"])


def sustained_below(below: np.ndarray, min_bins: int) -> np.ndarray:
    """Contiguous runs below the cut-off that last at least ``min_bins``."""
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


def period_of(minute: pd.Series) -> pd.Series:
    out = pd.Series(pd.NA, index=minute.index, dtype="object")
    for name, (start, end) in PERIODS.items():
        # NT wraps past midnight, so it is two spans rather than one.
        inside = (((minute >= start) & (minute < end)) if end <= 1440
                  else ((minute >= start) | (minute < end - 1440)))
        out[inside] = name
    return out


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    data = load_sources(args.multiweek_file, args.daily_file)
    data["period"] = period_of(data["minute"])
    data = data.dropna(subset=["period"])
    step_h = float(np.median(np.diff(np.sort(data["minute"].unique())))) / 60.0
    min_bins = max(1, int(round(MIN_EPISODE_H / step_h)))

    rows = []
    # One fundamental diagram per link and source: the two sources scale flow
    # differently (one averages across days, the other does not).
    for (source, link_id), link in data.groupby(["source", "link_id"]):
        capacity = float(link["flow"].quantile(0.995))
        speed_at_capacity = float(link.loc[link["flow"].idxmax(), "speed"])
        free_speed = float(link["speed"].quantile(0.95))
        if not free_speed > speed_at_capacity > 0 or capacity <= 0:
            continue
        cutoff = CUTOFF_RATIO * free_speed
        link = link.assign(q_speed=s3_flow(link["speed"].to_numpy(float), free_speed,
                                           speed_at_capacity, capacity))
        for (unit, period), g in link.groupby(["unit", "period"]):
            g = g.sort_values("minute")
            if len(g) < 8:
                continue
            below = sustained_below((g["speed"] < cutoff).to_numpy(), min_bins)
            rows.append({
                "source": source, "link_id": link_id, "unit": unit, "period": period,
                "bins": int(len(g)), "bins_below_cutoff": int(below.sum()),
                "cutoff_mph": cutoff, "capacity_vph": capacity,
                "D_counts": float((g["flow"].to_numpy()[below] * step_h).sum()),
                "D_speed": float((g["q_speed"].to_numpy()[below] * step_h).sum()),
                "V_counts": float((g["flow"] * step_h).sum()),
                "V_speed": float((g["q_speed"] * step_h).sum()),
            })

    frame = pd.DataFrame(rows)
    frame = frame[frame["V_counts"] > 0].copy()
    frame["V_err"] = (frame["V_speed"] - frame["V_counts"]) / frame["V_counts"] * 100
    congested = frame[frame["bins_below_cutoff"] > 0].copy()
    congested["D_err"] = (congested["D_speed"] - congested["D_counts"]) / congested["D_counts"] * 100
    frame.to_csv(args.output_dir / "d_vs_counts_i405.csv", index=False)

    fig, (left, right) = plt.subplots(1, 2, figsize=(10.4, 4.8))
    for ax, data_, xcol, ycol, err, title, size in [
        (left, congested, "D_counts", "D_speed", "D_err",
         f"D — congestion episodes of at least {MIN_EPISODE_H:g} h", 34),
        (right, frame, "V_counts", "V_speed", "V_err", "V — whole period, same links", 20),
    ]:
        # Scale to the bulk, not to the single worst point, and say how many
        # fall outside rather than quietly dropping them.
        top = max(data_[xcol].quantile(.98), data_[ycol].quantile(.98)) * 1.10
        outside = ((data_[xcol] > top) | (data_[ycol] > top)).sum()
        ax.plot([0, top], [0, top], color=INK, lw=1.2, ls="--", zorder=1)
        for period, g in data_.groupby("period"):
            ax.scatter(g[xcol].clip(upper=top), g[ycol].clip(upper=top), s=size,
                       color=PERIOD_COLOUR.get(period, SLATE),
                       alpha=.72, edgecolors="none", zorder=2, label=f"{period} (n={len(g)})")
        ax.set_xlim(0, top); ax.set_ylim(0, top)
        ax.set_xlabel(f"{xcol[0]} from measured counts (veh)")
        ax.set_ylabel(f"{xcol[0]} inferred from speed (veh)")
        ax.set_title(title)
        ax.legend(frameon=False, fontsize=8, loc="upper left")
        ax.text(.97, .06,
                f"n = {len(data_)}\nMAPE {data_[err].abs().mean():.1f}%\n"
                f"median bias {data_[err].median():+.1f}%\n"
                f"within ±20%: {(data_[err].abs() <= 20).mean()*100:.0f}%"
                + (f"\n{outside} beyond the axis, drawn at the edge" if outside else ""),
                transform=ax.transAxes, ha="right", va="bottom", fontsize=8.5,
                bbox=dict(boxstyle="round,pad=0.5", fc="#f4f7f9", ec="#cfdae1"))

    fig.suptitle("I-405, where counts exist: inferred against measured", fontweight="bold", y=0.99)
    fig.tight_layout()
    fig.savefig(FIG / "d_vs_counts.png", bbox_inches="tight")
    plt.close(fig)

    print(f"{frame['link_id'].nunique()} links, {len(frame)} link-period observations "
          f"({len(congested)} with a congestion episode of at least {MIN_EPISODE_H:g} h)")
    print(frame.groupby("source").agg(units=("unit", "nunique"), links=("link_id", "nunique"),
                                      rows=("unit", "size")).to_string())
    print()
    for label, d, err in [("D (congested)", congested, "D_err"), ("V (whole period)", frame, "V_err")]:
        print(f"{label:<18} n={len(d):>4}  MAPE {d[err].abs().mean():>6.1f}%  "
              f"median bias {d[err].median():>+6.1f}%  within +-20%: {(d[err].abs() <= 20).mean()*100:>5.1f}%")
    print(f"\nWrote {args.output_dir} and docs/figures/d_vs_counts.png")


if __name__ == "__main__":
    main()
