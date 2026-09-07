"""Resolve demand and capacity inputs onto one declared basis.

The QVDF equations take a ratio -- ``D/C`` or ``D/mu`` -- so they are blind to
whether the two sides are per-link or per-lane, provided *both* are. They are not
blind to a mismatch, and a mismatch is silent: a per-link volume over a per-lane
capacity gives a stress that is wrong by the lane count, which on a four-lane
link is a factor of four and still looks like a plausible number.

This module is the one place that decides. It takes every combination the
project actually receives, converts them onto a single declared basis, and
refuses the combinations that cannot be resolved rather than guessing.

Canonical rule: **the basis follows the capacity, and the volume is converted to
match it.** That is the convention the three required cases describe:

    link V + link C          -> qavg = V / H
    link V + per-lane C      -> qavg = V / (lanes * H)
    per-lane V + per-lane C  -> qavg = V / H

See docs/VARIABLE_CONTRACT.md for the symbols and units.
"""

from __future__ import annotations

from dataclasses import dataclass, asdict

PER_LINK = "per_link"
PER_LANE = "per_lane"
BASES = (PER_LINK, PER_LANE)

# What the supplied capacity number actually is.
NOMINAL_HOURLY = "nominal_hourly"          # veh/h, the declared capacity C
PERIOD_EQUIVALENT = "period_equivalent"    # veh over the whole period; NOT a rate
EFFECTIVE = "effective"                    # veh/h, already reduced to mu
CAPACITY_KINDS = (NOMINAL_HOURLY, PERIOD_EQUIVALENT, EFFECTIVE)

TOLERANCE = 1e-9


class BasisError(ValueError):
    """An input combination that cannot be resolved without guessing."""


@dataclass(frozen=True)
class ResolvedBasis:
    """Demand and supply on one basis, with every quantity named and derived."""

    basis: str
    lanes: int | None

    qavg_vph: float                    # V / H, on `basis`
    peak_demand_rate_D_vph: float      # k_d * qavg
    nominal_capacity_C_vph: float      # C, on `basis`
    effective_discharge_mu_vph: float  # k_mu * C

    demand_modifier_kd: float          # D / (V/H)
    capacity_retention_kmu: float      # mu / C

    dc_nominal: float                  # D / C
    dmu_effective: float               # D / mu

    def as_dict(self) -> dict:
        return asdict(self)


def _require_lanes(lanes: int | None, why: str) -> int:
    if lanes is None:
        raise BasisError(
            f"lanes is required to {why}, and was not given. Supply lanes, or "
            f"provide the volume and the capacity on the same basis.")
    if lanes <= 0:
        raise BasisError(f"lanes must be positive, got {lanes}")
    return int(lanes)


def resolve_basis(
    *,
    period_volume_V_veh: float,
    period_hours_H: float,
    capacity: float,
    volume_basis: str = PER_LINK,
    capacity_basis: str = PER_LINK,
    capacity_kind: str = NOMINAL_HOURLY,
    lanes: int | None = None,
    demand_modifier_kd: float | None = None,
    peak_load_factor_plf: float | None = None,
    capacity_retention_kmu: float | None = None,
    effective_discharge_mu_vph: float | None = None,
) -> ResolvedBasis:
    """Convert one set of inputs onto the capacity's basis.

    Parameters name what each number *is*, so nothing has to be inferred from
    magnitude. Every rejection below is a case where two inputs disagree or where
    a conversion needs a lane count that was not supplied.

    Raises
    ------
    BasisError
        - the basis or capacity kind is not a declared value
        - a per-link/per-lane conversion is needed and `lanes` is missing
        - the capacity is period-equivalent, which is not an hourly rate
        - the capacity is already effective and `k_mu != 1`, which double-counts
        - `k_d` and `1/plf` are both given and disagree
        - `mu`, `C` and `k_mu` are all given and disagree
    """
    if volume_basis not in BASES:
        raise BasisError(f"volume_basis must be one of {BASES}, got {volume_basis!r}")
    if capacity_basis not in BASES:
        raise BasisError(f"capacity_basis must be one of {BASES}, got {capacity_basis!r}")
    if capacity_kind not in CAPACITY_KINDS:
        raise BasisError(f"capacity_kind must be one of {CAPACITY_KINDS}, got {capacity_kind!r}")
    if period_hours_H <= 0:
        raise BasisError(f"period_hours_H must be positive, got {period_hours_H}")
    if capacity <= 0:
        raise BasisError(f"capacity must be positive, got {capacity}")

    # A period-equivalent capacity is a vehicle count over the period, not a
    # rate. Dividing a rate by it produces a dimensionless-looking number that is
    # wrong by a factor of H, which is exactly the kind of error that survives
    # review because it still lands near 1.
    if capacity_kind == PERIOD_EQUIVALENT:
        raise BasisError(
            "capacity_kind='period_equivalent' is a vehicle count over the period, "
            "not a nominal hourly capacity. Divide it by period_hours_H first and "
            "pass capacity_kind='nominal_hourly'.")

    # --- k_d, possibly given as a peak-load factor ---------------------------
    if peak_load_factor_plf is not None:
        if peak_load_factor_plf <= 0:
            raise BasisError(f"peak_load_factor_plf must be positive, got {peak_load_factor_plf}")
        implied_kd = 1.0 / float(peak_load_factor_plf)
        if demand_modifier_kd is not None and abs(demand_modifier_kd - implied_kd) > TOLERANCE:
            raise BasisError(
                f"demand_modifier_kd={demand_modifier_kd} and peak_load_factor_plf="
                f"{peak_load_factor_plf} disagree: k_d must equal 1/plf, which is "
                f"{implied_kd}. Supply one of them, not both.")
        k_d = implied_kd
    else:
        k_d = 1.0 if demand_modifier_kd is None else float(demand_modifier_kd)
    if k_d <= 0:
        raise BasisError(f"demand_modifier_kd must be positive, got {k_d}")

    # --- the volume onto the capacity's basis --------------------------------
    volume = float(period_volume_V_veh)
    basis = capacity_basis
    if volume_basis == PER_LINK and capacity_basis == PER_LANE:
        volume /= _require_lanes(lanes, "convert a per-link volume onto a per-lane capacity")
    elif volume_basis == PER_LANE and capacity_basis == PER_LINK:
        volume *= _require_lanes(lanes, "convert a per-lane volume onto a per-link capacity")

    qavg = volume / float(period_hours_H)
    demand = k_d * qavg
    nominal_C = float(capacity)

    # --- k_mu and mu ---------------------------------------------------------
    # An effective capacity is already mu. Scaling it again by k_mu applies the
    # same drop twice.
    if capacity_kind == EFFECTIVE:
        if capacity_retention_kmu is not None and abs(capacity_retention_kmu - 1.0) > TOLERANCE:
            raise BasisError(
                f"capacity_kind='effective' means the capacity given is already mu, "
                f"so capacity_retention_kmu must be 1 (or omitted). Got "
                f"{capacity_retention_kmu}, which would apply the drop twice.")
        if (effective_discharge_mu_vph is not None
                and abs(effective_discharge_mu_vph - nominal_C) > TOLERANCE * max(1.0, nominal_C)):
            raise BasisError(
                f"capacity_kind='effective' and effective_discharge_mu_vph="
                f"{effective_discharge_mu_vph} disagree with the capacity given "
                f"({nominal_C}).")
        mu = nominal_C
        k_mu = 1.0
    else:
        if effective_discharge_mu_vph is not None and capacity_retention_kmu is not None:
            implied = capacity_retention_kmu * nominal_C
            if abs(effective_discharge_mu_vph - implied) > TOLERANCE * max(1.0, implied):
                raise BasisError(
                    f"mu={effective_discharge_mu_vph}, C={nominal_C} and "
                    f"k_mu={capacity_retention_kmu} disagree: k_mu * C is {implied}. "
                    f"Supply two of the three, not all three.")
            mu = float(effective_discharge_mu_vph)
            k_mu = float(capacity_retention_kmu)
        elif effective_discharge_mu_vph is not None:
            mu = float(effective_discharge_mu_vph)
            k_mu = mu / nominal_C
        else:
            k_mu = 1.0 if capacity_retention_kmu is None else float(capacity_retention_kmu)
            mu = k_mu * nominal_C

    if not 0.0 < k_mu <= 1.0:
        raise BasisError(
            f"capacity_retention_kmu must satisfy 0 < k_mu <= 1; got {k_mu}. A "
            f"discharge rate above nominal capacity is not a capacity drop.")

    return ResolvedBasis(
        basis=basis,
        lanes=None if lanes is None else int(lanes),
        qavg_vph=qavg,
        peak_demand_rate_D_vph=demand,
        nominal_capacity_C_vph=nominal_C,
        effective_discharge_mu_vph=mu,
        demand_modifier_kd=k_d,
        capacity_retention_kmu=k_mu,
        dc_nominal=demand / nominal_C,
        dmu_effective=demand / mu,
    )
