from __future__ import annotations
import numpy as np
import pandas as pd


def regression_metrics(obs,pred,eps=1.0):
    y=np.asarray(obs,dtype=float); p=np.asarray(pred,dtype=float)
    m=np.isfinite(y)&np.isfinite(p); y=y[m]; p=p[m]
    if len(y)==0:return {}
    e=p-y; denom=np.maximum(np.abs(y),eps)
    ss=np.sum((y-y.mean())**2)
    return {'n':int(len(y)),'mae':float(np.mean(np.abs(e))),
            'rmse':float(np.sqrt(np.mean(e**2))),
            'mape_pct':float(100*np.mean(np.abs(e)/denom)),
            'r2':float(1-np.sum(e**2)/ss) if ss>0 else np.nan,
            'p90_abs_pct_error':float(np.quantile(100*np.abs(e)/denom,.90)),
            'p95_abs_pct_error':float(np.quantile(100*np.abs(e)/denom,.95)),
            'max_abs_pct_error':float(np.max(100*np.abs(e)/denom))}


def period_volume_closure(df, obs_col='flow_observed_vehph', pred_col='flow_ref_vehph', dt_minutes=5):
    rows=[]
    if obs_col not in df.columns:return pd.DataFrame()
    for p,g in df.groupby('period',sort=False):
        o=g[obs_col].sum()*dt_minutes/60.0; h=g[pred_col].sum()*dt_minutes/60.0
        rows.append({'period':p,'observed_volume_veh':o,'reconstructed_volume_veh':h,
                     'closure_error_pct':100*(h-o)/o if o else np.nan})
    return pd.DataFrame(rows)


def queue_qaqc(df,tol=1e-6):
    q=df['queue_end_veh'].to_numpy(); A=df['cumulative_arrivals_veh'].to_numpy(); D=df['cumulative_departures_veh'].to_numpy()
    initial=float(df['initial_queue_veh'].iloc[0]) if 'initial_queue_veh' in df.columns and len(df) else 0.0
    return {'queue_nonnegative':bool(np.nanmin(q)>=-tol),
            'cumulative_arrival_monotone':bool(np.all(np.diff(A)>=-tol)),
            'cumulative_departure_monotone':bool(np.all(np.diff(D)>=-tol)),
            'mass_balance_max_abs_veh':float(np.nanmax(np.abs((initial+A-D)-q)))}
