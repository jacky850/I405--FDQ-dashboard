"""Mode A and Mode B are the same model under a declared change of coefficient.

    LEGACY_NOMINAL_DC          P = f_d * (D/C)^n
    DECOMPOSED_EFFECTIVE_DMU   P = f_d_tilde * (D/mu)^n

Because `D/mu = (D/C) / k_mu` for constant `k_mu`, the two agree exactly when

    f_d_tilde = f_d * k_mu**n

That identity is the migration. It is checked here rather than asserted in the
module, and the failure mode it guards against is switching `stress_basis`
without migrating the coefficient, which silently rescales every duration.
"""

from __future__ import annotations

import numpy as np
import pytest

from fdqbench.slc_qvdf import (DECOMPOSED_EFFECTIVE_DMU, LEGACY_NOMINAL_DC,
                               SLCLinkParameters, decomposed_coefficient,
                               qvdf_forward, qvdf_inverse_identified)


def link(**over) -> SLCLinkParameters:
    base = dict(link_id="T-001", length_mi=1.2, period_hours=4.0, volume_veh=12000.0,
                free_speed_mph=65.0, cutoff_speed_mph=49.0, capacity_vph=5000.0,
                k_d=1.25, k_mu=0.85, stress_basis="D_over_C",
                f_d_h=5.0, n=1.10, f_p=0.24, s=1.40, T2_h=8.0)
    base.update(over)
    return SLCLinkParameters(**base)


K_MU_VALUES = [1.0, 0.95, 0.85, 0.72, 0.5]
N_VALUES = [1.0, 1.10, 1.25, 2.0]


@pytest.mark.parametrize("k_mu", K_MU_VALUES)
@pytest.mark.parametrize("n", N_VALUES)
def test_coefficient_identity_makes_the_modes_agree(k_mu, n):
    """The whole point: migrate f_d and the duration is unchanged."""
    legacy = link(k_mu=k_mu, n=n)
    migrated = link(k_mu=k_mu, n=n, f_d_h=decomposed_coefficient(legacy.f_d_h, k_mu, n))

    a = qvdf_forward(legacy, mode=LEGACY_NOMINAL_DC)
    b = qvdf_forward(migrated, mode=DECOMPOSED_EFFECTIVE_DMU)

    assert b["P"] == pytest.approx(a["P"], rel=1e-12)
    assert b["z"] == pytest.approx(a["z"], rel=1e-12)
    assert b["vT2"] == pytest.approx(a["vT2"], rel=1e-12)
    assert b["queue_delay_vht"] == pytest.approx(a["queue_delay_vht"], rel=1e-12)


@pytest.mark.parametrize("k_mu", K_MU_VALUES)
def test_the_two_modes_use_different_ratios(k_mu):
    legacy = qvdf_forward(link(k_mu=k_mu), mode=LEGACY_NOMINAL_DC)
    decomposed = qvdf_forward(link(k_mu=k_mu), mode=DECOMPOSED_EFFECTIVE_DMU)
    assert legacy["stress_ratio"] == "D_over_C"
    assert decomposed["stress_ratio"] == "D_over_mu"
    assert decomposed["x"] == pytest.approx(legacy["x"] / k_mu, rel=1e-12)


def test_both_ratios_are_reported_whichever_mode_ran():
    """The mode picks which ratio drives P; both still exist and are named."""
    for mode in (LEGACY_NOMINAL_DC, DECOMPOSED_EFFECTIVE_DMU):
        state = qvdf_forward(link(), mode=mode)
        assert state["dc_nominal"] == pytest.approx(
            state["peak_demand_rate_D_vph"] / state["nominal_capacity_C_vph"], rel=1e-12)
        assert state["dmu_effective"] == pytest.approx(
            state["peak_demand_rate_D_vph"] / state["effective_discharge_mu_vph"], rel=1e-12)
        assert state["mode"] == mode


def test_at_kmu_one_the_modes_coincide_without_migration():
    """k_mu = 1 means C and mu are the same number, so nothing to migrate."""
    lk = link(k_mu=1.0)
    assert decomposed_coefficient(lk.f_d_h, 1.0, lk.n) == pytest.approx(lk.f_d_h)
    a = qvdf_forward(lk, mode=LEGACY_NOMINAL_DC)
    b = qvdf_forward(lk, mode=DECOMPOSED_EFFECTIVE_DMU)
    for key in ["x", "P", "z", "vT2", "queue_delay_vht", "total_vht"]:
        assert b[key] == pytest.approx(a[key], rel=1e-12), key


@pytest.mark.parametrize("k_mu", [0.95, 0.85, 0.72])
def test_switching_the_ratio_without_migrating_is_not_neutral(k_mu):
    """Why `stress_basis` alone is not a migration mechanism.

    Same coefficient, different ratio: the duration changes by k_mu**-n. This is
    the silent rescaling the mode split exists to prevent.
    """
    lk = link(k_mu=k_mu)
    on_dc = qvdf_forward(lk, mode=LEGACY_NOMINAL_DC)
    on_dmu = qvdf_forward(link(k_mu=k_mu, stress_basis="D_over_mu"), mode=LEGACY_NOMINAL_DC)
    assert on_dmu["P"] == pytest.approx(on_dc["P"] * k_mu ** -lk.n, rel=1e-12)
    assert on_dmu["P"] > on_dc["P"]


@pytest.mark.parametrize("mode", [LEGACY_NOMINAL_DC, DECOMPOSED_EFFECTIVE_DMU])
def test_forward_inverse_round_trips_in_either_mode(mode):
    lk = link()
    state = qvdf_forward(lk, mode=mode)
    back = qvdf_inverse_identified(lk, state["P"], state["vT2"], mode=mode)
    assert back["V_hat"] == pytest.approx(lk.volume_veh, rel=1e-10)
    assert back["D_hat"] == pytest.approx(state["D"], rel=1e-10)
    assert back["x_hat"] == pytest.approx(state["x"], rel=1e-10)
    assert back["f_p_hat"] == pytest.approx(lk.f_p, rel=1e-10)
    assert back["mode"] == mode


def test_an_unknown_mode_is_refused():
    with pytest.raises(ValueError, match="mode must be one of"):
        qvdf_forward(link(), mode="D_over_something")


def test_an_unknown_stress_basis_is_still_refused():
    with pytest.raises(ValueError, match="stress_basis"):
        qvdf_forward(link(stress_basis="nonsense"), mode=LEGACY_NOMINAL_DC)


def test_decomposed_mode_ignores_stress_basis():
    """Mode B fixes the ratio at D/mu; a stale stress_basis must not leak in."""
    a = qvdf_forward(link(stress_basis="D_over_C"), mode=DECOMPOSED_EFFECTIVE_DMU)
    b = qvdf_forward(link(stress_basis="D_over_mu"), mode=DECOMPOSED_EFFECTIVE_DMU)
    assert a["P"] == pytest.approx(b["P"], rel=1e-12)
    assert a["stress_ratio"] == b["stress_ratio"] == "D_over_mu"
