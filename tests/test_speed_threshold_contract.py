"""Capacity, entry, exit and QVDF reference speeds are four distinct things.

They used to be one field named `cutoff_speed_vc_mph`, which held the episode
*exit* threshold (0.75 v_f). The severity equation `z = v_ref/v(T2) - 1` then read
it, so the recovery threshold was acting as the reference speed without saying
so. The S3 capacity speed is `v_f/sqrt(2)` = 0.707 v_f, about 6% away, and z is
linear in the choice.

The behaviour is unchanged in v0.3 and now declared: every row carries
`qvdf_reference_speed_source`. These tests fail if the four speeds are conflated
again, or if the reference is used without recording which one it was.

See docs/VARIABLE_CONTRACT.md section 3.
"""

from __future__ import annotations

import math
import re
import sys
from pathlib import Path

import numpy as np
import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from fdqbench.episodes import EpisodeDetectionConfig, detect_speed_episodes  # noqa: E402

RESULTS = ROOT / "outputs/i405_multiweek_average_holdout/leave_one_week_out_qvdf_results.csv"

ALLOWED_REFERENCE_SOURCES = {
    "CAPACITY_SPEED_S3",
    "EPISODE_EXIT_THRESHOLD",
    "EPISODE_ENTRY_THRESHOLD",
    "EXTERNAL_DECLARED",
}


@pytest.fixture(scope="module")
def episodes() -> pd.DataFrame:
    """A synthetic day with one clear episode, so the detector emits a row."""
    stamps = pd.date_range("2000-01-02 00:00", periods=288, freq="5min", tz="America/Los_Angeles")
    free_speed = 65.0
    speed = np.full(288, free_speed)
    speed[192:228] = 30.0          # 16:00-19:00 congestion
    speed[186:192] = 45.0
    speed[228:234] = 50.0
    frame, _ = detect_speed_episodes(stamps, pd.Series(speed), free_speed,
                                     EpisodeDetectionConfig())
    assert len(frame), "fixture produced no episode"
    return frame


def test_detector_emits_all_three_physical_speeds(episodes):
    row = episodes.iloc[0]
    free_speed = float(row["free_speed_p95_mph"])
    assert float(row["capacity_speed_mph"]) == pytest.approx(free_speed / math.sqrt(2.0))
    assert float(row["enter_threshold_mph"]) == pytest.approx(0.70 * free_speed)
    assert float(row["exit_threshold_mph"]) == pytest.approx(0.75 * free_speed)


def test_the_three_speeds_are_distinct_and_ordered(episodes):
    row = episodes.iloc[0]
    entry = float(row["enter_threshold_mph"])
    capacity = float(row["capacity_speed_mph"])
    exit_ = float(row["exit_threshold_mph"])
    # Hysteresis: a link enters congestion below entry and recovers above exit.
    assert entry < exit_, "entry must be the lower threshold"
    # 0.70 < 0.7071 < 0.75, so the capacity speed sits between them and is
    # neither of the two hysteresis thresholds.
    assert entry < capacity < exit_
    assert capacity != pytest.approx(exit_), "capacity speed must not equal the exit threshold"


@pytest.fixture(scope="module")
def results() -> pd.DataFrame:
    if not RESULTS.exists():
        pytest.skip("holdout results not generated")
    frame = pd.read_csv(RESULTS)
    return frame[frame["episode_identified"].astype(bool)]


class TestPublishedResults:
    def test_reference_speed_declares_its_source(self, results):
        assert "qvdf_reference_speed_mph" in results
        assert "qvdf_reference_speed_source" in results
        sources = set(results["qvdf_reference_speed_source"].dropna().unique())
        assert sources, "no reference-speed source recorded on any episode row"
        assert sources <= ALLOWED_REFERENCE_SOURCES, f"undeclared source: {sources}"

    def test_reference_speed_equals_the_field_it_names(self, results):
        field = {
            "CAPACITY_SPEED_S3": "capacity_speed_mph",
            "EPISODE_EXIT_THRESHOLD": "episode_exit_speed_mph",
            "EPISODE_ENTRY_THRESHOLD": "episode_entry_speed_mph",
        }
        for source, group in results.groupby("qvdf_reference_speed_source"):
            if source not in field:
                continue
            assert group["qvdf_reference_speed_mph"].to_numpy(float) == pytest.approx(
                group[field[source]].to_numpy(float)
            ), f"reference speed does not match the {source} it claims"

    def test_all_four_speeds_are_carried(self, results):
        for column in ["capacity_speed_mph", "episode_entry_speed_mph",
                       "episode_exit_speed_mph", "qvdf_reference_speed_mph"]:
            assert column in results, f"{column} is missing from the published results"
            assert results[column].notna().all(), f"{column} has gaps on episode rows"

    def test_legacy_field_is_retained_and_reconciled(self, results):
        """One release of overlap, and it must still mean what it used to."""
        assert "legacy_cutoff_speed_vc_mph" in results
        assert results["legacy_cutoff_speed_vc_mph"].to_numpy(float) == pytest.approx(
            results["episode_exit_speed_mph"].to_numpy(float)
        ), "the legacy field held the exit threshold; the migration table says so"


def test_no_bare_vc_field_remains_in_code():
    """`cutoff_speed_vc_mph` may survive only with the `legacy_` prefix."""
    offending = []
    for path in list((ROOT / "scripts").glob("*.py")) + list((ROOT / "dashboard").glob("*.js")):
        if path.name.endswith("_data.js"):
            continue                                    # generated payloads
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            for match in re.finditer(r"cutoff_speed_vc_mph", line):
                prefix = line[max(0, match.start() - 7):match.start()]
                if prefix.endswith("legacy_"):
                    continue
                if line.lstrip().startswith("#"):
                    continue                            # migration commentary
                offending.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
    assert not offending, "bare cutoff_speed_vc_mph still in use:\n" + "\n".join(offending)
