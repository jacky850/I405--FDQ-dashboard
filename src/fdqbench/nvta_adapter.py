from __future__ import annotations
import pandas as pd
import numpy as np
from .fd import TriangularFD
from .infer import speed_to_throughput, synthetic_arrival_from_period_volume
from .queue import fifo_waiting_time


def run_nvta_single_link(link_row, speed_profile, backward_wave_speed_mph, freeflow_policy='capacity_envelope'):
    """Convert an NVTA/TAPlite single-link speed profile into a benchmark table.

    Important: the 5-minute profile in the supplied anomaly-audit package is a
    TAPlite modeled profile, not raw observed TMC speed. The observed TMC fields in
    that package are period-level statistics. This adapter preserves that provenance.
    """
    fd=TriangularFD(
        free_speed_mph=float(link_row['free_speed_mph']),
        capacity_vehphpl=float(link_row['capacity_vehphpl']),
        cutoff_speed_mph=float(link_row['cutoff_speed_mph']),
        backward_wave_speed_mph=float(backward_wave_speed_mph),
    )
    t=speed_profile['time_hour'].to_numpy(dtype=float)
    inf=speed_to_throughput(speed_profile['speed_mph'].to_numpy(),fd,freeflow_policy=freeflow_policy)
    out=speed_profile.reset_index(drop=True).copy()
    out=pd.concat([out,inf],axis=1)
    lanes=int(link_row['lanes']); out['mu_total_vehph']=out['mu_from_speed_vehphpl']*lanes
    arr=synthetic_arrival_from_period_volume(
        t, float(link_row['period_volume_veh']), lanes,
        peak_rate_vehphpl=float(link_row['peak_demand_vehphpl']),
        peak_time_hour=float(link_row.get('t2_hour',(t[0]+t[-1])/2))
    )
    out['lambda_vehphpl']=arr['lambda_synthetic_vehphpl']; out['lambda_total_vehph']=arr['lambda_synthetic_total_vehph']
    dt=float(np.median(np.diff(t))) if len(t)>1 else 5/60
    fftt=float(link_row['length_mi'])/float(link_row['free_speed_mph'])*60.0
    fq=fifo_waiting_time(out['lambda_total_vehph'],out['mu_total_vehph'],dt,fftt)
    for c in fq.columns: out[c]=fq[c].to_numpy()
    return out, fd
