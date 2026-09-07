"""Each gate returns the status and reason code the plan specifies.

Every case ends in PASS / REVIEW / FAIL / INSUFFICIENT_DATA with a reason code,
and the aggregate takes the worst. The distinction these tests defend hardest is
INSUFFICIENT_DATA against FAIL: nothing was violated when evidence is missing,
and pooling the two miscounts attrition.
"""

from __future__ import annotations

import math

import pytest

from fdqbench.validation import (CAPACITY_FLOOR_VPHPL, CAPACITY_REVIEW_VPHPL,
                                 SPEED_MAE_LIMIT_MPH, DischargeSource, Status,
                                 WorkloadSource, combine, gate_capacity_basis,
                                 gate_capacity_plausibility, gate_conservation,
                                 gate_data_evidence, gate_duration_exponent,
                                 gate_episode_independence, gate_queue_state,
                                 gate_retention, gate_retention_monotonicity,
                                 gate_speed_profile)

COMPLETE_EVIDENCE = dict(detector_id="1201497", lanes=4, observed_mask_available=True,
                         time_basis="America/Los_Angeles", units_declared=True)


# --------------------------------------------------------------- data evidence

def test_complete_evidence_passes():
    result = gate_data_evidence(**COMPLETE_EVIDENCE)
    assert result.status is Status.PASS
    assert result.reason_code == "OK"


@pytest.mark.parametrize("field", sorted(COMPLETE_EVIDENCE))
def test_any_missing_evidence_is_insufficient_data_not_fail(field):
    kwargs = dict(COMPLETE_EVIDENCE)
    kwargs[field] = None
    result = gate_data_evidence(**kwargs)
    assert result.status is Status.INSUFFICIENT_DATA, (
        "missing evidence means the gate could not be evaluated; it is not a violation")
    assert result.reason_code == "EVIDENCE_MISSING"
    assert field in result.measured["missing"]


# -------------------------------------------------------------- capacity basis

def test_declared_nominal_hourly_basis_passes():
    assert gate_capacity_basis(capacity_basis_declared="per_lane",
                               capacity_kind="nominal_hourly").status is Status.PASS


@pytest.mark.parametrize("basis,kind,code", [
    (None, "nominal_hourly", "CAPACITY_BASIS_AMBIGUOUS"),
    ("per_lane", None, "CAPACITY_BASIS_AMBIGUOUS"),
    ("per_axle", "nominal_hourly", "CAPACITY_BASIS_AMBIGUOUS"),
    ("per_lane", "period_equivalent", "CAPACITY_NOT_NOMINAL_HOURLY"),
    ("per_lane", "effective", "CAPACITY_NOT_NOMINAL_HOURLY"),
])
def test_ambiguous_basis_fails(basis, kind, code):
    result = gate_capacity_basis(capacity_basis_declared=basis, capacity_kind=kind)
    assert result.status is Status.FAIL
    assert result.reason_code == code


# ------------------------------------------------------- capacity plausibility

def test_capacity_inside_the_range_passes():
    assert gate_capacity_plausibility(capacity_vphpl=2000.0).status is Status.PASS


def test_capacity_above_the_range_without_justification_fails():
    result = gate_capacity_plausibility(capacity_vphpl=2600.0)
    assert result.status is Status.FAIL
    assert result.reason_code == "CAPACITY_ABOVE_RANGE_UNJUSTIFIED"


def test_capacity_above_the_range_with_justification_is_review():
    result = gate_capacity_plausibility(
        capacity_vphpl=2600.0, justification="managed lane, measured 2580 on 12 days")
    assert result.status is Status.REVIEW
    assert result.reason_code == "CAPACITY_ABOVE_RANGE_JUSTIFIED"
    assert "managed lane" in result.detail


def test_capacity_below_the_range_is_review():
    result = gate_capacity_plausibility(capacity_vphpl=CAPACITY_FLOOR_VPHPL - 1)
    assert result.status is Status.REVIEW
    assert result.reason_code == "CAPACITY_BELOW_RANGE"


@pytest.mark.parametrize("value", [0.0, -100.0])
def test_non_positive_capacity_fails(value):
    assert gate_capacity_plausibility(capacity_vphpl=value).reason_code == "CAPACITY_NON_POSITIVE"


def test_missing_capacity_is_insufficient_data():
    assert gate_capacity_plausibility(capacity_vphpl=None).status is Status.INSUFFICIENT_DATA


# ------------------------------------------------------------------- retention

@pytest.mark.parametrize("k_mu", [0.5, 0.85, 1.0])
def test_retention_inside_zero_to_one_passes(k_mu):
    assert gate_retention(k_mu=k_mu).status is Status.PASS


@pytest.mark.parametrize("k_mu,code", [
    (0.0, "RETENTION_NON_POSITIVE"),
    (-0.2, "RETENTION_NON_POSITIVE"),
    (1.01, "RETENTION_ABOVE_ONE"),
    (1.5, "RETENTION_ABOVE_ONE"),
])
def test_retention_outside_the_range_fails(k_mu, code):
    result = gate_retention(k_mu=k_mu)
    assert result.status is Status.FAIL
    assert result.reason_code == code


def test_nan_retention_is_insufficient_data():
    assert gate_retention(k_mu=math.nan).status is Status.INSUFFICIENT_DATA


# ----------------------------------------------------------- duration exponent

@pytest.mark.parametrize("n", [1.0, 1.10, 2.0])
def test_exponent_at_or_above_one_passes(n):
    assert gate_duration_exponent(n=n, mode="DECOMPOSED_EFFECTIVE_DMU").status is Status.PASS


@pytest.mark.parametrize("n", [0.99, 0.5, 0.1])
def test_exponent_below_one_is_review_and_diagnostic_only(n):
    result = gate_duration_exponent(n=n, mode="DECOMPOSED_EFFECTIVE_DMU")
    assert result.status is Status.REVIEW
    assert result.reason_code == "EXPONENT_BELOW_ONE"
    assert "diagnostic only" in result.detail


def test_a_sub_linear_exponent_cannot_reach_a_physical_pass():
    """The acceptance criterion: n < 1 must not enter the physical chain."""
    verdict = combine([
        gate_data_evidence(**COMPLETE_EVIDENCE),
        gate_capacity_basis(capacity_basis_declared="per_lane",
                            capacity_kind="nominal_hourly"),
        gate_retention(k_mu=0.85),
        gate_duration_exponent(n=0.8, mode="DECOMPOSED_EFFECTIVE_DMU"),
    ], workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)
    assert verdict.status is Status.REVIEW
    assert verdict.is_physical is False


# ------------------------------------------------------ retention monotonicity

def test_non_increasing_retention_passes():
    result = gate_retention_monotonicity(severity_z=[0.2, 0.5, 0.9, 1.4],
                                         implied_k_mu=[0.95, 0.90, 0.86, 0.80])
    assert result.status is Status.PASS


def test_retention_rising_with_severity_fails():
    result = gate_retention_monotonicity(severity_z=[0.2, 0.5, 0.9],
                                         implied_k_mu=[0.80, 0.86, 0.95])
    assert result.status is Status.FAIL
    assert result.reason_code == "RETENTION_INCREASING"
    assert "rises with severity" in result.detail


def test_monotonicity_is_judged_in_severity_order_not_input_order():
    """Unsorted input must give the same verdict as sorted input."""
    ordered = gate_retention_monotonicity(severity_z=[0.2, 0.5, 0.9],
                                          implied_k_mu=[0.95, 0.90, 0.86])
    shuffled = gate_retention_monotonicity(severity_z=[0.9, 0.2, 0.5],
                                           implied_k_mu=[0.86, 0.95, 0.90])
    assert ordered.status is shuffled.status is Status.PASS


def test_a_single_point_cannot_show_a_trend():
    result = gate_retention_monotonicity(severity_z=[0.5], implied_k_mu=[0.9])
    assert result.status is Status.INSUFFICIENT_DATA


def test_mismatched_series_lengths_fail():
    result = gate_retention_monotonicity(severity_z=[0.1, 0.2], implied_k_mu=[0.9])
    assert result.reason_code == "SERIES_LENGTH_MISMATCH"


# ---------------------------------------------------------------- conservation

def test_conservation_within_tolerance_passes_and_reports_the_residual():
    result = gate_conservation(arrival_workload_veh=1000.0, served_veh=940.0,
                               delta_queue_veh=60.0, tolerance_veh=1.0)
    assert result.status is Status.PASS
    assert result.measured["residual_veh"] == pytest.approx(0.0, abs=1e-12)


def test_conservation_residual_is_reported_not_forced_to_zero():
    """The number is the finding. Nothing zeroes it."""
    result = gate_conservation(arrival_workload_veh=1000.0, served_veh=900.0,
                               delta_queue_veh=60.0, tolerance_veh=1.0)
    assert result.status is Status.FAIL
    assert result.reason_code == "CONSERVATION_RESIDUAL_ABOVE_TOLERANCE"
    assert result.measured["residual_veh"] == pytest.approx(40.0)


def test_conservation_with_a_missing_term_is_insufficient_data():
    assert gate_conservation(arrival_workload_veh=1000.0, served_veh=None,
                             delta_queue_veh=60.0,
                             tolerance_veh=1.0).status is Status.INSUFFICIENT_DATA


# --------------------------------------------------------------- speed profile

def test_speed_mae_within_the_limit_passes():
    result = gate_speed_profile(observed_bin_mae_mph=4.8, observed_bins=120)
    assert result.status is Status.PASS


def test_speed_mae_above_the_limit_without_justification_fails():
    result = gate_speed_profile(observed_bin_mae_mph=SPEED_MAE_LIMIT_MPH + 0.1,
                                observed_bins=120)
    assert result.status is Status.FAIL
    assert result.reason_code == "SPEED_MAE_ABOVE_LIMIT"


def test_speed_mae_above_the_limit_with_justification_is_review():
    result = gate_speed_profile(observed_bin_mae_mph=14.0, observed_bins=120,
                                justification="incident day retained deliberately")
    assert result.status is Status.REVIEW


def test_observed_and_imputed_bins_are_reported_separately():
    result = gate_speed_profile(observed_bin_mae_mph=4.8, observed_bins=120,
                                imputed_bin_mae_mph=19.4, imputed_bins=168)
    assert result.status is Status.PASS, "the imputed MAE must not affect the verdict"
    assert result.measured["imputed_bin_mae_mph"] == 19.4
    assert result.measured["observed_bins"] == 120


def test_an_mae_with_no_observed_bins_behind_it_is_insufficient_data():
    result = gate_speed_profile(observed_bin_mae_mph=3.0, observed_bins=0)
    assert result.status is Status.INSUFFICIENT_DATA
    assert result.reason_code == "NO_OBSERVED_BINS"


# ----------------------------------------------------------------- queue state

def test_a_well_behaved_queue_passes():
    result = gate_queue_state(queue_veh=[0.0, 5.0, 30.0, 12.0, 0.0],
                              period_boundary_indices=[2])
    assert result.status is Status.PASS
    assert result.measured["peak_veh"] == 30.0


def test_a_negative_queue_fails():
    result = gate_queue_state(queue_veh=[0.0, 5.0, -0.4, 1.0])
    assert result.status is Status.FAIL
    assert result.reason_code == "QUEUE_NEGATIVE"


@pytest.mark.parametrize("bad", [math.nan, math.inf, -math.inf])
def test_a_non_finite_queue_fails(bad):
    result = gate_queue_state(queue_veh=[0.0, bad, 1.0])
    assert result.status is Status.FAIL
    assert result.reason_code == "QUEUE_NOT_FINITE"


def test_a_queue_reset_at_a_period_boundary_fails():
    """Vehicles standing at 15:00 do not vanish because the period label changed.

    45 vehicles disappear in one interval on a link that can discharge 25.
    """
    result = gate_queue_state(queue_veh=[0.0, 20.0, 45.0, 0.0, 8.0],
                              period_boundary_indices=[3],
                              service_vph=[100.0] * 5, dt_h=0.25)
    assert result.status is Status.FAIL
    assert result.reason_code == "QUEUE_RESET_AT_PERIOD_BOUNDARY"
    assert "could discharge" in result.detail


def test_a_queue_that_genuinely_drains_at_a_boundary_is_not_a_reset():
    """The same shape, but the link can discharge more than the drop.

    This is the case the first version of this gate got wrong: on the real NVTA
    run it flagged five links draining 0.09 to 55.9 veh against a service
    capacity of 900 to 1500 per interval, every one of them physical.
    """
    result = gate_queue_state(queue_veh=[0.0, 20.0, 45.0, 0.0, 8.0],
                              period_boundary_indices=[3],
                              service_vph=[4000.0] * 5, dt_h=0.25)
    assert result.status is Status.PASS


def test_a_boundary_clearance_without_a_service_rate_cannot_be_judged():
    """No service rate means no way to tell a drain from a reset."""
    result = gate_queue_state(queue_veh=[0.0, 20.0, 45.0, 0.0, 8.0],
                              period_boundary_indices=[3])
    assert result.status is Status.REVIEW
    assert result.reason_code == "QUEUE_CLEARS_AT_BOUNDARY_UNVERIFIED"


def test_a_queue_already_at_zero_before_the_boundary_is_untouched():
    result = gate_queue_state(queue_veh=[0.0, 3.0, 1e-9, 0.0, 0.0],
                              period_boundary_indices=[3],
                              service_vph=[1000.0] * 5, dt_h=0.25)
    assert result.status is Status.PASS


def test_mismatched_queue_and_service_lengths_fail():
    result = gate_queue_state(queue_veh=[0.0, 1.0, 2.0],
                              service_vph=[100.0], dt_h=0.25)
    assert result.reason_code == "SERIES_LENGTH_MISMATCH"


# ------------------------------------------------------------------- aggregate

def all_passing() -> list:
    return [
        gate_data_evidence(**COMPLETE_EVIDENCE),
        gate_capacity_basis(capacity_basis_declared="per_lane", capacity_kind="nominal_hourly"),
        gate_capacity_plausibility(capacity_vphpl=2000.0),
        gate_retention(k_mu=0.85),
        gate_duration_exponent(n=1.10, mode="DECOMPOSED_EFFECTIVE_DMU"),
        gate_queue_state(queue_veh=[0.0, 4.0, 9.0, 2.0]),
    ]


def test_all_gates_passing_gives_a_physical_pass():
    verdict = combine(all_passing(), workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)
    assert verdict.status is Status.PASS
    assert verdict.reason_code == "OK"
    assert verdict.is_physical is True
    assert verdict.duration_validation_status == "HELD_OUT_PREDICTION"


def test_the_worst_status_wins_and_names_the_binding_gate():
    gates = all_passing() + [gate_retention(k_mu=1.4)]
    verdict = combine(gates, workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)
    assert verdict.status is Status.FAIL
    assert verdict.reason_code == "RETENTION_ABOVE_ONE"


def test_insufficient_data_outranks_fail():
    """A case that could not be evaluated is not a case that failed."""
    gates = all_passing() + [gate_retention(k_mu=1.4),
                             gate_capacity_plausibility(capacity_vphpl=None)]
    assert combine(gates, workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS).status is Status.INSUFFICIENT_DATA


def test_every_verdict_carries_a_status_and_a_reason_code_for_each_gate():
    """The acceptance criterion: every row has status and reason code."""
    row = combine(all_passing(),
                  workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS).as_row()
    assert row["status"] == "PASS"
    assert row["reason_code"] == "OK"
    for gate in ["data_evidence", "capacity_basis", "capacity_plausibility",
                 "retention", "duration_exponent", "queue_state"]:
        assert row[f"gate_{gate}"] in {s.value for s in Status}
        assert row[f"reason_{gate}"], f"{gate} has no reason code"


def test_combine_refuses_an_empty_gate_list():
    with pytest.raises(ValueError, match="at least one gate"):
        combine([], workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)


def test_gate_lookup_by_name():
    verdict = combine(all_passing(),
                      workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)
    assert verdict.gate("retention").status is Status.PASS
    with pytest.raises(KeyError):
        verdict.gate("nonexistent")


def test_discharge_sources_are_distinct_labels():
    """Measured and inferred mu are never the same evidence."""
    assert DischargeSource.MEASURED_DETECTOR != DischargeSource.INFERRED_FROM_SPEED
    assert len({s.value for s in DischargeSource}) == 3
