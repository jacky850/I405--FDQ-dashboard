# Stage C: speed-only episode robustness

This stage tests whether the asymmetric congestion episodes survive reasonable
changes to the detector inputs and settings. The grid was declared before the
results were inspected; it is not a parameter search and no variant is selected
because it produces a preferred answer.

## Frozen baseline

- Input: observed I-405 speed only, June 2–6, 2025, in Los Angeles local time.
- Baseline: entry at 70% of link p95 free speed, recovery at 75%, three
  consecutive 5-minute bins, 15-minute median smoothing, and a minimum
  20-minute/3-mph episode.
- Each link's p95 free speed is frozen from the unperturbed 5-minute data and is
  reused in every variant.
- PAQ, flow, demand, service rate, and queue are not used by the sensitivity
  detector.

## Predeclared perturbations

1. Entry threshold ratios: 0.65, 0.70, and 0.75. Recovery remains entry + 0.05.
2. Persistence durations: 10, 15, and 20 minutes.
3. Sampling intervals: 5, 10, and 15 minutes.
4. Additive Gaussian speed noise: 1, 3, and 5 mph, with 10 fixed-seed
   replicates per level.

The baseline combination is excluded, leaving 10 deterministic variants and 30
noise variants. Candidate episodes are greedily paired with baseline episodes
on the same link by descending temporal intersection-over-union (IoU).

## Stable-v1 rule

An episode is stable only when all conditions hold:

- baseline quality status is `accepted` (not censored and without internal
  missing-data or raw/robust-T2 disagreement flags);
- deterministic match rate is at least 0.80 and its median IoU is at least 0.50;
- both 10- and 15-minute samples match with IoU at least 0.50;
- noise match rate is at least 0.80 and its median IoU is at least 0.50.

## Results

- 28 baseline episodes were tested against 40 variants.
- 16 episodes pass the stable-v1 speed-only rule.
- All 7 prior strict speed-only + PAQ QVDF candidates pass Stage C.

Therefore, those 7 episodes are conservative daily validation cases. The primary
calibration target is the average-weekday canonical profile. The other episodes remain in the audit tables; a failed robustness
gate means they should not silently enter calibration, not that congestion was
necessarily absent.

## Outputs

- `episode_variant_matches.csv`: one baseline-episode/variant record, including
  match status, IoU, and changes in t0, T2, t3, and P.
- `episode_stability_summary.csv`: episode-level stability metrics and final
  stable-v1 flag.
- `stable_speed_only_episodes.csv`: all episodes passing speed-only stability.
- `stable_paq_qvdf_candidates.csv`: conservative candidates passing both the
  earlier PAQ screen and Stage C.
- `variant_run_summary.csv`: exact settings and episode count for every run.
- `figures/`: overview and deterministic IoU heatmap.

Run from the repository root:

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python scripts/run_i405_episode_sensitivity.py
```
