"""Per-link and per-lane inputs resolve to the same normalised stress.

The QVDF equations take a ratio, so they cannot tell a per-link volume over a
per-lane capacity from a correctly matched pair. The mismatch is wrong by the
lane count -- a factor of four on a four-lane link -- and still lands on a
plausible-looking number.

`fdqbench.basis.resolve_basis` is the one place that decides. The rule is that
the basis follows the capacity and the volume is converted to match it.
"""

from __future__ import annotations

import pytest

from fdqbench.basis import (EFFECTIVE, NOMINAL_HOURLY, PER_LANE, PER_LINK,
                            PERIOD_EQUIVALENT, BasisError, resolve_basis)

# One four-lane link: 12,000 veh over 4 h, 5,000 veh/h across the section.
LANES = 4
VOLUME_LINK = 12000.0
VOLUME_LANE = VOLUME_LINK / LANES
HOURS = 4.0
CAPACITY_LINK = 5000.0
CAPACITY_LANE = CAPACITY_LINK / LANES


def test_link_volume_with_link_capacity():
    r = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=CAPACITY_LINK, volume_basis=PER_LINK,
                      capacity_basis=PER_LINK, lanes=LANES)
    assert r.basis == PER_LINK
    assert r.qavg_vph == pytest.approx(VOLUME_LINK / HOURS)
    assert r.nominal_capacity_C_vph == pytest.approx(CAPACITY_LINK)


def test_link_volume_with_per_lane_capacity():
    """qavg = V / (lanes * H): the volume is brought onto the capacity's basis."""
    r = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=CAPACITY_LANE, volume_basis=PER_LINK,
                      capacity_basis=PER_LANE, lanes=LANES)
    assert r.basis == PER_LANE
    assert r.qavg_vph == pytest.approx(VOLUME_LINK / (LANES * HOURS))


def test_per_lane_volume_with_per_lane_capacity():
    r = resolve_basis(period_volume_V_veh=VOLUME_LANE, period_hours_H=HOURS,
                      capacity=CAPACITY_LANE, volume_basis=PER_LANE,
                      capacity_basis=PER_LANE, lanes=LANES)
    assert r.basis == PER_LANE
    assert r.qavg_vph == pytest.approx(VOLUME_LANE / HOURS)


def test_all_three_required_cases_give_the_same_normalised_stress():
    """The acceptance criterion. Same road, three input shapes, one D/C."""
    cases = [
        resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=CAPACITY_LINK, volume_basis=PER_LINK,
                      capacity_basis=PER_LINK, lanes=LANES),
        resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=CAPACITY_LANE, volume_basis=PER_LINK,
                      capacity_basis=PER_LANE, lanes=LANES),
        resolve_basis(period_volume_V_veh=VOLUME_LANE, period_hours_H=HOURS,
                      capacity=CAPACITY_LANE, volume_basis=PER_LANE,
                      capacity_basis=PER_LANE, lanes=LANES),
    ]
    reference = cases[0].dc_nominal
    for r in cases:
        assert r.dc_nominal == pytest.approx(reference, rel=1e-12)
        assert r.dmu_effective == pytest.approx(cases[0].dmu_effective, rel=1e-12)


def test_per_lane_volume_with_link_capacity_converts_upward():
    r = resolve_basis(period_volume_V_veh=VOLUME_LANE, period_hours_H=HOURS,
                      capacity=CAPACITY_LINK, volume_basis=PER_LANE,
                      capacity_basis=PER_LINK, lanes=LANES)
    assert r.basis == PER_LINK
    assert r.qavg_vph == pytest.approx(VOLUME_LINK / HOURS)


def test_the_mismatch_this_module_exists_to_prevent():
    """Declaring the wrong basis is off by the lane count, and looks plausible."""
    correct = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                            capacity=CAPACITY_LANE, volume_basis=PER_LINK,
                            capacity_basis=PER_LANE, lanes=LANES)
    mislabelled = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                                capacity=CAPACITY_LANE, volume_basis=PER_LANE,
                                capacity_basis=PER_LANE, lanes=LANES)
    assert mislabelled.dc_nominal == pytest.approx(correct.dc_nominal * LANES)
    assert 0.1 < mislabelled.dc_nominal < 10.0, (
        "the wrong answer is not obviously wrong, which is the point")


def test_kd_scales_demand_but_not_the_average_rate():
    plain = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                          capacity=CAPACITY_LINK)
    peaked = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                           capacity=CAPACITY_LINK, demand_modifier_kd=1.25)
    assert peaked.qavg_vph == pytest.approx(plain.qavg_vph)
    assert peaked.peak_demand_rate_D_vph == pytest.approx(1.25 * plain.qavg_vph)
    assert peaked.dc_nominal == pytest.approx(1.25 * plain.dc_nominal)


def test_plf_is_accepted_as_the_reciprocal_of_kd():
    by_kd = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                          capacity=CAPACITY_LINK, demand_modifier_kd=1.25)
    by_plf = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                           capacity=CAPACITY_LINK, peak_load_factor_plf=0.8)
    assert by_plf.demand_modifier_kd == pytest.approx(by_kd.demand_modifier_kd)
    assert by_plf.peak_demand_rate_D_vph == pytest.approx(by_kd.peak_demand_rate_D_vph)


def test_mu_and_kmu_are_interchangeable_ways_to_say_the_same_thing():
    by_kmu = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                           capacity=CAPACITY_LINK, capacity_retention_kmu=0.85)
    by_mu = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                          capacity=CAPACITY_LINK,
                          effective_discharge_mu_vph=0.85 * CAPACITY_LINK)
    assert by_mu.capacity_retention_kmu == pytest.approx(0.85)
    assert by_mu.effective_discharge_mu_vph == pytest.approx(by_kmu.effective_discharge_mu_vph)
    assert by_mu.dmu_effective == pytest.approx(by_kmu.dmu_effective)


def test_defaults_are_the_neutral_ones():
    r = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=CAPACITY_LINK)
    assert r.demand_modifier_kd == 1.0
    assert r.capacity_retention_kmu == 1.0
    assert r.effective_discharge_mu_vph == pytest.approx(CAPACITY_LINK)
    assert r.dc_nominal == pytest.approx(r.dmu_effective)


def test_an_effective_capacity_is_accepted_on_its_own():
    r = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=4250.0, capacity_kind=EFFECTIVE)
    assert r.capacity_retention_kmu == 1.0
    assert r.effective_discharge_mu_vph == pytest.approx(4250.0)


def test_as_dict_round_trips_every_field():
    r = resolve_basis(period_volume_V_veh=VOLUME_LINK, period_hours_H=HOURS,
                      capacity=CAPACITY_LINK, capacity_retention_kmu=0.85,
                      demand_modifier_kd=1.25, lanes=LANES)
    d = r.as_dict()
    for field in ["basis", "lanes", "qavg_vph", "peak_demand_rate_D_vph",
                  "nominal_capacity_C_vph", "effective_discharge_mu_vph",
                  "demand_modifier_kd", "capacity_retention_kmu",
                  "dc_nominal", "dmu_effective"]:
        assert field in d
    assert d["dmu_effective"] == pytest.approx(d["dc_nominal"] / 0.85, rel=1e-12)
