from __future__ import annotations
import pandas as pd


def average_weekday(raw: pd.DataFrame, timestamp_col='timestamp', group_cols=None,
                    speed_col='speed_mph', flow_col='flow_vehph', interval='5min'):
    """Create one average weekday profile from raw multi-day observations.

    Averages by clock time after filtering Monday-Friday. group_cols can include
    TMC/link IDs. Returned time_of_day is HH:MM and is directly consumable by
    build_reference_day().
    """
    d=raw.copy(); d[timestamp_col]=pd.to_datetime(d[timestamp_col])
    d=d[d[timestamp_col].dt.dayofweek<5].copy()
    d['time_of_day']=d[timestamp_col].dt.floor(interval).dt.strftime('%H:%M')
    keys=list(group_cols or [])+['time_of_day']
    agg={speed_col:'mean'}
    if flow_col in d.columns: agg[flow_col]='mean'
    out=d.groupby(keys,as_index=False).agg(agg)
    return out.sort_values(keys).reset_index(drop=True)
