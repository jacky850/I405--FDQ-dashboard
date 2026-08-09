from __future__ import annotations
import numpy as np
import pandas as pd


def fluid_queue(arrival_vehph, service_vehph, dt_hour, initial_queue_veh=0.0):
    """Deterministic point/fluid queue, preserving residual queue across all intervals."""
    lam=np.asarray(arrival_vehph,dtype=float); mu=np.asarray(service_vehph,dtype=float)
    if lam.shape!=mu.shape: raise ValueError('arrival and service shapes must match')
    n=len(lam); q=np.zeros(n); dep=np.zeros(n); A=np.zeros(n); D=np.zeros(n)
    q0=np.zeros(n); q_prev=float(initial_queue_veh); a=d=0.0
    for i in range(n):
        q0[i]=q_prev
        ai=max(lam[i],0.0)*dt_hour; cap=max(mu[i],0.0)*dt_hour
        di=min(cap,q_prev+ai)
        q_prev=q_prev+ai-di; a+=ai; d+=di
        q[i]=q_prev; dep[i]=di/dt_hour if dt_hour>0 else 0.0; A[i]=a; D[i]=d
    return pd.DataFrame({'queue_start_veh':q0,'queue_end_veh':q,
                         'realized_departure_vehph':dep,
                         'cumulative_arrivals_veh':A,'cumulative_departures_veh':D})


def fifo_waiting_time(arrival_vehph, service_vehph, dt_hour, free_flow_time_min=0.0,
                      initial_queue_veh=0.0):
    fq=fluid_queue(arrival_vehph,service_vehph,dt_hour,initial_queue_veh)
    A=fq['cumulative_arrivals_veh'].to_numpy()+float(initial_queue_veh)
    D=fq['cumulative_departures_veh'].to_numpy()
    n=len(A); wait=np.full(n,np.nan)
    for i in range(n):
        j=np.searchsorted(D,A[i]-1e-9,side='left')
        if j<n: wait[i]=max(0.0,(j-i)*dt_hour*60.0)
    fq['waiting_time_min']=wait
    fq['travel_time_min']=wait+free_flow_time_min
    return fq


def fdq_dynamic_service(capacity_vehph, queue_veh, theta_vehph_per_veh, floor_vehph=0.0):
    return np.maximum(float(floor_vehph),float(capacity_vehph)-float(theta_vehph_per_veh)*np.asarray(queue_veh,dtype=float))
