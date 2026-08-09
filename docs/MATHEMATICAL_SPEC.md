# FDQueue v0.2 mathematical specification

## Scope
Single link, deterministic fluid queue, 5-minute intervals, no spillback. The goal is a **reference link oracle** for Stage-1 QA/QC and later OpenDTA loading. AM/MD/PM are calibration blocks, not queue-reset boundaries.

## 1. Speed-to-volume layer

### S3 full-range option

\[
v(k)=\frac{v_f}{[1+(k/k_c)^m]^{2/m}},\qquad q(k)=k v(k).
\]

Because speed is monotone in density, the inverse used by the package is

\[
k(v)=k_c\left[\left(\frac{v_f}{v}\right)^{m/2}-1\right]^{1/m},\qquad
q(v)=v\,k(v).
\]

This is the default full-range speed-to-volume starting point for Jinxi's calibration.

### Triangular FD congested-branch option

\[
q=w_b(k_j-k),\qquad q=vk,
\]
so
\[
q(v)=\frac{v w_b k_j}{v+w_b}.
\]

This inversion is used only for observations classified as congested. Free-flow speed alone does not uniquely identify flow under the triangular FD.

## 2. Period service reference

Stage 1 uses one service rate per analysis period:

\[
\mu_a(t)=\mu_{a,p},\quad t\in p.
\]

Default estimator is the median reconstructed/observed flow after `t2`, clipped by link capacity. Alternatives in code: `post_t2_mean`, `q90`, `capacity`. Optional short blending smooths AM/MD/PM service discontinuities.

Crucially, a period boundary does **not** reset the queue.

## 3. Fluid queue

With rates in veh/h and interval length \(\Delta t\) in hours, realized departures are limited by service and available vehicles. The implementation directly tracks cumulative arrivals and departures and residual queue continuously across all periods.

For 5-minute data, \(\Delta t=5/60\) hour.

## 4. OpenDTA interface

The reference package exports, for each link/time interval:

\[
\lambda_a^{ref}(t),\;\mu_a^{ref}(t),\;Q_a^{ref}(t),\;w_a^{ref}(t),\;TT_a^{ref}(t).
\]

In later DNL, \(\lambda_a^{sim}(t)\) should be generated from loaded vehicles/path/departure times, while \(\mu_a^{ref}(t)\) can be fixed as an externally supplied service oracle for the first benchmark.

## 5. Stage-2 FDQ option

Once Stage 1 is stable, the package has a hook for

\[
\mu(t)=Cap-\theta Q(t),
\]

with \(\theta=w_b/\phi\). This is intentionally not the default in v0.2.
