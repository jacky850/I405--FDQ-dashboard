# Variable contract v0.3

**Scope:** `jacky850/I405--FDQ-dashboard` and `jacky850/pems-cbi-dv`.
**Status:** authoritative. Where this document and any other file disagree, this
document wins and the other file is a defect.

One symbol has one meaning and one unit in both repositories. Every primary
output column declares its evidence layer. Nothing below is a suggestion: the
tests listed in each section fail the build when a rule here is broken.

`schema_version = "0.3"` is written into every summary JSON generated after this
contract landed. A file without that key predates the contract and its column
names must be read through the migration tables in section 5.

---

## 1. Evidence layers

Every CSV field, figure, table, dashboard metric and model output identifies one
of four layers.

| Layer | Meaning | Examples |
|---|---|---|
| `A_OBSERVED` | Direct probe, sensor or detector observation | speed, flow, occupancy, station id, observed mask |
| `B_RECOVERED` | CBI / DTA-QVDF model-informed recovery | T0/T2/T3, P, speed-inferred flow, recovered discharge |
| `C_ASSIGNED_BASELINE` | Full-day TAPLite assigned baseline | assigned link volume, assigned period demand |
| `D_FINAL_DNL` | Final adjusted and physically validated DNL | only after OD/path/time adjustment and DNL validation |

Two prohibitions, both of which have already been violated once in this project:

- **Layer B is not "observed."** A quantity that passed through the S3 inversion
  is recovered, not measured, however good the fit.
- **Layer C is not "final calibrated DNL."** An assignment output is an input to
  this work, not a result of it.

For full-day Layer C output, each interval carries one status:

```
OBSERVED_AND_CALIBRATED
ASSIGNMENT_ONLY
FREE_FLOW_INFERRED
ZERO_PLACEHOLDER_NOT_CALIBRATED
MISSING_INPUT
```

---

## 2. Symbols and units

| Canonical name | Symbol | Unit | Definition |
|---|---:|---:|---|
| `period_volume_V_veh` | V | veh | total link volume over planning period H |
| `period_hours_H` | H | h | planning-period duration |
| `period_average_rate_vph` | V/H | veh/h | average rate over H |
| `peak_demand_rate_D_vph` | D | veh/h | peak-hour or queue-corrected demand rate |
| `demand_modifier_kd` | k_d | – | D / (V/H) |
| `nominal_capacity_C_vph` | C | veh/h | declared nominal hourly capacity |
| `effective_discharge_mu_vph` | mu | veh/h | effective queued discharge rate |
| `capacity_retention_kmu` | k_mu | – | mu / C |
| `dc_rate` | D/C | – | rate-based demand loading |
| `dmu_effective` | D/mu | – | effective demand–supply stress |
| `congested_passed_volume_veh` | – | veh | observed/recovered vehicles passing during congested bins |
| `episode_workload_DQ_veh` | D_Q | veh | episode arrival/processed workload, with declared source |
| `capacity_equivalent_hours` | – | h | congested_passed_volume / C |
| `congestion_duration_P_h` | P | h | T3 − T0 |

### 2.1 The five quantities that must never be interchanged

These are distinct. Two of them were conflated in released output; see section 5.

| | Unit | Is it a rate? | Is it a ratio? |
|---|---|---|---|
| `peak_demand_rate_D_vph` | veh/h | yes | no |
| `period_volume_V_veh` | veh | no | no |
| `congested_passed_volume_veh` | veh | no | no |
| `capacity_equivalent_hours` | h | no | no |
| `dc_rate` | – | no | yes |

- `congested_passed_volume_veh` is **not** the rate-based `D` in `D/C`.
- `capacity_equivalent_hours` is vehicles divided by an hourly rate. It has
  **units of hours** and must never be labelled `D/C`.
- `demand_modifier_kd` is `D/(V/H)`, a peak-load factor. It is **not** `D/C`.
  On the I-405 multiweek set `k_d` has median 1.069 and never drops below 1.0,
  while the true `dc_rate` has median 0.990 and ranges 0.611–1.289. They are not
  the same number and do not have the same range.

---

## 3. Physical speed names

Four distinct speeds. `vc` alone is not a permitted name for any of them.

```
capacity_speed_mph        = v_f / sqrt(2)          for S3 with m = 4
episode_entry_speed_mph   = 0.70 * v_f             unless a declared alternative is used
episode_exit_speed_mph    = 0.75 * v_f             unless a declared alternative is used
qvdf_reference_speed_mph  = the speed used in the severity equation
qvdf_reference_speed_source = which of the above it was taken from
```

`episode_entry_speed_mph < episode_exit_speed_mph` always: entry and recovery use
hysteresis, and the recovery threshold is the higher one.

### 3.1 Declared reference-speed sources

`qvdf_reference_speed_source` takes one of:

```
CAPACITY_SPEED_S3          v_f / sqrt(2)
EPISODE_EXIT_THRESHOLD     0.75 * v_f
EPISODE_ENTRY_THRESHOLD    0.70 * v_f
EXTERNAL_DECLARED          supplied by configuration, value recorded alongside
```

The severity equation must state which one it used. It may not silently take the
exit threshold and treat it as the capacity speed — those differ by about 6%
(0.750 vs 0.707 of free speed), and the severity ratio `z = v_ref/v(T2) − 1` is
linear in that choice.

**Current state, declared rather than changed.** The I-405 multiweek holdout
resolves its reference speed to `EPISODE_EXIT_THRESHOLD`, and every episode row
now says so in `qvdf_reference_speed_source`. That default is frozen legacy
behaviour for v0.3 so the released numbers stay reproducible; it is recorded, not
endorsed. `--qvdf-reference-speed` selects a different one.

The choice matters to the severity branch and barely at all to the reported
accuracy, which is exactly why it had to be named rather than left implicit
(measured over 31 episode cases, 21 supported):

| | `episode_exit` (default) | `capacity_speed` |
|---|---:|---:|
| median `v_ref` | 51.96 mph | 48.99 mph |
| median observed `z` | 0.4244 | 0.3429 |
| median calibrated `f_p` | 0.09918 | **0.06962** |
| speed-gate failures | 7 | 6 |
| supported cases | 21 | 21 |
| `v(T2)` MAE | 2.206 mph | 2.125 mph |
| volume MAPE | 16.876% | 16.876% |

`f_p` moves 30% while volume MAPE does not move at all, because the duration
branch never touches `v_ref`. Anyone quoting `f_p` across the two conventions
without saying which one they used is quoting two different numbers.

---

## 4. Period clock

One authoritative source. Any document, dashboard string or output metadata that
disagrees is a defect.

| Period | Start | End | Hours |
|---|---|---|---:|
| AM | 06:00 | 09:00 | 3 |
| MD | 09:00 | 15:00 | 6 |
| PM | 15:00 | 19:00 | 4 |
| NT | 19:00 | 06:00 | 11 |

These follow the assignment's own clock. The NVTA queue run window is 06:00–19:00
(AM+MD+PM); NT is excluded because the assignment carries no night period.

**A period boundary never resets a queue.** AM, MD and PM are labels on the
anchor and on reporting, not independent simulations. On the NVTA network 23
links carry a standing queue across the 15:00 boundary, median 29.7 veh.

---

## 5. Migration from legacy names

Legacy aliases are retained for one release and produce numerically identical
values. They are removed in v0.4.

### 5.1 `pems-cbi-dv`

| Legacy column | Canonical column | Unit | Layer |
|---|---|---|---|
| `D_counts` | `congested_passed_volume_counts_veh` | veh | `A_OBSERVED` |
| `D_speed` | `congested_passed_volume_speed_veh` | veh | `B_RECOVERED` |
| `DC_hours` | `capacity_equivalent_hours_counts` | h | `A_OBSERVED` |
| `V_counts` | `period_volume_counts_veh` | veh | `A_OBSERVED` |
| `V_speed` | `period_volume_speed_veh` | veh | `B_RECOVERED` |

Required wording, carried in `pems-cbi-dv/DATA_DICTIONARY.md`:

```
D_counts and D_speed are congested-bin passed volumes in vehicles.
They are not the rate-based demand D in D/C.
DC_hours is congested passed volume divided by hourly capacity and has units of
hours. It is not a dimensionless D/C ratio.
```

### 5.2 `I405--FDQ-dashboard`

| Legacy column | Canonical column | Unit | Note |
|---|---|---|---|
| `d_over_c_observed` | `peak_load_factor_kd_observed` | – | **was mislabelled**; it is `k_d`, not `D/C` |
| — (new) | `dc_rate_observed` | – | `observed_peak_1h_demand_veh_h / capacity_vph` |
| `d_over_c_inferred` | `dc_rate_inferred` | – | unchanged value; `D_hat_veh_h / capacity_vph` |
| `cutoff_speed_vc_mph` | `qvdf_reference_speed_mph` | mph | plus `qvdf_reference_speed_source` |
| `cutoff_speed_vc_mph` | `legacy_cutoff_speed_vc_mph` | mph | retained one release, records which new field it was |

`capacity_vph` in `dc_rate_observed` must be the training-only capacity for that
leave-one-week-out case. An assertion enforces that it did not use holdout flow.

---

## 6. What each rule is tested by

| Rule | Test |
|---|---|
| Dashboard values equal generated values | `tests/test_dashboard_metrics.py` |
| `k_d` is never labelled `D/C` | `tests/test_dashboard_metrics.py` |
| Capacity/entry/exit/reference speeds are distinct and ordered | `tests/test_speed_threshold_contract.py` |
| AM is 06:00–09:00 everywhere | `tests/test_period_clock.py` |
| Queue kernel reproduces published output | `tests/test_nvta_kernel.py` |

No row in this contract is "implemented" without a test and a committed evidence
output.
