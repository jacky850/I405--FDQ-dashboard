# Average-weekday canonical I-405 episodes

The advisor-facing calibration target is a typical weekday, not one selected
calendar day. For each link, the pipeline first averages Monday through Friday
at every 5-minute Los Angeles wall-clock bin:

```text
five daily speed/flow profiles
    -> station-to-link aggregation
    -> 288-bin average-weekday speed and observed flow
    -> canonical t0, T2, t3, P from average speed
```

The daily episodes remain a separate robustness layer. They quantify recurrence
and day-to-day variation but are not substituted for the average-weekday target.

## Timestamp evidence

The PeMS source timestamp is Pacific local wall-clock time. The dataset builder
parses the original naive timestamp and serializes it with a literal `Z` without
performing a UTC conversion. Accordingly, the pipeline strips that suffix and
localizes the unchanged clock to `America/Los_Angeles`. This is also consistent
with the repository's historical-profile builder, which groups directly on the
serialized `HH:MM` field.

## Current direct7 result

All seven links have 288 bins and five contributing weekdays per bin. Under the
predeclared detector rules, three average-weekday canonical episodes remain:

| Link | t0 | T2 | t3 | P |
|---|---:|---:|---:|---:|
| L405S-012 | 07:05 | 08:25 | 09:33 | 2.454 h |
| L405S-018 | 17:15 | 17:30 | 17:49 | 0.568 h |
| L405S-115 | 06:34 | 07:35 | 09:30 | 2.919 h |

The other four links may have daily speed reductions, but their average-weekday
speed does not satisfy the strict threshold, persistence, duration, and depth
rules simultaneously. They remain valid non-congested or non-identifiable
controls rather than being forced into a congestion episode.

## Reproduce

```powershell
$env:PYTHONPATH = (Join-Path (Get-Location) 'src')
python scripts/build_i405_average_weekday_canonical.py
```

Outputs are under `outputs/i405_average_weekday_canonical_direct7/`:

- `average_weekday_speed_flow_5min.csv`
- `canonical_average_weekday_episodes.csv`
- `canonical_vs_daily_episode_summary.csv`
- `figures/`
