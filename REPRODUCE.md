# Reproducing these results

Two levels. **Level 1 needs nothing but this repository, and now covers every
result here.** The inputs that queue steps 1 and 5 used to take from an external
package are staged in `data/nvta_link_queue_inputs/` — 2.6 MB, gzipped and
filtered to the four studied corridors. Level 2 is only for pointing at the full
external package, to work on corridors outside that set.

One exception, stated plainly: `run_i405_multiweek_average_holdout.py` reads a
744 MB PeMS detector-state file that is not committed. Everything downstream of
its committed result table regenerates at level 1.

---

## Level 1 — clean clone, no external data

```bash
git clone https://github.com/jacky850/I405--FDQ-dashboard.git
cd I405--FDQ-dashboard
python -m venv .venv && . .venv/bin/activate      # Windows: .venv\Scripts\activate
python -m pip install -U pip
python -m pip install -e ".[test]"
pytest -q
```

Expected: **92 passed** from a clean clone. (A working tree with extra uncommitted files under `docs/` collects a few more cases of the period-clock check, which globs that directory.) No `PYTHONPATH` is required; `pyproject.toml` puts `src`
and the repository root on the path for the test run.

### The queue kernel, and the reproducible I-395 / I-66 example

```bash
python nvta_queue_kernel/reproduce.py
```

Runs the single-link queue on one I-395 NB link and one I-66 EB link, from
`lambda(t)` and `mu(t)` through `Q(t)`, travel time and `speed(t)`, and compares
every interval with the published output in
`outputs/nvta_queue/step8_speed_variants_15min.csv`.

Expected last line:

```
All values reproduce the published output (worst difference 5.684e-14, tolerance 1e-09).
```

See [`nvta_queue_kernel/README.md`](nvta_queue_kernel/README.md) and
[`nvta_queue_kernel/PORTING_NOTES.md`](nvta_queue_kernel/PORTING_NOTES.md).

### The multiweek QVDF holdout outputs and dashboard

Everything from `leave_one_week_out_qvdf_results.csv` onward regenerates without
raw PeMS:

```bash
python scripts/build_i405_observed_vs_inferred_d_v.py
python scripts/run_i405_forward_projection_speed.py
python scripts/build_i405_multiweek_dashboard_data.py
python scripts/stamp_dashboard_assets.py
pytest -q tests/test_dashboard_metrics.py
```

To view the dashboard, serve the repository root over HTTP — opening the file
directly gives the browser a `file://` origin and the payload script will not
load:

```bash
python -m http.server 8912
# then open http://localhost:8912/dashboard/qvdf_multiweek.html
```

### The whole NVTA queue chain, steps 1 to 8

All eight run with no configuration. Steps 1 and 5 read
`data/nvta_link_queue_inputs/`; the rest read the previous step's output.

```bash
python scripts/queue_step1_flow_from_speed.py
python scripts/queue_free_speed_audit.py
python scripts/queue_step2_service_rate.py
python scripts/queue_step3_speed_implied_queue.py
python scripts/queue_step4_arrival_rate.py
python scripts/queue_step5_volume_anchor.py
python scripts/queue_step6_run_queue.py
python scripts/queue_step7_queue_to_speed.py
python scripts/queue_step8_validation.py --period PM
```

`--period AM` and `--period MD` score the other two periods; the run window is
already the whole 06:00-19:00 day.

### What reruns bit-for-bit and what does not

Steps 1, 2, 3 reproduce the committed output to floating-point noise:

| Step | Worst difference vs committed |
|---|---:|
| 1, `step1_flow_average_weekday_15min.csv` | 6.8e-13 |
| 2, `step2_mu_15min.csv` | 1.8e-12 |
| 3, `step3_queue_target_15min.csv` | 1.8e-12 |

**Step 4 does not, and cannot be expected to.** Individual `lambda_vph` values
move by up to 4,024 veh/h between platforms, which propagates into steps 5-7.

This is the non-identifiability the method already reports, showing up in the
solver. `lambda` is fitted by `scipy.optimize.least_squares(method="lm")` against
a residual that is non-smooth by construction — it contains `abs`, `maximum`, and
the `min`/`max` of the queue recurrence — with 27 coefficients and only
**5.6% of bins identifiable**. On the other 94.4% the queue is identically zero
for any `lambda` below `mu`, so the residual is flat and a different MINPACK build
stops at a different, equally good point.

The fit is equally good, and every conclusion is unchanged. Regenerated on macOS
against the committed run:

| | Committed | Regenerated |
|---|---:|---:|
| links fitted / distinct TMCs | 76 / 44 | 76 / 44 |
| identifiable bins | 1,363 | 1,363 |
| residual RMSE, median | 1.98 veh | 1.98 veh |
| residual / peak, median | 0.0407 | 0.0400 |
| step 8 anchored episode MAE | 2.06 mph | 2.047 mph |
| episodes observed / matched / invented | 47 / 46 / 0 | 47 / 46 / 0 |
| P, T2, v(T2) MAE | 0.508 h, 0.0 min, 0.349 mph | identical |

So: **quote the conclusions, not the per-bin `lambda`.** A `lambda` on an
unidentifiable bin is one member of a set the data cannot distinguish between,
and the committed file records one arbitrary member of that set.

Pinning it exactly would need a deterministic solver — a convex reformulation, or
a fixed-seed global search — which is a modelling change, not a packaging one.

---

## Level 2 — pointing at the full external package

Only needed for corridors outside the four staged ones. The default already
resolves to `data/nvta_link_queue_inputs/`.

No script carries a personal path. Override the source one of three ways,
checked in this order:

```bash
# 1. on the command line
python scripts/queue_step1_flow_from_speed.py --shared /path/to/link-queue-simulation

# 2. in the environment
export FDQ_LINK_QUEUE_SIMULATION=/path/to/link-queue-simulation

# 3. in a gitignored local config
cp configs/data_sources.json configs/data_sources.local.json
# then set sources.link_queue_simulation.path
```

If a source is unset and has no committed default, the script exits with the
three options above and the files it expected, rather than a missing-path
traceback.

The package must contain, with `.csv` or `.csv.gz`:

```
tmc-15min-speed/<CORRIDOR>/Readings.csv
tmc-matching/canonical_node_pair_tmc-1v1.csv
TAPLite-model-input-output-subset/{am,md,pm}/link_performance.csv
```

To re-stage a different corridor set into the repository:

```bash
python scripts/stage_nvta_inputs.py --shared /path/to/link-queue-simulation
```

That filters the network tables to the links the chosen corridors map to,
gzips everything, and writes a manifest with row counts and the SHA-256 of each
source file. Reading the unfiltered package takes a while; on a cloud-synced
folder the files may have to download first.

The PeMS multiweek holdout (`scripts/run_i405_multiweek_average_holdout.py`)
likewise needs its raw detector states; pass `--raw-file`, or configure
`pems_i405_raw` the same way.

---

## What is not reproducible from here, and why

| | Status |
|---|---|
| Queue steps 1-3 | reproducible at level 1, to 1e-12 |
| Queue steps 4-8 | runnable at level 1; conclusions reproduce, per-bin `lambda` does not — see above |
| The queue kernel example | reproducible at level 1, to 5.7e-14 |
| Multiweek holdout downstream of `leave_one_week_out_qvdf_results.csv` | reproducible at level 1 |
| `run_i405_multiweek_average_holdout.py` itself | needs raw PeMS detector states |
| A C++ build of the kernel | does not exist; see `PORTING_NOTES.md` section 0 |

---

## Conventions that will change your numbers if you get them wrong

Full list in [`docs/VARIABLE_CONTRACT.md`](docs/VARIABLE_CONTRACT.md). The three
that have actually caused defects here:

- `queue[i]` is the queue at the **start** of interval `i`.
- `mu` is **whole-link**, already multiplied by lanes.
- AM is **06:00-09:00**, and a period boundary never resets a queue.
