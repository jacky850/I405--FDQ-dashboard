from pathlib import Path
import json,sys
import pandas as pd
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/'src'))
from fdqbench.calibrate import fit_models
from fdqbench.reference import build_reference_day
from fdqbench.metrics import regression_metrics,period_volume_closure,queue_qaqc
from fdqbench.io import write_json
from fdqbench.opendta import export_link_reference,export_vehicle_template

cfg=json.loads((ROOT/'configs/synthetic_full_day.json').read_text())
avg=pd.read_csv(ROOT/cfg['average_weekday_csv'])
meta=json.loads((ROOT/cfg['link_metadata_json']).read_text())
models=fit_models(avg,'speed_mph','flow_vehph',meta['lanes'])
out=ROOT/'outputs/synthetic_full_day'; out.mkdir(parents=True,exist_ok=True)
write_json(models,out/'fitted_models.json')
anchor=cfg.get('speed_volume_model',{}).get('period_volume_anchor','none')
cfg['speed_volume_model']={'name':'s3','parameters':models['s3']['parameters'],'period_volume_anchor':anchor}
ref,mu=build_reference_day(avg,meta,cfg['periods'],cfg['speed_volume_model'],cfg['mu_config'],cfg['dt_minutes'],cfg['initial_queue_veh'])
ref.to_csv(out/'reference_day.csv',index=False)
write_json(mu,out/'mu_by_period.json')
metrics={'speed_volume_raw':regression_metrics(ref['flow_observed_vehph'],ref['flow_speed_only_vehph']),
         'speed_volume_anchored':regression_metrics(ref['flow_observed_vehph'],ref['flow_ref_vehph']),
         'queue_qaqc':queue_qaqc(ref)}
write_json(metrics,out/'metrics.json')
period_volume_closure(ref,dt_minutes=cfg['dt_minutes']).to_csv(out/'period_volume_closure.csv',index=False)
export_link_reference(ref,out/'opendta_link_reference.csv')
export_vehicle_template(out/'vehicle_file_template.csv')

x=range(len(ref)); labels=ref['time_of_day'].iloc[::24].tolist(); xt=list(range(0,len(ref),24))
plt.figure(figsize=(11,5)); plt.plot(x,ref['speed_mph'],label='Average weekday speed'); plt.xticks(xt,labels,rotation=45); plt.ylabel('mph'); plt.title('Input speed profile'); plt.tight_layout(); plt.savefig(out/'01_speed_profile.png',dpi=160); plt.close()
plt.figure(figsize=(11,5)); plt.plot(x,ref['flow_observed_vehph'],label='Observed volume'); plt.plot(x,ref['flow_ref_vehph'],'--',label='Reconstructed from speed'); plt.plot(x,ref['mu_ref_vehph'],label='mu reference'); plt.xticks(xt,labels,rotation=45); plt.ylabel('veh/h'); plt.legend(); plt.title('Speed-to-volume and service reference'); plt.tight_layout(); plt.savefig(out/'02_flow_mu.png',dpi=160); plt.close()
plt.figure(figsize=(11,5)); plt.plot(x,ref['queue_end_veh'],label='Q(t)'); plt.xticks(xt,labels,rotation=45); plt.ylabel('vehicles'); plt.title('Full-day queue: no AM/MD/PM reset'); plt.tight_layout(); plt.savefig(out/'03_queue.png',dpi=160); plt.close()
plt.figure(figsize=(11,5)); plt.plot(x,ref['waiting_time_min'],label='waiting'); plt.plot(x,ref['travel_time_min'],label='travel time'); plt.xticks(xt,labels,rotation=45); plt.ylabel('minutes'); plt.legend(); plt.title('Waiting/travel time reference'); plt.tight_layout(); plt.savefig(out/'04_wait_travel.png',dpi=160); plt.close()
print(json.dumps(metrics,indent=2))
