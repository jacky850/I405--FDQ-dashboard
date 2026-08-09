# Turnkey handoff: what each person does next

## Jinxi
1. Drop in real California/HPE raw weekdays with `timestamp, link_id, tmc_id, speed_mph, flow_vehph`.
2. Run average-weekday preparation.
3. Fit S3 + triangular models link-by-link/corridor-by-corridor.
4. Validate speed->volume on held-out data using RMSE/MAPE/R2, period closure, and tail/worst-link error.
5. Freeze recommended parameter sets and `mu` strategy for the gold links.

## Muhammad
1. Consume `opendta_link_reference.csv` and/or the same `mu_ref(t)` lookup.
2. Keep Stage-1 assignment/QVDF replication separate from FDQueue calibration.
3. Do not reset queue at AM/MD/PM boundaries.
4. Compare `lambda_sim, Q_sim, TT_sim` against the reference package outputs.

## Simon
1. Select 5-10 gold links/cases for acceptance gates.
2. Decide whether the final Stage-1 `mu` is `post_t2_median`, `post_t2_mean`, or another calibrated rule.
3. Only after Stage 1 passes, activate dynamic FDQ `mu(t)=Cap-theta Q(t)` and multi-link/spillback logic.
