"""Gates that decide whether a case may be reported as a physical result.

Every case ends in one of four statuses and carries a reason code, not free
text, so a reviewer can filter and count without reading prose:

    PASS               every gate satisfied; may enter the physical chain
    REVIEW             something is outside the declared range but defensible
    FAIL               a physical or basis violation; not a physical result
    INSUFFICIENT_DATA  a gate could not be evaluated at all

The four are ordered. A case takes the worst status any of its gates returned,
and the reason code of the gate that bound it.

Two distinctions this module exists to keep
-------------------------------------------

**Physical against diagnostic.** A diagnostic number is one the model reproduces
because it was told the answer. It is not wrong, and it is not a prediction. The
clearest case here: when an episode's workload is computed as `mu_e * P` from the
*same* episode's observed duration, feeding it back through the duration branch
returns that duration by construction. That is a conservation closure and this
module refuses to let it be labelled a held-out prediction.

**Measured against inferred `mu`.** A discharge rate counted at a detector and
one recovered from speed through a fundamental diagram are different evidence.
They are labelled separately and never pooled into one sample size.

See docs/IDENTIFIABILITY_AND_GATES.md.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from enum import Enum
from typing import Iterable, Sequence


class Status(str, Enum):
    PASS = "PASS"
    REVIEW = "REVIEW"
    FAIL = "FAIL"
    INSUFFICIENT_DATA = "INSUFFICIENT_DATA"


# Worst-first. A case takes the highest-ranked status any gate returned.
_SEVERITY = {
    Status.INSUFFICIENT_DATA: 3,
    Status.FAIL: 2,
    Status.REVIEW: 1,
    Status.PASS: 0,
}


class WorkloadSource(str, Enum):
    """Where an episode's arrival/processed workload `D_Q` came from."""

    OBSERVED_UPSTREAM_ARRIVALS = "OBSERVED_UPSTREAM_ARRIVALS"
    QUEUE_CORRECTED_ARRIVALS = "QUEUE_CORRECTED_ARRIVALS"
    CONSERVATION_FROM_OBSERVED_P = "CONSERVATION_FROM_OBSERVED_P"
    MODEL_INFERRED = "MODEL_INFERRED"


class DischargeSource(str, Enum):
    """How `mu` was obtained. Never pooled into one sample size."""

    MEASURED_DETECTOR = "MEASURED_DETECTOR"
    INFERRED_FROM_SPEED = "INFERRED_FROM_SPEED"
    ASSUMED_CAPACITY = "ASSUMED_CAPACITY"


#: Duration validation is not independent when the workload came from the same
#: episode's observed clearance time.
NOT_INDEPENDENT = "NOT_INDEPENDENT_DIAGNOSTIC_CLOSURE"
HELD_OUT = "HELD_OUT_PREDICTION"

#: Above this, a per-lane capacity needs a documented justification.
CAPACITY_REVIEW_VPHPL = 2400.0
#: Below this, a per-lane capacity is not a freeway mainline number.
CAPACITY_FLOOR_VPHPL = 1000.0
#: Observed-only speed MAE above this needs a justification.
SPEED_MAE_LIMIT_MPH = 10.0


@dataclass(frozen=True)
class GateResult:
    gate: str
    status: Status
    reason_code: str
    detail: str = ""
    measured: dict = field(default_factory=dict)

    @property
    def blocks_physical(self) -> bool:
        return self.status in (Status.FAIL, Status.INSUFFICIENT_DATA)


@dataclass(frozen=True)
class CaseVerdict:
    status: Status
    reason_code: str
    gates: tuple[GateResult, ...]
    duration_validation_status: str
    is_physical: bool

    def gate(self, name: str) -> GateResult:
        for result in self.gates:
            if result.gate == name:
                return result
        raise KeyError(f"no gate named {name!r}; have {[g.gate for g in self.gates]}")

    def as_row(self) -> dict:
        """One flat record per case, for a CSV a reviewer can filter."""
        row = {
            "status": self.status.value,
            "reason_code": self.reason_code,
            "duration_validation_status": self.duration_validation_status,
            "is_physical": self.is_physical,
        }
        for result in self.gates:
            row[f"gate_{result.gate}"] = result.status.value
            row[f"reason_{result.gate}"] = result.reason_code
        return row


# ----------------------------------------------------------------- the gates

def gate_data_evidence(*, detector_id=None, lanes=None, observed_mask_available=None,
                       time_basis=None, units_declared=None) -> GateResult:
    """Everything needed to interpret the numbers is present.

    Missing evidence is `INSUFFICIENT_DATA`, never `FAIL`: nothing was violated,
    the gate simply could not be evaluated, and the two must not be pooled when
    counting attrition.
    """
    missing = [name for name, value in [
        ("detector_id", detector_id), ("lanes", lanes),
        ("observed_mask_available", observed_mask_available),
        ("time_basis", time_basis), ("units_declared", units_declared),
    ] if value in (None, "", False)]
    if missing:
        return GateResult("data_evidence", Status.INSUFFICIENT_DATA,
                          "EVIDENCE_MISSING",
                          f"missing: {', '.join(missing)}",
                          {"missing": missing})
    return GateResult("data_evidence", Status.PASS, "OK",
                      measured={"lanes": lanes, "time_basis": time_basis})


def gate_capacity_basis(*, capacity_basis_declared: str | None,
                        capacity_kind: str | None) -> GateResult:
    """The capacity must be a declared nominal hourly rate on a named basis.

    An ambiguous basis is a `FAIL`, not a `REVIEW`: the resulting stress is wrong
    by the lane count and there is no way to tell from the number itself.
    """
    if not capacity_basis_declared or not capacity_kind:
        return GateResult("capacity_basis", Status.FAIL, "CAPACITY_BASIS_AMBIGUOUS",
                          "capacity basis or kind not declared")
    if capacity_basis_declared not in ("per_link", "per_lane"):
        return GateResult("capacity_basis", Status.FAIL, "CAPACITY_BASIS_AMBIGUOUS",
                          f"unknown basis {capacity_basis_declared!r}")
    if capacity_kind != "nominal_hourly":
        return GateResult("capacity_basis", Status.FAIL, "CAPACITY_NOT_NOMINAL_HOURLY",
                          f"capacity_kind is {capacity_kind!r}, not a nominal hourly rate")
    return GateResult("capacity_basis", Status.PASS, "OK",
                      measured={"basis": capacity_basis_declared})


def gate_capacity_plausibility(*, capacity_vphpl: float | None,
                               justification: str | None = None) -> GateResult:
    """Within the declared facility range, or justified in writing."""
    if capacity_vphpl is None or not math.isfinite(capacity_vphpl):
        return GateResult("capacity_plausibility", Status.INSUFFICIENT_DATA,
                          "EVIDENCE_MISSING", "no per-lane capacity")
    measured = {"capacity_vphpl": capacity_vphpl}
    if capacity_vphpl <= 0:
        return GateResult("capacity_plausibility", Status.FAIL, "CAPACITY_NON_POSITIVE",
                          f"{capacity_vphpl} veh/h/lane", measured)
    if capacity_vphpl > CAPACITY_REVIEW_VPHPL:
        if justification:
            return GateResult("capacity_plausibility", Status.REVIEW,
                              "CAPACITY_ABOVE_RANGE_JUSTIFIED",
                              f"{capacity_vphpl:.0f} > {CAPACITY_REVIEW_VPHPL:.0f}: "
                              f"{justification}", measured)
        return GateResult("capacity_plausibility", Status.FAIL,
                          "CAPACITY_ABOVE_RANGE_UNJUSTIFIED",
                          f"{capacity_vphpl:.0f} veh/h/lane exceeds "
                          f"{CAPACITY_REVIEW_VPHPL:.0f} with no documented justification",
                          measured)
    if capacity_vphpl < CAPACITY_FLOOR_VPHPL:
        return GateResult("capacity_plausibility", Status.REVIEW, "CAPACITY_BELOW_RANGE",
                          f"{capacity_vphpl:.0f} veh/h/lane is low for a freeway mainline",
                          measured)
    return GateResult("capacity_plausibility", Status.PASS, "OK", measured=measured)


def gate_retention(*, k_mu: float | None) -> GateResult:
    """`0 < k_mu <= 1`. A discharge above nominal capacity is not a drop."""
    if k_mu is None or not math.isfinite(k_mu):
        return GateResult("retention", Status.INSUFFICIENT_DATA, "EVIDENCE_MISSING",
                          "no k_mu")
    measured = {"k_mu": k_mu}
    if k_mu <= 0:
        return GateResult("retention", Status.FAIL, "RETENTION_NON_POSITIVE",
                          f"k_mu = {k_mu}", measured)
    if k_mu > 1.0:
        return GateResult("retention", Status.FAIL, "RETENTION_ABOVE_ONE",
                          f"k_mu = {k_mu} implies discharge above nominal capacity",
                          measured)
    return GateResult("retention", Status.PASS, "OK", measured=measured)


def gate_duration_exponent(*, n: float | None, mode: str) -> GateResult:
    """`n >= 1` for a physical decomposed run.

    `n < 1` is not refused outright -- it may still be a useful fit -- but it is
    diagnostic only and cannot enter the physical discharge chain, because a
    sub-linear duration response means each additional unit of stress adds less
    delay than the last, which no queue does.
    """
    if n is None or not math.isfinite(n):
        return GateResult("duration_exponent", Status.INSUFFICIENT_DATA,
                          "EVIDENCE_MISSING", "no n")
    measured = {"n": n, "mode": mode}
    if n < 1.0:
        return GateResult("duration_exponent", Status.REVIEW, "EXPONENT_BELOW_ONE",
                          f"n = {n} < 1: diagnostic only, not a physical PASS",
                          measured)
    return GateResult("duration_exponent", Status.PASS, "OK", measured=measured)


def gate_retention_monotonicity(*, severity_z: Sequence[float],
                                implied_k_mu: Sequence[float],
                                tolerance: float = 1e-9) -> GateResult:
    """Implied `k_mu(z)` must not increase with severity.

    Retention rising as congestion deepens says the road discharges better the
    worse it gets. That is a `FAIL` for a physical result.
    """
    z = list(severity_z)
    k = list(implied_k_mu)
    if len(z) != len(k):
        return GateResult("retention_monotonicity", Status.FAIL, "SERIES_LENGTH_MISMATCH",
                          f"{len(z)} severities against {len(k)} retentions")
    if len(z) < 2:
        return GateResult("retention_monotonicity", Status.INSUFFICIENT_DATA,
                          "EVIDENCE_MISSING",
                          f"{len(z)} point(s); need at least 2 to see a trend")
    order = sorted(range(len(z)), key=lambda i: z[i])
    rises = [(z[order[i]], k[order[i]], k[order[i + 1]])
             for i in range(len(order) - 1)
             if k[order[i + 1]] > k[order[i]] + tolerance]
    measured = {"points": len(z), "rises": len(rises)}
    if rises:
        first = rises[0]
        return GateResult("retention_monotonicity", Status.FAIL, "RETENTION_INCREASING",
                          f"k_mu rises with severity at z = {first[0]:.4g} "
                          f"({first[1]:.4g} -> {first[2]:.4g}); {len(rises)} rise(s)",
                          measured)
    return GateResult("retention_monotonicity", Status.PASS, "OK", measured=measured)


def gate_conservation(*, arrival_workload_veh: float | None,
                      served_veh: float | None,
                      delta_queue_veh: float | None,
                      tolerance_veh: float) -> GateResult:
    """`D_Q - integral(mu) - delta_Q` within tolerance. The residual is reported.

    The residual is never zeroed by construction: a model that closes because it
    was made to close has not been checked. What is returned is the number.
    """
    inputs = (arrival_workload_veh, served_veh, delta_queue_veh)
    if any(v is None or not math.isfinite(v) for v in inputs):
        return GateResult("conservation", Status.INSUFFICIENT_DATA, "EVIDENCE_MISSING",
                          "arrivals, served or delta-queue missing")
    residual = arrival_workload_veh - served_veh - delta_queue_veh
    measured = {"arrival_workload_veh": arrival_workload_veh,
                "served_veh": served_veh,
                "delta_queue_veh": delta_queue_veh,
                "residual_veh": residual,
                "tolerance_veh": tolerance_veh}
    if abs(residual) > tolerance_veh:
        return GateResult("conservation", Status.FAIL, "CONSERVATION_RESIDUAL_ABOVE_TOLERANCE",
                          f"residual {residual:+.3f} veh exceeds ±{tolerance_veh:.3f}",
                          measured)
    return GateResult("conservation", Status.PASS, "OK",
                      f"residual {residual:+.3f} veh", measured)


def gate_episode_independence(*, workload_source: WorkloadSource | str) -> GateResult:
    """Duration validation is independent only if the workload did not use P or T3.

    `CONSERVATION_FROM_OBSERVED_P` means `D_Q` was built as `mu_e * P` from the
    same episode. Pushing that back through the duration branch returns P by
    construction. It closes; it does not predict.
    """
    source = WorkloadSource(workload_source)
    measured = {"workload_source": source.value}
    if source is WorkloadSource.CONSERVATION_FROM_OBSERVED_P:
        return GateResult("episode_independence", Status.REVIEW,
                          "WORKLOAD_FROM_OBSERVED_DURATION",
                          "D_Q came from the same episode's observed P; duration "
                          "validation is a conservation closure, not a prediction",
                          measured)
    if source is WorkloadSource.MODEL_INFERRED:
        return GateResult("episode_independence", Status.REVIEW,
                          "WORKLOAD_MODEL_INFERRED",
                          "D_Q is a model output; independence depends on what fed it",
                          measured)
    return GateResult("episode_independence", Status.PASS, "OK", measured=measured)


def duration_validation_status(workload_source: WorkloadSource | str) -> str:
    """`NOT_INDEPENDENT_DIAGNOSTIC_CLOSURE` when the workload used the observed P."""
    source = WorkloadSource(workload_source)
    if source in (WorkloadSource.CONSERVATION_FROM_OBSERVED_P,
                  WorkloadSource.MODEL_INFERRED):
        return NOT_INDEPENDENT
    return HELD_OUT


def gate_speed_profile(*, observed_bin_mae_mph: float | None,
                       observed_bins: int | None = None,
                       imputed_bin_mae_mph: float | None = None,
                       imputed_bins: int | None = None,
                       justification: str | None = None) -> GateResult:
    """Scored on observed bins only. Imputed bins are reported, never pooled.

    An MAE computed over filled bins measures the filler, not the model.
    """
    if observed_bin_mae_mph is None or not math.isfinite(observed_bin_mae_mph):
        return GateResult("speed_profile", Status.INSUFFICIENT_DATA, "EVIDENCE_MISSING",
                          "no observed-bin MAE")
    if not observed_bins:
        return GateResult("speed_profile", Status.INSUFFICIENT_DATA, "NO_OBSERVED_BINS",
                          "the MAE has no observed bins behind it")
    measured = {"observed_bin_mae_mph": observed_bin_mae_mph,
                "observed_bins": observed_bins,
                "imputed_bin_mae_mph": imputed_bin_mae_mph,
                "imputed_bins": imputed_bins}
    if observed_bin_mae_mph > SPEED_MAE_LIMIT_MPH:
        if justification:
            return GateResult("speed_profile", Status.REVIEW, "SPEED_MAE_ABOVE_LIMIT_JUSTIFIED",
                              f"{observed_bin_mae_mph:.2f} mph on {observed_bins} observed "
                              f"bins: {justification}", measured)
        return GateResult("speed_profile", Status.FAIL, "SPEED_MAE_ABOVE_LIMIT",
                          f"{observed_bin_mae_mph:.2f} mph on {observed_bins} observed bins "
                          f"exceeds {SPEED_MAE_LIMIT_MPH:.0f} with no justification", measured)
    return GateResult("speed_profile", Status.PASS, "OK", measured=measured)


def gate_queue_state(*, queue_veh: Sequence[float],
                     period_boundary_indices: Iterable[int] = (),
                     service_vph: Sequence[float] | None = None,
                     dt_h: float | None = None,
                     continuity_tolerance_veh: float = 1e-6) -> GateResult:
    """Non-negative, finite, and continuous across a period boundary.

    A queue that resets at 09:00 or 15:00 is a reporting artefact, not a road
    emptying itself, and it silently discards the vehicles standing there.

    **A queue reaching zero at a boundary is not by itself a reset.** A link that
    genuinely drains is indistinguishable from one that was reset unless the
    service rate is known: the test is whether the drop exceeds what the link
    could have discharged in that interval, `mu * dt`. Pass `service_vph` and
    `dt_h` to get that test. Without them the check degrades to `REVIEW`, because
    the evidence to decide is absent -- on the real NVTA run the weaker test
    flags five links whose queues drain 0.09 to 55.9 vehicles against a service
    capacity of 900 to 1500 per interval, every one of them physical.
    """
    queue = list(queue_veh)
    if not queue:
        return GateResult("queue_state", Status.INSUFFICIENT_DATA, "EVIDENCE_MISSING",
                          "empty queue series")
    non_finite = [i for i, q in enumerate(queue) if not math.isfinite(q)]
    if non_finite:
        return GateResult("queue_state", Status.FAIL, "QUEUE_NOT_FINITE",
                          f"{len(non_finite)} non-finite value(s), first at index "
                          f"{non_finite[0]}", {"non_finite": len(non_finite)})
    negative = [i for i, q in enumerate(queue) if q < 0.0]
    if negative:
        return GateResult("queue_state", Status.FAIL, "QUEUE_NEGATIVE",
                          f"{len(negative)} negative value(s), first at index "
                          f"{negative[0]} ({queue[negative[0]]:.4g} veh)",
                          {"negative": len(negative)})
    service = list(service_vph) if service_vph is not None else None
    if service is not None and len(service) != len(queue):
        return GateResult("queue_state", Status.FAIL, "SERIES_LENGTH_MISMATCH",
                          f"{len(queue)} queue values against {len(service)} service values")

    impossible, undecidable = [], []
    for index in period_boundary_indices:
        if not 0 < index < len(queue):
            continue
        drop = queue[index - 1] - queue[index]
        if drop <= continuity_tolerance_veh or queue[index] != 0.0:
            continue
        if service is None or dt_h is None:
            undecidable.append((index, drop))
            continue
        dischargeable = service[index - 1] * dt_h
        if drop > dischargeable + continuity_tolerance_veh:
            impossible.append((index, drop, dischargeable))

    if impossible:
        index, drop, dischargeable = impossible[0]
        return GateResult("queue_state", Status.FAIL, "QUEUE_RESET_AT_PERIOD_BOUNDARY",
                          f"queue drops {drop:.3f} veh to zero at index {index}, more than the "
                          f"{dischargeable:.1f} veh the link could discharge in that interval; "
                          f"a period boundary does not empty a road",
                          {"resets": len(impossible)})
    if undecidable:
        index, drop = undecidable[0]
        return GateResult("queue_state", Status.REVIEW, "QUEUE_CLEARS_AT_BOUNDARY_UNVERIFIED",
                          f"queue drops {drop:.3f} veh to zero at index {index}; pass "
                          f"service_vph and dt_h to tell a genuine drain from a reset",
                          {"boundary_clears": len(undecidable)})
    return GateResult("queue_state", Status.PASS, "OK",
                      measured={"bins": len(queue), "peak_veh": max(queue)})


# ------------------------------------------------------------- the aggregate

def combine(gates: Sequence[GateResult], *,
            workload_source: WorkloadSource | str) -> CaseVerdict:
    """Worst status wins, and the binding gate supplies the reason code.

    `workload_source` is required and has no default on purpose. A default would
    have to be one of the independent sources to be useful, and then forgetting
    to pass it would silently award `HELD_OUT_PREDICTION` -- the permissive
    answer -- to a case nobody had classified. Making it explicit is the whole
    point of the flag.

    `is_physical` is stricter than `status`: a `REVIEW` case may still be
    reported, but it does not enter the physical discharge chain if what earned
    the review was a sub-linear exponent or a workload built from the observed
    duration.
    """
    if not gates:
        raise ValueError("combine() needs at least one gate result")

    binding = max(gates, key=lambda g: (_SEVERITY[g.status], g.gate))
    status = binding.status

    blocks = {"EXPONENT_BELOW_ONE", "WORKLOAD_FROM_OBSERVED_DURATION",
              "WORKLOAD_MODEL_INFERRED"}
    is_physical = (
        status is Status.PASS
        or (status is Status.REVIEW
            and not any(g.reason_code in blocks for g in gates))
    )
    return CaseVerdict(
        status=status,
        reason_code=binding.reason_code,
        gates=tuple(gates),
        duration_validation_status=duration_validation_status(workload_source),
        is_physical=is_physical,
    )
