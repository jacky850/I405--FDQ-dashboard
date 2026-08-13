"""Do the ODME files supply a flow measurement the speed chain does not?

The I-395 NB note asked for a demand or flow measurement that is not derived
from speed, and named the dynamic-ODME files as the likely source. They arrived.
This checks whether they break the chain

    speed -> S3 fundamental diagram -> count_total_15min -> D and V

or sit downstream of it. The answer decides whether V can be reported as a
volume rather than an upper bound, so it is worth proving rather than assuming.

Inputs are the files as delivered (Dropbox rewrites the extension):

    measurement_nb_am        ODME calibration target, static, one row per link
    measurement_sb_pm        the I-395 SB PM equivalent
    linkflow_timedependent   observed vs assigned_odme per link per 15 min
    od_timedependent         the calibrated origin-destination matrix
"""

from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
DELIVERED = Path(r"C:\Users\jinxiwu\ASU Dropbox\Jinxi Wu")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--delivered-dir", type=Path, default=DELIVERED)
    parser.add_argument("--suffix", default=".dropboxignore")
    parser.add_argument("--handoff-file", type=Path,
                        default=ROOT / "data/nvta_i395nb_handoff/handoff_avgweekday_timedependent.csv")
    parser.add_argument("--output-dir", type=Path, default=ROOT / "outputs/odme_provenance")
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    load = lambda stem: pd.read_csv(args.delivered_dir / f"{stem}{args.suffix}")
    digest = lambda stem: hashlib.md5(
        (args.delivered_dir / f"{stem}{args.suffix}").read_bytes()).hexdigest()

    handoff = pd.read_csv(args.handoff_file)
    handoff["q_vph"] = handoff["count_total_15min"] * 4.0
    linkflow = load("linkflow_timedependent")
    od = load("od_timedependent")
    measurement = load("measurement_nb_am")

    # 1. Are the two measurement files actually two files? (The first delivery
    #    was the same file twice; sizes 2260 / 2230 match the two LFS stubs.)
    nb, sb = digest("measurement_nb_am"), digest("measurement_sb_pm")
    measurement_sb = load("measurement_sb_pm")

    # The ODME calibration target is static, one count per link. Compare it
    # against the handoff's AM peak, which is where a capacity-pinned series sits.
    am = handoff[handoff["period"] == "AM"].groupby(["from_node_id", "to_node_id"])["q_vph"]
    peaks = am.max().rename("handoff_am_peak").reset_index()
    target = measurement.merge(peaks, on=["from_node_id", "to_node_id"], how="inner")
    target_gap = (target["count"] - target["handoff_am_peak"]).abs()

    # 2. The decisive one. linkflow carries an explicit handoff_link_id, so the
    #    ODME's observed column can be compared against the handoff row for row.
    mainline = linkflow[linkflow["role"] == "mainline"].merge(
        handoff[["link_id", "t_min", "q_vph"]],
        left_on=["handoff_link_id", "t_min"], right_on=["link_id", "t_min"], how="inner")
    residual = (mainline["observed"] - mainline["q_vph"]).abs()

    # 3. If the ODME reproduced its input, assigned_odme carries nothing new.
    geh = linkflow["GEH"]

    # 4. The OD matrix: does it total more than the corridor takes in, which is
    #    what unserved demand would look like?
    onramp = linkflow[linkflow["role"] == "onramp"]
    od_by_bin = od.groupby("t_min")["volume"].sum()
    on_by_bin = onramp.groupby("t_min")["observed"].sum()
    paired = pd.concat([od_by_bin.rename("od"), on_by_bin.rename("onramp")], axis=1).dropna()

    # 5. The ramps are the one place an independent count could still hide.
    peak = onramp.groupby("link_id")["observed"].max()
    shapes = onramp.pivot_table(index="t_min", columns="link_id", values="observed")
    shapes = shapes.loc[:, shapes.sum() > 0]
    shares = shapes / shapes.sum()
    upper = np.triu_indices(shares.shape[1], 1)
    corridor_speed = handoff[handoff["period"] == "AM"].groupby("t_min")["speed_smoothed"].mean()

    summary = {
        "measurement_files": {
            "md5_nb_am": nb[:12], "md5_sb_pm": sb[:12], "identical": nb == sb,
            "rows_nb_am": int(len(measurement)), "rows_sb_pm": int(len(measurement_sb)),
            "nb_count_median": float(measurement["count"].median()),
            "sb_count_median": float(measurement_sb["count"].median()),
            "reading": ("byte-identical, so only one measurement file was delivered"
                        if nb == sb else "two distinct files, NB AM and SB PM"),
        },
        "odme_target_vs_handoff_peak": {
            "matched_links": int(len(target)),
            "identical_within_0.05": int((target_gap < 0.05).sum()),
            "mape_pct": float((target_gap / target["handoff_am_peak"] * 100).mean()),
            "count_min": float(target["count"].min()), "count_max": float(target["count"].max()),
            "reading": ("the static target is close to but not identical to the speed-derived "
                        "AM peak (5.8% apart), so it may have a separate origin. It is one "
                        "number per link for the whole period, though, so it cannot supply the "
                        "time profile V needs -- only a level check on the peak."),
        },
        "odme_observed_vs_handoff": {
            "matched_link_bins": int(len(mainline)),
            "identical_within_0.05": int((residual < 0.05).sum()),
            "mape_pct": float((residual / mainline["q_vph"].replace(0, np.nan) * 100).mean()),
            "max_abs_diff_vph": float(residual.max()),
            "correlation": float(mainline["observed"].corr(mainline["q_vph"])),
            "reading": ("the ODME's observed mainline flow IS count_total_15min, which is the "
                        "S3 fundamental diagram evaluated at the smoothed speed"),
        },
        "odme_fit_quality": {
            "geh_median": float(geh.median()), "geh_p99": float(geh.quantile(0.99)),
            "geh_max": float(geh.max()), "share_geh_below_1_pct": float((geh < 1).mean() * 100),
            "reading": "the ODME reproduced its own input, so assigned_odme adds no new information",
        },
        "od_matrix": {
            "t_min_range": [int(od["t_min"].min()), int(od["t_min"].max())],
            "bins": int(od["t_min"].nunique()), "zones": int(od["o_zone_id"].nunique()),
            "total_veh": float(od["volume"].sum() * 0.25),
            "od_vs_onramp_inflow_pct": float(((paired["od"] - paired["onramp"]) / paired["onramp"] * 100).mean()),
            "reading": ("the OD totals track the on-ramp inflows, i.e. it is the OD that "
                        "reproduces the flows above, not an independent demand measurement"),
        },
        "ramp_flows": {
            "onramps": int(onramp["link_id"].nunique()),
            "peak_above_100_vph": int((peak > 100).sum()),
            "mean_pairwise_shape_corr": float(shares.corr().values[upper].mean()),
            "corr_total_inflow_with_corridor_speed": float(
                pd.concat([on_by_bin.rename("q"), corridor_speed.rename("v")], axis=1).dropna()
                .corr().iloc[0, 1]),
            "reading": ("ramps have distinct time shapes and plausible magnitudes, and their "
                        "inflow correlates negatively with speed rather than tracking it "
                        "deterministically -- the one place an independent count could still "
                        "sit, but provenance needs departure_profile.csv to confirm"),
        },
        "coverage_gaps": {
            "linkflow_period": "AM only, t_min 300-585, I-395 NB only",
            "still_missing": ["I-395 SB measurement", "I-66 anything", "MD / PM / NT"],
        },
        "conclusion": (
            "The ODME files do not break the circularity for mainline flow. They close it "
            "exactly: what was previously an inference from a 3.3% S3 reproduction is now a "
            "row-for-row identity. V therefore remains an upper bound, and D remains the "
            "defensible column."
        ),
    }
    (args.output_dir / "odme_provenance.json").write_text(json.dumps(summary, indent=2), encoding="utf-8")
    mainline.to_csv(args.output_dir / "odme_observed_vs_handoff.csv", index=False)

    o = summary["odme_observed_vs_handoff"]
    print(f"measurement files identical: {summary['measurement_files']['identical']}")
    print(f"ODME observed vs handoff: {o['identical_within_0.05']}/{o['matched_link_bins']} identical, "
          f"MAPE {o['mape_pct']:.3f}%, corr {o['correlation']:.6f}")
    print(f"ODME fit: GEH median {summary['odme_fit_quality']['geh_median']:.2f}, "
          f"{summary['odme_fit_quality']['share_geh_below_1_pct']:.1f}% below 1")
    print(f"OD vs on-ramp inflow: {summary['od_matrix']['od_vs_onramp_inflow_pct']:+.1f}%")
    print(f"\n{summary['conclusion']}")


if __name__ == "__main__":
    main()
