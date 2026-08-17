# Appendix to the NVTA PM single-link queue delivery

Supporting material for [`NVTA_PM_LINK_QUEUE.md`](NVTA_PM_LINK_QUEUE.md): the
field dictionary for all three files, the scope caveats, and the findings that
were deliberately kept off the main document because they are not on the line
from D to speed.

---

## 1. Field dictionary

### `nvta_queue_pm_link_summary.csv` — 47 × 25

One row per link carrying an **observed PM episode**. This is the delivery.

| Column | Meaning |
|---|---|
| `corridor`, `net_link_id`, `tmc_code` | identifiers. `tmc_code` is included so the sample can be de-duplicated — see §2 |
| `lanes`, `miles` | link geometry |
| `C_vphpl`, `C_veh_per_h` | capacity per lane and total. Equals `μ_free` |
| `free_speed_mph`, `cutoff_mph` | the TMC's own observed p95, and `0.70 ×` it |
| `D_assign_vphpl` | **the assignment's demand**, `V_assign / (lanes × 4 h)` |
| `D_obs_vphpl` | the discharge the speed data already shows, same units. A floor, independent of the assignment |
| `D_ratio` | `D_assign / D_obs`. Below 1 means the assignment is short |
| `P_h_obs`, `T2_clock_obs`, `vT2_mph_obs` | observed episode: duration, time of trough, speed at trough |
| `P_h_model`, `T2_clock_model`, `vT2_mph_model` | the same three read off the model's speed by the same detector |
| `P_h_err`, `T2_min_err`, `vT2_mph_err` | model − observed. **`P_h_err` is blank where the model episode was still open at 19:00** |
| `speed_mae_episode_mph` | mean absolute speed error inside the episode |
| `speed_mae_pm_mph` | the same across the whole 15:00–19:00 window |
| `mae_episode_assignment_only_mph` | the ablation: the same recurrence driven by `V_assign` alone |
| `note` | per-link caveats, see below |

`note` takes four values, in these combinations:

| Note | Links |
|---|---:|
| model episode still open at 19:00; V_assign below the observed discharge | 27 |
| V_assign below the observed discharge | 5 |
| model episode still open at 19:00; V_assign above what free-flow bins can absorb | 4 |
| model found no PM episode; V_assign below the observed discharge | 1 |

### `nvta_queue_pm_speed_15min.csv` — 13,104 × 18

One row per link and 15-minute bin, **06:00–19:00**, all 252 links.

| Column | Meaning |
|---|---|
| `t_min`, `clock`, `anchor_period`, `in_pm_period` | time, and which period the anchor used |
| `obs_speed_mph` | INRIX, average weekday, unsmoothed |
| `model_speed_mph` | the delivered model, `L / (L/v_f + Q/μ)` |
| `assignment_only_speed_mph` | the ablation variant |
| `queue_model_veh` | what the recurrence produced |
| `queue_meas_veh` | what the observed speed implies — the step 4 fitting target |
| `in_episode_obs`, `in_episode_model` | below cut-off; inside a detected model episode |

### `nvta_queue_pm_link_full.csv` — 756 × 62

**All 252 links × 3 periods (AM, MD, PM).** Everything the pipeline computed.
Groups: the step 5 anchor and its bounds (`V_assign_veh`, `lower_bound_veh`,
`upper_bound_veh`, `inside_window`, `below_lower`, `above_upper`, plus the
placement diagnostics), the step 6 run (`queue_peak_*`, `peak_ratio`, boundary
carry-over, `storage_veh`, `unmet_demand_veh`, residuals), the step 8 scores for
all three variants (`mae_*_anchored` / `_assignment` / `_free_flow`), and both
episode parameter sets per period.

Use this for AM and MD, which the main delivery does not cover.

---

## 2. Scope caveats

**252 links, but only 132 independent speed observations.** One TMC covers
several links, and every link under the same TMC receives an identical speed
profile, cut-off and episode.

| Links per TMC | TMCs |
|---:|---:|
| 1 | 72 |
| 2 | 31 |
| 3–6 | 27 |
| 10 | 2 |

Any count of links is therefore an overcount of evidence. The 47-link PM
delivery should be reported as such, but significance should be judged on the
TMC count. `tmc_code` is carried in all three files for this reason.

**The run window ends at 19:00** because the assignment has no night period. 33
links still carry a queue at that point, and 28 links are still observed below
their cut-off at 18:45 — the residual is real congestion, not a modelling
failure. Its consequence is that P is censored on 31 of 46 matched episodes.

**`v̂ = v_f` on 90.6% of bins.** A point queue with no queue in it produces no
delay, so the model has nothing to say about free-flow speed variation. Only the
in-episode comparison carries information; the whole-period MAE is dominated by
bins where the model is pinned at free flow by construction.

---

## 3. Findings kept off the main document

These came out of the step work and are worth recording, but none of them is on
the D → speed line.

### μ_free is an input, not a measurement

Running the estimator against five assumed capacities returns the same answer
every time:

| Assumed C | μ_free / C |
|---:|---:|
| 1800 | 0.9979 |
| 2000 | 0.9979 |
| 2200 | 0.9979 |
| 2400 | 0.9979 |

This is an identity, not estimation error. S3 returns exactly `C` at
`v = v_f/√2 = 0.707·v_f`, and the congestion cut-off is `0.70·v_f` — the
"maximum flow before breakdown" window necessarily sweeps that point. On link
25947 at 16:15, `v/v_f = 0.709` and the flow reads 1800.0, 2000.0 or 2200.0
depending only on what was assumed. The pipeline therefore reads `link_capacity`
directly rather than pretending to measure it.

Only the **ratio** survives: capacity drop `1 − μ_queued/μ_free` is
capacity-free (C cancels to 3.3e-16) and measures **6.83%**, against the 10%
previously assumed. Even this is not an independent measurement — both flows come
from the same speed curve through the same S3 map.

### Free-flow speed had to be re-derived

The assignment's `free_speed_mph` exceeds the road's own observed maximum on **72
of 154 TMCs**. I-66 WB has 75 mph assigned to all 109 links; link 26304 never
exceeds 55.00 mph all day.

Corridor-level p95 is also wrong: within-corridor spread is 16–22 mph, so the
I-66 EB corridor value of 71.0 applied to a segment whose own p95 is 54.3 shifts
the cut-off by 11.7 mph and makes that segment permanently congested.

Per-TMC p95 was adopted. It agrees with two independent routes — correlation
**0.963** against INRIX's own `reference_speed` and **0.979** against the
00:00–05:00 observed median — and moving the percentile from p85 to p99 shifts
the cut-off by only 1.7–3.8 mph. Adopting it removed 9 of 12 spurious all-day
episodes with no filtering rule.

| Corridor | TMCs | Adopted p95 | Corridor p95 | Night median | INRIX ref | Assignment |
|---|---:|---:|---:|---:|---:|---:|
| I-395 NB | 21 | 65.62 | 65.89 | 61.92 | 59.0 | 63.0 |
| I-395 SB | 20 | 63.18 | 64.77 | 59.57 | 59.5 | 63.0 |
| I-66 EB | 57 | 67.86 | 71.00 | 63.60 | 64.0 | **75.0** |
| I-66 WB | 56 | 67.88 | 70.93 | 64.52 | 64.0 | **75.0** |

### The B-spline is about falsifiability, not noise

The original rationale was noise suppression. Measured, pointwise differencing is
only **1.3× noisier** than the spline (23 vph against 17, both 0.3% of μ), with
zero negative arrival rates either way — the data is cleaner than assumed because
of the 15-minute bins and 23-day average.

The real reason is different. Feeding 96 free pointwise λ values into the
recurrence gives a residual of **exactly 0.000** — 96 unknowns against 96 bins is
square, so it cannot fail and therefore proves nothing. Sweeping the knot spacing:

| Knots | Coefficients | Bins per coefficient | RMSE | Share of peak |
|---:|---:|---:|---:|---:|
| 15 min | 99 | 0.97 | — | solver refuses |
| 20 min | 75 | 1.3 | 2.88 | 2.2% |
| **60 min** | **27** | **3.6** | 5.50 | **4.1%** |
| 480 min | 6 | 16.0 | 10.94 | 8.5% |

The 4.1% residual is the price of a model that could have failed. Tightening the
knots would make it look better and make the validation meaningless.

### The upper bound predicted which links would blow up

Before clipping, 4 links ran their queues to **55× storage**, 3 of them with a
measured queue of exactly 0.0 — thousands of vehicles invented on links the speed
data shows flowing freely. Those 4 are exactly the links step 5 flagged
`above_upper`, and every link with `bins_pushed_over_mu > 0` failed. Clipping λ at
`μ_free` on free-flow bins fixed it:

| | Before | After |
|---|---:|---:|
| Bins over storage | 102 | **0** |
| Worst peak / storage | 55.12 | **0.71** |
| Largest queue carried into PM | 10,076 veh | 151 veh |

17,826 vehicles could not be placed and are reported in
`volume_not_placed_veh` rather than absorbed silently.

### Breakdown happens above the S3 capacity speed

Ignoring thresholds and locating the sharpest single-bin speed drop puts
breakdown at **0.82·v_f**, not 0.707. 72% of links break down above the speed S3
calls capacity, a median of 10.6 mph higher; back-solving suggests `m = 7` rather
than 4. The cost of leaving it alone was measured at step 3 and is **6.5%** of
captured queue, so it was left alone.

### AM against PM capacity drop: not answerable here

| | n | Median drop |
|---|---:|---:|
| AM | 34 | 3.99% |
| PM | 47 | 8.67% |

Mann-Whitney p = 0.030, but the AM-congested and PM-congested links are largely
different links, so the contrast confounds "which links congest" with time of
day. On the **7 links** with both, PM − AM is **−2.13 points** — the opposite
sign. Each episode keeps its own `μ_queued`, so nothing downstream depends on
resolving this.

### The 54.5% of queue discarded outside episodes is an artefact

Zeroing the queue outside episodes discards 54.5% of the total, which looks
alarming. Per bin it is 43.5 vehicles inside against **3.11** outside, with 16.7×
as many bins outside; 65% of the discarded total sits on links that never
congest. The 3.11 is the floor of the measure itself — `v_f` is a p95, so 95% of
bins run slightly below it and `L/v − L/v_f` is a small positive number
everywhere. True clipping of real queue is **6.5%**.

---

## 4. Reproducing

```powershell
python scripts/queue_step1_flow_from_speed.py
python scripts/queue_free_speed_audit.py
python scripts/queue_step2_service_rate.py
python scripts/queue_step3_speed_implied_queue.py
python scripts/queue_step4_arrival_rate.py
python scripts/queue_step5_volume_anchor.py
python scripts/queue_step6_run_queue.py
python scripts/queue_step7_queue_to_speed.py
python scripts/queue_step8_validation.py
python scripts/make_nvta_queue_pm_tables.py
python scripts/make_nvta_queue_pm_figures.py
```

Each `queue_step*.py` writes a `step*_summary.json` beside its CSV carrying that
step's full statistics and its caveats.

A step-by-step narrative of the experiments, in Chinese, is in
[`QUEUE_STEPS_ZH.md`](QUEUE_STEPS_ZH.md).
