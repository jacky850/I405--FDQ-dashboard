from __future__ import annotations

import numpy as np
import pandas as pd

from fdqbench.episodes import EpisodeDetectionConfig, detect_speed_episodes


def test_single_spike_is_rejected_but_persistent_asymmetric_episode_is_kept() -> None:
    time = pd.date_range("2025-06-02", periods=288, freq="5min", tz="America/Los_Angeles")
    speed = np.full(288, 65.0)
    speed[20] = 20.0
    speed[80:87] = [44, 39, 31, 23, 26, 34, 42]
    episodes, _ = detect_speed_episodes(
        pd.Series(time),
        speed,
        free_speed_mph=65.0,
        config=EpisodeDetectionConfig(minimum_depth_mph=2.0),
    )
    assert len(episodes) == 1
    assert episodes.iloc[0]["T2_la"].startswith("2025-06-02T06:55")
    assert episodes.iloc[0]["asymmetry_ratio"] != 1.0


def test_no_congestion_returns_no_episode() -> None:
    time = pd.date_range("2025-06-02", periods=288, freq="5min", tz="America/Los_Angeles")
    speed = np.full(288, 63.0)
    episodes, process = detect_speed_episodes(time, speed, free_speed_mph=65.0)
    assert episodes.empty
    assert len(process) == 288


def test_detector_supports_fifteen_minute_sampling() -> None:
    time = pd.date_range("2025-06-02", periods=96, freq="15min", tz="America/Los_Angeles")
    speed = np.full(96, 65.0)
    speed[24:32] = [44, 38, 30, 24, 27, 33, 40, 48]
    episodes, process = detect_speed_episodes(
        time,
        speed,
        free_speed_mph=65.0,
        config=EpisodeDetectionConfig(
            interval_min=15,
            smoothing_bins=1,
            enter_persistence_bins=1,
            exit_persistence_bins=1,
            max_interpolation_gap_bins=1,
            minimum_depth_mph=2.0,
        ),
    )
    assert len(episodes) == 1
    assert len(process) == 96
