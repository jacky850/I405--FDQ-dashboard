# Single-link full-day queue from speed and a static assignment

**Plan for review. No code written against this yet.**

---

## What this has to produce

A time-dependent **speed profile** for one link, generated from static assignment
output, realistic enough to replace the polynomial split currently used.

## Why the observed speed cannot simply be the input

The assignment model exists to run **scenarios** — a 2045 forecast, a new lane, a
policy change. Those have no observed speed, because they have not happened. So
the production path must be

$$\text{assignment volume} \longrightarrow \text{queue} \longrightarrow \text{speed}$$

Observed speed enters twice: it supplies the **temporal pattern**, and it is the
**validation target**. It is never the level.

## The one structural idea

Everything below follows from a single observation about where each data source
carries information:

| Regime | Can observed speed determine the arrival rate? | Why |
|---|---|---|
| **Queue present** | **Yes** | The queue trajectory pins λ — a larger λ grows the queue faster, and that is visible in the speed |
| **No queue** | **No** | Any λ below μ produces the same zero queue. Speed says nothing at all |

And the assignment is the mirror image: it carries no timing, but it carries the
total. **The two sources do not overlap and do not compete.** Speed governs the
shape where a queue exists; the assignment fixes the level where it does not.

---

## Steps

### 0. Inputs

| Input | Source |
|---|---|
| `v(t)`, 5-min observed speed | RITIS / INRIX, average weekday |
| `V_assign(period)` link volume | static assignment |
| Link attributes: lanes, length `L`, capacity, free speed `v_f` | network / `config.py` |
| QVDF parameters | `qvdf_params_by_corridor_week.csv` |
| OD matrix (2020 HTS) | hard bound on total trips |

### 1. Flow from speed

$$q(t) = S_3\big(v(t)\big), \qquad m = 4$$

Validated against measured counts on ten PeMS corridor-directions: **20.7% MAPE
on congested bins, 84.6% on free-flow bins.** That split is the reason for every
design choice that follows — `q` is trusted only below the cut-off.

### 2. Service rate μ(t)

μ is a **ceiling**, not a flow: the most the link can discharge per hour. The
actual outflow is `min(μ, what wants to leave)`.

That is why it can only be measured under a queue. With nobody waiting, the
observed flow says what arrived, not what the link could have handled — like
counting three people strolling through a doorway and learning nothing about how
many could fit. Under a queue the ceiling is being hit, so the observed flow *is*
the ceiling.

So μ is read in two places, both of them measurements:

| Regime | μ(t) | What it is |
|---|---|---|
| **Queued** | `q(t)` | the queue-discharge rate |
| **Free-flowing** | peak `q` just before breakdown | the capacity |

Both are measured, and the **capacity drop falls out as their ratio** rather than
being assumed at 10%. The pre-breakdown value is also the best-conditioned point
on the whole fundamental diagram: `dq/dv ≈ 0` at the peak, so the flow there is
well determined even where the speed is not.

This replaces `μ = 1900 × lanes × (1 − drop)`, whose config file states plainly
that *"mu is an assumption, not a measurement"*.

**Where μ matters and where it does not.** Deep in free flow its exact value is
irrelevant — with `λ < μ`, `min(μ, λ) = λ` whatever μ is. But near the onset it
decides whether a queue forms at all, and when. Set it too low and congestion is
manufactured; too high and real congestion is suppressed. So a value is always
needed, and only its precision is negotiable.

Links that never congest offer no measurement. They also never queue, so the HCM
prior is a safe fallback there.

### 3. Speed-implied queue

$$Q_{\text{meas}}(t) = \mu(t)\left(\frac{L}{v(t)} - \frac{L}{v_f}\right), \qquad Q_{\text{meas}} = 0 \text{ where not congested}$$

This is the **fitting target**, not the queue itself.

### 4. Arrival rate λ(t)

A smooth B-spline in time of day, 60-minute knot spacing, whose coefficients are
fitted so the queue produced by the recurrence matches `Q_meas`.

This is conservation, `λ = μ + dQ/dt`, solved with a smoothness prior rather than
pointwise. That matters: a pointwise derivative over 5-minute bins is
noise-dominated on a single link, while a spline with ~15 degrees of freedom
cannot absorb that noise. **The smoothness prior is what makes a single link
tractable.**

### 5. Volume anchor

$$\sum_t \lambda(t)\,\Delta t = V_{\text{assign}}(\text{period})$$

as a **soft** constraint with a tolerance. The free-flow bins absorb the
adjustment, which is correct: they are the bins where λ was never identifiable
from speed in the first place.

Priority order when sources conflict:

1. **OD matrix — hard.** Total trips on a link cannot exceed it.
2. **Assignment volume — soft.** Within tolerance; a large divergence is a
   finding to report, not something to force.
3. **Speed — shape only.** Never the level.

### 6. Run the queue

$$\text{out}(t) = \min\Big(\mu(t),\ \lambda(t) + \tfrac{Q(t)}{\Delta t}\Big)$$
$$Q(t+\Delta t) = \max\Big(0,\ Q(t) + \big[\lambda(t) - \text{out}(t)\big]\,\Delta t\Big)$$

**One continuous recurrence over all 288 bins.** AM / MD / PM / NT are labels;
nothing resets at a boundary, so residual queue carries across periods by
construction.

### 7. Queue back to speed

$$TT(t) = \frac{L}{v_f} + \frac{Q(t)}{\mu(t)}, \qquad \hat v(t) = \frac{L}{TT(t)}$$

**P and T₂ are outputs here, not inputs.** They emerge from the profile rather
than being computed in advance and used to shape it — which is the substantive
difference from the polynomial approach being replaced.

### 8. Validation

Compare `v̂(t)` against `v(t)`. This is only a genuine test because of step 5:

| Quantity | Real test? |
|---|---|
| **Timing** of congestion (onset, T₂) | **No** — the shape was taken from speed |
| **Depth** of congestion, `v(T₂)` | **Yes** — depth comes from the queue, the queue from the level, and the level from the assignment |

So the headline metric is the error in **v(T₂)**, not in P.

**A feasibility condition that costs nothing to check.** Over a full episode with
`Q(t₀) = Q(t₃) = 0`, conservation forces

$$\int_{t_0}^{t_3}\lambda\,\mathrm{d}t = \int_{t_0}^{t_3}q\,\mathrm{d}t$$

That part of the arrival total is **locked by the data and cannot be adjusted**.
Since the period must also total `V_assign`, the free-flow bins get whatever is
left:

$$\sum_{\text{free-flow}}\lambda\,\Delta t = V_{\text{assign}} - \int_{t_0}^{t_3}q\,\mathrm{d}t$$

**If that is negative the model has no solution** — the assignment would be
claiming fewer vehicles used the link over the period than were observed
discharging during the queue alone. That is the strict form of the volume
conflict, and it should be reported rather than absorbed.

### 9. Sensitivity

Report as a band, not a point:

- capacity sweep, already configured at 1200–2400 vphpl
- free-speed source — **this one dominates everything**, see below

---

## Already built

| | Where |
|---|---|
| Continuous 288-bin recurrence, no period reset | `run_nvta_full_day_queue.py` |
| Smooth spline arrival, fitted to the speed-implied queue | same |
| Identifiability flag for bins with no queue | same |
| S3 speed-to-flow, validated on 824 links | `run_nvta_corridors_dv_from_ritis.py` |
| Free-speed source already parameterised (4 options) | `run_nvta_full_day_queue.py` |
| Capacity sweep | `configs/nvta_mu_prior.json` |

## To build

- μ read from congested `q` instead of the assumed 1900
- volume anchoring to `V_assign` with a tolerance
- OD matrix as a hard bound
- queue → speed, and the `v(T₂)` validation
- episode-volume cross-check

---

## Three decisions needed before coding

**1. Which free speed?** It sets the cut-off at `0.70 × v_f`, so it decides which
bins count as congested, and therefore μ, `Q_meas`, and the free-flow travel time.
Measured effect on D: **median −22%, range −100% to +119%** — larger than any
other factor, and far larger than the S3 exponent (±14%). Sources disagree:
`config.py` says 70 for every NVTA freeway, `corridor_tmc_mapping.csv` assigns
63 / 69 / 75 per TMC, and the observed 95th percentile runs 50–69 per TMC.

**2. What exactly is the QVDF "average discharge rate"?** No explicit discharge
column appears in the QVDF outputs. If it is simply capacity, it duplicates
decision 1 and step 2.

**3. Is the tolerance on `V_assign` a percentage, and what is it?** Step 5 needs
a number, and the answer determines what counts as a reportable conflict rather
than an adjustment.
