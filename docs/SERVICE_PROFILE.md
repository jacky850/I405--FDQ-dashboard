# External service profile, Mode A

`mu(t)` for all 252 NVTA links, in the `service_profile_source = external` format
from the validation-ladder note, plus a single genuine link record for
`G1_1LINK_1PERIOD_EXTERNAL_MU`.

| File | Rows | Content |
|---|---:|---|
| `outputs/nvta_service_profile/service_profile.csv` | 24,192 | `interval_id, link_id, mu_veh_per_hour` — exactly the three columns of the Mode A spec |
| `outputs/nvta_service_profile/time_horizon.csv` | 96 | what each `interval_id` means |
| `outputs/nvta_service_profile/g1_service_profile.csv` | 16 | the PM slice for the G1 link, ready to run |
| `outputs/nvta_service_profile/g1_link_record.csv` | 1 | that link's genuine attributes |

---

## Interval numbering

`interval_id` counts quarter hours from midnight, 1-based, so interval 1 is
00:00–00:15 and interval 61 is 15:00–15:15. That is carried in
`time_horizon.csv` rather than left implicit:

| interval_id | start_time | end_time | start_minute | period |
|---:|---|---|---:|---|
| 25 | 06:00 | 06:15 | 360 | AM |
| 37 | 09:00 | 09:15 | 540 | MD |
| 61 | 15:00 | 15:15 | 900 | PM |
| 77 | 19:00 | 19:15 | 1140 | NT |

Periods follow the assignment's own clock: AM 06:00–09:00, MD 09:00–15:00,
PM 15:00–19:00.

## How mu was derived

Two regimes per link:

```
outside a congestion episode   mu = lane_capacity * lanes
inside a congestion episode    mu = median of the speed-implied flow over that
                                    episode's intervals
```

`lane_capacity` is read from the assignment's link table (1900 or 2000 vph/lane
here). It is an input rather than an estimate: the estimator returns `0.998 * C`
for any assumed `C` between 1800 and 2400, because the S3 fundamental diagram
returns exactly `C` at `0.707 v_f` while the congestion cut-off sits at
`0.70 v_f`, so the "maximum flow before breakdown" window necessarily sweeps
that point.

Only the ratio between the regimes is measured. The capacity drop
`1 - mu_queued/mu_free` is 6.83% at the median across 87 episodes, against the
10% previously assumed, and it is independent of the assumed capacity.

`mu` is defined on all 96 intervals of all 252 links, with no gaps. A link takes
one distinct value if it never congests, two if it has a single episode, and
three where it has both a morning and an evening episode with different queued
rates:

| Distinct `mu` values | Links |
|---:|---:|
| 1 — never congests | 176 |
| 2 — one episode | 65 |
| 3 — two episodes, different queued rates | 11 |

---

## The G1 case

**Link 26776, I-395 SB, PM, intervals 61–76.**

Chosen because its assigned volume agrees with the observed discharge, its
episode opens and closes inside the run window, and its capacity drop is
unremarkable — so nothing about the link itself is unusual enough to confound a
loading test.

| | |
|---|---|
| Geometry | 4 lanes, 0.25 mi |
| Free-flow speed (observed p95) | 63.78 mph |
| Congestion cut-off | 44.65 mph |
| `mu_free` | 7,600 vph |
| `mu_queued` | 6,969 vph (drop 8.3%) |
| `V_assign` for PM | 25,317 veh |
| Observed discharge while queued | 24,839 veh — **ratio 1.02** |
| Observed episode | P = 3.57 h, v(T2) = 29.0 mph |
| Physical storage | 200 veh |

Its service profile is a clean step, which is the shape a loading test wants:

```
interval_id, link_id, mu_veh_per_hour
61, 26776, 7600.00
62, 26776, 6969.08
...                    <- 6969.08 through interval 75
76, 26776, 7600.00
```

`g1_link_record.csv` carries the full row, including both free-flow speeds, both
volumes, the observed and reconstructed episode parameters, and the queue peak.

**On the queue peak in that record.** `queue_peak_model_veh` is 33 vehicles, but
that is what *our* arrival profile produced — the one fitted to the observed
speed. It is not the expected answer for G1, where the OD and departure profile
are synthetic. It is a reference point for G2, where the only thing that changes
is the source of `mu(t)`.

---

## What is not in here

The synthetic side of G1 — `demand.csv`, `demand_profile.csv`, the OD pair —
is not supplied, since the point of the gate is that those are known and
controlled rather than inferred.

`node.csv`, `link.csv` and `link_period.csv` are not emitted in the engine's own
schema either, because that schema is not visible from this side.
`g1_link_record.csv` carries the attribute values needed to populate them —
`from_node_id`, `to_node_id`, `lanes`, `length_mi`, `lane_capacity`,
`free_speed_mph` — under our column names.

---

```powershell
python scripts/make_service_profile.py
```

Related: [`ODME_LINK_DATASET.md`](ODME_LINK_DATASET.md) documents the full link
dataset these values were drawn from.
