# QVDF held-out speed-severity gate v1

## Why this gate exists

The mentor QVDF has a duration branch and a speed-severity branch:

```text
P = f_d x^n
z = v_c / v(T2) - 1 = f_p P^s
```

The second equation is not another volume equation and must not be used to
silently rewrite the mentor inverse. Instead it tests whether a holdout speed
episode is consistent with the QVDF state learned on the other weekdays. If the
state is inconsistent, the correct output is `not_identified`/abstain rather
than a forced volume estimate.

## Holdout protocol

- Freeze `s=1.40` from the mentor synthetic gold link.
- Calibrate `f_p` on the other congested weekdays.
- Use holdout `P` to predict holdout `v(T2)`.
- Compare against `v(T2)` read only from holdout speed.
- Flow remains hidden throughout this gate; it is opened only for the final
  volume score.

The predeclared support rule requires both:

- observed/predicted severity ratio between 0.5 and 2.0;
- absolute `v(T2)` error no greater than 10 mph.

## Result

- 12 holdout cases evaluated.
- 11 cases supported; coverage 91.7%.
- Held-out `v(T2)` MAE: about 2.19 mph across all cases.
- Volume MAPE across all forced predictions: 48.1%.
- Volume MAPE among supported cases: 21.5%.
- Supported-case median volume APE: about 15.6%.

The only abstention is `L405S-018`, 2025-06-03 PM. It is also the prior
128,000-versus-29,000 vehicle structural failure. The gate identifies it using
speed only: the duration branch predicts `v(T2)` near 15.8 mph while observed
holdout speed bottoms near 27.5 mph, and the severity ratio is about 0.386.

No observation is deleted. The failed row remains in the output with
`inverse_status=not_identified_speed_branch_failure`.

## Average-weekday caution

Daily-calibrated speed parameters do not automatically transfer to a profile
formed by averaging speeds across days because the QVDF relation is nonlinear.
Two of the three average-weekday speed-branch rows fail this transfer diagnostic.
This is not a fair held-out-week test: only one week is currently available.
The final INRIX-style average-weekday gate requires multiple weeks, calibrating
on some weeks and holding out another complete average-weekday profile.

## Outputs

- `heldout_qvdf_speed_branch_gate.csv`
- `canonical_qvdf_speed_branch.csv`
- `speed_branch_gate_metrics.csv`
- `speed_branch_gate_summary.json`
- `figures/heldout_speed_branch_and_volume_gate.png`
