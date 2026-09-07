"""Ambiguous or double-counted inputs fail loudly instead of being guessed at.

Each case below is a combination where two inputs disagree, or where a
conversion needs a lane count nobody supplied. Silently picking one and carrying
on is how a capacity gets applied twice or a stress comes out wrong by the lane
count, so `resolve_basis` refuses.

The five refusals the plan requires are the first five tests.
"""

from __future__ import annotations

import pytest

from fdqbench.basis import (EFFECTIVE, NOMINAL_HOURLY, PER_LANE, PER_LINK,
                            PERIOD_EQUIVALENT, BasisError, resolve_basis)

BASE = dict(period_volume_V_veh=12000.0, period_hours_H=4.0)


def test_missing_lane_count_when_converting_link_to_per_lane():
    with pytest.raises(BasisError, match="lanes is required"):
        resolve_basis(**BASE, capacity=1250.0,
                      volume_basis=PER_LINK, capacity_basis=PER_LANE)


def test_missing_lane_count_when_converting_per_lane_to_link():
    with pytest.raises(BasisError, match="lanes is required"):
        resolve_basis(**BASE, capacity=5000.0,
                      volume_basis=PER_LANE, capacity_basis=PER_LINK)


def test_period_equivalent_capacity_is_not_an_hourly_capacity():
    """A vehicle count over the period, divided into a rate, is wrong by H."""
    with pytest.raises(BasisError, match="not a nominal hourly capacity"):
        resolve_basis(**BASE, capacity=20000.0, capacity_kind=PERIOD_EQUIVALENT)


def test_effective_capacity_combined_with_a_capacity_drop():
    """The supplied number is already mu; scaling it again applies the drop twice."""
    with pytest.raises(BasisError, match="already mu"):
        resolve_basis(**BASE, capacity=4250.0, capacity_kind=EFFECTIVE,
                      capacity_retention_kmu=0.85)


def test_conflicting_kd_and_plf():
    with pytest.raises(BasisError, match="k_d must equal 1/plf"):
        resolve_basis(**BASE, capacity=5000.0,
                      demand_modifier_kd=1.25, peak_load_factor_plf=0.9)


def test_conflicting_mu_capacity_and_kmu():
    with pytest.raises(BasisError, match=r"k_mu \* C is"):
        resolve_basis(**BASE, capacity=5000.0,
                      capacity_retention_kmu=0.85, effective_discharge_mu_vph=4000.0)


# --- the agreeing versions of the same combinations are accepted -------------

def test_consistent_kd_and_plf_are_accepted():
    r = resolve_basis(**BASE, capacity=5000.0,
                      demand_modifier_kd=1.25, peak_load_factor_plf=0.8)
    assert r.demand_modifier_kd == pytest.approx(1.25)


def test_consistent_mu_capacity_and_kmu_are_accepted():
    r = resolve_basis(**BASE, capacity=5000.0,
                      capacity_retention_kmu=0.85, effective_discharge_mu_vph=4250.0)
    assert r.effective_discharge_mu_vph == pytest.approx(4250.0)
    assert r.capacity_retention_kmu == pytest.approx(0.85)


def test_effective_capacity_with_kmu_of_one_is_accepted():
    r = resolve_basis(**BASE, capacity=4250.0, capacity_kind=EFFECTIVE,
                      capacity_retention_kmu=1.0)
    assert r.effective_discharge_mu_vph == pytest.approx(4250.0)


# --- range and vocabulary checks --------------------------------------------

@pytest.mark.parametrize("k_mu", [0.0, -0.1, 1.2, 2.0])
def test_capacity_retention_outside_zero_to_one(k_mu):
    with pytest.raises(BasisError, match="0 < k_mu <= 1"):
        resolve_basis(**BASE, capacity=5000.0, capacity_retention_kmu=k_mu)


@pytest.mark.parametrize("lanes", [0, -2])
def test_non_positive_lane_count(lanes):
    with pytest.raises(BasisError, match="lanes must be positive"):
        resolve_basis(**BASE, capacity=1250.0, volume_basis=PER_LINK,
                      capacity_basis=PER_LANE, lanes=lanes)


def test_unknown_basis_name():
    with pytest.raises(BasisError, match="volume_basis must be one of"):
        resolve_basis(**BASE, capacity=5000.0, volume_basis="per_axle")


def test_unknown_capacity_kind():
    with pytest.raises(BasisError, match="capacity_kind must be one of"):
        resolve_basis(**BASE, capacity=5000.0, capacity_kind="whatever")


@pytest.mark.parametrize("kwargs,pattern", [
    (dict(period_hours_H=0.0, capacity=5000.0), "period_hours_H must be positive"),
    (dict(period_hours_H=4.0, capacity=0.0), "capacity must be positive"),
    (dict(period_hours_H=4.0, capacity=5000.0, demand_modifier_kd=0.0),
     "demand_modifier_kd must be positive"),
    (dict(period_hours_H=4.0, capacity=5000.0, peak_load_factor_plf=-1.0),
     "peak_load_factor_plf must be positive"),
])
def test_non_positive_scalars(kwargs, pattern):
    with pytest.raises(BasisError, match=pattern):
        resolve_basis(period_volume_V_veh=12000.0, **kwargs)


def test_every_refusal_is_a_basis_error_not_a_bare_value_error():
    """Callers catch BasisError; nothing should escape as a plain ValueError."""
    with pytest.raises(BasisError):
        resolve_basis(**BASE, capacity=1250.0, capacity_basis=PER_LANE)
    assert issubclass(BasisError, ValueError), (
        "BasisError subclasses ValueError so existing except-clauses still work")
