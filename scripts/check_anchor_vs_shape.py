"""How much of the 2.18 mph fit comes from the QVDF shape, and how much from the anchors?

Same four anchors (t0, T2, t3, v_T2) read off the observation, three different
things drawn between them:

  qvdf      v_c / (1 + z (1 - tau^2)^2), the delivered curve
  triangle  straight lines t0 -> T2 -> t3. No shape model at all.
  flat      v_T2 held across the whole episode. The crudest thing that still
            honours the depth.

If the triangle scores close to the QVDF curve, the anchors are doing the work
and the shape family is barely being tested.
"""
import sys
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/nvta_pm_link_speed"

series = pd.read_csv(OUT / "nvta_pm_link_speed_15min.csv")
summary = pd.read_csv(OUT / "nvta_pm_link_summary_full.csv").set_index("net_link_id")

rows = []
for link_id, g in series.groupby("net_link_id"):
    s = summary.loc[link_id]
    if not s["congested"]:
        continue
    g = g.sort_values("t_min")
    t = g["t_min"].to_numpy(float)
    obs = g["obs_speed_smoothed_mph"].to_numpy(float)
    qvdf = g["backcalc_speed_mph"].to_numpy(float)
    keep = g["in_pm_period"].to_numpy(bool) & g["in_episode"].to_numpy(bool)
    if keep.sum() < 3:
        continue

    t0, t2, t3 = s["t0_min"], s["T2_min"], s["t3_min"]
    vc, vt2 = s["cutoff_mph"], s["vT2_mph"]
    triangle = np.interp(t, [t0, t2, t3], [vc, vt2, vc])
    flat = np.full_like(t, vt2)

    for name, model in [("qvdf", qvdf), ("triangle", triangle), ("flat", flat)]:
        err = model[keep] - obs[keep]
        rows.append({"net_link_id": link_id, "model": name,
                     "mae": np.abs(err).mean(), "rmse": np.sqrt((err ** 2).mean()),
                     "n": int(keep.sum())})

frame = pd.DataFrame(rows)
print(f"{frame.net_link_id.nunique()} links with a PM episode, "
      f"{frame[frame.model == 'qvdf'].n.sum()} PM bins inside one\n")
print(f"{'drawn between the anchors':<28} {'median MAE':>11} {'median RMSE':>12}")
print("-" * 54)
for name in ["qvdf", "triangle", "flat"]:
    g = frame[frame.model == name]
    print(f"{name:<28} {g.mae.median():>10.2f}  {g.rmse.median():>11.2f}")

wide = frame.pivot(index="net_link_id", columns="model", values="mae")
print(f"\nQVDF beats the triangle on {int((wide.qvdf < wide.triangle).sum())} "
      f"of {len(wide)} links")
print(f"median improvement of QVDF over the triangle: "
      f"{(wide.triangle - wide.qvdf).median():+.2f} mph")
print(f"median improvement of the triangle over flat: "
      f"{(wide.flat - wide.triangle).median():+.2f} mph")
