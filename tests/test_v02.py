import sys,unittest
from pathlib import Path
import numpy as np,pandas as pd
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
from fdqbench.fd import S3FD,TriangularFD
from fdqbench.queue import fluid_queue
from fdqbench.reference import build_reference_day
from fdqbench.calibrate import fit_s3_from_speed_flow
from fdqbench.closure import backward_closure, reconstruct_speed_from_flow, closure_speed_metrics

class TestV02(unittest.TestCase):
    def test_s3_speed_inverse(self):
        fd=S3FD(65,32,4); k=np.linspace(2,100,50); v=fd.speed_from_density(k); kh=fd.density_from_speed(v)
        self.assertLess(np.max(np.abs(k-kh)),1e-8)
    def test_tri_congested_inverse(self):
        fd=TriangularFD(65,1800,50,12,180); v=25; q=fd.congested_flow_from_speed(v); k=q/v
        self.assertAlmostEqual(q,fd.backward_wave_speed_mph*(fd.jam_density-k),places=8)
    def test_queue_dt_and_residual(self):
        f=fluid_queue([2000]*12,[1500]*12,5/60,10)
        self.assertAlmostEqual(f.queue_end_veh.iloc[-1],510,places=6)
    def test_s3_fit(self):
        fd=S3FD(65,30,4); k=np.linspace(4,90,120); v=fd.speed_from_density(k); q=fd.flow_from_density(k)
        hat,_=fit_s3_from_speed_flow(v,q,1)
        self.assertLess(abs(hat.free_speed_mph-65),0.5)
        self.assertLess(abs(hat.critical_density_vehpmipl-30),0.5)
    def test_no_period_queue_reset(self):
        times=pd.date_range('2000-01-01 06:00',periods=24,freq='5min').strftime('%H:%M')
        avg=pd.DataFrame({'time_of_day':times,'speed_mph':[25]*24})
        fd=S3FD(65,30,4)
        meta={'link_id':'x','lanes':1,'length_mi':1,'free_speed_mph':65,'capacity_vehphpl':fd.capacity_vehphpl,'cutoff_speed_mph':fd.critical_speed_mph}
        periods=[{'name':'AM','start':'06:00','end':'07:00'},{'name':'MD','start':'07:00','end':'08:00'}]
        cfg={'name':'s3','parameters':fd.to_dict()}
        ref,_=build_reference_day(avg,meta,periods,cfg,{'mode':'capacity'},5,0)
        self.assertAlmostEqual(ref.queue_start_veh.iloc[12],ref.queue_end_veh.iloc[11],places=9)

    def test_closure_backward_and_forward_round_trip(self):
        fd=S3FD(65,30,4)
        density=np.array([10,20,40,60,80],dtype=float)
        speed=fd.speed_from_density(density)
        flow=fd.flow_from_density(density)
        profile=pd.DataFrame({
            'speed_mph':speed,
            'flow_observed_vehph':flow,
            'period':['AM']*len(speed),
        })
        backward,summary=backward_closure(profile,fd,{'AM':fd.capacity_vehphpl},dt_minutes=5)
        self.assertAlmostEqual(summary.observed_volume_veh,summary.inferred_volume_veh,places=8)
        branch=np.where(density <= fd.critical_density_vehpmipl,'free','congested')
        forward=reconstruct_speed_from_flow(flow,fd,branch=branch)
        joined=profile.join(forward)
        metrics=closure_speed_metrics(joined)
        self.assertLess(metrics['mae'],1e-8)
        self.assertTrue(backward['queue_end_veh'].ge(0).all())
if __name__=='__main__': unittest.main()
