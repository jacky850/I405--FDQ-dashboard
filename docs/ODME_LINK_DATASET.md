# Link dataset for ODME — data dictionary

Northern Virginia, four corridors (I-395 NB/SB, I-66 EB/WB). **252 network links
from 132 INRIX TMC segments.** Speeds are the average weekday over 23 October
2025 weekdays at 15-minute resolution.

| File | Rows × cols | Content |
|---|---|---|
| `outputs/nvta_odme/odme_link_period.csv` | 756 × 51 | one row per link and period (AM/MD/PM). The ODME input |
| `outputs/nvta_odme/odme_link_15min.csv` | 13,104 × 22 | one row per link and 15-minute bin, 06:00–19:00 |

The assignment's link table carries `obs_volume = -1` on all 756 rows — there is
no counted volume anywhere on this subnetwork. Every volume below is inferred
from observed speed through a single-link queue model.

---

## Provenance — the most important attribute of any column

| Label | Meaning |
|---|---|
| **OBS** | Derived from observed speed only. Never touches the assignment. **Usable as an ODME observation.** |
| **ASSIGN** | From the assignment's own output. **Not an observation.** |
| **GEOM** | Static link attribute. |
| **MODEL** | Produced by the queue recurrence. Diagnostic, not an observation. |

**A queue is the only thing that makes speed informative about volume.** With no
queue, `Q = 0` holds for any arrival rate below the service rate, so λ = 800 vph
and λ = 1900 vph give identical speeds. That is structural non-identifiability,
not noise.

| | Rows | Share |
|---|---:|---:|
| At least one queued bin — speed constrains volume | **139** | 18% |
| No queued bin — the volume is whatever the assignment said | 617 | 82% |

On the 617 rows our λ was made by spreading `V_assign` over the period. **Using
it as an ODME observation would be circular.** Filter on `observation_weight > 0`.

---

## How the numbers are built

Speed enters the S3 fundamental diagram (`m = 4`) to give a flow `q(t)`. The
delay against free flow gives the queue in vehicles. The arrival rate is then
fitted so the recurrence reproduces that queue.

```
q(t)      = S3(v(t)) * lanes                        vph, whole link
Q_meas(t) = mu(t) * ( L/v(t) - L/v_f )              veh
out(t)    = min( mu(t), lambda(t) + Q(t)/dt )       vph
Q(t+dt)   = max( 0, Q(t) + [lambda(t) - out(t)]*dt) veh
v_model   = L / ( L/v_f + Q(t)/mu(t) )              mph
```

`dt` = 0.25 h. Period lengths: AM 3 h (06–09), MD 6 h (09–15), PM 4 h (15–19).

**Every volume column is one of these rates times 0.25 h, summed over bins.** The
only differences are which rate and over which bins.

λ is a cubic B-spline in time of day — 27 coefficients on 60-minute knots against
96 bins. Fewer parameters than data points is deliberate: 96 free values would
make the system square and force the residual to zero, so the fit could not fail.
At 27 coefficients the median residual is 4.1% of peak queue, correlation 0.9842.

---

## File A — `odme_link_period.csv`, 756 rows

### Identity and geometry

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `link_id` | — | GEOM | Network link id |
| `from_node_id`, `to_node_id` | — | GEOM | Endpoints, for network matching |
| `tmc_code` | — | GEOM | INRIX segment supplying the speed |
| `corridor`, `road`, `direction` | — | GEOM | I395_NB / I395_SB / I66_EB / I66_WB |
| `period` | — | GEOM | AM, MD or PM |
| `period_hours` | h | GEOM | 3, 6 or 4 |
| `bins_in_period` | — | GEOM | 12, 24 or 16 |
| `lanes` | — | GEOM | Lane count |
| `length_mi` | mi | GEOM | Link length, `L` |
| `links_sharing_this_tmc` | — | GEOM | How many links read this same TMC. **See limitations** |

### Free-flow speed — both derivations, side by side

This is the input the two sides disagree on most, and it propagates into every
volume through the congestion cut-off.

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `free_speed_obs_p95_mph` | mph | **OBS** | 95th percentile of this TMC's own observed speed profile |
| `free_speed_assign_mph` | mph | **ASSIGN** | `free_speed_mph` from the assignment's link table |
| `free_speed_diff_mph` | mph | — | `assign − obs`. Positive means the assignment is faster |
| `observed_max_mph` | mph | OBS | Highest speed this TMC was ever observed to run, all day |
| `assign_free_speed_impossible` | bool | — | `free_speed_assign > observed_max`. True on **96 of 252 links (52 of 132 TMCs)** |
| `cutoff_obs_mph` | mph | OBS | `0.70 × free_speed_obs_p95_mph`. **This is the one used throughout** |
| `cutoff_assign_mph` | mph | ASSIGN | `0.70 × free_speed_assign_mph`, carried for comparison only |

By corridor:

| Corridor | Links | Ours (p95) | Assignment | Diff | Links flagged impossible |
|---|---:|---:|---:|---:|---:|
| I-395 NB | 29 | 66.15 | 63.00 | −2.65 | 2 |
| I-395 SB | 32 | 63.78 | 63.00 | +0.59 | 4 |
| I-66 EB | 82 | 69.99 | **75.00** | +2.20 | **35** |
| I-66 WB | 109 | 68.98 | **75.00** | +3.60 | **55** |

I-66 has 75 mph assigned to every link. Link 26304 never exceeds 55.00 mph all
day, so under the assignment's cut-off it would be congested 24 hours a day.
Our p95 correlates 0.963 with INRIX's own `reference_speed` and 0.979 with the
00:00–05:00 observed median.

### Service rate

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `lane_capacity_vphpl` | vph/lane | GEOM | From the assignment's link table (1900 or 2000 here) |
| `mu_free_vph` | vph | GEOM | `lane_capacity × lanes`. **An input, not a measurement** |
| `mu_queued_vph` | vph | OBS | Median `q(t)` over the episode's bins. Blank where no episode |
| `capacity_drop` | — | OBS | `1 − mu_queued/mu_free`. Median 6.83% |

`mu_free` was tested and found unmeasurable: the estimator returns `0.998 × C`
for every assumed `C` from 1800 to 2400, because S3 returns exactly `C` at
`0.707 v_f` while the cut-off sits at `0.70 v_f` — the "maximum flow before
breakdown" window necessarily sweeps that point. Only the ratio survives.

### Volumes — what ODME consumes

All are period totals in vehicles, summed over all lanes.

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `V_assign_veh` | veh | **ASSIGN** | The `volume` field of the assignment's link table. Verified a period total over all lanes: `D = volume/(lanes × period_hours × vdf_plf)` reproduces their own `D` on 100% of rows. **The seed, not an observation** |
| `V_throughput_obs_veh` | veh | **OBS** | `sum over queued bins of q(t) × 0.25`. Vehicles seen to discharge while queued. **Closest analogue to a detector count** |
| `V_demand_obs_veh` | veh | **OBS** | `sum over queued bins of lambda(t) × 0.25`. Vehicles that had to arrive to reproduce the observed congestion. **Closest analogue to OD demand** |
| `V_max_feasible_veh` | veh | **OBS** | `V_throughput_obs + mu_free × 0.25 × (free-flow bins)`. A ceiling — a free-flow bin cannot have carried more than `mu_free`, or a queue would have formed and it would not be free-flow |
| `V_from_assignment_veh` | veh | **ASSIGN** | `V_assign − V_demand_obs`, the remainder spread over free-flow bins. **Listed only so it can be excluded** |
| `obs_volume_in_assignment` | veh | ASSIGN | Always −1: the assignment's sentinel for "no count available" |

`V_throughput_obs` and `V_demand_obs` land close to each other when a queue starts
and ends empty inside the period, since what arrives must leave. Medians 24,676
and 24,392 veh — a useful internal check.

### Demand rates

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `D_assign_vphpl` | vph/lane | ASSIGN | `V_assign / (lanes × period_hours)` |
| `D_obs_vphpl` | vph/lane | OBS | `V_throughput_obs / (lanes × period_hours)` |
| `D_ratio` | — | — | `V_assign / V_throughput_obs`. Below 1 means the assignment places fewer vehicles than were observed to pass |

**Caution.** The assignment's own `D` column divides by an extra peak load factor
(`vdf_plf`, 0.58–0.72 here), making it a *peak-hour* rate about 1.68× larger than
the period-average rate used here. Comparing their `D` against our `D_obs` mixes
two different quantities and reverses the conclusion. **Compare period totals in
vehicles.**

### Confidence — read before weighting anything

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `queued_bins` | — | OBS | Bins inside a congestion episode |
| `observation_weight` | — | OBS | `queued_bins / bins_in_period`. **Zero means the row carries no observation** |
| `inside_window` | bool | — | `V_throughput_obs ≤ V_assign ≤ V_max_feasible` |
| `below_lower` | bool | — | `V_assign < V_throughput_obs`. The assignment places fewer vehicles than were observed to pass — physically impossible. **68 of the 139 informative rows** (AM 22, MD 12, PM 34) |
| `above_upper` | bool | — | `V_assign > V_max_feasible`. The assignment implies a queue the speed does not show |

### Episode parameters — for validating the reconstruction, not for ODME

`_obs` comes from an episode detector run on the observed speed. `_model` comes
from **the same detector** run on the reconstructed speed, so these are outputs of
the queue rather than read-offs.

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `t0_min_obs` / `_model` | min from midnight | OBS / MODEL | Onset of congestion |
| `T2_min_obs` / `_model` | min from midnight | OBS / MODEL | Time of the speed trough |
| `t3_min_obs` / `_model` | min from midnight | OBS / MODEL | Recovery |
| `P_h_obs` / `_model` | h | OBS / MODEL | Duration, `t3 − t0` |
| `vT2_mph_obs` / `_model` | mph | OBS / MODEL | Speed at the trough |
| `right_censored` | bool | MODEL | The model episode was still open at 19:00, so its `P` is a window artefact. **`P_h_model` is blanked where true** |
| `speed_mae_episode_mph` | mph | — | Mean absolute error of reconstructed against observed speed, queued bins only |
| `speed_mae_period_mph` | mph | — | The same across the whole period |

**How to read `speed_mae_episode_mph`.** The reconstruction
`v = L/(L/v_f + Q/mu)` is the exact algebraic inverse of `Q = mu(L/v − L/v_f)`;
feeding the speed-implied queue back through it returns the observed speed to
machine precision. Since λ was fitted to reproduce that same queue, close
agreement is inherited rather than predicted. **This column measures the spline
residual, not predictive skill.**

---

## File B — `odme_link_15min.csv`, 13,104 rows

252 links × 52 bins over 06:00–19:00, the window the recurrence runs in.

| Column | Unit | Prov. | Definition |
|---|---|---|---|
| `link_id`, `tmc_code`, `corridor` | — | GEOM | Identity |
| `t_min`, `clock` | min / HH:MM | GEOM | Bin start, minutes from midnight |
| `period` | — | GEOM | AM / MD / PM |
| `lanes`, `length_mi` | — | GEOM | Geometry |
| `free_speed_obs_p95_mph` | mph | OBS | Ours |
| `free_speed_assign_mph` | mph | ASSIGN | Theirs |
| `cutoff_obs_mph` | mph | OBS | `0.70 ×` ours — the threshold actually used |
| `obs_speed_mph` | mph | **OBS** | INRIX average weekday, unsmoothed |
| `q_vphpl` | vph/lane | **OBS** | `S3(v(t))`. Informative only below the cut-off |
| `mu_vph` | vph | GEOM / OBS | `mu_free` outside episodes, `mu_queued` inside |
| `queue_meas_veh` | veh | **OBS** | `Q_meas`, the speed-implied queue. Zeroed outside episodes |
| `lambda_identifiable` | bool | OBS | **True only where a queue exists** |
| `lambda_vph` | vph | **mixed** | Fitted from the queue where `lambda_identifiable`, otherwise spread from `V_assign`. **Never use without reading `lambda_identifiable`** |
| `outflow_vph` | vph | MODEL | `min(mu, lambda + Q/dt)` |
| `queue_model_veh` | veh | MODEL | Queue produced by the recurrence |
| `storage_veh` | veh | GEOM | Physical storage of the link. The model never exceeds it |
| `model_speed_mph` | mph | MODEL | Reconstructed speed |
| `assignment_only_speed_mph` | mph | ASSIGN | The same recurrence driven by a flat `V_assign / period_hours`, no speed input |

**Why `assignment_only_speed_mph` is included.** Driving the recurrence from the
assignment's volumes alone gives a median `lambda/mu` of 0.448, and on 249 of 252
links λ never reaches μ in any bin — no queue can form, so the reconstructed
speed stays at free flow all day. Its in-episode error is 31.7 mph, identical to
predicting free flow everywhere. This is the quantitative statement of the
problem ODME is being asked to fix, and it lets the ODME result be scored against
a null.

---

## Using these columns in ODME

```
observation_weight > 0     equality target available:
                             V_demand_obs_veh      (as OD demand)
                             V_throughput_obs_veh  (as a count analogue)
                           weight by observation_weight

observation_weight = 0     no target. Inequality only:
                             V_throughput_obs_veh <= V <= V_max_feasible_veh
```

`V_assign_veh` and `V_from_assignment_veh` must not enter as observations under
any weighting. They are the quantity being estimated, not evidence about it.

---

## Limitations

**Links are not independent observations.** One TMC supplies several links, which
then share an identical speed profile, cut-off and episode — 252 links carry only
132 independent speed series, and one TMC covers as many as 10 links.
`links_sharing_this_tmc` and `tmc_code` are carried so rows can be grouped or
down-weighted.

**The window ends at 19:00** because the assignment has no night period. 33 links
still carry a queue there and 28 are still observed below cut-off at 18:45, so the
residual is real congestion. Its consequence is that `P_h_model` is censored on
most links.

**Volumes rest on S3 and on the free-flow speed**, not on the queue recurrence —
`V_throughput_obs` is a direct integral of speed-derived flow. But they inherit
any error in the fundamental diagram and in `v_f`. On the congested branch the S3
error is of the order of 20%.

**A single-link model cannot represent spillback.** A link can queue while its own
demand is well below its own capacity, because the queue reaches back from a
bottleneck downstream. Where the inferred demand disagrees with the assignment by
a large factor, spillback is a candidate explanation this dataset cannot separate
from a genuine volume error.

**Fourteen rows look miscoded rather than miscalibrated.** All I-66 EB in the AM,
they carry an assigned volume near 120 vehicles against an observed discharge
above 9,000 — a factor of roughly 79. At 20 vph/lane the assignment is effectively
not loading these links at all. Inspect them before fitting, or ODME will try to
force a large volume onto a path the network believes is unusable.

---

```powershell
python scripts/make_odme_link_dataset.py
```
