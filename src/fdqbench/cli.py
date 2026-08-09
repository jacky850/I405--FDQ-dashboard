from __future__ import annotations
import argparse, json
from pathlib import Path
import pandas as pd
from .io import read_json,write_json
from .preprocess import average_weekday
from .calibrate import fit_models
from .reference import build_reference_day
from .metrics import regression_metrics,period_volume_closure,queue_qaqc
from .opendta import export_link_reference,export_vehicle_template


def cmd_average(args):
    d=pd.read_csv(args.input); out=average_weekday(d,args.timestamp,group_cols=args.group,speed_col=args.speed,flow_col=args.flow)
    out.to_csv(args.output,index=False)

def cmd_fit(args):
    d=pd.read_csv(args.input); result=fit_models(d,args.speed,args.flow,args.lanes); write_json(result,args.output)

def cmd_build(args):
    cfg=read_json(args.config); avg=pd.read_csv(cfg['average_weekday_csv']); meta=read_json(cfg['link_metadata_json'])
    ref,mu=build_reference_day(avg,meta,cfg['periods'],cfg['speed_volume_model'],cfg['mu_config'],cfg.get('dt_minutes',5),cfg.get('initial_queue_veh',0.0))
    out=Path(cfg.get('output_dir','outputs')); out.mkdir(parents=True,exist_ok=True)
    ref.to_csv(out/'reference_day.csv',index=False); write_json(mu,out/'mu_by_period.json')
    metrics={'queue_qaqc':queue_qaqc(ref)}
    if 'flow_observed_vehph' in ref:
        metrics['speed_volume']=regression_metrics(ref['flow_observed_vehph'],ref['flow_ref_vehph'])
        period_volume_closure(ref,dt_minutes=cfg.get('dt_minutes',5)).to_csv(out/'period_volume_closure.csv',index=False)
    write_json(metrics,out/'metrics.json'); export_link_reference(ref,out/'opendta_link_reference.csv'); export_vehicle_template(out/'vehicle_file_template.csv')

def main():
    p=argparse.ArgumentParser(prog='fdqbench'); s=p.add_subparsers(dest='cmd',required=True)
    a=s.add_parser('average-weekday'); a.add_argument('input'); a.add_argument('output'); a.add_argument('--timestamp',default='timestamp'); a.add_argument('--speed',default='speed_mph'); a.add_argument('--flow',default='flow_vehph'); a.add_argument('--group',nargs='*',default=[]); a.set_defaults(func=cmd_average)
    f=s.add_parser('fit-speed-volume'); f.add_argument('input'); f.add_argument('output'); f.add_argument('--speed',default='speed_mph'); f.add_argument('--flow',default='flow_vehph'); f.add_argument('--lanes',type=int,default=1); f.set_defaults(func=cmd_fit)
    b=s.add_parser('build-reference'); b.add_argument('config'); b.set_defaults(func=cmd_build)
    x=p.parse_args(); x.func(x)
if __name__=='__main__': main()
