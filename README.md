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
