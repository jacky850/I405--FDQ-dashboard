"""Compare the local QVDF oracle against the mentor reference code.

The I-405 cases in this script are interface/parity fixtures only.  They use
real canonical metadata, observed period volume, and derived daily k_d, but
freeze the remaining uncalibrated coefficients to the mentor synthetic-link
values.  They must not be interpreted as I-405 calibration results.
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import sys
from pathlib import Path

import numpy as np
import pandas as pd


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.slc_qvdf import (  # noqa: E402
    SLCLinkParameters,
    qvdf_episode_profile,
    qvdf_forward,
    qvdf_inverse_identified,
)


DEFAULT_MENTOR_PACKAGE = (
    ROOT.parent
    / "fdq_single_link_benchmark_v0_2"
    / "SLC_I10_Jinxin_Student_Package"
    / "SLC_I10_Jinxin_Package"
)
STATE_KEYS = [
    "V",
    "D",
    "mu",
    "x",
    "P",
    "z",
    "vT2",
    "t0",
    "T2",
    "t3",
    "TT_T2_h",
    "free_flow_vht",
    "queue_delay_vht",
    "total_vht",
]
INVERSE_KEYS = ["z_hat", "x_hat", "D_hat", "V_hat", "f_p_hat"]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser()
    parser.add_argument("--mentor-package", type=Path, default=DEFAULT_MENTOR_PACKAGE)
    parser.add_argument(
        "--canonical-dir",
        type=Path,
        default=ROOT / "outputs/i405_slc_canonical_direct4",
    )
    parser.add_argument(
        "--output-dir",
        type=Path,
        default=ROOT / "outputs/i405_slc_mentor_parity",
    )
    parser.add_argument("--random-cases", type=int, default=1000)
    return parser.parse_args()


def load_mentor_module(package: Path):
    script = package / "scripts/run_slc_i10.py"
    spec = importlib.util.spec_from_file_location("mentor_slc_reference", script)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"Unable to load mentor module: {script}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def ours_from_dict(values: dict[str, object]) -> SLCLinkParameters:
    return SLCLinkParameters(**values)


def mentor_from_dict(module, values: dict[str, object]):
    return module.LinkParameters(**values)


def clock_hour(timestamp: str, fallback: float) -> float:
    value = str(timestamp)
    if len(value) >= 16 and ":" in value[11:16]:
        hour, minute = value[11:16].split(":")
        return float(hour) + float(minute) / 60.0
    return float(fallback)


def compare_case(
    mentor,
    case_id: str,
    evidence_level: str,
    values: dict[str, object],
    volume_veh: float,
) -> tuple[list[dict[str, object]], dict[str, object]]:
    ours_link = ours_from_dict(values)
    mentor_link = mentor_from_dict(mentor, values)
    ours_state = qvdf_forward(ours_link, volume_veh)
    mentor_state = mentor.forward(mentor_link, volume_veh)
    rows: list[dict[str, object]] = []
    for variable in STATE_KEYS:
        ours_value = float(ours_state[variable])
        mentor_value = float(mentor_state[variable])
        rows.append(
            {
                "case_id": case_id,
                "evidence_level": evidence_level,
                "direction": "forward",
                "variable": variable,
                "mentor_value": mentor_value,
                "our_value": ours_value,
                "absolute_difference": abs(ours_value - mentor_value),
            }
        )

    ours_inverse = qvdf_inverse_identified(ours_link, ours_state["P"], ours_state["vT2"])
    mentor_inverse = mentor.inverse_identified(
        mentor_link, mentor_state["P"], mentor_state["vT2"]
    )
    for variable in INVERSE_KEYS:
        ours_value = float(ours_inverse[variable])
        mentor_value = float(mentor_inverse[variable])
        rows.append(
            {
                "case_id": case_id,
                "evidence_level": evidence_level,
                "direction": "inverse",
                "variable": variable,
                "mentor_value": mentor_value,
                "our_value": ours_value,
                "absolute_difference": abs(ours_value - mentor_value),
            }
        )

    time = np.linspace(ours_state["t0"], ours_state["t3"], 101)
    our_speed, our_queue = qvdf_episode_profile(ours_link, ours_state, time)
    mentor_speed, mentor_queue = mentor.profile(mentor_link, mentor_state, time)
    profile = {
        "case_id": case_id,
        "evidence_level": evidence_level,
        "profile_points": len(time),
        "max_abs_speed_difference_mph": float(np.nanmax(np.abs(our_speed - mentor_speed))),
        "max_abs_queue_difference_veh": float(np.nanmax(np.abs(our_queue - mentor_queue))),
    }
    return rows, profile


def synthetic_parameter_dict(mentor, package: Path) -> dict[str, object]:
    source = mentor.load_gold_link(package / "data/synthetic_gold_link.csv")
    return {name: getattr(source, name) for name in source.__dataclass_fields__}


def i405_fixture_rows(canonical_dir: Path, template: dict[str, object]) -> list[dict[str, object]]:
    states = pd.read_csv(
        canonical_dir / "canonical_daily_period_states.csv", dtype={"tmc_id": str}
    )
    metadata = pd.read_csv(
        canonical_dir / "canonical_link_sensor_metadata.csv", dtype={"tmc_id": str}
    )
    joined = states.merge(
        metadata,
        on=["model_link_id", "tmc_id"],
        validate="many_to_one",
        suffixes=("_state", "_meta"),
    )
    period_midpoint = {"NT1": 3.0, "AM": 8.0, "MD": 12.5, "PM": 17.0, "NT2": 21.5}
    fixtures: list[dict[str, object]] = []
    for row in joined.itertuples(index=False):
        values = dict(template)
        values.update(
            {
                "link_id": f"{row.model_link_id}|{row.tmc_id}|{row.day_id}|{row.period_id}",
                "length_mi": float(row.length_mi),
                "period_hours": float(row.period_hours),
                "volume_veh": float(row.observed_volume_veh),
                "free_speed_mph": float(row.free_speed_mph),
                "cutoff_speed_mph": float(row.cutoff_speed_mph_meta),
                "capacity_vph": float(row.nominal_capacity_vph_meta),
                "k_d": float(row.k_d_daily_derived),
                "T2_h": clock_hour(
                    row.T2_timestamp_la, period_midpoint[str(row.period_id)]
                ),
            }
        )
        fixtures.append(
            {
                "case_id": values["link_id"],
                "volume_veh": float(row.observed_volume_veh),
                "parameters": values,
            }
        )
    return fixtures


def main() -> None:
    args = parse_args()
    args.output_dir.mkdir(parents=True, exist_ok=True)
    mentor = load_mentor_module(args.mentor_package)
    template = synthetic_parameter_dict(mentor, args.mentor_package)
    comparison_rows: list[dict[str, object]] = []
    profile_rows: list[dict[str, object]] = []

    # Baseline plus randomized perturbations exercise the exact mentor oracle.
    rows, profile = compare_case(
        mentor, "GOLD-001-baseline", "synthetic_gold", template, float(template["volume_veh"])
    )
    comparison_rows.extend(rows)
    profile_rows.append(profile)
    rng = np.random.default_rng(20260810)
    for index, factor in enumerate(rng.uniform(0.5, 1.5, args.random_cases), start=1):
        rows, profile = compare_case(
            mentor,
            f"GOLD-001-random-{index:04d}",
            "synthetic_random",
            template,
            float(template["volume_veh"]) * float(factor),
        )
        comparison_rows.extend(rows)
        profile_rows.append(profile)

    # Real I-405 fields verify adapter compatibility only; uncalibrated QVDF
    # coefficients remain frozen to the mentor synthetic values.
    for fixture in i405_fixture_rows(args.canonical_dir, template):
        rows, profile = compare_case(
            mentor,
            str(fixture["case_id"]),
            "i405_interface_fixture_not_calibrated",
            fixture["parameters"],
            float(fixture["volume_veh"]),
        )
        comparison_rows.extend(rows)
        profile_rows.append(profile)

    comparisons = pd.DataFrame(comparison_rows)
    profiles = pd.DataFrame(profile_rows)
    comparisons.to_csv(args.output_dir / "mentor_vs_our_qvdf_state_parity.csv", index=False)
    profiles.to_csv(args.output_dir / "mentor_vs_our_qvdf_profile_parity.csv", index=False)
    tolerance = 1e-12
    summary = {
        "mentor_script": str(args.mentor_package / "scripts/run_slc_i10.py"),
        "our_module": "src/fdqbench/slc_qvdf.py",
        "synthetic_random_cases": args.random_cases,
        "i405_interface_cases": int(
            profiles["evidence_level"].eq("i405_interface_fixture_not_calibrated").sum()
        ),
        "state_comparisons": int(len(comparisons)),
        "profile_comparisons": int(len(profiles)),
        "max_abs_state_difference": float(comparisons["absolute_difference"].max()),
        "max_abs_speed_profile_difference_mph": float(
            profiles["max_abs_speed_difference_mph"].max()
        ),
        "max_abs_queue_profile_difference_veh": float(
            profiles["max_abs_queue_difference_veh"].max()
        ),
        "tolerance": tolerance,
        "pass": bool(
            comparisons["absolute_difference"].max() <= tolerance
            and profiles["max_abs_speed_difference_mph"].max() <= tolerance
            and profiles["max_abs_queue_difference_veh"].max() <= tolerance
        ),
        "i405_fixture_warning": (
            "I-405 rows test interface/formula parity only. f_d, n, f_p, s, and k_mu "
            "are frozen synthetic values and are not I-405 calibration results."
        ),
    }
    (args.output_dir / "parity_summary.json").write_text(
        json.dumps(summary, indent=2), encoding="utf-8"
    )
    print(json.dumps(summary, indent=2))
    if not summary["pass"]:
        raise SystemExit("Mentor/local QVDF parity failed")


if __name__ == "__main__":
    main()
