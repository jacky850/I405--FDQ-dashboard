from __future__ import annotations
from dataclasses import dataclass, asdict
import math
import numpy as np


@dataclass(frozen=True)
class TriangularFD:
    """Triangular fundamental diagram in per-lane units."""
    free_speed_mph: float
    capacity_vehphpl: float
    cutoff_speed_mph: float
    backward_wave_speed_mph: float
    jam_density_vehpmipl: float | None = None

    @property
    def critical_density(self) -> float:
        return self.capacity_vehphpl / self.cutoff_speed_mph

    @property
    def jam_density(self) -> float:
        if self.jam_density_vehpmipl is not None:
            return self.jam_density_vehpmipl
        return self.critical_density + self.capacity_vehphpl / self.backward_wave_speed_mph

    def flow_from_density(self, density_vehpmipl):
        k=np.asarray(density_vehpmipl,dtype=float)
        return np.minimum(self.free_speed_mph*k,
                          self.backward_wave_speed_mph*np.maximum(self.jam_density-k,0.0))

    def congested_flow_from_speed(self, speed_mph: float) -> float:
        """Exact inversion on congested branch: q=v*w_b*k_j/(v+w_b)."""
        v=float(speed_mph)
        if not math.isfinite(v) or v < 0: return math.nan
        wb=self.backward_wave_speed_mph
        return v*wb*self.jam_density/(v+wb) if (v+wb)>0 else math.nan

    def congested_density_from_speed(self, speed_mph: float) -> float:
        v=float(speed_mph)
        if not math.isfinite(v) or v < 0: return math.nan
        wb=self.backward_wave_speed_mph
        return wb*self.jam_density/(v+wb) if (v+wb)>0 else math.nan

    def state_from_speed(self, speed_mph: float, tolerance_mph: float=1e-9) -> str:
        return 'congested' if speed_mph < self.cutoff_speed_mph-tolerance_mph else 'free_or_critical'

    def to_dict(self): return asdict(self)


@dataclass(frozen=True)
class S3FD:
    """S-shaped three-parameter (S3) speed-density model.

    v(k)=vf/[1+(k/kc)^m]^(2/m), q(k)=k*v(k).
    At k=kc, q is maximal and vc=vf/2^(2/m).
    """
    free_speed_mph: float
    critical_density_vehpmipl: float
    m: float = 4.0

    @property
    def critical_speed_mph(self) -> float:
        return self.free_speed_mph/(2.0**(2.0/self.m))

    @property
    def capacity_vehphpl(self) -> float:
        return self.critical_density_vehpmipl*self.critical_speed_mph

    def speed_from_density(self, density_vehpmipl):
        k=np.asarray(density_vehpmipl,dtype=float)
        x=np.maximum(k,0.0)/self.critical_density_vehpmipl
        return self.free_speed_mph/np.power(1.0+np.power(x,self.m),2.0/self.m)

    def flow_from_density(self, density_vehpmipl):
        k=np.asarray(density_vehpmipl,dtype=float)
        return k*self.speed_from_density(k)

    def density_from_speed(self, speed_mph):
        v=np.asarray(speed_mph,dtype=float)
        ratio=np.maximum(self.free_speed_mph/np.clip(v,1e-9,None),1.0)
        x=np.power(np.maximum(np.power(ratio,self.m/2.0)-1.0,0.0),1.0/self.m)
        return self.critical_density_vehpmipl*x

    def flow_from_speed(self, speed_mph):
        v=np.asarray(speed_mph,dtype=float)
        return v*self.density_from_speed(v)

    def to_dict(self): return asdict(self)
