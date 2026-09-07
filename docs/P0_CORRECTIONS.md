# P0 corrections: what changed, and what it changed

Against the action plan's Issues 01, 03, 04 and most of 07. Scope-frozen: no
new corridor, model layer, dashboard or sensitivity study.

---

## 1. `k_d` was being reported as the observed `D/C`

`scripts/build_i405_observed_vs_inferred_d_v.py:86` mapped

```python
"d_over_c_observed": raw["k_d_observed"]
```

`k_d` is the peak-load factor `D/(V/H)`: how far the peak hour rises above the
period average. `D/C` is the peak demand rate over nominal capacity. The
comparison put an inferred `D/C` against an observed peak-load factor.

They are not close, and not the same shape:

| | median | range |
|---|---:|---:|
| `k_d_observed` | 1.069 | 1.024 – 1.259 (never below 1) |
| true `dc_rate_observed` | 0.990 | 0.611 – 1.289 (straddles 1) |

**Fix.** Three fields where there was one:

```python
"peak_load_factor_kd_observed": raw["k_d_observed"],
"dc_rate_observed": raw["observed_peak_1h_demand_veh_h"] / raw["capacity_vph"],
"dc_rate_inferred": raw["D_hat_veh_h"] / raw["capacity_vph"],
```

`k_d` is now reported on its own and never against an inferred `D/C`.

**Added:** `assert_capacity_is_training_only()` recomputes the leave-one-week-out
median of `capacity_proxy_week_p95_vph` and requires the stored `capacity_vph` to
match. It passes on all 168 cases, so the capacity in `dc_rate_observed` provably
never saw holdout flow.

An earlier draft of that assertion flagged 24 false positives by testing against
the all-week median. Dropping one week from an odd-sized set often leaves the
median where it was, so that test had no content; only the recomputed
leave-one-out value does.

### Before / after

| Metric | Before | After | Why |
|---|---:|---:|---|
| `demand_D` MAPE, supported | 15.96% | 15.96% | unchanged |
| `volume_V` MAPE, supported | 16.88% | 16.88% | unchanged |
| `volume_V` median APE | 14.51% | 14.51% | unchanged |
| `d_over_c` MAPE | 17.15% | **removed** | was comparing two different quantities |
| `dc_rate` MAPE | – | **15.96%** | new, correct quantity |
| Coverage (168 / 31 / 21) | same | same | unchanged |

**No accuracy claim moved.** The 17.15% figure was never a real metric. The new
`dc_rate` MAPE equals the demand MAPE exactly, because both sides divide by the
same training capacity — it is a restatement, not a third independent check, and
the dashboard now says so.

---

## 2. The dashboard showed the speed MAPE as the volume MAPE

`dashboard/qvdf_multiweek.html:30` carried

```html
<article><span>Supported MAPE</span><strong>16.51%</strong>
         <small>conditional on both gates</small></article>
```

**16.51%** is `forward_projection_speed_summary.json` →
`supported_cases.period.forward.mape_pct`: the whole-period 5-minute
**speed-profile** MAPE. The supported **volume** MAPE is **16.88%**, in a
different file. Under the heading "Supported MAPE" next to coverage, it read as
the volume number.

A second tile hard-coded a median APE of **14.71%** against a generated
**14.51%**.

**Fix.** The headline section is now empty markup with an id, rendered by
`renderHeadline()` from `window.QVDF_MULTI`. Five tiles, with the two accuracy
metrics labelled and separated, and coverage stated on each:

| Tile | Value | Source |
|---|---|---|
| Eligible cases | 168 | `comparison.coverage.total_cases` |
| Final coverage | 12.50% | `comparison.coverage.supported_pct` |
| **Volume MAPE** | **16.88%** | `comparison.supported_cases.volume_V.mape_pct` |
| Volume median APE | 14.51% | `comparison.supported_cases.volume_V.median_ape_pct` |
| **Speed-profile MAPE** | **16.52%** | `projection.supported_cases.period.forward.mape_pct` |

16.52 rather than 16.51 is the same number rounded from 16.516 rather than
truncated.

**Test.** `tests/test_dashboard_metrics.py`, 25 cases: the payload equals the
source JSON; every value the headline reads exists in both and agrees to 1e-6;
no percentage literal survives in the headline markup; `16.51%` and `14.71%`
appear nowhere in the page; the removed `d_over_c` block has not returned; and
`k_d`'s minimum is `>= 1`, which fails if the field ever carries something else.

---

## 3. AM was documented as 06:00–10:00 and run as 06:00–09:00

`docs/MULTIWEEK_AVERAGE_HOLDOUT_V1.md:30` said 06:00–10:00. The code has always
used `PERIODS = {"AM": (6.0, 9.0), "PM": (15.0, 19.0)}`, and the dashboard has
always used `PERIOD_WINDOW={AM:[360,540]}`.

**This was a documentation defect only. No result changes.** The document now
states 06:00–09:00 and says why the old value is named in the correction note.

`docs/VARIABLE_CONTRACT.md` section 4 is now the one authoritative clock.
`tests/test_period_clock.py` checks the contract, the runner, the dashboard and
every file in `docs/` against each other.

---

## 4. Personal absolute paths in published artefacts

Ten committed artefacts recorded a provenance path under a home directory,
including `dashboard/data.js`, **which is served on GitHub Pages**.

**Fix.**

- `src/fdqbench/paths.py`: `as_repo_relative()` for anything written into an
  artefact, and `resolve_source()` for locating external inputs.
- `configs/data_sources.json` declares each external input, with `path: null`.
  Resolution order is command-line argument, then `FDQ_<NAME>`, then
  `configs/data_sources.local.json` (gitignored), then this file. An unset source
  exits with those three options and the files it expected, not a traceback.
- `scripts/scrub_personal_paths.py` rewrote the ten artefacts. It touches
  provenance strings only; no computed value changes.
- Personal-path defaults removed from `queue_step1`, `queue_step5`,
  `queue_free_speed_audit`, `make_odme_link_dataset`, and
  `run_i405_multiweek_average_holdout` (the one the plan names).

**Not finished:** 15 older scripts still hard-code a path. None is on the path
that regenerates any published result. CI lists them and fails only on artefacts.

The first scrub pass was wrong in a way worth recording: the tail pattern stopped
at whitespace, and these paths contain spaces (`ASU Dropbox`), so it rewrote the
first segment and left the rest. Fixed by running the tail to the enclosing
quote, plus a repair pass over the half-rewritten strings.

---

## 5. `pytest` needed `PYTHONPATH` set by hand

Three of the four existing test modules failed to import `fdqbench` from a plain
checkout.

**Fix.** `[tool.pytest.ini_options] pythonpath = ["src", "."]` and a
`test` extra. `pip install -e ".[test]" && pytest -q` now works from a fresh
clone: **92 passed**, including the new contract, kernel and staged-input tests.

---

## 6. `pems-cbi-dv` was a live git repository nested in this working tree

With its own `.git`, on `main`, carrying uncommitted changes, and untracked here.
A `git add -A` would have committed it as a broken gitlink. Now ignored, with the
reason in `.gitignore`. It belongs beside this repository, not inside it.

---

## 7. The severity equation used the exit threshold without saying so

Issue 04: the QVDF severity equation may not silently use the episode exit
threshold as the capacity speed. It did.
`run_i405_multiweek_average_holdout.py` stored `episode["exit_threshold_mph"]`
(`0.75 * v_f`) in a field called `cutoff_speed_vc_mph`, and the severity equation
read that field as the reference in `z = v_ref / v(T2) - 1`. The S3 capacity
speed is `v_f / sqrt(2)` = `0.707 * v_f`. The same substitution was in
`run_i405_qvdf_speed_severity_gate.py:89`.

**Fix.** Four speeds, each named for what it is, emitted on every episode row:

```
capacity_speed_mph          = v_f / sqrt(2)      0.7071 v_f
episode_entry_speed_mph     = 0.70 * v_f
episode_exit_speed_mph      = 0.75 * v_f
qvdf_reference_speed_mph    the one the severity equation used
qvdf_reference_speed_source which of the above that was
```

`--qvdf-reference-speed {episode_exit,capacity_speed,episode_entry}` selects it.
The default is `episode_exit`, so **every published number is unchanged**:
volume MAPE 16.8757%, coverage 168 / 31 / 21, 7 speed-gate and 3 duration-gate
failures, all identical to the previous run.

`legacy_cutoff_speed_vc_mph` is retained for one release and asserted equal to
`episode_exit_speed_mph`, which records exactly what the old field held.

The episode detector now also emits `capacity_speed_mph`. Hysteresis is
untouched: entry stays 0.70, exit stays 0.75.

### What the alternative would do

Ran end to end with `--qvdf-reference-speed capacity_speed`, 31 episode cases:

| | `episode_exit` (default) | `capacity_speed` |
|---|---:|---:|
| median `v_ref` | 51.96 mph | 48.99 mph |
| median observed `z` | 0.4244 | 0.3429 |
| median calibrated `f_p` | 0.09918 | **0.06962** |
| speed-gate failures | 7 | 6 |
| supported cases | 21 | 21 |
| `v(T2)` MAE | 2.206 mph | 2.125 mph |
| volume MAPE | 16.876% | 16.876% |

**`f_p` moves 30%; the reported accuracy barely moves at all.** Volume MAPE is
identical because the duration branch never touches `v_ref`. So the convention
was never going to show up as a bad result — it would only have shown up as an
`f_p` that could not be compared with anyone else's. That is the reason it had to
be declared rather than left implicit.

Switching the default is not part of this release. On these numbers the case for
switching is real but weak, and it would move `f_p` in a report that already
quotes it.

---

## 8. The NVTA inputs are now in the repository

Queue steps 1 and 5 read an external `link-queue-simulation` package at a
hard-coded Windows path. Everyone else could run steps 2-4 and 6-8 from committed
outputs, but nobody could rerun the chain from observed speed.

`scripts/stage_nvta_inputs.py` copies what those two steps read into
`data/nvta_link_queue_inputs/`, mirroring the external layout so one code path
reads either:

| | Rows kept | Size |
|---|---:|---:|
| I-395 NB / SB readings | 46,365 / 44,157 | 0.3 / 0.3 MB |
| I-66 EB / WB readings | 125,856 / 123,648 | 0.9 / 0.8 MB |
| TMC-to-link matching | 285 of 5,578 | 0.03 MB |
| Assignment link tables, AM/MD/PM | 285 of 5,578 each | 0.1 MB each |
| **Total** | | **2.6 MB** |

35 MB of source becomes 2.6 MB: the network tables are filtered to the links the
four corridors map to, and everything is gzipped. `fdqbench.paths.table()`
resolves `.csv` or `.csv.gz`, so no caller had to change. `manifest.json` records
row counts and the SHA-256 of every source file.

**Verified end to end with nothing configured** — no argument, no environment
variable, no local config:

| Step | Against committed output |
|---|---:|
| 1, `step1_flow_average_weekday_15min.csv` (24,192 rows) | worst difference **6.8e-13** |
| 5, `step5_lambda_anchored_15min.csv` (13,104 rows) | worst difference **1.8e-12** |
| 5, `step5_volume_anchor_by_link.csv` (756 rows) | worst difference **3.6e-12** |

Step 5's reported counts are identical to the published ones: AM 226 inside /
22 below / 4 above, MD 239 / 12 / 1, PM 213 / 34 / 5, 60 bins clipped at `mu_free`
on 5 links, 17,826 veh not placed.

`--shared` still points at the full external package for corridors outside the
staged four.

### What running the whole chain from a clean clone exposed

Cloning the branch fresh and running steps 1-8 with nothing configured works, and
turned up something worth stating rather than glossing:

**Steps 1-3 reproduce to 1e-12. Step 4 does not, by up to 4,024 veh/h on
individual `lambda_vph` values, and that propagates into steps 5-7.**

`lambda` is fitted with `scipy.optimize.least_squares(method="lm")` against a
residual that is non-smooth by construction — `abs`, `maximum`, and the `min`/`max`
inside the queue recurrence — over 27 coefficients, with only **5.6% of bins
identifiable**. On the other 94.4% the queue is identically zero for any `lambda`
below `mu`, so the residual surface is flat there and a different MINPACK build
halts at a different, equally good point.

The fit quality and every conclusion are unchanged:

| | Committed (Windows) | Regenerated (macOS) |
|---|---:|---:|
| links fitted / distinct TMCs | 76 / 44 | 76 / 44 |
| identifiable bins | 1,363 | 1,363 |
| restarts needed | 2 | 2 |
| residual RMSE, median | 1.98 veh | 1.98 veh |
| residual / peak, median | 0.0407 | 0.0400 |
| step 8 anchored episode MAE | 2.06 mph | **2.047 mph** |
| episodes observed / matched / invented | 47 / 46 / 0 | 47 / 46 / 0 |
| P / T2 / v(T2) MAE | 0.508 h / 0.0 min / 0.349 mph | identical |

This is not a defect introduced here — it is the documented non-identifiability
appearing in the solver. It does change what may be claimed: **the conclusions
are reproducible, the per-bin `lambda` is not.** A `lambda` on an unidentifiable
bin is one arbitrary member of a set the data cannot distinguish between, and the
committed file records one such member.

Pinning it would take a deterministic solver — a convex reformulation, or a
fixed-seed global search. That is a modelling change and is out of scope here.
Recorded in `REPRODUCE.md` so nobody reads a `lambda` diff as a regression.

Redistribution of the INRIX readings inside this repository was authorised by the
project owner; the provenance is recorded in the staging script's docstring and
in the manifest.

---

## 9. Not yet covered

| Plan issue | Status |
|---|---|
| 01 variable contract | `docs/VARIABLE_CONTRACT.md` written; `pems-cbi-dv` side not started |
| 02 PeMS canonical columns | not started |
| 03 D/C and dashboard | **done** |
| 04 speed-threshold contract | **done**: four named speeds, declared source, legacy field retained |
| 05 QVDF legacy / decomposed modes | not started |
| 06 identifiability and physical gates | not started |
| 07 reproducibility and CI | **done** for the clean-install path: `REPRODUCE.md`, `ci.yml`, path config, and the NVTA inputs staged so steps 1-8 run unconfigured. `experiments/` registry and top-level `manifest.json` hashes not done |
| 08 I-10 development, I-405 holdout | not started |
| 09 report | not started |
