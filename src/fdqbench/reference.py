from __future__ import annotations
import numpy as np
import pandas as pd
from .fd import S3FD, TriangularFD
from .queue import fifo_waiting_time


def clock_minutes(s):
    h,m=map(int,str(s).split(':')[:2]); return 60*h+m


def assign_period(time_of_day, periods):
    mins=np.array([clock_minutes(x) for x in time_of_day])
    out=np.full(len(mins),'UNASSIGNED',dtype=object)
    for p in periods:
        a,b=clock_minutes(p['start']),clock_minutes(p['end'])
        mask=(mins>=a)&(mins<b) if b>a else ((mins>=a)|(mins<b))
        out[mask]=p['name']
    return out


def reconstruct_flow_from_speed(speed_mph, model_name, parameters, lanes=1):
    v=np.asarray(speed_mph,dtype=float)
    if model_name=='s3':
        fd=S3FD(**parameters); qpl=fd.flow_from_speed(v)
    elif model_name=='triangular_congested':
        fd=TriangularFD(**parameters)
        qpl=np.array([fd.congested_flow_from_speed(x) if x<fd.cutoff_speed_mph else np.nan for x in v])
    else: raise ValueError(f'Unknown speed-volume model: {model_name}')
    return qpl*float(lanes)


def estimate_period_mu(df, periods, flow_col='flow_ref_vehph', speed_col='speed_mph',
                       cutoff_speed_mph=None, mode='post_t2_median', capacity_vehph=None,
                       t2_by_period=None):
    """Estimate one constant service rate per period.

    post_t2_* uses rows after supplied t2 clock time; if absent, it uses the half
    of the period after its minimum speed. Values are clipped by capacity.
    """
    out={}; t2_by_period=t2_by_period or {}
    for p in periods:
        sub=df[df['period']==p['name']].copy()
        if sub.empty: continue
        if mode=='capacity': val=float(capacity_vehph)
        else:
            if p['name'] in t2_by_period:
                t2m=clock_minutes(t2_by_period[p['name']]); mm=sub['time_of_day'].map(clock_minutes)
                cand=sub[mm>=t2m]
            else:
                idx=sub[speed_col].astype(float).idxmin(); pos=sub.index.get_loc(idx) if idx in sub.index else len(sub)//2
                cand=sub.loc[idx:]
            if cutoff_speed_mph is not None:
                c2=cand[cand[speed_col].astype(float)<=float(cutoff_speed_mph)]
                if len(c2)>=2: cand=c2
            x=cand[flow_col].dropna().astype(float)
            if len(x)==0: x=sub[flow_col].dropna().astype(float)
            if mode=='post_t2_mean': val=float(x.mean())
            elif mode=='post_t2_median': val=float(x.median())
            elif mode=='q90': val=float(sub[flow_col].quantile(.90))
            else: raise ValueError(mode)
            if capacity_vehph is not None: val=min(val,float(capacity_vehph))
        out[p['name']]=val
    return out


def service_profile(period_labels, mu_by_period, blend_intervals=0):
    mu=np.array([mu_by_period.get(p,np.nan) for p in period_labels],dtype=float)
    if blend_intervals<=0: return mu
    # causal/simple linear blend across each period boundary, without resetting queue.
    y=mu.copy(); n=len(y)
    changes=np.where(np.r_[False,period_labels[1:]!=period_labels[:-1]])[0]
    for i in changes:
        lo=max(0,i-blend_intervals); hi=min(n,i+blend_intervals+1)
        left=mu[i-1]; right=mu[i]
        y[lo:hi]=np.linspace(left,right,hi-lo)
    return y


def build_reference_day(avg: pd.DataFrame, link_meta: dict, periods: list[dict],
                        speed_volume_model: dict, mu_config: dict,
                        dt_minutes=5, initial_queue_veh=0.0):
    """Turn average-weekday speed into a full-day single-link FDQueue reference.

    No queue reset occurs at AM/MD/PM boundaries. The reference arrival is the
    reconstructed speed->volume profile unless avg already contains arrival_vehph.
    """
    d=avg.copy().sort_values('time_of_day').reset_index(drop=True)
    d['period']=assign_period(d['time_of_day'].astype(str),periods)
    lanes=float(link_meta['lanes'])
    qhat=reconstruct_flow_from_speed(d['speed_mph'],speed_volume_model['name'],
                                     speed_volume_model['parameters'],lanes)
    d['flow_speed_only_vehph']=qhat
    d['flow_ref_vehph']=qhat.copy()
    d['flow_ref_source']='speed_to_volume:'+speed_volume_model['name']
    if 'flow_vehph' in d.columns:
        d['flow_observed_vehph']=d['flow_vehph']
    # Optional period-volume anchoring: preserve the speed-derived 5-min shape but
    # force each period's integral to a trusted aggregate volume. This is the
    # recommended deployment mode when Cube/TMC/agency period volume exists.
    anchor=speed_volume_model.get('period_volume_anchor','none')
    explicit=speed_volume_model.get('period_volumes_veh',{})
    dt_h=dt_minutes/60.0
    d['volume_anchor_factor']=1.0
    for pname,gidx in d.groupby('period').groups.items():
        idx=list(gidx); raw_total=float(np.nansum(d.loc[idx,'flow_ref_vehph'])*dt_h)
        target=None
        if anchor=='observed' and 'flow_observed_vehph' in d.columns:
            target=float(np.nansum(d.loc[idx,'flow_observed_vehph'])*dt_h)
        elif pname in explicit:
            target=float(explicit[pname])
        if target is not None and raw_total>1e-9:
            fac=target/raw_total
            d.loc[idx,'flow_ref_vehph']=d.loc[idx,'flow_ref_vehph']*fac
            d.loc[idx,'volume_anchor_factor']=fac
            d.loc[idx,'flow_ref_source']=d.loc[idx,'flow_ref_source']+'+period_volume_anchor'
    if 'arrival_vehph' in d.columns:
        d['lambda_ref_vehph']=d['arrival_vehph'].astype(float); d['lambda_ref_source']='observed_arrival'
    else:
        d['lambda_ref_vehph']=d['flow_ref_vehph']; d['lambda_ref_source']='speed_to_volume_proxy'
    cap_total=float(link_meta['capacity_vehphpl'])*lanes
    mu_flow_col=mu_config.get('flow_col','flow_ref_vehph')
    if mu_flow_col not in d.columns:
        raise ValueError(f"mu flow column not found: {mu_flow_col}")
    mu_by=estimate_period_mu(d,periods,flow_col=mu_flow_col,speed_col='speed_mph',
                            cutoff_speed_mph=link_meta.get('cutoff_speed_mph'),
                            mode=mu_config.get('mode','post_t2_median'),capacity_vehph=cap_total,
                            t2_by_period=mu_config.get('t2_by_period',{}))
    d['mu_ref_vehph']=service_profile(d['period'].to_numpy(),mu_by,int(mu_config.get('blend_intervals',0)))
    ff_min=60.0*float(link_meta['length_mi'])/float(link_meta['free_speed_mph'])
    fq=fifo_waiting_time(d['lambda_ref_vehph'],d['mu_ref_vehph'],dt_minutes/60.0,ff_min,initial_queue_veh)
    for c in fq.columns: d[c]=fq[c].to_numpy()
    d['net_flow_ref_vehph']=d['lambda_ref_vehph']-d['mu_ref_vehph']
    d['link_id']=link_meta['link_id']; d['tmc_id']=link_meta.get('tmc_id','')
    d['dt_minutes']=dt_minutes; d['initial_queue_veh']=initial_queue_veh
    return d,mu_by
