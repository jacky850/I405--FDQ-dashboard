"""The single-link queue kernel, on its own.

This is the whole model that produced the NVTA full-day results. It is separated
out here because it is the part that goes into a dynamic network loading: given
an arrival rate and a service rate per interval, it returns the queue, the
discharge flow, the travel time and the speed.

Nothing in this file reads INRIX speed, the assignment, or any fitted parameter.
Those belong to the steps that *produce* lambda and mu (steps 1-5 of the NVTA
pipeline, `scripts/queue_step1..5`). A DNL produces its own lambda from loaded
vehicles and can take mu from `outputs/nvta_service_profile/service_profile.csv`,
so it needs none of that.

Units, fixed:

    lambda, mu, outflow   veh/h        whole link, all lanes
    queue                 veh
    dt                    h            0.25 for the 15-minute NVTA run
    length                mile
    free_speed, speed     mph
    travel_time, delay    h

Read PORTING_NOTES.md before translating this to C++. The index convention in
particular is easy to get wrong and shifts every queue by one interval.
"""

from __future__ import annotations

import numpy as np


def run_queue(arrival_vph, service_vph, dt_h, initial_queue_veh=0.0):
    """One continuous point queue. Nothing resets at a period boundary.

        out(t)    = min( mu(t), lambda(t) + Q(t)/dt )
        Q(t + dt) = max( 0, Q(t) + [lambda(t) - out(t)] * dt )

    `queue[i]` is the queue standing at the **start** of interval `i`, before that
    interval's arrivals are served. `queue[0]` is therefore `initial_queue_veh`,
    and the queue left at the end of the run is returned separately as
    `final_queue_veh` because there is no interval `n` to hold it.

    The `Q(t)/dt` term is what lets a standing queue discharge: without it the
    link could never clear faster than its arrivals, and a queue once formed
    would never drain.

    Returns
    -------
    queue_veh : ndarray, shape (n,)
    outflow_vph : ndarray, shape (n,)
    final_queue_veh : float
    """
    arrival = np.asarray(arrival_vph, dtype=float)
    service = np.asarray(service_vph, dtype=float)
    if arrival.shape != service.shape:
        raise ValueError(f"arrival {arrival.shape} and service {service.shape} must match")
    if arrival.ndim != 1:
        raise ValueError("arrival and service must be one-dimensional")
    if dt_h <= 0:
        raise ValueError(f"dt_h must be positive, got {dt_h}")
    if np.isnan(arrival).any() or np.isnan(service).any():
        raise ValueError("arrival and service must not contain NaN; the queue would propagate it")
    if (arrival < 0).any() or (service < 0).any():
        raise ValueError("arrival and service must be non-negative")

    n = arrival.size
    queue = np.zeros(n)
    outflow = np.zeros(n)
    standing = float(initial_queue_veh)
    if standing < 0:
        raise ValueError(f"initial_queue_veh must be non-negative, got {standing}")

    for i in range(n):
        queue[i] = standing
        available = arrival[i] + standing / dt_h
        outflow[i] = min(service[i], available)
        standing = max(0.0, standing + (arrival[i] - outflow[i]) * dt_h)
    return queue, outflow, standing


def queue_to_speed(queue_veh, service_vph, length_mi, free_speed_mph):
    """Point-queue delay turned back into a link speed.

        TT(t) = L / v_f + Q(t) / mu(t)
        v(t)  = L / TT(t)

    `Q/mu` is the time to discharge the standing queue at the current service
    rate: a deterministic queueing delay, not a FIFO cumulative-curve wait. The
    two differ; PORTING_NOTES.md section 3 says which one this project reports.

    Nothing is fitted here. With `Q = 0` the result is exactly `v_f`, so the model
    says nothing about free-flow speed variation and only in-episode bins carry
    information.
    """
    queue = np.asarray(queue_veh, dtype=float)
    service = np.asarray(service_vph, dtype=float)
    if length_mi <= 0:
        raise ValueError(f"length_mi must be positive, got {length_mi}")
    if free_speed_mph <= 0:
        raise ValueError(f"free_speed_mph must be positive, got {free_speed_mph}")

    free_travel_h = length_mi / free_speed_mph
    delay_h = queue / np.maximum(service, 1e-6)
    travel_time_h = free_travel_h + delay_h
    speed_mph = length_mi / np.maximum(travel_time_h, 1e-9)
    return speed_mph, travel_time_h, delay_h


def run_link(arrival_vph, service_vph, dt_h, length_mi, free_speed_mph,
             initial_queue_veh=0.0):
    """Both halves in the order the pipeline runs them.

    Returns a dict of arrays, keyed with the same names as the published
    `outputs/nvta_queue/step8_speed_variants_15min.csv` columns.
    """
    queue, outflow, final_queue = run_queue(
        arrival_vph, service_vph, dt_h, initial_queue_veh)
    speed, travel_time, delay = queue_to_speed(
        queue, service_vph, length_mi, free_speed_mph)
    return {
        "queue_model_veh": queue,
        "outflow_vph": outflow,
        "delay_h": delay,
        "travel_time_h": travel_time,
        "speed_model_mph": speed,
        "final_queue_veh": final_queue,
    }
