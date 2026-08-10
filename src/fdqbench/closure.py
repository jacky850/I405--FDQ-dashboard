"""Single-link backward/forward closure utilities.

The backward direction starts from a speed profile and constructs a
speed-derived arrival-flow profile, a supplied/estimated service profile, and
the resulting fluid queue.  The forward direction inverts the same S3 FD on a
declared free or congested branch to reconstruct speed from flow.

This module is deliberately small and explicit.  It is a validation utility;
it does not replace the mentor's final QVDF implementation.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Sequence

import numpy as np
import pandas as pd
from scipy.optimize import brentq

from .fd import S3FD
from .metrics import regression_metrics
from .queue import fluid_queue


@dataclass(frozen=True)
class ClosureSummary:
    """Period-independent summary of a closure run."""

    observed_volume_veh: float
    inferred_volume_veh: float
    volume_error_veh: float
    volume_error_pct: float
    congestion_duration_h: float
    t2_index: int | None


def _as_float_array(values: Sequence[float] | pd.Series) -> np.ndarray:
    return np.asarray(values, dtype=float)


def _s3_speed_from_flow_per_lane(
    flow_vehphpl: float,
    fd: S3FD,
    branch: str = "free",
) -> float:
    """Invert S3 flow on one explicitly selected density branch."""

    q = float(flow_vehphpl)
    if not np.isfinite(q):
        return np.nan
    if q < 0:
        return np.nan
    capacity = float(fd.capacity_vehphpl)
    if q > capacity:
        # A flow above the fitted S3 capacity cannot be inverted.  Return the
        # capacity speed and let the caller retain the clipping flag.
        q = capacity
    if q == 0:
        return float(fd.free_speed_mph if branch == "free" else 0.0)

    kc = float(fd.critical_density_vehpmipl)
    # A finite upper bracket is enough because S3 flow tends to zero at high
    # density.  Expanding it protects unusual parameterizations.
    hi = max(kc * 2.0, kc)
    while fd.flow_from_density(hi) > q and hi < 1e6:
        hi *= 2.0
    if branch == "free":
        lo, upper = 0.0, kc
    elif branch == "congested":
        lo, upper = kc, hi
    else:
        raise ValueError("branch must be 'free' or 'congested'")
    density = float(brentq(lambda k: float(fd.flow_from_density(k)) - q, lo, upper))
    return float(fd.speed_from_density(density))


def reconstruct_speed_from_flow(
    flow_vehph: Sequence[float] | pd.Series,
    fd: S3FD,
    lanes: float = 1.0,
    branch: Sequence[str] | str = "free",
) -> pd.DataFrame:
    """Reconstruct speed from flow using the S3 model and a branch label.

    Flow alone is not sufficient to identify speed near/below capacity because
    the S3 FD has a free-flow and a congested branch.  The branch must
    therefore be supplied or derived from an observed speed profile during
    validation.
    """

    q = _as_float_array(flow_vehph)
    branches = [branch] * len(q) if isinstance(branch, str) else list(branch)
    if len(branches) != len(q):
        raise ValueError("branch must have the same length as flow_vehph")
    speeds = []
    clipped = []
    for value, state in zip(q, branches):
        qpl = value / float(lanes)
        clipped.append(bool(np.isfinite(qpl) and qpl > fd.capacity_vehphpl))
        speeds.append(_s3_speed_from_flow_per_lane(qpl, fd, state))
    return pd.DataFrame({
        "speed_reconstructed_mph": speeds,
        "s3_branch": branches,
        "flow_clipped_to_capacity": clipped,
    })


def backward_closure(
    profile: pd.DataFrame,
    fd: S3FD,
    mu_by_period: Mapping[str, float] | None = None,
    lanes: float = 1.0,
    dt_minutes: float = 5.0,
    speed_col: str = "speed_mph",
    observed_flow_col: str = "flow_observed_vehph",
    period_col: str = "period",
    initial_queue_veh: float = 0.0,
) -> tuple[pd.DataFrame, ClosureSummary]:
    """Build the first backward closure from a speed profile.

    ``lambda_speed_vehph`` is the S3 speed-derived arrival profile.  ``mu`` is
    intentionally supplied by period because service rate is not identifiable
    from free-flow speed alone.  If observed flow is present, it is retained
    solely for ground-truth validation and volume-error calculation.
    """

    required = {speed_col, period_col}
    missing = required - set(profile.columns)
    if missing:
        raise ValueError(f"profile is missing columns: {sorted(missing)}")
    d = profile.copy().reset_index(drop=True)
    speed = _as_float_array(d[speed_col])
    d["flow_inferred_vehph"] = fd.flow_from_speed(speed) * float(lanes)
    d["lambda_speed_vehph"] = d["flow_inferred_vehph"]
    mu_by_period = mu_by_period or {}
    d["mu_vehph"] = d[period_col].map(mu_by_period).astype(float)
    if d["mu_vehph"].isna().any():
        missing_periods = sorted(d.loc[d["mu_vehph"].isna(), period_col].astype(str).unique())
        raise ValueError(f"mu_by_period is missing periods: {missing_periods}")

    fq = fluid_queue(d["lambda_speed_vehph"], d["mu_vehph"], dt_minutes / 60.0, initial_queue_veh)
    for col in fq.columns:
        d[col] = fq[col].to_numpy()
    d["congested_by_speed"] = speed < float(fd.critical_speed_mph)
    d["dt_hours"] = float(dt_minutes) / 60.0
    d["volume_inferred_interval_veh"] = d["flow_inferred_vehph"] * d["dt_hours"]
    d["volume_observed_interval_veh"] = np.nan
    if observed_flow_col in d.columns:
        d["volume_observed_interval_veh"] = d[observed_flow_col].astype(float) * d["dt_hours"]

    t2_index = int(np.nanargmin(speed)) if len(speed) else None
    duration_h = float(d["congested_by_speed"].sum() * float(dt_minutes) / 60.0)
    observed_volume = float(d["volume_observed_interval_veh"].sum()) if d["volume_observed_interval_veh"].notna().any() else np.nan
    inferred_volume = float(d["volume_inferred_interval_veh"].sum())
    error = inferred_volume - observed_volume if np.isfinite(observed_volume) else np.nan
    error_pct = 100.0 * error / observed_volume if np.isfinite(observed_volume) and observed_volume else np.nan
    summary = ClosureSummary(observed_volume, inferred_volume, error, error_pct, duration_h, t2_index)
    return d, summary


def closure_speed_metrics(profile: pd.DataFrame, observed_speed_col: str = "speed_mph") -> dict:
    """Return speed reconstruction metrics for a completed forward run."""

    if observed_speed_col not in profile or "speed_reconstructed_mph" not in profile:
        raise ValueError("profile must contain observed and reconstructed speed columns")
    return regression_metrics(profile[observed_speed_col], profile["speed_reconstructed_mph"])
