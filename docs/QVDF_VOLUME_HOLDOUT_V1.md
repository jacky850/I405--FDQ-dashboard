# QVDF speed-duration to period-volume validation v1

## Contract

This stage uses the mentor equations with `stress_basis=D_over_C`:

```text
D = k_d V / T_p
P = f_d (D/C)^n
V_hat = T_p C (P/f_d)^(1/n) / k_d
```

The exponent `n=1.10` is frozen from the mentor synthetic gold link for this
first benchmark. Capacity `C`, demand concentration `k_d`, and duration
coefficient `f_d` are calibrated from observed PeMS flow on training weekdays.
They are never presented as speed-identified quantities.

For each of the three average-weekday canonical link-period pairs, one
congested weekday is held out in turn. Parameters are recalibrated on the other
congested weekdays and then frozen before `P` from the held-out speed episode is
converted to period volume. This produces 12 genuinely held-out cases.

## Result

- Overall holdout MAE: about 13,341 vehicles per four-hour period.
- Overall holdout MAPE: about 48.1%.
- Median holdout APE: reported in `qvdf_volume_summary.json` and is preferred as
  a robust companion because one structural failure dominates the mean.
- Average-weekday in-sample canonical MAPE: about 5.2%.

The in-sample number must not be reported alone. `L405S-018` on 2025-06-03 has
similar PM period volume to the other weekdays but a much longer speed-derived
congestion duration (about 2.26 h versus roughly 0.36--0.54 h). The duration-only
inverse consequently predicts roughly 128,000 vehicles against about 29,000
observed. This is retained and flagged as a duration-volume structural failure,
not removed as an outlier to improve the score.

## Interpretation

The first QVDF inverse is formula-consistent and unit-consistent, but it does not
yet pass the held-out gate. Congestion duration alone is not sufficient on every
day/link. The next model revision should test whether the speed severity state
`v(T2)` and calibrated speed branch (`f_p`, `s`) can distinguish days with
similar total volume but very different congestion duration. Incident/mapping
evidence should also be checked when available.

The reported recovery `mu` is the median observed flow from `T2` to `t3` in the
average-weekday profile. It is observed-flow-derived calibration evidence and
is not inferred from speed alone.

## Outputs

- `daily_leave_one_out_qvdf_volume_validation.csv`
- `daily_leave_one_out_metrics_by_link.csv`
- `average_weekday_canonical_qvdf_volume.csv`
- `qvdf_volume_summary.json`
- `figures/holdout_volume_observed_vs_inferred.png`
- `figures/canonical_average_weekday_volume.png`
