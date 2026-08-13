"""Robust speed-only congestion-episode detection.

The detector uses a local-time speed series, persistent entry/recovery rules,
hysteresis, short-gap interpolation, and independent observed t0/T2/t3.  It
does not assume that T2 is the midpoint of the episode and does not consume
flow, demand, or queue fields.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np
import pandas as pd


@dataclass(frozen=True)
class EpisodeDetectionConfig:
    interval_min: int = 5
    smoothing_bins: int = 3
    enter_ratio: float = 0.70
    exit_ratio: float = 0.75
    enter_persistence_bins: int = 3
    exit_persistence_bins: int = 3
    max_interpolation_gap_bins: int = 2
    minimum_duration_min: float = 20.0
    minimum_depth_mph: float = 3.0


def _interpolated_crossing(
    t_left: pd.Timestamp,
    v_left: float,
    t_right: pd.Timestamp,
    v_right: float,
    threshold: float,
) -> pd.Timestamp:
    if not np.isfinite(v_left) or not np.isfinite(v_right) or v_left == v_right:
        return t_right
    fraction = float(np.clip((threshold - v_left) / (v_right - v_left), 0.0, 1.0))
    return t_left + (t_right - t_left) * fraction


def _persistent(mask: np.ndarray, start: int, count: int) -> bool:
    stop = start + count
    return stop <= len(mask) and bool(np.all(mask[start:stop]))


def _period_of(timestamp: pd.Timestamp) -> str:
    hour = timestamp.hour + timestamp.minute / 60.0
    if 0 <= hour < 6:
        return "NT1"
    if 6 <= hour < 9:
        return "AM"
    if 9 <= hour < 15:
        return "MD"
    if 15 <= hour < 19:
        return "PM"
    return "NT2"


def detect_speed_episodes(
    timestamps: pd.Series | pd.DatetimeIndex,
    speed_mph: pd.Series | np.ndarray,
    free_speed_mph: float,
    config: EpisodeDetectionConfig | None = None,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Detect asymmetric episodes and return episode and process tables."""

    cfg = config or EpisodeDetectionConfig()
    time = pd.DatetimeIndex(pd.to_datetime(timestamps))
    if time.tz is None:
        raise ValueError("timestamps must be timezone-aware local timestamps")
    raw = pd.Series(np.asarray(speed_mph, dtype=float), index=time).sort_index()
    if raw.index.has_duplicates:
        raw = raw.groupby(level=0).mean()
    if raw.empty:
        return pd.DataFrame(), pd.DataFrame()

    full_index = pd.date_range(
        raw.index.min().normalize(),
        raw.index.max().normalize() + pd.Timedelta(days=1) - pd.Timedelta(minutes=cfg.interval_min),
        freq=f"{cfg.interval_min}min",
        tz=raw.index.tz,
    )
    raw = raw.reindex(full_index)
    short_gap_filled = raw.interpolate(
        method="time",
        limit=cfg.max_interpolation_gap_bins,
        limit_area="inside",
    )
    smoothed = short_gap_filled.rolling(
        cfg.smoothing_bins,
        center=True,
        min_periods=1 if cfg.smoothing_bins == 1 else max(2, cfg.smoothing_bins - 1),
    ).median()
    enter_threshold = float(free_speed_mph) * cfg.enter_ratio
    exit_threshold = float(free_speed_mph) * cfg.exit_ratio
    enter_mask = (smoothed <= enter_threshold).fillna(False).to_numpy()
    exit_mask = (smoothed >= exit_threshold).fillna(False).to_numpy()
    speed_values = smoothed.to_numpy(dtype=float)
    raw_values = raw.to_numpy(dtype=float)
    episodes: list[dict[str, object]] = []
    i = 0
    while i < len(full_index):
        if not _persistent(enter_mask, i, cfg.enter_persistence_bins):
            i += 1
            continue
        onset_index = i
        if onset_index > 0 and np.isfinite(speed_values[onset_index - 1]):
            t0 = _interpolated_crossing(
                full_index[onset_index - 1],
                speed_values[onset_index - 1],
                full_index[onset_index],
                speed_values[onset_index],
                enter_threshold,
            )
            left_censored = False
        else:
            t0 = full_index[onset_index]
            left_censored = True

        recovery_index: int | None = None
        j = onset_index + cfg.enter_persistence_bins
        while j < len(full_index):
            if _persistent(exit_mask, j, cfg.exit_persistence_bins):
                recovery_index = j
                break
            j += 1
        if recovery_index is None:
            final_index = len(full_index) - 1
            t3 = full_index[final_index] + pd.Timedelta(minutes=cfg.interval_min)
            right_censored = True
            next_index = len(full_index)
        else:
            final_index = max(onset_index, recovery_index - 1)
            if final_index < recovery_index and np.isfinite(speed_values[final_index]):
                t3 = _interpolated_crossing(
                    full_index[final_index],
                    speed_values[final_index],
                    full_index[recovery_index],
                    speed_values[recovery_index],
                    exit_threshold,
                )
            else:
                t3 = full_index[recovery_index]
            right_censored = False
            next_index = recovery_index + cfg.exit_persistence_bins

        episode_slice = slice(onset_index, final_index + 1)
        local_smooth = speed_values[episode_slice]
        local_raw = raw_values[episode_slice]
        if not np.isfinite(local_smooth).any():
            i = max(i + 1, next_index)
            continue
        robust_offset = int(np.nanargmin(local_smooth))
        robust_index = onset_index + robust_offset
        t2 = full_index[robust_index]
        robust_min = float(speed_values[robust_index])
        raw_at_t2 = float(raw_values[robust_index]) if np.isfinite(raw_values[robust_index]) else np.nan
        if np.isfinite(local_raw).any():
            raw_offset = int(np.nanargmin(local_raw))
            raw_min_index = onset_index + raw_offset
            raw_t2 = full_index[raw_min_index]
            raw_min = float(raw_values[raw_min_index])
        else:
            raw_t2 = pd.NaT
            raw_min = np.nan

        duration_min = (t3 - t0).total_seconds() / 60.0
        depth_mph = enter_threshold - robust_min
        missing_bins = int(raw.iloc[episode_slice].isna().sum())
        accepted = duration_min >= cfg.minimum_duration_min and depth_mph >= cfg.minimum_depth_mph
        if accepted:
            onset_to_t2 = (t2 - t0).total_seconds() / 3600.0
            t2_to_recovery = (t3 - t2).total_seconds() / 3600.0
            asymmetry = onset_to_t2 / t2_to_recovery if t2_to_recovery > 0 else np.nan
            flags = []
            if left_censored:
                flags.append("left_censored")
            if right_censored:
                flags.append("right_censored")
            if missing_bins:
                flags.append("missing_inside")
            if abs((raw_t2 - t2).total_seconds()) > cfg.interval_min * 60 if pd.notna(raw_t2) else False:
                flags.append("raw_robust_t2_disagree")
            episodes.append(
                {
                    "episode_id": f"E{len(episodes) + 1}",
                    "t0_la": t0.isoformat(),
                    "T2_la": t2.isoformat(),
                    "t3_la": t3.isoformat(),
                    "P_h": duration_min / 60.0,
                    "onset_to_T2_h": onset_to_t2,
                    "T2_to_recovery_h": t2_to_recovery,
                    "asymmetry_ratio": asymmetry,
                    "vT2_robust_mph": robust_min,
                    "speed_raw_at_robust_T2_mph": raw_at_t2,
                    "T2_raw_la": raw_t2.isoformat() if pd.notna(raw_t2) else "",
                    "vT2_raw_min_mph": raw_min,
                    "free_speed_p95_mph": float(free_speed_mph),
                    "enter_threshold_mph": enter_threshold,
                    "exit_threshold_mph": exit_threshold,
                    "period_by_T2": _period_of(t2),
                    "cross_period": _period_of(t0) != _period_of(t3 - pd.Timedelta(microseconds=1)),
                    "missing_bins_inside": missing_bins,
                    "quality_status": "accepted" if not flags else "accepted_with_flags",
                    "quality_flags": ";".join(flags),
                    "detection_source": "speed_only",
                }
            )
        i = max(i + 1, next_index)

    process = pd.DataFrame(
        {
            "timestamp_la": full_index,
            "speed_raw_mph": raw.to_numpy(),
            "speed_short_gap_filled_mph": short_gap_filled.to_numpy(),
            "speed_smoothed_mph": smoothed.to_numpy(),
            "enter_threshold_mph": enter_threshold,
            "exit_threshold_mph": exit_threshold,
        }
    )
    return pd.DataFrame(episodes), process
