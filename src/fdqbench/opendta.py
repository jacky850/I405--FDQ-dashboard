from __future__ import annotations
import pandas as pd


def export_link_reference(reference_df: pd.DataFrame, path):
    cols=['link_id','tmc_id','time_of_day','period','dt_minutes','lambda_ref_vehph','mu_ref_vehph',
          'flow_ref_vehph','speed_mph','queue_start_veh','queue_end_veh','waiting_time_min','travel_time_min',
          'cumulative_arrivals_veh','cumulative_departures_veh','flow_ref_source','lambda_ref_source']
    keep=[c for c in cols if c in reference_df.columns]
    reference_df[keep].to_csv(path,index=False)


def export_vehicle_template(path):
    pd.DataFrame(columns=['vehicle_id','origin_zone','destination_zone','departure_time','path_id','link_sequence','demand_type']).to_csv(path,index=False)
