# Multiweek average-weekday holdout v1

## Purpose

This is the first validation that matches the intended INRIX deployment unit
and applies the frozen protocol without selecting favorable link-periods.
Each sample is a complete weekly average-weekday speed profile, rather than one
calendar day. For a holdout week, every flow observation from that week is
hidden during inference.

```text
other weekly average speed + flow profiles
    -> calibrate and freeze C, k_d, f_d, f_p
holdout-week average speed only
    -> P, T2, v(T2)
    -> duration volume inverse
    -> speed-severity consistency gate
    -> duration-extrapolation gate
open holdout-week average flow
    -> score period volume
```

## Data declaration

- Window: 2025-06-02 through 2025-08-29.
- Thirteen complete Monday--Friday weeks are present for all seven links.
- The week beginning 2025-06-30 is excluded by a predeclared calendar rule
  because it contains Independence Day (2025-07-04).
- Twelve ordinary complete weeks remain for each of seven direct links.
- Both AM (06:00--10:00) and PM (15:00--19:00) are evaluated, producing 14
  fixed link-period groups and 168 link-period-week cases.
- Every weekly profile has 288 five-minute bins and five contributing weekdays.
- PeMS clock values are interpreted as Los Angeles local wall time; the source
  builder's literal `Z` is not treated as a UTC conversion.

## Frozen model contract

- Mentor stress basis: `D_over_C`.
- Duration exponent: `n=1.10`, assumed/frozen from the mentor gold link.
- Severity exponent: `s=1.40`, assumed/frozen from the mentor gold link.
- `C`, `k_d`, `f_d`, and `f_p` are recalibrated only from the non-holdout weeks.
- Speed gate: severity ratio 0.5--2.0 and absolute `v(T2)` error no greater than
  10 mph.
- Duration-extrapolation gate: inferred holdout `D/C` may not exceed 1.25 times
  the largest observed `D/C` among that case's training episode weeks. This
  uses training flow only; holdout flow remains hidden.

## Results

Across 168 link-period-week cases:

- 31/168 (18.5%) contain an identifiable canonical episode in the declared
  link-period;
- 24/168 pass the speed consistency gate;
- three of those 24 fail the duration-extrapolation gate;
- 21/168 (12.5%) pass both gates and receive a supported volume estimate;
- supported-case volume MAPE is 16.5%;
- supported-case median APE is 14.7%.

| Link-period with supported cases | Identified coverage | Supported volume MAPE |
|---|---:|---:|
| L405S-012 AM | 7/12 = 58.3% | 15.1% |
| L405S-018 AM | 1/12 = 8.3% | 37.7% |
| L405S-018 PM | 3/12 = 25.0% | 26.9% |
| L405S-115 AM | 10/12 = 83.3% | 12.3% |

The other ten link-period groups have no supported cases under the frozen
episode definition. Coverage and error must be reported together. A 16.5%
conditional error score does not mean the model produces a reliable value for
every week: 137 cases have no qualifying average-speed episode and seven
additional episode cases fail the speed gate, and three cases fail the
duration-extrapolation gate. These rows remain explicit abstentions.

## Interpretation

The result is materially more defensible than both the one-week in-sample 5.2%
MAPE and the selected three-link-period result. Expanding without selecting
favorable links exposes the earlier selection bias. The added duration gate
then removes three holdout inversions that exceed the training `D/C` envelope
by more than 25%. The current pipeline is promising
for recurring strongly congested link-periods such as L405S-115 AM and
L405S-012 AM, but it is not a general I-405 speed-to-volume solution.

The free-flow/no-episode case remains fundamentally weak for speed-only volume
inference: when speed stays near free flow, many traffic volumes can produce
similar speed. The correct output is presently `not_identified_no_speed_episode`,
not a fabricated point estimate.

## Outputs

- `weekly_average_weekday_profiles_5min.csv`
- `weekly_data_completeness.csv`
- `weekly_canonical_states_and_ground_truth.csv`
- `leave_one_week_out_qvdf_results.csv`
- `leave_one_week_out_metrics.csv`
- `supported_case_accuracy.csv`
- `multiweek_holdout_summary.json`
- `figures/representative_weekly_speed_episode.png`
- `figures/multiweek_holdout_volume_scatter.png`
- `figures/multiweek_coverage_matrix.png`
