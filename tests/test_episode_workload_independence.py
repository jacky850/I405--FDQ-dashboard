"""A conservation closure cannot be reported as a held-out duration prediction.

When an episode's workload is built as `D_Q = mu_e * P` from that same episode's
observed duration, pushing `D_Q` back through the duration branch returns `P`
exactly. Nothing was predicted. The arithmetic below demonstrates the identity
rather than describing it, so the reason the gate exists is visible in the test
file and not only in prose.

The rule: `episode_workload_source == CONSERVATION_FROM_OBSERVED_P` forces
`duration_validation_status == NOT_INDEPENDENT_DIAGNOSTIC_CLOSURE`.
"""

from __future__ import annotations

import pytest

from fdqbench.validation import (HELD_OUT, NOT_INDEPENDENT, Status,
                                 WorkloadSource, combine,
                                 duration_validation_status,
                                 gate_data_evidence, gate_episode_independence,
                                 gate_retention)

COMPLETE_EVIDENCE = dict(detector_id="1201497", lanes=4, observed_mask_available=True,
                         time_basis="America/Los_Angeles", units_declared=True)


# --------------------------------------------------- the identity being guarded

def test_workload_from_observed_P_round_trips_by_construction():
    """`D_Q = mu_e * P` inverted through `P = D_Q / mu_e` returns P. Always.

    No model quality is involved. This is why such a round trip cannot be quoted
    as a duration prediction, however small its error.
    """
    for observed_P_h, mu_e_vph in [(2.5, 1800.0), (4.0, 2000.0), (0.75, 1650.0)]:
        workload = mu_e_vph * observed_P_h          # built from the observed P
        recovered_P = workload / mu_e_vph           # the "prediction"
        assert recovered_P == pytest.approx(observed_P_h, rel=1e-15), (
            "the round trip is exact by construction, not by fit")


def test_an_independent_workload_does_not_round_trip_exactly():
    """Contrast: a workload measured upstream carries its own error."""
    observed_P_h, mu_e_vph = 2.5, 1800.0
    measured_workload = 4275.0                       # counted, not derived from P
    recovered_P = measured_workload / mu_e_vph
    assert recovered_P != pytest.approx(observed_P_h, rel=1e-6)
    assert recovered_P == pytest.approx(2.375, rel=1e-9)


# ------------------------------------------------------------- the status rule

@pytest.mark.parametrize("source,expected", [
    (WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS, HELD_OUT),
    (WorkloadSource.QUEUE_CORRECTED_ARRIVALS, HELD_OUT),
    (WorkloadSource.CONSERVATION_FROM_OBSERVED_P, NOT_INDEPENDENT),
    (WorkloadSource.MODEL_INFERRED, NOT_INDEPENDENT),
])
def test_the_source_decides_the_duration_validation_status(source, expected):
    assert duration_validation_status(source) == expected


def test_the_required_status_string_is_exactly_as_specified():
    assert NOT_INDEPENDENT == "NOT_INDEPENDENT_DIAGNOSTIC_CLOSURE"


def test_the_status_rule_accepts_the_bare_string_too():
    assert duration_validation_status("CONSERVATION_FROM_OBSERVED_P") == NOT_INDEPENDENT


def test_an_unknown_source_is_refused_rather_than_defaulted():
    with pytest.raises(ValueError):
        duration_validation_status("SOMEWHERE")


# ------------------------------------------------------------------- the gate

def test_an_independent_workload_passes_the_gate():
    result = gate_episode_independence(
        workload_source=WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)
    assert result.status is Status.PASS


def test_a_workload_from_the_observed_duration_is_flagged():
    result = gate_episode_independence(
        workload_source=WorkloadSource.CONSERVATION_FROM_OBSERVED_P)
    assert result.status is Status.REVIEW
    assert result.reason_code == "WORKLOAD_FROM_OBSERVED_DURATION"
    assert "not a prediction" in result.detail


def test_a_model_inferred_workload_is_flagged():
    result = gate_episode_independence(workload_source=WorkloadSource.MODEL_INFERRED)
    assert result.reason_code == "WORKLOAD_MODEL_INFERRED"


# ------------------------------------------------- what the verdict then says

def build(source):
    return combine(
        [gate_data_evidence(**COMPLETE_EVIDENCE),
         gate_retention(k_mu=0.85),
         gate_episode_independence(workload_source=source)],
        workload_source=source)


def test_a_closure_is_reviewable_but_never_physical():
    verdict = build(WorkloadSource.CONSERVATION_FROM_OBSERVED_P)
    assert verdict.status is Status.REVIEW
    assert verdict.is_physical is False
    assert verdict.duration_validation_status == NOT_INDEPENDENT


def test_an_independent_case_is_physical_and_held_out():
    verdict = build(WorkloadSource.OBSERVED_UPSTREAM_ARRIVALS)
    assert verdict.status is Status.PASS
    assert verdict.is_physical is True
    assert verdict.duration_validation_status == HELD_OUT


def test_the_verdict_row_carries_the_circularity_flag():
    row = build(WorkloadSource.CONSERVATION_FROM_OBSERVED_P).as_row()
    assert row["duration_validation_status"] == NOT_INDEPENDENT
    assert row["is_physical"] is False
    assert row["reason_episode_independence"] == "WORKLOAD_FROM_OBSERVED_DURATION"


def test_every_workload_source_in_the_vocabulary_is_handled():
    """A new source must not silently inherit `HELD_OUT`."""
    for source in WorkloadSource:
        status = duration_validation_status(source)
        assert status in (HELD_OUT, NOT_INDEPENDENT), source


def test_the_workload_source_has_no_default():
    """Forgetting to classify a case must not award it the permissive answer.

    Any usable default would be an independent source, so an unclassified case
    would silently come out as HELD_OUT_PREDICTION. The argument is required.
    """
    with pytest.raises(TypeError, match="workload_source"):
        combine([gate_retention(k_mu=0.9)])
