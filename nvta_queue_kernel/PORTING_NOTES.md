# Porting the queue kernel into a dynamic network loading

Everything here is a decision the Python made that a C++ port has to make the
same way, or the numbers move. Each section says what the choice was and what
happens if it is made differently.

---

## 0. There is no C++ implementation yet

The whole project is Python. `grep -r --include='*.cpp' --include='*.h' .`
returns nothing. `kernel.py` is 4 lines of arithmetic wrapped in validation, and
a reference translation is in section 7 — but it has not been compiled, run, or
checked against the Python, so treat it as a starting point, not a tested port.
The first thing worth doing after translating is running `data/*.csv` through it
and diffing against `data/expected_output.csv`, which is what
`reproduce.py` does on the Python side.

---

## 1. `queue[i]` is the queue at the START of interval `i`

This is the single easiest thing to get wrong.

```
queue[0] = initial_queue_veh          # not the queue after interval 0
outflow[i] = min(mu[i], lambda[i] + queue[i]/dt)
queue[i+1] = max(0, queue[i] + (lambda[i] - outflow[i]) * dt)
```

The queue left when the run ends has no interval to live in, so it is returned
separately as `final_queue_veh`. If you instead store the end-of-interval queue
in `queue[i]`, every value shifts by one interval: on I-395 NB link 26469 that
moves the published queue by up to **27.6 veh** and the speed by up to
**21.9 mph**, while still looking like a plausible profile. Nothing crashes.

The published columns `queue_model_veh`, `delay_h`, `travel_time_h` and
`speed_model_mph` in `outputs/nvta_queue/step*_15min.csv` all use the
start-of-interval convention.

---

## 2. The `Q/dt` term is load-bearing

```
available = lambda[i] + queue[i]/dt
```

Dropping `queue[i]/dt` and writing `outflow = min(mu, lambda)` is a different
model: a link could then never discharge faster than its current arrivals, so a
queue once formed would never drain and every congested link would still be
queued at 19:00. The term converts the standing queue into a rate over the
interval so it can compete for the same service capacity as the new arrivals.

---

## 3. "Waiting time" has two definitions in this repository, and they differ

| | Definition | Where |
|---|---|---|
| **Used for every published NVTA number** | `delay_h = Q(t) / mu(t)` | `kernel.py:queue_to_speed`, and `scripts/queue_step7_queue_to_speed.py` |
| Not used for NVTA | FIFO horizontal distance between cumulative arrival and departure curves | `src/fdqbench/queue.py:fifo_waiting_time` |

The first is the time to discharge the queue standing now, at the rate applying
now. The second is how long the vehicle arriving now will actually wait, which
depends on future service rates. They agree only when `mu` is constant across the
whole queued spell.

**Pick one deliberately.** If the DNL needs a per-vehicle experienced delay, the
FIFO form is the correct one and the published NVTA delays are not comparable
with it.

---

## 4. Units, and the one conversion that bites

| Quantity | Unit | Note |
|---|---|---|
| `lambda`, `mu`, `outflow` | veh/h | **whole link, all lanes** — not per lane |
| `queue` | veh | whole link |
| `dt` | h | `0.25` for the 15-minute NVTA run |
| `length` | mile | |
| `free_speed`, `speed` | mph | |
| `travel_time`, `delay` | h | |

`mu` in `outputs/nvta_service_profile/service_profile.csv` is already
lane-multiplied: a 4-lane link at 2000 vph/lane carries `mu = 8000`, not 2000.
Multiplying by lanes a second time doubles capacity and silently removes every
queue.

Lane capacity itself is read from the assignment's link table (1900 or 2000
vph/lane on this network). It is **an input, not an estimate**: the estimator
returns `0.998 * C` for any assumed `C` between 1800 and 2400, because the S3
fundamental diagram returns exactly `C` at `0.707 * v_f` while the congestion
cut-off sits at `0.70 * v_f`, so the "maximum flow before breakdown" window
necessarily sweeps that point.

---

## 5. Initial queue and period carryover

```
Q(06:00) = 0
```

An empty link before the AM build-up. The run window is 06:00-19:00 because the
assignment has no night period, not because the road is empty at 19:00 — 28
links still show observed speeds below the cut-off at 18:45, and 33 links end the
run with a queue.

**A period boundary never resets the queue.** AM, MD and PM are labels on the
volume anchor and on reporting, not separate simulations. On this network **23
links carry a standing queue across the 15:00 boundary**, median 29.7 veh, max
150.8 veh. A PM-only run starting from an empty link discards those vehicles.

`run_queue` takes `initial_queue_veh` precisely so a DNL can chain intervals
across a boundary rather than restarting.

---

## 6. Free-flow speed must be per segment, and is not the assignment's value

`v_f` sets the cut-off at `0.70 * v_f`, which decides which intervals count as
congested, which decides everything downstream.

- The assignment's `free_speed_mph` exceeds the road's **own observed maximum
  speed** on **72 of 154 TMCs**. I-66 WB carries 75 mph on all 109 links, but
  link 26304 never exceeds 55.00 mph all day.
- One value per corridor is also wrong: within a corridor the 95th-percentile
  speed varies by **16-22 mph** between segments.

The published run uses each TMC's own observed 95th percentile. It correlates
0.963 with INRIX's own `reference_speed` and 0.979 with the overnight median.

---

## 7. Reference translation

Untested — see section 0.

```cpp
// queue[i] is the queue standing at the START of interval i.
// Returns the queue left after the last interval.
double RunQueue(const std::vector<double>& lambda,   // veh/h
                const std::vector<double>& mu,       // veh/h
                double dt_h,                         // h, 0.25 for 15 min
                double initial_queue_veh,
                std::vector<double>* queue,          // out, size n
                std::vector<double>* outflow) {      // out, size n
  const size_t n = lambda.size();
  queue->assign(n, 0.0);
  outflow->assign(n, 0.0);
  double standing = initial_queue_veh;
  for (size_t i = 0; i < n; ++i) {
    (*queue)[i] = standing;
    const double available = lambda[i] + standing / dt_h;
    (*outflow)[i] = std::min(mu[i], available);
    standing = std::max(0.0, standing + (lambda[i] - (*outflow)[i]) * dt_h);
  }
  return standing;
}

// TT = L/v_f + Q/mu ;  v = L/TT
void QueueToSpeed(const std::vector<double>& queue,
                  const std::vector<double>& mu,
                  double length_mi, double free_speed_mph,
                  std::vector<double>* speed_mph,
                  std::vector<double>* travel_time_h) {
  const double free_travel_h = length_mi / free_speed_mph;
  const size_t n = queue.size();
  speed_mph->assign(n, 0.0);
  travel_time_h->assign(n, 0.0);
  for (size_t i = 0; i < n; ++i) {
    const double tt = free_travel_h + queue[i] / std::max(mu[i], 1e-6);
    (*travel_time_h)[i] = tt;
    (*speed_mph)[i] = length_mi / std::max(tt, 1e-9);
  }
}
```

---

## 8. What to expect once the DNL drives it

This matters before the port is judged.

The published NVTA speeds come from a **closed loop**: observed speed produced
the queue target, the queue target fitted `lambda`, and `lambda` then reproduced
the speed. The PM in-episode MAE of **2.06 mph** is that loop's self-consistency,
not predictive accuracy.

When a DNL supplies its own `lambda`, the binding constraint is not the kernel:

| | |
|---|---:|
| Median `lambda/mu` from the assignment alone | **0.448** |
| Links where assignment `lambda` can ever exceed `mu` | **3 of 252** |
| PM links with an observed queue whose assignment volume is below the *observed* discharge | **34 of 53** |

**The assignment's volumes are about 2x below what the speed data shows was
discharged** (I-66 WB is 3x low; I-395 SB agrees to within 5%). With those
volumes the kernel produces no queue on 249 of 252 links, correctly — the input
says the road is at 45% of capacity.

So the first check after wiring the kernel in is not "does the queue match", it
is **"is the DNL's lambda large enough to queue at all"**. If it is not, the
kernel is working and the demand is the problem.

A point queue also cannot represent **downstream spillback** — a link queueing
because the bottleneck ahead of it backed up, while its own flow is well under
its own capacity. That is a structural limit of the single-link form, not a
calibration gap, and it is one candidate explanation for the 2x above.
