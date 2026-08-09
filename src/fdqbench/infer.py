from __future__ import annotations
import numpy as np
import pandas as pd
from .fd import TriangularFD


def speed_to_throughput(speed_mph, fd: TriangularFD, freeflow_policy='nan'):
    """Map speed to FD-consistent throughput on the congested branch.

    Congested v < v_c: exact triangular-FD inversion.
    Free/critical v >= v_c: speed alone is non-identifying; default is NaN.
    Use freeflow_policy='capacity_envelope' only when an upper service envelope,
    not observed flow, is acceptable.
    """
    rows=[]
    for v in np.asarray(speed_mph,dtype=float):
        state=fd.state_from_speed(v)
        if state=='congested':
            q=fd.congested_flow_from_speed(v); k=fd.congested_density_from_speed(v)
        elif freeflow_policy=='capacity_envelope':
            q=fd.capacity_vehphpl; k=fd.critical_density
        else:
            q=np.nan; k=np.nan
        rows.append((state,q,k))
    return pd.DataFrame(rows,columns=['fd_state','mu_from_speed_vehphpl','density_from_speed_vehpmipl'])


def synthetic_arrival_from_period_volume(times_hour, period_volume_veh_total, lanes,
                                         peak_rate_vehphpl=None, peak_time_hour=None,
                                         sigma_hour=None):
    """Construct a clearly-labeled synthetic arrival profile from aggregate volume.

    This is not an observation. It is a Gaussian maximum-entropy-like smooth prior
    normalized exactly to the supplied period volume. If a peak rate is supplied,
    sigma is estimated from area ~= peak*sqrt(2*pi)*sigma unless given explicitly.
    """
    t=np.asarray(times_hour,dtype=float)
    if len(t)<2: raise ValueError('at least two time points required')
    dt=float(np.median(np.diff(t)))
    if peak_time_hour is None: peak_time_hour=float((t[0]+t[-1])/2)
    volume_per_lane=period_volume_veh_total/lanes
    if sigma_hour is None:
        if peak_rate_vehphpl and peak_rate_vehphpl>0:
            sigma_hour=max(dt, volume_per_lane/(peak_rate_vehphpl*np.sqrt(2*np.pi)))
        else:
            sigma_hour=max(dt,(t[-1]-t[0]+dt)/4)
    shape=np.exp(-0.5*((t-peak_time_hour)/sigma_hour)**2)
    # Normalize discrete interval volumes exactly.
    lam_pl=shape*(volume_per_lane/(shape.sum()*dt))
    return pd.DataFrame({'time_hour':t,'lambda_synthetic_vehphpl':lam_pl,
                         'lambda_synthetic_total_vehph':lam_pl*lanes,
                         'arrival_is_synthetic':True,
                         'arrival_sigma_hour':sigma_hour,
                         'arrival_peak_time_hour':peak_time_hour})
