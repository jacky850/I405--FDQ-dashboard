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

Expected: **94 passed**. No `PYTHONPATH` is required; `pyproject.toml` puts `src`
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

Regenerated output matches what is committed to within floating-point noise:
step 1 to 6.8e-13, step 5 to 1.8e-12.

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
| Queue steps 1-8 | reproducible at level 1 |
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
