"""Current NVTA audit-package adapter using v0.2 full-day/reference API."""
from pathlib import Path
import sys,math,json,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from fdqbench.reference import build_reference_day
from fdqbench.opendta import export_link_reference
from fdqbench.metrics import queue_qaqc

link=pd.read_csv(ROOT/'data/nvta_i66_eb_26736_pm/link.csv').iloc[0]
spd=pd.read_csv(ROOT/'data/nvta_i66_eb_26736_pm/speed_profile_5min.csv')
avg=pd.DataFrame({'time_of_day':spd['time'],'speed_mph':spd['speed_mph']})
vf=float(link.free_speed_mph); vc=float(link.cutoff_speed_mph)
m=2*math.log(2)/math.log(vf/vc) if vf>vc>0 else 4.0
kc=float(link.capacity_vehphpl)/vc
meta={'link_id':str(link.link_id),'tmc_id':str(link.tmc_code),'lanes':int(link.lanes),
      'length_mi':float(link.length_mi),'free_speed_mph':vf,
      'capacity_vehphpl':float(link.capacity_vehphpl),'cutoff_speed_mph':vc}
model={'name':'s3','parameters':{'free_speed_mph':vf,'critical_density_vehpmipl':kc,'m':m},
       'period_volumes_veh':{'PM':float(link.period_volume_veh)}}
periods=[{'name':'PM','start':'15:00','end':'19:05'}]
mu_cfg={'mode':'post_t2_median','t2_by_period':{'PM':'17:45'},'blend_intervals':0}
ref,mu=build_reference_day(avg,meta,periods,model,mu_cfg,5,0)
out=ROOT/'outputs/nvta_i66_v02'; out.mkdir(parents=True,exist_ok=True)
ref.to_csv(out/'reference_pm.csv',index=False); export_link_reference(ref,out/'opendta_link_reference.csv')
(out/'mu_by_period.json').write_text(json.dumps(mu,indent=2))
(out/'qaqc.json').write_text(json.dumps(queue_qaqc(ref),indent=2))
print('S3 parameters:',model['parameters']); print('mu:',mu); print(out)
