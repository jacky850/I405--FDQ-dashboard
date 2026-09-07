# Identifiability and physical gates

What a case must satisfy before its numbers may be reported as a physical
result, and which of this project's quantities cannot be identified at all.

Implemented in `src/fdqbench/validation.py`. Every gate is one function with one
job, so a reviewer can run them individually and see the number each looked at.

---

## 1. Four statuses, and a reason code

Every case ends in exactly one:

| Status | Meaning |
|---|---|
| `PASS` | every gate satisfied; may enter the physical discharge chain |
| `REVIEW` | outside a declared range but defensible, or diagnostic rather than predictive |
| `FAIL` | a physical or basis violation; not a physical result |
| `INSUFFICIENT_DATA` | a gate could not be evaluated at all |

A case takes the **worst** status any gate returned, and the reason code of the
gate that bound it. `INSUFFICIENT_DATA` outranks `FAIL`, because a case that
could not be evaluated is not a case that failed, and pooling the two miscounts
attrition — which is the number a reader needs to judge coverage.

Reason codes are a controlled vocabulary, never free text, so cases can be
filtered and counted:

```
OK                                        EXPONENT_BELOW_ONE
EVIDENCE_MISSING                          RETENTION_INCREASING
CAPACITY_BASIS_AMBIGUOUS                  SERIES_LENGTH_MISMATCH
CAPACITY_NOT_NOMINAL_HOURLY               CONSERVATION_RESIDUAL_ABOVE_TOLERANCE
CAPACITY_NON_POSITIVE                     WORKLOAD_FROM_OBSERVED_DURATION
CAPACITY_ABOVE_RANGE_UNJUSTIFIED          WORKLOAD_MODEL_INFERRED
CAPACITY_ABOVE_RANGE_JUSTIFIED            SPEED_MAE_ABOVE_LIMIT
CAPACITY_BELOW_RANGE                      SPEED_MAE_ABOVE_LIMIT_JUSTIFIED
RETENTION_NON_POSITIVE                    NO_OBSERVED_BINS
RETENTION_ABOVE_ONE                       QUEUE_NEGATIVE
QUEUE_NOT_FINITE                          QUEUE_RESET_AT_PERIOD_BOUNDARY
```

### `is_physical` is stricter than `PASS`

A `REVIEW` case may still be reported. It does **not** enter the physical
discharge chain when what earned the review was a sub-linear duration exponent or
a workload built from the observed duration. Those two are not "slightly outside
a range"; they mean the result is diagnostic, and diagnostic results are not
inputs to a physical model.

---

## 2. The gates

| Gate | `PASS` | Otherwise |
|---|---|---|
| `data_evidence` | detector, lanes, observed mask, time basis and units all present | any missing → `INSUFFICIENT_DATA` |
| `capacity_basis` | a declared nominal hourly rate on a named basis | ambiguous or not hourly → `FAIL` |
| `capacity_plausibility` | 1000–2400 veh/h/lane | above 2400 → `FAIL`, or `REVIEW` with a written justification; below 1000 → `REVIEW` |
| `retention` | `0 < k_mu <= 1` | otherwise `FAIL` |
| `duration_exponent` | `n >= 1` | `n < 1` → `REVIEW`, diagnostic only |
| `retention_monotonicity` | implied `k_mu(z)` non-increasing | any rise → `FAIL` |
| `conservation` | residual within tolerance | outside → `FAIL`; **the residual is always reported** |
| `episode_independence` | workload did not use the observed `P` or `T3` | otherwise → `REVIEW` |
| `speed_profile` | observed-only MAE ≤ 10 mph | above → `FAIL`, or `REVIEW` with a justification |
| `queue_state` | non-negative, finite, continuous across a period boundary | otherwise `FAIL` |

### Why some of these are `FAIL` and not `REVIEW`

**An ambiguous capacity basis.** The resulting stress is wrong by the lane count
— a factor of four on a four-lane link — and nothing about the number reveals it.
There is no version of this that a reviewer can judge by eye, so it cannot be a
review.

**Retention rising with severity.** `k_mu(z)` increasing says the road discharges
better the worse the congestion gets. No queue does that, so a fit that implies
it is not describing a discharge process.

**A queue reset at a period boundary.** Vehicles standing on a link at 15:00 do
not vanish because the reporting label changed. On the NVTA network 23 links
carry a standing queue across 15:00, median 29.7 veh; a PM-only run starting from
an empty link discards them.

### The conservation residual is never forced to zero

`D_Q − ∫μ − ΔQ` is reported whatever it is. A model that closes because it was
made to close has not been checked, and the residual is the only thing that says
which it was.

---

## 3. Circularity: closure is not prediction

`episode_workload_source` records where an episode's workload came from:

```
OBSERVED_UPSTREAM_ARRIVALS      counted upstream
QUEUE_CORRECTED_ARRIVALS        counted, corrected for the standing queue
CONSERVATION_FROM_OBSERVED_P    built as mu_e * P from this episode's own P
MODEL_INFERRED                  a model output
```

The last two force

```
duration_validation_status = NOT_INDEPENDENT_DIAGNOSTIC_CLOSURE
```

and it may not be reported as a held-out duration prediction.

The reason is arithmetic, not judgement. If `D_Q = μ_e · P` and the duration is
then recovered as `P̂ = D_Q / μ_e`, then `P̂ = P` exactly, for any `μ_e`, any `P`,
and any model quality. The round trip is a rearrangement of the definition.
`tests/test_episode_workload_independence.py` demonstrates it rather than
describing it.

`workload_source` is a **required** argument with no default. Any usable default
would be one of the independent sources, so an unclassified case would silently
be awarded the permissive answer.

---

## 4. Measured against inferred `mu`

`DischargeSource` labels how a discharge rate was obtained:

```
MEASURED_DETECTOR      counted at a detector
INFERRED_FROM_SPEED    recovered from speed through a fundamental diagram
ASSUMED_CAPACITY       read from a configuration file
```

These are different evidence and are never pooled into one sample size. The
distinction matters concretely here: the NVTA capacity drop of 6.83% is computed
from two flows that both came from the same speed curve through the same S3
inversion, so it is not the independent before-and-after measurement the
literature's capacity drop is.

---

## 5. What cannot be identified in this project

These are structural, not precision problems. No amount of data fixes them, and a
gate cannot repair them — it can only stop them being reported as something they
are not.

### `λ` is unidentifiable on 94.4% of bins

With no queue, `Q ≡ 0` holds for **any** `λ` below `μ`. On the NVTA network only
**5.6% of bins** (1,363 of 24,192) carry a queue, so on the rest `λ = 800`,
`λ = 1500` and `λ = 1999` produce identical queues and identical speeds.

Consequence: a per-bin `λ` on an unidentifiable bin is one arbitrary member of a
set the data cannot distinguish between. It is not a measurement, and a diff
between two runs of it is not a regression. `REPRODUCE.md` records that the
solver lands on different members of that set on different platforms.

### `μ_free` is an input, not a measurement

The estimator returns `0.998 · C` for any assumed `C` between 1800 and 2400,
because S3 returns exactly `C` at `0.707 v_f` while the congestion cut-off sits
at `0.70 v_f`, so the "maximum flow before breakdown" window necessarily sweeps
that point. Only the **ratio** `1 − μ_queued/μ_free` carries information.

### Free-flow speed must be per segment

`v_f` sets the cut-off at `0.70 v_f`, which decides which bins count as
congested, which decides everything downstream. The assignment's `free_speed_mph`
exceeds the road's own observed maximum on **72 of 154 TMCs**. Within a corridor
the 95th-percentile speed varies by **16–22 mph** between segments, so one value
per corridor is also wrong.

### The current NVTA chain is a closed loop

```
observed speed → queue → fitted λ → recurrence → queue → model speed → compare
       ↑                                                          │
       └────────────────────── the same data ─────────────────────┘
```

The PM in-episode MAE of 2.06 mph is that loop's self-consistency. It is not a
predictive accuracy and must not be quoted as one. Under this module that is a
`REVIEW` with `WORKLOAD_MODEL_INFERRED`, and `is_physical = False`.

---

## 5A. The gates applied to the NVTA run

`scripts/run_nvta_gate_report.py` runs the framework over all 252 links of the
full-day run and writes `outputs/nvta_gates/`. The result is the honest one:

| Status | Links | Binding reason |
|---|---:|---|
| `INSUFFICIENT_DATA` | 176 | `EVIDENCE_MISSING` — no queued bin, so no observed-bin MAE exists to score |
| `REVIEW` | 73 | `WORKLOAD_MODEL_INFERRED` |
| `FAIL` | 3 | `SPEED_MAE_ABOVE_LIMIT` |
| **`is_physical`** | **0 of 252** | |

Nothing in this run is a physical result. `λ` is fitted so the recurrence
reproduces the speed-implied queue, then scored against that same speed, so
`episode_workload_source` is `MODEL_INFERRED` and every duration result is a
diagnostic closure. The framework says that in a field rather than in a paragraph
a reader can skip.

The 176 abstentions are not failures. They are links with no queue, where the
model is pinned at free speed by construction and an error computed there
measures the pinning.

### A false positive the real data caught

The first version of `gate_queue_state` called any drop to zero at a period
boundary a reset, and flagged five links `FAIL`. All five were genuine drains:
they cleared 0.09 to 55.9 vehicles against a service capacity of 900 to 1500 per
interval. A queue reaching zero is indistinguishable from one that was reset
unless the service rate is known, so the gate now takes `service_vph` and `dt_h`
and only calls a reset when the drop **exceeds what the link could discharge**.
Without them it returns `REVIEW`, not `FAIL`: the evidence to decide is absent.

---

## 6. What each rule is tested by

| Rule | Test |
|---|---|
| Every case has a status and a reason code | `tests/test_physical_gates.py` |
| Missing evidence is `INSUFFICIENT_DATA`, not `FAIL` | `tests/test_physical_gates.py` |
| `n < 1` cannot reach a physical `PASS` | `tests/test_physical_gates.py` |
| The conservation residual is reported, not zeroed | `tests/test_physical_gates.py` |
| Observed and imputed speed bins are scored separately | `tests/test_physical_gates.py` |
| A queue reset at a period boundary fails | `tests/test_physical_gates.py` |
| A closure cannot be labelled a held-out prediction | `tests/test_episode_workload_independence.py` |
| `workload_source` has no permissive default | `tests/test_episode_workload_independence.py` |
