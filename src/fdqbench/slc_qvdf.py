"""Canonical single-link QVDF oracle used for mentor-code parity checks.

This module implements the frozen field and unit contract in the mentor SLC
technical report.  It is intentionally separate from the existing S3
speed-to-flow utilities: parity between two implementations of this module's
QVDF equations is a code check, while S3-versus-QVDF is a model comparison.

Two duration modes, chosen explicitly
-------------------------------------

    LEGACY_NOMINAL_DC          P = f_d * (D/C)^n
    DECOMPOSED_EFFECTIVE_DMU   P = f_d_tilde * (D/mu)^n

`LEGACY_NOMINAL_DC` reproduces the v0.2 output exactly and is the default. It is
pinned by `tests/gold/slc_qvdf_legacy_v02.json`, which was frozen from the
untouched module before any of this was written.

`DECOMPOSED_EFFECTIVE_DMU` is a separate output path, not a reinterpretation of
the same one: in that mode `f_d_h` carries `f_d_tilde`, a coefficient calibrated
against `D/mu`, and nothing is converted on the fly.

To carry a Mode A calibration across, convert it once with
:func:`decomposed_coefficient`. For constant `k_mu` the two modes then agree
exactly, because `D/mu = (D/C) / k_mu` gives

    f_d_tilde = f_d * k_mu**n

`tests/test_qvdf_mode_transform.py` checks that identity rather than asserting it
here.

`stress_basis` is retained and still selects the ratio, but it is **not** the
migration mechanism: it changes the ratio without changing the coefficient, so
switching it silently rescales P. Pass `mode` instead. See ISSUE 05.

What `k_mu` touches, and why that is frozen
-------------------------------------------

`mu = k_mu * C` is computed on every call and feeds `queue_delay_vht` and the
queue profile **regardless of which duration mode is in use**. On the reference
link that is a 15% difference in `queue_delay_vht` between `k_mu = 0.85` and
`k_mu = 1.0` on a run whose duration came from `D/C`.

That is deliberate and it is **frozen legacy behaviour**, on this reasoning:
`mu` is the physical discharge rate, and the delay a queue imposes depends on
the rate it drains at whatever ratio was used to parameterise the duration. How
the duration is parameterised and what the service rate is are two separate
modelling choices. Mode B changes only the first.

The decision is recorded here rather than made silently, and the golden file
carries both `k_mu = 0.85` and `k_mu = 1.0` cases on both bases so any future
drift in it is visible as a test failure.
"""

from __future__ import annotations

from dataclasses import dataclass

import numpy as np

# Duration modes. See the module docstring.
LEGACY_NOMINAL_DC = "LEGACY_NOMINAL_DC"
DECOMPOSED_EFFECTIVE_DMU = "DECOMPOSED_EFFECTIVE_DMU"
MODES = (LEGACY_NOMINAL_DC, DECOMPOSED_EFFECTIVE_DMU)


def decomposed_coefficient(f_d_h: float, k_mu: float, n: float) -> float:
    """`f_d_tilde = f_d * k_mu**n`, the Mode A -> Mode B coefficient migration.

    Exact for constant `k_mu`: substituting `D/mu = (D/C)/k_mu` into
    `P = f_d_tilde * (D/mu)^n` and matching `P = f_d * (D/C)^n` gives this and
    nothing else.
    """
    return float(f_d_h) * float(k_mu) ** float(n)


def _resolve_stress(link: "SLCLinkParameters", demand: float, service: float,
                    mode: str) -> tuple[float, float, str]:
    """Return (stress, duration coefficient, the ratio's name) for `mode`.

    Mode A keeps `stress_basis` so v0.2 callers behave identically. Mode B fixes
    the ratio at `D/mu`.

    In Mode B, `link.f_d_h` **is** `f_d_tilde` -- the coefficient calibrated
    against `D/mu`. It is not converted here. Converting it automatically would
    make Mode B algebraically identical to Mode A for every input, which is the
    opposite of a separate output path: there would be nothing to calibrate and
    nothing to compare. Use :func:`decomposed_coefficient` to carry a Mode A
    calibration across, then pass the result as `f_d_h`.
    """
    if mode == DECOMPOSED_EFFECTIVE_DMU:
        return demand / service, float(link.f_d_h), "D_over_mu"
    if mode != LEGACY_NOMINAL_DC:
        raise ValueError(f"mode must be one of {MODES}, got {mode!r}")
    if link.stress_basis == "D_over_C":
        return demand / float(link.capacity_vph), float(link.f_d_h), "D_over_C"
    if link.stress_basis == "D_over_mu":
        return demand / service, float(link.f_d_h), "D_over_mu"
    raise ValueError("stress_basis must be 'D_over_C' or 'D_over_mu'")


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
    mode: str = LEGACY_NOMINAL_DC,
) -> dict[str, float]:
    """Evaluate the canonical reduced-form QVDF/fluid-queue forward map.

    `mode` selects the duration branch; see the module docstring. The default
    reproduces v0.2 exactly.
    """

    volume = float(link.volume_veh if volume_veh is None else volume_veh)
    qavg = volume / float(link.period_hours)
    demand = float(link.k_d) * qavg
    service = float(link.k_mu) * float(link.capacity_vph)
    stress, duration_coefficient, ratio_name = _resolve_stress(link, demand, service, mode)

    duration = duration_coefficient * stress ** float(link.n)
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
        # --- explicitly resolved quantities, ISSUE 05 --------------------
        # Named so a reader never has to infer which ratio produced P, nor
        # which basis D and C are on. dc_nominal and dmu_effective are both
        # reported whichever mode ran, because the mode chooses which one
        # drives the duration, not which one exists.
        "mode": mode,
        "stress_ratio": ratio_name,
        "duration_coefficient_h": duration_coefficient,
        "qavg_vph": qavg,
        "peak_demand_rate_D_vph": demand,
        "nominal_capacity_C_vph": float(link.capacity_vph),
        "effective_discharge_mu_vph": service,
        "dc_nominal": demand / float(link.capacity_vph),
        "dmu_effective": demand / service,
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
    mode: str = LEGACY_NOMINAL_DC,
) -> dict[str, float]:
    """Recover identified states with all non-identifiable inputs frozen.

    The exact inverse of :func:`qvdf_forward` under the same `mode`: the ratio
    the duration was inverted through is the one that turns the stress back into
    a demand rate, so a forward/inverse round trip returns the volume it started
    from in either mode.
    """

    duration = float(congestion_duration_h)
    minimum_speed = float(minimum_speed_mph)
    severity = float(link.cutoff_speed_mph) / minimum_speed - 1.0
    service = float(link.k_mu) * float(link.capacity_vph)

    # Invert with the same coefficient and the same ratio the forward map used.
    # Passing a demand of 1.0 asks _resolve_stress only which ratio and which
    # coefficient apply; the value is discarded.
    _, duration_coefficient, ratio_name = _resolve_stress(link, 1.0, service, mode)
    stress = (duration / duration_coefficient) ** (1.0 / float(link.n))
    denominator = float(link.capacity_vph) if ratio_name == "D_over_C" else service
    demand = stress * denominator

    volume = float(link.period_hours) * demand / float(link.k_d)
    speed_coefficient = severity / duration ** float(link.s)
    return {
        "z_hat": severity,
        "x_hat": stress,
        "D_hat": demand,
        "V_hat": volume,
        "f_p_hat": speed_coefficient,
        "mode": mode,
        "stress_ratio": ratio_name,
        "duration_coefficient_h": duration_coefficient,
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
