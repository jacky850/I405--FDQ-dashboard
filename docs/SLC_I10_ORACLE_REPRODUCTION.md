# SLC I-10 Oracle Reproduction

Reproduction date: 2026-08-10

Source package:

`fdq_single_link_benchmark_v0_2/SLC_I10_Jinxin_Student_Package/SLC_I10_Jinxin_Package`

This check reproduces Deliverable 1 of the mentor-provided Single-Link Closure package. The mentor source code was run unchanged.

## Command and environment

```bash
python scripts/run_slc_i10.py
```

- Windows 10 build 26200
- Python 3.11.9
- NumPy 2.4.2
- pandas 3.0.0
- Matplotlib 3.10.8

Console result:

```text
Generated outputs under: .../SLC_I10_Jinxin_Package/outputs
Self-tests passed: 4
```

All four package self-tests passed. A second complete run produced identical SHA-256 hashes for every generated CSV, TXT, and PNG output.

## Independent synthetic gold-link check

The following values were recomputed directly from the input CSV and report equations without importing the mentor script:

| State | Independently recomputed value |
|---|---:|
| D | 3750.000000 veh/h |
| mu | 4250.000000 veh/h |
| x | 0.750000 |
| P | 3.643656216987 h |
| z | 1.466775318330 |
| v(T2) | 19.863989896401 mph |
| t0 | 6.178171891507 h |
| T2 | 8.000000000000 h |
| t3 | 9.821828108493 h |
| Queue-delay VHT | 296.670122868398 veh-h |
| Total VHT | 518.208584406860 veh-h |
| Recovered V | 12000.000000 veh |

These values match `outputs/synthetic_forward_backward_closure.csv` to floating-point precision.

## Independent I-10 +20% checks

The finite-change formulas were independently evaluated for the mild Q1 and severe Q5 cases.

| Case | New V (veh) | New P (h) | P change | New v(T2) (mph) | v(T2) change | TT(T2) change |
|---|---:|---:|---:|---:|---:|---:|
| Q1 | 21240.0 | 2.716080236447 | +21.253582% | 23.252440554354 | -10.395219% | +11.601188% |
| Q5 | 22481.4 | 6.919556830009 | +23.079986% | 7.476054399087 | -24.484299% | +32.422792% |

The results match `outputs/i10_plus20_summary.csv`.

## Key SHA-256 provenance

| File | SHA-256 |
|---|---|
| `data/synthetic_gold_link.csv` | `54C435F9E588B7D7FC37514821E561220FAE6D4B68783F47F35D198D2A4FA6FA` |
| `data/i10_five_case_baseline.csv` | `62648BAA1C3BD5C42D07FE2F62034317E2E79C20AAF1C9A3FEDDBAA46ECF3C78` |
| `scripts/run_slc_i10.py` | `0A00614A45782E9A4F647256BE18303386EB8B15B38D8714D678C431869C41DF` |
| `outputs/synthetic_forward_backward_closure.csv` | `CE8F75E1B95BD17F7465F416A9BD9359F0CBB24F13AC591EE9B673B16E1C25E8` |
| `outputs/synthetic_volume_sensitivity.csv` | `F336D5A1CD430524496157A004442FF791CACE277BC953130C308714CF5C8B40` |
| `outputs/i10_plus20_summary.csv` | `4158233EECE9356E534619036EAFC0FDA6A5C960B988E25C51179C5B2D8F7FF7` |
| `outputs/i10_volume_sensitivity.csv` | `263555A9C45C712BF795975652C563E5E2BE8E86459F669866E37AA6BE49AD69` |
| `outputs/self_test_results.txt` | `8C02989906035ED96BCC92F9BC0BC49C4034AD51CA064FC8E22965B7B5C0ACAB` |

## Gate decision

- SLC-0 package contract: pass for the supplied synthetic link.
- SLC-1 forward hand calculation versus code: pass.
- SLC-2 exact inverse recovery: pass.
- Dense deterministic rerun: pass.
- Real-link holdout validation: not evaluated in this oracle step.

The next implementation step is an adapter that maps the existing I-405 PeMS/FDQ fields into the mentor package's canonical field and unit contract. The real-link calibration and held-out validation must remain separate.
