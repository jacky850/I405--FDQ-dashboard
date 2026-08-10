"""Apply the mentor PAQ queue-object logic to the I-405 S calibration week.

The implementation follows paq_d12_extract_standalone.py: 70% of a
data-driven free-flow threshold, contiguous fragments, spatial/temporal
fragment merging, and xstar/pm_range queue-object outputs. The output maps
PAQ postmile positions back to the PeMS link IDs observed at those postmiles.
"""

from __future__ import annotations

import argparse
from itertools import combinations
from pathlib import Path

import numpy as np
import pandas as pd


THRESH_RATIO = 0.70
MIN_DUR = 20.0
OVERLAP_MIN = 30.0
MIN_DURATION = 60.0
RULE_C_TOL = 10.0
ONSET_GAP = 45.0
DT = 5.0
TARGETS = ["L405S-012", "L405S-018", "L405S-028", "L405S-030", "L405S-058", "L405S-098", "L405S-115"]


def find_fragments(v: np.ndarray, t: np.ndarray, threshold: float) -> list[tuple[float, float]]:
    below = v < threshold
    runs = []
    start = None
    for i, flag in enumerate(below):
        if flag and start is None:
            start = i
        elif not flag and start is not None:
            runs.append((start, i - 1))
            start = None
    if start is not None:
        runs.append((start, len(below) - 1))
    return [(float(t[s]), float(t[e])) for s, e in runs if t[e] - t[s] >= MIN_DUR]


def coverage_t0(sub: pd.DataFrame) -> float:
    starts = np.sort(sub.groupby("seg_idx")["T0"].min().values)
    return float(starts[max(1, int(np.ceil(0.50 * len(starts)))) - 1])


def extract_day(post: np.ndarray, times: np.ndarray, speeds: np.ndarray, thresholds: dict[float, float], link_by_pm: dict[float, str]) -> list[dict]:
    pool = []
    for j, pm in enumerate(post):
        for t0, t3 in find_fragments(speeds[:, j], times, thresholds[pm]):
            pool.append({"seg_idx": j, "postmile": pm, "T0": t0, "T3": t3, "link_id": link_by_pm[pm]})
    if not pool:
        return []
    frame = pd.DataFrame(pool)
    parent = list(range(len(frame)))

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, j in combinations(range(len(frame)), 2):
        fi, fj = frame.iloc[i], frame.iloc[j]
        if abs(fi.postmile - fj.postmile) > 1.0:
            continue
        if max(0.0, min(fi.T3, fj.T3) - max(fi.T0, fj.T0)) < OVERLAP_MIN:
            continue
        up, dn = (fi, fj) if fi.postmile < fj.postmile else (fj, fi)
        if up.T0 < dn.T0 - RULE_C_TOL:
            continue
        if abs(fi.T0 - fj.T0) > ONSET_GAP:
            continue
        union(i, j)

    groups: dict[int, list[int]] = {}
    for i in range(len(frame)):
        groups.setdefault(find(i), []).append(i)
    objects = []
    for n, indices in enumerate(groups.values(), start=1):
        sub = frame.iloc[indices]
        t0_eff = coverage_t0(sub)
        t0_raw = float(sub.T0.min())
        t3 = float(sub.T3.max())
        if t3 - t0_eff < MIN_DURATION:
            continue
        window = (times >= t0_eff) & (times <= t3)
        unique_seg = sorted(set(sub.seg_idx.astype(int)))
        means = [float(speeds[window, s].mean()) for s in unique_seg]
        xstar = float(post[unique_seg[int(np.argmin(means))]])
        pm_lo, pm_hi = float(sub.postmile.min()), float(sub.postmile.max())
        objects.append({
            "object": f"O{n}", "T0_min": t0_eff, "T0_raw_min": t0_raw, "T3_min": t3,
            "T0_hhmm": f"{int(t0_eff // 60):02d}:{int(t0_eff % 60):02d}",
            "T3_hhmm": f"{int(t3 // 60):02d}:{int(t3 % 60):02d}",
            "duration_min": t3 - t0_eff, "n_segments": len(unique_seg),
            "pm_lo": pm_lo, "pm_hi": pm_hi, "xstar_pm": xstar,
            "xstar_link_id": link_by_pm[min(post, key=lambda p: abs(p - xstar))],
            "range_link_ids": ";".join(sorted(set(sub.link_id))),
            "fragment_n": len(sub),
        })
    return objects


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--raw-file", type=Path, required=True)
    ap.add_argument("--output-dir", type=Path, required=True)
    args = ap.parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)

    raw = pd.read_csv(args.raw_file)
    raw["date"] = pd.to_datetime(raw["date"]).dt.strftime("%Y-%m-%d")
    raw = raw[raw["date"].between("2025-06-02", "2025-06-06")].copy()
    raw["time_min"] = pd.to_datetime(raw["timestamp"], utc=True).dt.hour * 60 + pd.to_datetime(raw["timestamp"], utc=True).dt.minute
    raw["speed_mph"] = raw["speed"] * (1.0 / 1.60934)

    # Every postmile is mapped to the modal observed link ID at that location.
    pm_link = (raw.groupby("milepost")["link_id"].agg(lambda s: s.mode().iloc[0]).to_dict())
    free = raw.groupby("milepost")["speed_mph"].quantile(0.95).to_dict()
    threshold = {pm: THRESH_RATIO * vf for pm, vf in free.items()}

    objects = []
    for date, day in raw.groupby("date", sort=True):
        mat = day.pivot_table(index="time_min", columns="milepost", values="speed_mph", aggfunc="mean").sort_index()
        post = np.array(sorted(mat.columns), dtype=float)
        mat = mat.reindex(columns=post)
        times = mat.index.to_numpy(dtype=float)
        values = mat.to_numpy(dtype=float)
        day_objects = extract_day(post, times, values, threshold, pm_link)
        for row in day_objects:
            objects.append({"date": date, **row})

    object_df = pd.DataFrame(objects)
    object_df.to_csv(args.output_dir / "i405_s_paq_objects_week_2025-06-02_to_2025-06-06.csv", index=False)

    # Join PAQ evidence to the seven D/μ test links.
    rows = []
    for link_id in TARGETS:
        hit = object_df[object_df["range_link_ids"].fillna("").str.split(";").map(lambda x: link_id in x)] if not object_df.empty else object_df
        xstar_hit = object_df[object_df.get("xstar_link_id", pd.Series(dtype=str)).eq(link_id)] if not object_df.empty else object_df
        rows.append({
            "link_id": link_id, "paq_object_count_in_range": len(hit),
            "paq_xstar_count": len(xstar_hit),
            "paq_dates_in_range": ";".join(sorted(hit["date"].unique())) if len(hit) else "",
            "paq_xstar_dates": ";".join(sorted(xstar_hit["date"].unique())) if len(xstar_hit) else "",
            "paq_xstar_pm_values": ";".join(f"{x:.2f}" for x in sorted(xstar_hit["xstar_pm"].unique())) if len(xstar_hit) else "",
            "paq_range_values": ";".join(f"{x:.2f}-{y:.2f}" for x, y in zip(hit["pm_lo"], hit["pm_hi"])) if len(hit) else "",
            "detector_postmile_min": float(raw.loc[raw["link_id"] == link_id, "milepost"].min()) if (raw["link_id"] == link_id).any() else np.nan,
            "detector_postmile_max": float(raw.loc[raw["link_id"] == link_id, "milepost"].max()) if (raw["link_id"] == link_id).any() else np.nan,
            "mu_source_recommendation": "target_or_downstream_after_paq_review" if len(hit) else "no_paq_object_in_week",
        })
    pd.DataFrame(rows).to_csv(args.output_dir / "i405_s_paq_detector_comparison_direct7.csv", index=False)
    print(f"PAQ objects: {len(object_df)}; wrote mapped seven-link comparison")


if __name__ == "__main__":
    main()
