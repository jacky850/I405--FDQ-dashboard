# I-405 FDQ Ground-Truth Dashboard

This repository contains the reproducible Stage-1 single-link benchmark used to build the I-405 FDQ dashboard.

Dashboard: https://jacky850.github.io/I405--FDQ-dashboard/

## What is included

- `data/`: processed I-405 weekday data, synthetic fallback data, and small reference examples.
- `scripts/`: data preparation, unit diagnostics, S3 calibration, period-specific S3, queue sensitivity, dynamic-μ, mentor comparison, and dashboard-data generation scripts.
- `src/fdqbench/`: reusable FD, speed-to-flow, queue, metrics, preprocessing, and OpenDTA export code.
- `outputs/`: fitted models, reconstructed reference tables, diagnostics, queue scenarios, and dashboard inputs.
- `dashboard/`: local dashboard source files.
- `configs/`, `schemas/`, `docs/`, and `tests/`: configuration, data contracts, mathematical notes, handoff notes, and tests.

## Reproducible workflow

The project uses 5-minute intervals and LA local time for weekday grouping and dashboard labels. Source timestamps remain available in UTC format where applicable.

1. Prepare the I-405 week and average weekday profile:

   ```bash
   python scripts/prepare_jinxi_i405_week.py
   ```

2. Run the constant-μ benchmark for all selected links:

   ```bash
   python scripts/run_jinxi_i405_all_links_constant_mu.py
   ```

3. Fit period-specific and anchored S3 speed-to-flow models:

   ```bash
   python scripts/run_jinxi_i405_s3_period_models.py
   python scripts/run_jinxi_i405_s3_anchored_models.py
   ```

4. Run queue sensitivity and the preliminary dynamic-μ candidate:

   ```bash
   python scripts/run_jinxi_i405_queue_sensitivity.py
   python scripts/run_jinxi_i405_dynamic_mu.py
   ```

5. Build dashboard data:

   ```bash
   python scripts/build_jinxi_i405_dashboard_data.py
   ```

6. Run tests:

   ```bash
   python -m unittest discover -s tests -v
   ```

## How speed is converted to flow

The S3 model is calibrated from reference speed-flow observations. For each observed speed, the model inverts the S3 speed-density relationship to estimate density, then calculates:

```text
flow = speed × density × number_of_lanes
```

The flow unit is veh/h. The pure S3 result is kept separate from the observed-flow queue baseline. Period-specific S3 fits separate parameters for NT1, AM, MD, PM, and NT2. Anchored S3 preserves the inferred shape but rescales period totals to the observed weekday volume and is therefore a synthetic-reference candidate rather than a pure speed-only score.

## Queue and μ conventions

- The observed PeMS flow is used as the ground-truth arrival input for the baseline queue.
- The constant-μ baseline uses one service rate per calibration period and propagates queue continuously across period boundaries.
- The current dynamic-μ candidate linearly blends neighboring period μ values over 30 minutes around each boundary. It is a sensitivity version, not the final state-dependent FDQ μ model.

## Dashboard

The public dashboard is hosted with GitHub Pages at the link above. The repository `index.html` is the dashboard entry page; GitHub's code view displays its source, while the Pages link executes the HTML and JavaScript.

## Data and scope note

The repository contains the processed I-405 week, average-weekday data, model inputs, outputs, and diagnostics used for the benchmark. The original external download package is not duplicated here. The project is intended for a transparent single-link Stage-1 benchmark before corridor/OpenDTA integration.

## I-405 South PAQ-aware D/mu calibration (review branch)

This branch adds an episode-level calibration for seven I-405 South links with directly observed upstream mainline flow:

```text
L405S-012, L405S-018, L405S-028, L405S-030,
L405S-058, L405S-098, L405S-115
```

The calibration week is 2025-06-02 through 2025-06-06. PeMS timestamps are retained in UTC, while `time_la` is used for LA-time profiles and period labels. Flow is in veh/h; source speed is converted from km/h to mph for the PAQ threshold and dashboard display.

### D construction

For each target link and 5-minute interval:

```text
D(t) = observed upstream mainline flow + observed on-ramp flow
```

The link-period demand rate is the peak of a declared 1-hour rolling mean of `D(t)`, following the report's direct-profile route. Upstream link selection comes from `lwr_mainline_topology.csv`. Ramp flow is included only when the ramp observation is valid; imputation is preserved and labelled in the preprocessing outputs.

### PAQ-aware mu construction

The PAQ implementation follows `paq_d12_extract_standalone.py`: it detects speed fragments below 70% of the data-driven free-flow speed, merges spatially and temporally overlapping fragments, and produces `T0`, `T3`, `pm_range`, and `xstar_pm`.

For each target-link episode, the observed flow source is selected from the PAQ bottleneck location:

1. Match a PAQ object on the same source date, overlapping episode time, and containing the target detector postmile.
2. Use the object's `xstar_link_id` as `mu_flow_link_id`.
3. Compute `mu_e` as the mean observed flow from `t0` through `t3` on that selected link.
4. If no PAQ object matches, retain `target_flow_no_paq_match`; this is a limited preliminary result, not a silently accepted bottleneck discharge estimate.

The report-aligned identities are:

```text
mu_e = mean(mu(t)) over t0...t3
k_mu = mu_e / C
DQ = integral of D(t) over t0...t3
```

### Reproduce the PAQ-aware outputs

Run these commands from the repository root after the processed weekday input has been prepared:

```bash
python scripts/run_i405_s_paq_bottleneck_mapping.py \
  --raw-file <I405-S-train-detector-states.csv> \
  --output-dir outputs/i405_s_paq_aware_direct7

python scripts/build_i405_s_direct7_calibration.py \
  --test-file outputs/i405_s_paq_aware_direct7/i405_s_link_ramp_flow_test.csv \
  --raw-file <I405-S-train-detector-states.csv> \
  --corridor-root <D12_I405_S-corridor-root> \
  --summary outputs/i405_s_paq_aware_direct7/i405_s_d_mu_summary_direct7.csv \
  --paq-file outputs/i405_s_paq_aware_direct7/i405_s_paq_objects_week_2025-06-02_to_2025-06-06.csv \
  --output-dir outputs/i405_s_paq_aware_direct7
```

### Review status and outputs

The main table is `outputs/i405_s_paq_aware_direct7/i405_s_calibration_link_period_direct7.csv`. Supporting tables include the 5-minute D/mu profile, congestion episode summary, PAQ objects, PAQ-to-detector comparison, and bottleneck decision audit. Figures are in `outputs/i405_s_paq_aware_direct7/figures/`.

This is a review branch. Episodes without a PAQ match or without a complete recovery are explicitly flagged and should not be treated as fully identified mu calibration cases without additional validation.
