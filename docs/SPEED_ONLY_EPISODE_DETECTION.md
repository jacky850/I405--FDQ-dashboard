# Speed-Only Asymmetric Episode Detection

Status: first auditable implementation for I-405 direct7, 2026-08-10.

## Purpose

Extract observed congestion episodes from 5-minute speed without using flow, demand, service rate, or queue fields. The resulting `t0`, `T2`, `t3`, `P`, and `vT2` states are the observed inputs to the mentor-aligned QVDF calibration and inverse-recovery stages.

The detector does not force `T2` to be the midpoint:

```text
observed onset duration   = T2 - t0
observed recovery duration = t3 - T2
asymmetry ratio            = (T2 - t0) / (t3 - T2)
```

## Input contract

The production detector reads only:

- PeMS Pacific-local wall-clock timestamp;
- model link ID;
- observed speed;
- speed observation/missing flags.

The source builder read PeMS local timestamps as naive datetimes and then appended a literal `Z` while serializing; no UTC conversion occurred. The detector therefore removes that literal suffix and localizes the unchanged clock value to `America/Los_Angeles`. Treating the suffix as true UTC would incorrectly shift every profile by seven or eight hours.

## Detection rules, version v1

- free speed: link-level 95th percentile from the declared training week;
- entry threshold: 70% of free speed;
- recovery threshold: 75% of free speed;
- smoothing: centered 3-bin median;
- entry persistence: 3 consecutive 5-minute bins;
- recovery persistence: 3 consecutive 5-minute bins;
- short-gap interpolation: at most 2 bins;
- minimum duration: 20 minutes;
- minimum robust speed depth below entry threshold: 3 mph;
- `t0` and `t3`: independently interpolated threshold crossings;
- `T2`: minimum of the robust speed series inside the episode;
- raw minimum and raw-minimum time are retained separately;
- each link is processed continuously across the entire week, not reset at midnight or at NT1/AM/MD/PM/NT2 boundaries.

Every episode carries censoring, missing-data, raw-versus-robust `T2`, cross-period, and multiple-episode flags.

## PAQ role

Legacy PAQ objects are an external spatial/temporal reference, not detector inputs. Their clock minutes inherit the same PeMS local-wall-clock convention and are explicitly localized to Los Angeles time before comparison.

PAQ provides `T0`, `T3`, spatial range, and `xstar`; it does not independently publish a target-link `T2`. The reported PAQ-window `T2` diagnostic is calculated from the same target-link speed inside the PAQ window, so a zero `T2` difference is not an independent accuracy result.

PAQ duration and single-link speed duration also need not be identical: PAQ describes a spatial queue object, while this detector describes the local link episode.

## Direct7 results

| Result | Value |
|---|---:|
| Links | 7 |
| LA weekdays | 5 |
| Speed-only episodes | 28 |
| Link-days with no identifiable episode | 14 |
| Episodes matched to a PAQ object | 19 |
| Speed-only unmatched episodes | 9 |
| PAQ-only unmatched objects in target ranges | 2 |
| Median absolute `t0` difference on matches | 8.425 min |
| Median absolute `t3` difference on matches | 11.338 min |
| Median absolute duration difference on matches | 23.592 min |

`L405S-098` has no identifiable congestion episode on any of the five local weekdays. Its QVDF speed-only period volume must therefore be marked non-identifiable unless an external prior is supplied.

## Strict QVDF candidate set v1

The first conservative candidate set requires:

- no detector quality flags;
- a PAQ temporal intersection-over-union of at least 0.50.

Seven episodes pass this rule after correcting the source timestamp semantics. This is a screening set for the next calibration step, not a certified gold-label release.

## Reproduction

```bash
python scripts/run_i405_speed_only_episode_detection.py
python scripts/plot_i405_speed_only_episodes.py
```

Primary outputs:

- `outputs/i405_speed_only_episodes_direct7/speed_only_asymmetric_episodes.csv`
- `outputs/i405_speed_only_episodes_direct7/speed_only_day_status.csv`
- `outputs/i405_speed_only_episodes_direct7/speed_only_vs_paq_reference.csv`
- `outputs/i405_speed_only_episodes_direct7/qvdf_episode_candidates_strict_v1.csv`
- `outputs/i405_speed_only_episodes_direct7/figures/`

## Next gate

The predeclared sensitivity gate is complete. Daily results now provide robustness and uncertainty evidence for the average-weekday canonical calibration profile.
