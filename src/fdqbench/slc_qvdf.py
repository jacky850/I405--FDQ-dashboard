"""Canonical single-link QVDF oracle used for mentor-code parity checks.

This module implements the frozen field and unit contract in the mentor SLC
technical report.  It is intentionally separate from the existing S3
speed-to-flow utilities: parity between two implementations of this module's
QVDF equations is a code check, while S3-versus-QVDF is a model comparison.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np


@dataclass(frozen=True)
class SLCLinkParameters:
    link_id: str
    length_mi: float
    period_hours: float
    volume_veh: float
    free_speed_mph: float
    cutoff_speed_mph: float
    capacity_vph: float
    k_d: float
    k_mu: float
    stress_basis: str
    f_d_h: float
    n: float
    f_p: float
    s: float
    T2_h: float


def qvdf_forward(
    link: SLCLinkParameters,
    volume_veh: float | None = None,
) -> dict[str, float]:
    """Evaluate the canonical reduced-form QVDF/fluid-queue forward map."""

    volume = float(link.volume_veh if volume_veh is None else volume_veh)
    demand = float(link.k_d) * volume / float(link.period_hours)
    service = float(link.k_mu) * float(link.capacity_vph)
    if link.stress_basis == "D_over_C":
        stress = demand / float(link.capacity_vph)
    elif link.stress_basis == "D_over_mu":
        stress = demand / service
    else:
        raise ValueError("stress_basis must be 'D_over_C' or 'D_over_mu'")

    duration = float(link.f_d_h) * stress ** float(link.n)
    severity = float(link.f_p) * duration ** float(link.s)
    minimum_speed = float(link.cutoff_speed_mph) / (1.0 + severity)
    onset = float(link.T2_h) - duration / 2.0
    recovery = float(link.T2_h) + duration / 2.0
    free_flow_vht = volume * float(link.length_mi) / float(link.free_speed_mph)
    queue_delay_vht = (
        (8.0 / 15.0)
        * service
        * (float(link.length_mi) / float(link.cutoff_speed_mph))
        * severity
        * duration
    )
    return {
        "V": volume,
        "D": demand,
        "mu": service,
        "x": stress,
        "P": duration,
        "z": severity,
        "vT2": minimum_speed,
        "t0": onset,
        "T2": float(link.T2_h),
        "t3": recovery,
        "TT_T2_h": float(link.length_mi) / minimum_speed,
        "free_flow_vht": free_flow_vht,
        "queue_delay_vht": queue_delay_vht,
        "total_vht": free_flow_vht + queue_delay_vht,
    }


def qvdf_inverse_identified(
    link: SLCLinkParameters,
    congestion_duration_h: float,
    minimum_speed_mph: float,
) -> dict[str, float]:
    """Recover identified states with all non-identifiable inputs frozen."""

    duration = float(congestion_duration_h)
    minimum_speed = float(minimum_speed_mph)
    severity = float(link.cutoff_speed_mph) / minimum_speed - 1.0
    stress = (duration / float(link.f_d_h)) ** (1.0 / float(link.n))
    service = float(link.k_mu) * float(link.capacity_vph)
    if link.stress_basis == "D_over_C":
        demand = stress * float(link.capacity_vph)
    elif link.stress_basis == "D_over_mu":
        demand = stress * service
    else:
        raise ValueError("stress_basis must be 'D_over_C' or 'D_over_mu'")
    volume = float(link.period_hours) * demand / float(link.k_d)
    speed_coefficient = severity / duration ** float(link.s)
    return {
        "z_hat": severity,
        "x_hat": stress,
        "D_hat": demand,
        "V_hat": volume,
        "f_p_hat": speed_coefficient,
    }


def qvdf_episode_profile(
    link: SLCLinkParameters,
    state: dict[str, float],
    clock_time_h: np.ndarray,
) -> tuple[np.ndarray, np.ndarray]:
    """Return episode-local speed and point-queue profiles."""

    time = np.asarray(clock_time_h, dtype=float)
    duration = float(state["P"])
    normalized_time = 2.0 * (time - float(state["T2"])) / duration
    inside = np.abs(normalized_time) <= 1.0
    shape = np.zeros_like(time)
    shape[inside] = (1.0 - normalized_time[inside] ** 2) ** 2
    speed = np.full_like(time, np.nan, dtype=float)
    speed[inside] = float(link.cutoff_speed_mph) / (
        1.0 + float(state["z"]) * shape[inside]
    )
    queue = np.full_like(time, np.nan, dtype=float)
    queue[inside] = (
        float(state["mu"])
        * (float(link.length_mi) / float(link.cutoff_speed_mph))
        * float(state["z"])
        * shape[inside]
    )
    return speed, queue
