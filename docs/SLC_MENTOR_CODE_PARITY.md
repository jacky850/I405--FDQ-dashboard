# SLC Mentor-Code Parity

Validation date: 2026-08-10

## Question

Does the local canonical QVDF implementation produce the same intermediate and final states as the mentor reference code when both receive exactly the same inputs?

## Implementations

- Mentor reference: `SLC_I10_Jinxin_Package/scripts/run_slc_i10.py`
- Local independent implementation: `src/fdqbench/slc_qvdf.py`
- Comparison runner: `scripts/compare_slc_qvdf_with_mentor.py`

The local QVDF module is separate from the existing S3 speed-to-flow code. This test checks implementation parity for the same QVDF equations; it does not assert that S3 and QVDF are the same model.

## Test coverage

The comparison includes:

1. the mentor synthetic gold-link baseline;
2. 1,000 deterministic random volume perturbations between 0.5 and 1.5 times baseline volume;
3. forward states `V`, `D`, `mu`, `x`, `P`, `z`, `vT2`, `t0`, `T2`, `t3`, `TT_T2_h`, free-flow VHT, queue-delay VHT, and total VHT;
4. inverse states `z_hat`, `x_hat`, `D_hat`, `V_hat`, and `f_p_hat`;
5. 101-point episode-local speed and queue profiles;
6. 100 I-405 link-day-period interface cases produced by the canonical adapter.

## Result

| Check | Count | Maximum absolute difference |
|---|---:|---:|
| State comparisons | 20,919 | 0.0 |
| Profile comparisons | 1,101 | 0.0 |
| Speed-profile difference | 1,101 profiles | 0.0 mph |
| Queue-profile difference | 1,101 profiles | 0.0 veh |

Tolerance: `1e-12`

Decision: **PASS**.

The local QVDF implementation is formula- and interface-consistent with the mentor reference for all tested inputs.

## I-405 interpretation boundary

The I-405 cases in this parity test use real metadata, observed period volume, and daily derived `k_d`. However, `k_mu`, `f_d`, `n`, `f_p`, and `s` are deliberately frozen to the mentor synthetic-link values so that the interface can be exercised before calibration.

Therefore these I-405 rows prove:

- canonical I-405 fields enter both implementations consistently;
- units and field ordering do not create a mentor/local difference;
- the two implementations return identical results for identical inputs.

They do **not** prove:

- that the frozen synthetic parameters are valid for I-405;
- that I-405 flow or speed has been accurately inferred;
- that held-out real-link closure has passed.

The next gate is I-405 calibration-day parameter estimation followed by held-out-day prediction with all calibrated parameters frozen.
