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

## D is solid. V is an upper bound.

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
profiles, 23,616 five-minute bins, S3 with the standard exponent `m = 4`:

| | n | MAPE | median bias | bins off by >50% |
|---|---:|---:|---:|---:|
| Congested bins | 890 | **20.7%** | +5.4% | 11.8% |
| Free-flow bins | 22,726 | **84.6%** | −4.2% | 30.7% |

The right panel above shows how much that matters: **40–94% of V comes from
free-flow bins**, depending on corridor and period. Only I-395 NB in AM gets
below half.

The per-bin errors do largely cancel when summed, so period volume comes out far
better than 84.6% suggests — **23.1% MAPE at −6.4% bias** on the same profiles.
V is usable at the period level with that error attached. It is still not a
measurement, and against the DTA assignment it reads 1.09–1.15× high where
congestion is heaviest and 1.3–1.9× high where it is lighter.

### D, checked the same way

![D and V against measured counts](figures/d_vs_counts.png)

Restricting to congestion episodes of at least half an hour — the
`MIN_EPISODE_H` rule in `config.py`, which matters because a brief dip is not
congestion and the diagram reads any low speed as high density — D lands at
**14.2% MAPE, +1.2% median bias, 83% of cases within ±20%** across 82
link-periods on 23 links. V on the same links is 41.2% MAPE.

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

Failing that, an AADT or daily count per link would let me rescale the profile,
which is cruder but would turn V from a ceiling into an estimate.

---

```powershell
python scripts/run_nvta_corridors_dv_from_ritis.py
python scripts/check_odme_provenance.py
```
