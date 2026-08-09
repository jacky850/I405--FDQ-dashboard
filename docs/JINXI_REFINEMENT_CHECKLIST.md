# Jinxi refinement checklist

The package is intentionally opinionated so the first validation is reproducible. Refine only after the baseline runs.

1. Replace `data/synthetic_full_day/raw_weekdays.csv` with real HPE/California multi-day link data.
2. Preserve canonical `TMC_ID <-> network_link_id` mapping and lane count.
3. Generate **average weekday** 5-min speed and volume first; keep individual days only for robustness tests.
4. Fit S3 and triangular FD on the same training rows. Hold out links/days for validation.
5. Report speed->volume MAE/RMSE/MAPE/R2 plus period-volume closure and 90/95/worst percent errors.
6. Test `mu` strategies: `post_t2_median` (default), `post_t2_mean`, `q90`, `capacity`.
7. Do not reset queue at AM/MD/PM boundaries. Flag any period boundary where Q>0 or speed remains below cutoff.
8. For NVTA deployment, mark reconstructed volume as `synthetic/inferred`, never observed.
9. Freeze 5-10 gold links: uncongested, normal congested, severe congested, cross-period residual queue, and anomalous mapping/closure case.
10. Only after those pass, activate dynamic FDQ `mu(t)=Cap-theta Q(t)` and multi-link/spillback logic.
