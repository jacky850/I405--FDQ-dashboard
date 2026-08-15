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

So μ takes **two regimes, both measured**:

| Regime | Applies | Estimator |
|---|---|---|
| **Free-flowing** | before breakdown, and after the queue clears | peak `q` just before breakdown |
| **Queued** | breakdown → dissipation | median `q` over the episode |

Two regimes is not two numbers. μ_free is one value for the day; **μ_queued is
one value per episode**, so a link with an AM and a PM queue carries three.

The switch is on **queue state, not on the clock**. That is the same principle
that keeps the queue itself continuous across period boundaries — a discharge
rate that jumped at 09:00 would reintroduce exactly the artefact the continuous
recurrence was built to remove.

Within an episode μ_queued is flat. It does not track the flow's own wiggles,
because it should not: **capacity drop is hysteretic.** Once a queue forms the
discharge stays down even if demand momentarily eases, and it recovers only when
the queue clears. Reading μ pointwise off `q(t)` would contradict that and would
also pour five-minute measurement noise into a quantity that is physically flat.

**The capacity drop then falls out as `1 − μ_queued / μ_free`** rather than being
assumed at 10%.

#### Two estimation details that matter

**Measure per day, then average — not the other way round.** Breakdown time
varies between days, so averaging the profiles first smears the peak into a
gradual decline and the measured capacity comes out low: `max(mean) ≤ mean(max)`.
Estimate the pre-breakdown peak on each individual day, then take the median of
those. The raw 5-minute RITIS data supports this; the average-weekday profile
does not.

**Whether AM and PM share a capacity is an empirical question.** Measure both. If
they agree within noise, pool them for a more stable estimate; if they differ,
keep them apart and report the difference, because it points at different
bottleneck mechanisms or traffic composition rather than at noise.

#### Where μ matters, and where it does not

Deep in free flow its exact value is irrelevant — with `λ < μ`, `min(μ, λ) = λ`
whatever μ is. But near the onset it decides whether a queue forms at all, and
when. Set it too low and congestion is manufactured; too high and real congestion
is suppressed. So a value is always needed, and only its precision is negotiable.

Episodes shorter than `MIN_EPISODE_H` give an unstable median. Fall back to
another episode on the same link, or to the prior. Links that never congest offer
no measurement at all — and never queue, so the HCM prior is safe there.

This whole section replaces `μ = 1900 × lanes × (1 − drop)`, whose config file
states plainly that *"mu is an assumption, not a measurement"*. Nothing above is
assumed; every value is read from the data.

### 3. Speed-implied queue

$$Q_{\text{meas}}(t) = \mu(t)\left(\frac{L}{v(t)} - \frac{L}{v_f}\right), \qquad Q_{\text{meas}} = 0 \text{ where not congested}$$

This is the **fitting target**, not the queue itself.

### 4. Arrival rate λ(t)

λ is the **demand** — how many vehicles per hour want through — as against μ,
what the link can pass, and `out`, what actually got through. In free flow all
three coincide; under a queue λ exceeds the other two and the difference
accumulates.

**λ is never directly observable here.** In free flow it does equal the flow, but
that is exactly where recovering flow from speed fails (84.6%). Under a queue the
flow we can recover is the *discharge*, which is μ. Neither regime hands it over.

#### The queue is the recorder

What makes λ recoverable at all is that the queue accumulates the gap:

$$Q(t+\Delta t) - Q(t) = \big[\lambda(t) - \text{out}(t)\big]\,\Delta t$$

Concretely — if the queue stood at 0 at 07:00 and 500 vehicles at 08:00 while the
link discharged at 2,000 veh/h, then 2,500 veh/h arrived. Nothing else is
consistent with those numbers. **The height of the queue is a record of how far λ
ran above μ**, which rearranges to `λ = μ + dQ/dt`.

#### Why that equation is not used pointwise

`Q` is itself derived from speed, so a wobble in `v` becomes a wobble in `Q`, and
differencing over 5-minute bins multiplies it by twelve. With `Q ≈ 200` veh
carrying ±10 veh of noise, `dQ/dt` inherits ±120 veh/h of pure noise against a
signal that might be 300 — the derivative is dominated by the error.

So λ is parameterised instead as a B-spline in time of day, 60-minute knots:
**about 25 coefficients rather than 288 free values.** The coefficients are
fitted by running the recurrence forward and comparing the resulting queue
against `Q_meas`.

The smoothness is a **physical prior, not a numerical convenience** — real demand
builds and decays over tens of minutes, it does not jump every five. And a curve
with 25 degrees of freedom cannot absorb five-minute noise, so the noise is
filtered rather than amplified.

**This is the same conservation equation, regularised.** Pointwise it is
ill-posed; restricted to smooth solutions it is well-posed. That distinction is
what makes a **single link** tractable rather than forcing a corridor aggregate.

#### The queue is produced, not read

`Q` comes out of the recurrence, never out of the data. So it carries `Q(t−1)` by
construction, cannot jump between bins, and satisfies conservation automatically.
`Q_meas` is only the target. The residual therefore measures something meaningful:
**how much of the observed speed a physically smooth arrival process can account
for.**

#### Where λ cannot be recovered

With no queue, `Q ≡ 0` for **any** λ below μ:

| λ | out | Q |
|---:|---:|---:|
| 800 | 800 | 0 |
| 1,500 | 1,500 | 0 |
| 1,999 | 1,999 | 0 |

Same queue, same speed, nothing to fit against. Those bins are handed to step 5.

### 5. Volume anchor

$$\sum_t \lambda(t)\,\Delta t = V_{\text{assign}}(\text{period})$$

as a **soft** constraint with a tolerance. The congested bins are already pinned
by the queue, so **the free-flow bins absorb the whole adjustment** — which is
exactly right, since those are the bins step 4 could not identify.

The two sources therefore never argue: speed fixes λ where a queue records it,
the assignment fixes the total where it does not.

Priority order when sources conflict:

1. **OD matrix — hard.** Total trips on a link cannot exceed it.
2. **Assignment volume — soft.** Within tolerance; a large divergence is a
   finding to report, not something to force.
3. **Speed — shape only.** Never the level.

#### The tolerance is computed, not chosen

`V_assign` is not an observation. The OD matrix is survey data, but the link
volume is a routing model's output, several assumptions downstream of it. And
static assignment is **not capacity-constrained**: BPR stays defined at
`V/C = 2`, inflating the travel time while still loading the link with more
vehicles than it could pass. Producing volumes a link cannot physically carry is
a known property of the method, not a rare failure — and it is the reason this
work exists, so treating that same volume as ground truth would assume away the
problem.

Two bounds follow directly, and **neither comes from the assignment**, so this is
a genuine cross-check rather than the model validating itself.

**Lower bound — what was already observed to discharge.** Over an episode with
`Q(t₀) = Q(t₃) = 0`, arrivals must equal departures, so the episode's share of
the total is fixed by the data:

$$V_{\text{assign}} \ \geq\ \int_{t_0}^{t_3} q\,\mathrm{d}t$$

Below this, the free-flow bins would need a negative number of vehicles: the
assignment would be claiming fewer vehicles over the whole period than were seen
discharging during the queue alone.

**Upper bound — what the free-flow bins can physically hold.** Each of them
admits at most `μ_free · Δt` before a queue would form:

$$V_{\text{assign}} \ \leq\ \int_{t_0}^{t_3} q\,\mathrm{d}t \ +\ \sum_{\text{free-flow}} \mu_{\text{free}}\,\Delta t$$

Above this, anchoring would push some free-flow λ past μ and manufacture a queue
that the speed data does not show.

So the feasible window is **specific to each link and period, computed from that
link's own data** — not a global ±X%. Inside it, anchor. Outside it, report the
conflict: it points at the network coding, the volume-delay calibration, or the
OD on that movement, and forcing the number would erase the signal while still
producing a plausible-looking speed profile.

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

Report alongside it whether `V_assign` fell inside the feasible window of step 5,
and by how much if not. A link whose volume had to be pulled to the edge of the
window can still produce a good-looking speed profile, so that has to be visible
rather than inferred from the fit quality.

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

## One decision needed before coding

**Which free speed?**

It sets the cut-off at `0.70 × v_f`, so it decides which bins count as congested
— and therefore μ, `Q_meas`, the free-flow travel time, and where the volume
window sits. Everything downstream moves with it.

Measured effect on D: **median −22%, range −100% to +119%.** That is larger than
any other choice in the pipeline, and far larger than the S3 exponent, which
moves it ±14%.

The three sources disagree:

| Source | Value |
|---|---|
| `config.py` | 70 mph for every NVTA freeway |
| `corridor_tmc_mapping.csv` | 63 / 69 / 75 per TMC |
| Observed 95th percentile | 50–69 per TMC |

### Two earlier questions that the design resolved

**The QVDF average discharge rate is no longer needed.** Step 2 reads both
service rates from the data, so nothing depends on locating a discharge column
in the QVDF outputs.

**The tolerance on `V_assign` does not need to be chosen.** Step 5 computes a
feasible window per link and period from that link's own observed discharge and
free-flow capacity, which is stricter and better founded than a global ±X%.
