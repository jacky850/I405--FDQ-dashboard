# P0 corrections: what changed, and what it changed

Against the action plan's Issues 01, 03, 04 (partial) and 07. Scope-frozen: no
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
clone: **74 passed**.

---

## 6. `pems-cbi-dv` was a live git repository nested in this working tree

With its own `.git`, on `main`, carrying uncommitted changes, and untracked here.
A `git add -A` would have committed it as a broken gitlink. Now ignored, with the
reason in `.gitignore`. It belongs beside this repository, not inside it.

---

## What this does not cover

| Plan issue | Status |
|---|---|
| 01 variable contract | `docs/VARIABLE_CONTRACT.md` written; `pems-cbi-dv` side not started |
| 02 PeMS canonical columns | not started |
| 03 D/C and dashboard | **done** |
| 04 speed-threshold contract | contract written and the current resolution declared; field migration in code not done |
| 05 QVDF legacy / decomposed modes | not started |
| 06 identifiability and physical gates | not started |
| 07 reproducibility and CI | `REPRODUCE.md`, `ci.yml`, path config **done**; `experiments/` registry and `manifest.json` hashes not done |
| 08 I-10 development, I-405 holdout | not started |
| 09 report | not started |

### One thing to raise rather than bury

Issue 04 says the QVDF severity equation may not silently use the episode exit
threshold as the capacity speed. It currently does:
`run_i405_multiweek_average_holdout.py:170` takes `episode["exit_threshold_mph"]`
(`0.75 * v_f`) into `cutoff_speed_vc_mph`, and line 189 uses it as the reference
in `z = v_ref / v(T2) - 1`. The S3 capacity speed is `v_f / sqrt(2)`
= `0.707 * v_f` — about 6% apart, and `z` is linear in that choice.

This release **declares** that resolution (contract section 3.1,
`EPISODE_EXIT_THRESHOLD`) rather than changing it, so the published numbers stay
reproducible. Changing it moves every `z`, `f_p` and predicted `v(T2)`, and
belongs in its own change with its own before/after table.
