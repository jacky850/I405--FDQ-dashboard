from __future__ import annotations
from dataclasses import asdict
import numpy as np
import pandas as pd
from scipy.optimize import least_squares
from .fd import TriangularFD, S3FD


def _clean(speed, flow, lanes=1):
    v=np.asarray(speed,dtype=float)
    q=np.asarray(flow,dtype=float)/float(lanes)
    m=np.isfinite(v)&np.isfinite(q)&(v>1e-6)&(q>=0)
    v=v[m]; q=q[m]
    if len(v)<10: raise ValueError('Need at least 10 valid speed-flow observations')
    k=q/v
    return v,q,k


def fit_s3_from_speed_flow(speed_mph, flow_vehph, lanes=1, m_bounds=(1.5,8.0)):
    """Fit S3 for the actual deployment task: speed -> observed flow.

    Density is still used to initialize the critical-density parameter, but the
    optimizer minimizes flow residuals after applying the speed inverse. This
    avoids optimizing a speed-density surrogate and then evaluating a different
    speed-to-flow objective.
    """
    v,q,k=_clean(speed_mph,flow_vehph,lanes)
    vf0=max(np.quantile(v,0.95),np.max(v)*0.98)
    kc0=max(np.quantile(k,0.45),5.0)
    x0=np.array([vf0,kc0,4.0])
    lo=np.array([max(20.0,np.quantile(v,0.5)),1.0,m_bounds[0]])
    hi=np.array([max(100.0,np.max(v)*1.25),max(250.0,np.max(k)*2.0),m_bounds[1]])
    def res(x):
        fd=S3FD(x[0],x[1],x[2])
        return fd.flow_from_speed(v)-q
    opt=least_squares(res,x0,bounds=(lo,hi),loss='soft_l1')
    fd=S3FD(*opt.x)
    pred=fd.flow_from_speed(v)
    return fd, {'success':bool(opt.success),'cost':float(opt.cost),'n':int(len(v)),
                'fit_target':'flow_from_speed_direct',
                'flow_rmse_vehphpl':float(np.sqrt(np.mean((pred-q)**2)))}


def fit_triangular_from_speed_flow(speed_mph, flow_vehph, lanes=1):
    """Fit a continuous triangular FD from speed-flow observations via k=q/v.

    Parameters fitted: vf, kc, wb. Capacity=vf*kc and jam density=kc+capacity/wb.
    """
    v,q,k=_clean(speed_mph,flow_vehph,lanes)
    vf0=max(np.quantile(v,0.9),50.0)
    kc0=max(np.quantile(k,0.45),8.0)
    wb0=12.0
    x0=np.array([vf0,kc0,wb0])
    lo=np.array([30.0,2.0,2.0]); hi=np.array([100.0,max(250.0,np.max(k)*2),40.0])
    def pred_q(x):
        vf,kc,wb=x; cap=vf*kc; kj=kc+cap/wb
        return np.minimum(vf*k,wb*np.maximum(kj-k,0.0))
    def res(x): return pred_q(x)-q
    opt=least_squares(res,x0,bounds=(lo,hi),loss='soft_l1')
    vf,kc,wb=opt.x; cap=vf*kc
    fd=TriangularFD(vf,cap,vf,wb,kc+cap/wb)
    # cutoff_speed for an ideal triangular FD equals vf at the apex; retain explicit field.
    return fd, {'success':bool(opt.success),'cost':float(opt.cost),'n':int(len(v)),
                'flow_rmse_vehphpl':float(np.sqrt(np.mean(res(opt.x)**2)))}


def fit_models(df: pd.DataFrame, speed_col='speed_mph', flow_col='flow_vehph', lanes=1):
    s3,s3info=fit_s3_from_speed_flow(df[speed_col],df[flow_col],lanes)
    tri,triinfo=fit_triangular_from_speed_flow(df[speed_col],df[flow_col],lanes)
    return {'s3': {'parameters':s3.to_dict(),'fit':s3info},
            'triangular': {'parameters':tri.to_dict(),'fit':triinfo}}
