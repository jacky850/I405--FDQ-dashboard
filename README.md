# I-405 Full-Day Single-Link Queue Reconstruction

This branch is a focused Stage-A prototype for recovering a **continuous
full-day residual queue** on one freeway link. It uses PeMS because PeMS
provides speed and flow at the same five-minute resolution: speed is used to
identify the congestion episode, while observed upstream, ramp, and downstream
flows provide an independent vehicle-count reference for validating the queue.

The main design requirement is that the 24-hour state is continuous. AM, MD,
PM, NT1, and NT2 are labels for reporting only; they are not independent queue
simulations, and the queue is never reset merely because a period boundary is
crossed.

## Dashboard

- [Dashboard source](dashboard/full_day_residual_queue.html)

The third-party branch preview was removed because its external-content
confirmation page can enter a refresh loop in an embedded browser. The public
GitHub Pages URL will be added after these dashboard assets are synchronized to
the repository's Pages branch. The local preview instructions are provided
under [Reproduce the result](#reproduce-the-result).

The dashboard focuses on the main evidence: the full-day reporting-period
definition, the count-based residual queue from formation to dissipation, and
the observed speed episode with T0, T2, T3, and P. AM and MD use different
background colors. The 10:00 line shows the period handoff, where a nonzero
queue demonstrates that the state is carried into the next period.

## Current case

| Item | Value |
|---|---:|
| Date | 2025-07-29 |
| Time zone | America/Los_Angeles |
| Resolution | 5 minutes, 288 bins |
| Target/downstream link | L405S-004 |
| Upstream link | L405S-041 |
| Upstream mainline detector | 1201497 |
| On-ramp detector | 1201517 |
| Downstream detector | 1201525 |
| Segment length | 1.480596 km |

This is one **observed Tuesday**, not an average-weekday profile. A real day was
selected deliberately because the present task is to demonstrate whether a
physical queue can survive a reporting-period boundary. Average-weekday and
multi-day tests should be added after this single-day conservation test is
stable.

The repository contains a minimal reproducible PeMS input containing only the
three selected detectors for this date:

```text
data/pems_single_link_2025-07-29_L405S-004.csv.gz
```

Each detector has all 288 five-minute records. The input follows the original
PeMS station five-minute layout and includes timestamp, detector metadata,
five-minute flow, occupancy, speed, and percent observed. Flow is converted
from vehicles per five-minute bin to veh/h inside the script; speed is already
in mph.

## Computational pipeline

```mermaid
flowchart LR
    S["Downstream speed"] --> E["Detect T0, T2, T3"]
    U["Time-shifted upstream flow"] --> A["Observed arrival lambda(t)"]
    R["On-ramp flow"] --> A
    D["Downstream flow"] --> M["Observed discharge mu(t)"]
    A --> C["Cumulative vehicle conservation"]
    M --> C
    C --> Q["Drift-corrected residual queue Q(t)"]
    E --> Q
    Q --> B["Carry Q across AM, MD, PM boundaries"]
```

### 1. Build a single 24-hour clock

All three detector series must contain the same 288 timestamps. The upstream
mainline flow is shifted by the approximate free-flow travel time from the
upstream detector to the downstream detector. The observed arrival and service
rates are then

$$
\lambda_{\mathrm{obs}}(t)
=q_{\mathrm{upstream}}(t-\tau)+q_{\mathrm{ramp}}(t),
\qquad
\mu_{\mathrm{obs}}(t)=q_{\mathrm{downstream}}(t).
$$

For this test, the ramp has observed flow, so no ramp imputation is used.

### 2. Identify the congestion episode from speed

The downstream speed is smoothed with a centered three-bin median. The
free-flow reference is the 95th percentile of the full-day smoothed speed.
Congestion begins when speed falls below 70% of that reference and ends after
two consecutive bins at or above 75%. Episodes shorter than 20 minutes are
discarded.

For the selected day:

| Parameter | Result |
|---|---:|
| Free-flow speed | 70.465 mph |
| Entry threshold | 49.326 mph |
| Exit threshold | 52.849 mph |
| T0 | 07:25 LA time |
| T2, minimum-speed time | 09:55 LA time |
| T3 | 10:25 LA time |
| Congestion duration | 185 minutes |
| Minimum speed | 10.7 mph |

The episode is asymmetric: T2 is the observed minimum-speed bin and T0/T3 are
detected independently. No artificial symmetry around T2 is imposed.

### 3. Recover the count-based reference queue

Vehicle conservation is integrated across the entire day with
$\Delta t=5/60$ hours:

$$
C_{k+1}=C_k+
\left[\lambda_{\mathrm{obs}}(k)-\mu_{\mathrm{obs}}(k)\right]\Delta t.
$$

Upstream and downstream detectors can have a small persistent count mismatch.
If this detector drift is accumulated for many hours it can look like a large
queue even during free flow. To avoid that artifact, the implementation uses
one-hour free-flow windows before and after the detected episode, estimates a
linear baseline $B_k$ between their median cumulative-count levels, and defines

$$
Q_k^{\mathrm{count}}=\max\left(0,\ C_k-B_k\right).
$$

This correction removes only the measured linear detector drift. It does not
fit the shape or peak of the queue. Speed determines when an episode is active,
but AM/MD/PM boundaries do not reset $Q_k$.

### 4. Carry the residual queue across periods

The queue recurrence is one continuous state equation:

$$
Q_{k+1}=\max(0,\;Q_k+(\lambda_k-y_k)\Delta t).
$$

where the realized outflow is bounded by available vehicles and service rate:

$$
y_k=\min(\mu_k,\;\lambda_k+Q_k/\Delta t).
$$

At 10:00, the reporting label changes from AM to MD, but the count-based queue
is still **255.44 vehicles**. The queue reaches **354.14 vehicles** at 09:00 and
is cleared only after the speed-recovery gate, not at the period boundary.

## How this result is validated with PeMS

PeMS makes this case especially useful because the model does not need to
pretend that speed alone is ground truth. It provides three complementary
checks.

### A. Detector coverage and topology check

The median percent-observed value is 100% for the upstream, ramp, and downstream
detectors. The arrival boundary contains the upstream mainline plus the on-ramp;
the discharge boundary is the downstream mainline detector. Omitting the ramp
would violate conservation for this segment.

### B. Independent cumulative-count queue

The primary queue is calculated directly from observed arrival and discharge
counts. It is therefore the PeMS reference against which a speed-implied queue
can be judged. Its maximum is 354.14 vehicles and its value at the AM-to-MD
boundary is 255.44 vehicles.

### C. Speed-implied diagnostic comparison

The CSV also retains an experimental speed-delay queue:

$$
Q_k^{\mathrm{speed}}
=\mu_k\max\left(0,
\frac{L}{v_k}-\frac{L}{v_k^{\mathrm{baseline}}}
\right).
$$

This branch produces a maximum of 404.54 vehicles. During the episode its MAE
against the count-based queue is 81.72 vehicles, correlation is 0.485, and the
two peak times differ by 60 minutes. These values show that speed captures the
broad buildup and dissipation pattern but does **not** yet recover the physical
queue accurately enough to replace observed counts.

The very small forward-closure error and the 0.176 mph congested reconstructed-
speed MAE are algebraic consistency checks: the same speed-delay relationship
is inverted and then run forward. They confirm that the recurrence is coded
consistently, but they are not independent evidence that the inferred queue is
correct. The independent evidence is the count-based comparison above.

## Why the speed-implied branch is difficult

Several limitations matter before this method can be transferred to speed-only
data:

1. **Flow is not uniquely identifiable from free-flow speed.** Many demand
   levels can produce nearly the same high speed, so a free-flow link needs a
   prior, assignment volume, or an abstention rule.
2. **Delay is not identical to the number of queued vehicles.** The simple
   $\mu\Delta TT$ expression compresses spatial queue propagation and detector
   location effects into one point-queue approximation.
3. **Detector drift accumulates.** A small persistent difference between
   upstream and downstream counts can create a false queue unless conservation
   is corrected using free-flow baselines.
4. **Boundary topology matters.** On-ramps, off-ramps, HOV/HOT lanes, and
   unmatched detector coverage must be included or explicitly modeled.
5. **Travel-time alignment matters.** Upstream flow must be shifted before it
   is compared with downstream discharge.
6. **Inverse/forward reconstruction can be circular.** Reconstructing speed
   with parameters derived from that same speed is a closure check, not a true
   holdout validation.

## Expected adaptation for NVTA / INRIX

NVTA/INRIX is expected to provide time-dependent speed but not the same
upstream, ramp, and downstream flow measurements. Therefore the count-based
PeMS reference cannot be used directly in deployment. The recommended transfer
path is:

1. Expand this PeMS experiment across many links, days, link types, and queue
   shapes.
2. Calibrate a speed-to-queue/service model against the PeMS count-based
   reference, using leakage-safe holdout links or dates.
3. Freeze the calibrated parameters and episode rules before applying them to
   INRIX speed.
4. Supply $\mu(t)$ from calibrated capacity/QVDF parameters or trusted network
   attributes; infer a smooth $\lambda(t)$ under the full-day conservation
   constraints.
5. Add a separate free-flow branch using a historical time-of-day or Cube/QVDF
   volume prior. If no defensible prior exists, return an interval or abstain
   rather than claim a unique flow.
6. Audit link matching before inference, especially general-purpose versus
   HOV/HOT/APV links, ramps, direction, and link length.
7. Validate corridor-level propagation only after the single-link PeMS holdout
   tests are stable.

In short, PeMS supplies the ground truth needed to learn and test the mapping;
INRIX deployment will use the frozen mapping plus network priors, not hidden
INRIX flow.

## Reproduce the result

From the repository root, run:

```powershell
python scripts/run_pems_full_day_single_link.py `
  --raw-file data/pems_single_link_2025-07-29_L405S-004.csv.gz `
  --output-dir outputs/pems_full_day_residual_queue_2025-07-29_L405S-004

python scripts/build_full_day_residual_dashboard_data.py `
  --input-dir outputs/pems_full_day_residual_queue_2025-07-29_L405S-004 `
  --output dashboard/full_day_residual_data.js

python -m http.server 8772
```

Then open:

```text
http://127.0.0.1:8772/dashboard/full_day_residual_queue.html
```

Required Python packages are `numpy` and `pandas`. The dashboard itself is
static HTML/CSS/JavaScript and uses ECharts from a public CDN.

## Files to continue from

| File | Purpose |
|---|---|
| `scripts/run_pems_full_day_single_link.py` | Main 24-hour episode, conservation, queue, and validation pipeline |
| `data/pems_single_link_2025-07-29_L405S-004.csv.gz` | Minimal reproducible three-detector PeMS input |
| `outputs/pems_full_day_residual_queue_2025-07-29_L405S-004/full_day_timeseries_5min.csv` | Complete 288-bin output with speed, flow, lambda, mu, queue, and diagnostics |
| `outputs/pems_full_day_residual_queue_2025-07-29_L405S-004/congestion_episodes.csv` | T0, T2, T3, duration, queue peaks, and comparison metrics |
| `outputs/pems_full_day_residual_queue_2025-07-29_L405S-004/summary.json` | Machine-readable case summary and boundary states |
| `scripts/build_full_day_residual_dashboard_data.py` | Converts the CSV/JSON outputs into static dashboard data |
| `dashboard/full_day_residual_queue.html` | Dashboard entry point |

## Scope and next step

This branch proves the full-day state logic for **one PeMS link and one day**.
It does not yet claim an all-link or NVTA-ready speed-only estimator. The next
scientific step is to repeat the independent count-based validation on multiple
PeMS links/days, estimate how error changes with topology and episode shape,
and then design the calibrated speed-only NVTA branch.
