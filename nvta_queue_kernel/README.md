# NVTA single-link queue kernel

The part of the NVTA full-day queue model that goes into a dynamic network
loading: **given `lambda(t)` and `mu(t)`, return `Q(t)`, discharge flow, travel
time and `speed(t)`.**

Self-contained. Needs `numpy` and `pandas`, nothing else from this repository,
and no external data package.

```bash
python nvta_queue_kernel/reproduce.py
```

That runs one I-395 NB link and one I-66 EB link and compares every interval
against the published output. It exits 0 only if everything matches to 1e-9.
Current worst difference: **5.7e-14**.

---

## The model

```
out(t)    = min( mu(t), lambda(t) + Q(t)/dt )        veh/h
Q(t + dt) = max( 0, Q(t) + [lambda(t) - out(t)]*dt ) veh
TT(t)     = L/v_f + Q(t)/mu(t)                       h
v(t)      = L / TT(t)                                mph
```

`dt = 0.25 h`. `Q(06:00) = 0`. One continuous run 06:00-19:00; **nothing resets
at a period boundary**.

Read [`PORTING_NOTES.md`](PORTING_NOTES.md) before translating this. It covers
the index convention, the two incompatible definitions of "waiting time", the
per-lane/whole-link unit trap, and what to expect once a DNL supplies its own
`lambda`.

---

## Files

| File | What it is |
|---|---|
| `kernel.py` | `run_queue`, `queue_to_speed`, `run_link`. The model, with no I/O |
| `reproduce.py` | Runs the two cases and checks them against the published output |
| `PORTING_NOTES.md` | Every decision a C++ port has to make the same way |
| `data/link_26469_i395nb.csv` | 52 intervals: `lambda`, `mu`, geometry, observed speed |
| `data/link_31804_i66eb.csv` | same, for I-66 EB |
| `data/expected_output.csv` | published `Q`, outflow, delay, travel time, model speed |

The two data files are cut verbatim from
`outputs/nvta_queue/step8_speed_variants_15min.csv`, which carries all 252 links.

## The two cases

Chosen as the largest queue on each corridor, and they happen to cover both peaks:

| | I-395 NB link 26469 | I-66 EB link 31804 |
|---|---|---|
| TMC | 110P04130 | 110N04179 |
| Length, lanes | 0.20 mi, 6 | 1.10 mi, 4 |
| `v_f` (own observed p95) | 52.15 mph | 68.35 mph |
| `mu` in episode | 9,988 veh/h | 6,807 veh/h |
| Peak queue | 170.1 veh at **15:45 (PM)** | 331.4 veh at **08:00 (AM)** |
| Model speed at peak | 9.59 mph (observed 10.06) | 16.98 mph (observed 18.18) |
| Queue at 19:00 | 74.3 veh, still queued | 0.0 veh, cleared |

---

## Where the inputs come from, and where they do not have to

`lambda` and `mu` here are the ones the NVTA study produced from observed speed,
because that network has **no counted volume anywhere** — the assignment's link
table carries `obs_volume = -1` on all 756 link-periods. Steps 1-5 of
`scripts/queue_step*.py` exist only to manufacture them.

A DNL does not need any of that:

- **`lambda`** is what the DNL itself produces, by loading vehicles from OD,
  path and departure time onto the link.
- **`mu`** is already packaged in the Mode A external-service format at
  `outputs/nvta_service_profile/service_profile.csv` — 24,192 rows of
  `interval_id, link_id, mu_veh_per_hour` for all 252 links, with
  `time_horizon.csv` giving the interval clock.

---

## Full results for all 252 links

| Want | File |
|---|---|
| Observed and model `speed(t)`, `lambda`, `mu`, `Q`, outflow, travel time, in one row per link-interval | `outputs/nvta_queue/step8_speed_variants_15min.csv` (13,104 rows) |
| Per-link, per-period diagnostics | `outputs/nvta_queue_pm/nvta_queue_pm_link_full.csv` (756 x 62) |
| `mu(t)` in DNL-ready form | `outputs/nvta_service_profile/service_profile.csv` |
| How each step works, and which of its assumptions failed | `docs/QUEUE_STEPS_ZH.md` (Chinese), `docs/NVTA_PM_LINK_QUEUE.md` (English) |
| Symbols, units, evidence layers | `docs/VARIABLE_CONTRACT.md` |

Corridors: I-395 NB (29 links), I-395 SB (32), I-66 EB (82), I-66 WB (109), from
154 INRIX TMCs, average weekday over 23 October 2025 weekdays at 15 minutes.

**One TMC covers several links**, so 252 links carry only 154 independent speed
observations. Sample sizes must be quoted in TMCs, not links.
