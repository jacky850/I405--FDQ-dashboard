# D and V for four NVTA corridors

I-395 NB, I-395 SB, I-66 EB, I-66 WB — **104 TMCs, 61.6 miles**, average weekday
2025-10-06 to 10-10, 15-minute bins.

Built from RITIS speed plus `corridor_tmc_mapping.csv` and the constants in
`qvdf_selfdemo/config.py`. **No calibrated QVDF parameter is used** — D is
summed forward, not inverted out of the duration branch.

---

## How D and V are computed

**1. Flow from speed.** The S3 fundamental diagram, inverted onto the congested
branch, with `m = 4` so that `v_c = v_f/√2` = 49.5 mph at `v_f` = 70:

$$k(v) = k_c\left[\left(\frac{v_f}{v}\right)^{m/2} - 1\right]^{1/m}, \qquad q(t) = k\big(v(t)\big)\cdot v(t)$$

**2. Sum it.** D over the congested bins, V over the whole period:

$$D = \sum_{t\,:\,v(t)\,\lt\,v_{\text{cutoff}}} q(t)\,\Delta t \qquad\qquad V = \sum_{t \in \text{period}} q(t)\,\Delta t$$

Both in **vehicles**, with `v_cutoff = 0.70·v_f` = 49 mph and `Δt` = 15 min.

**3. Ratio.** D/C divides a period volume by an *hourly* capacity, so it carries
units of hours:

$$\frac{D}{C} = \frac{\bar q}{C}\times P$$

where P is the time below the cut-off. Values of 3–4 are ordinary.

## Results

Median link, on the pipeline clock (AM 5 h, MD 4 h, PM 6 h, NT 2 h).

| Corridor | Period | Congested | P median | **D/C** | **D** (veh/lane) | **V** (veh/lane) |
|---|---|---:|---:|---:|---:|---:|
| **I-395 NB** | AM | **20/20** | 3.00 h | 2.67 | 5,881 | 10,113 |
| (20 TMCs, 9.25 mi) | MD | 9/20 | 4.00 h | 3.44 | 7,576 | 8,487 |
| | PM | 16/20 | 5.38 h | 3.72 | 8,178 | 12,665 |
| | NT | 5/20 | 2.00 h | 1.89 | 4,150 | 4,177 |
| **I-395 SB** | AM | 5/21 | 3.75 h | 3.74 | 8,237 | 10,180 |
| (21 TMCs, 9.94 mi) | MD | 4/21 | 4.00 h | 3.99 | 8,771 | 8,416 |
| | PM | **19/21** | 3.75 h | 3.59 | 7,888 | 12,806 |
| | NT | 5/21 | 2.00 h | 1.99 | 4,387 | 4,202 |
| **I-66 EB** | AM | 24/36 | 2.75 h | 2.51 | 5,528 | 9,862 |
| (36 TMCs, 22.29 mi) | MD | 19/36 | 1.00 h | 0.99 | 2,173 | 8,290 |
| | PM | 31/36 | 3.75 h | 3.68 | 8,088 | 12,345 |
| | NT | 5/36 | 1.25 h | 1.25 | 2,748 | 3,943 |
| **I-66 WB** | AM | 14/27 | 2.00 h | 1.77 | 3,899 | 9,793 |
| (27 TMCs, 20.13 mi) | MD | 18/27 | 1.00 h | 0.97 | 2,131 | 8,484 |
| | PM | **27/27** | 2.00 h | 1.86 | 4,083 | 12,219 |
| | NT | 4/27 | 1.00 h | 1.00 | 2,199 | 4,020 |

![Results](figures/corridor_dv_results.png)

Per-TMC values, link totals, and the same table on the **assignment clock**
(AM 3 h / MD 6 h / PM 4 h / NT 11 h) are in
`outputs/nvta_corridors_dv_ritis/corridor_dv_by_tmc.csv`.

**Two checks.** Rebuilding I-395 NB from RITIS reproduces the handoff-derived
D/C to −5.2% / −0.8% / +4.0% / +1.3% across the four periods, on a different
link definition. And the directional pattern is right: NB is 20/20 congested in
AM, SB is 19/21 in PM; on I-66 the AM queue sits 20–40 mi out on EB while the PM
queue is corridor-wide on WB.

## D is solid. V carries a much wider error band.

Both come from the same q(t), but the inversion behaves differently on the two
branches of the fundamental diagram.

**Below the cut-off** the congested branch is steep and single-valued. Speed is
*set by* density there — spacing dictates how fast you can go — so
`v → k → q` is a real physical chain. D rests on that.

**Above the cut-off** it breaks. Drivers pick their own speed largely regardless
of how many others are on the road, so one speed is consistent with a wide band
of flows: 65 mph at 03:00 and 65 mph at 06:30 are completely different traffic.
The diagram returns one answer anyway.

Scored against measured counts on I-405 — 7 links × 12 weekly average-weekday
profiles, S3 with the standard exponent `m = 4`. **D and V are delivered per
period, so those are the rows that describe the deliverable**; the per-bin rows
below them are diagnostic, and show where the error lives.

| Period | **D** n | **D** MAPE | **D** bias | **V** n | **V** MAPE | **V** bias |
|---|---:|---:|---:|---:|---:|---:|
| **AM** | 26 | **6.1%** | +0.4% | 82 | **16.1%** | −14.7% |
| **MD** | 17 | **14.5%** | +9.2% | 82 | **16.8%** | −11.9% |
| **PM** | 4 | 45.1% | +42.9% | 82 | **18.6%** | −12.7% |
| **NT** | 1 | — | — | 82 | **40.9%** | +36.1% |

One observation is one link-week-period. Seven links across twelve weeks gives 84
link-weeks, less two where the maximum-flow bin sat above the 95th-percentile
speed and the diagram could not be fitted, so **V is scored on all 82 in every
period**. **D is scored only on those containing a congestion episode of at least
half an hour** — 26 of 82 in AM, 4 in PM — which is why its sample varies. An
observation with two episodes still counts once; D sums across both.

Errors are per observation, `(inferred − measured) / measured`. MAPE is the mean
of the absolute values; **bias is the median**, taken rather than the mean so a
single 200% case cannot set it.

For reference, the same data per 5-minute bin: 20.7% MAPE on congested bins,
84.6% on free-flow bins. The gap to the period rows is the bin errors
cancelling — they are scatter rather than a consistent lean, so summing 36–72 of
them leaves far less.

**Two things this table says that a pooled number would hide.**

**V is steady at 16–19% through AM, MD and PM, and only breaks down at night**
(40.9%). Its bias also changes sign — around −13% in the day, +36% at night — so
a pooled bias would average to near zero and imply an accuracy that is not there.
The daytime lean is mildly *low*, not high, which is why I would not describe V
as a bound in either direction. It does read high against the DTA assignment
(1.09–1.15× where congestion is heaviest, 1.3–1.9× where lighter), but neither
series is ground truth there, so that gap is an open question rather than a
correction.

**D is well tested in AM and barely tested in PM.** 26 AM cases at 6.1% is a
solid result. But these seven I-405 links are 97% free-flow bins in PM, so only
4 congestion episodes exist to score there and one at night — too few to conclude
anything, and the 45.1% should be read as an absence of evidence rather than
evidence of error. **That is a real gap, because PM is where the NVTA numbers are
largest** (I-66 EB is congested on 31 of 36 links in PM). Confirming D in a PM
peak needs a corridor that actually has one and has counts.

### D, checked the same way

![D and V against measured counts](figures/d_vs_counts.png)

Congestion episodes must last at least half an hour — the `MIN_EPISODE_H` rule
in `config.py`, which matters because a brief dip is not congestion and the
diagram reads any low speed as high density however few vehicles are behind it.

Pooling the weekly profiles above with 5 individual weekdays widens the sample to
**82 episodes across 23 links**, where D lands at **14.2% MAPE, +1.2% median
bias, 83% of cases within ±20%** — consistent with the 16.6% in the table, which
is the 7-link weekly subset alone.

![One speed, how many flows](figures/flow_information.png)

*Left: measured I-405 detector flow. At 65 mph the road carries anywhere from 4%
to 100% of that link's daily peak. Right: the NVTA series, which traces a single
curve because it is the diagram evaluated at the observed speed.*

## The question

**Is there any vehicle count on these corridors** — detector, tube, ramp — that
started as something being counted rather than a speed being converted?

I checked the dynamic-ODME files for this. They do not supply one: the
`observed` column in `linkflow_timedependent.csv` is identical to the handoff's
`count_total_15min` in **460 of 460** mainline link-bins, MAPE 0.000%,
correlation 1.000000. GEH is a median 0.16, so `assigned_odme` reproduces that
input, and the OD matrix tracks the on-ramp inflows to within 1.7%.

The one place a real count could still be is the **ramp flows** — 19 of 24
on-ramps peak above 100 vph, their time shapes are mutually uncorrelated
(mean pairwise r = 0.02), and total inflow correlates with corridor speed at
−0.67 rather than tracking it. If those are measured, conservation gives V
without the fundamental diagram at all. `departure_profile.csv` would settle it.

Failing that, an AADT or daily count per link would let me anchor the profile,
which is cruder but would pull most of the free-flow scatter out of V.

---

```powershell
python scripts/run_nvta_corridors_dv_from_ritis.py
python scripts/check_odme_provenance.py
```
