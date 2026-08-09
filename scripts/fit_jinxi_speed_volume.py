"""Template: compare S3 and triangular FD using true average-weekday speed+volume."""
from pathlib import Path
import sys,pandas as pd,json
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from fdqbench.calibrate import fit_models
INPUT=ROOT/'data/synthetic_full_day/average_weekday.csv'
LANES=1
m=fit_models(pd.read_csv(INPUT),'speed_mph','flow_vehph',LANES)
OUT=ROOT/'outputs/jinxi_fitted_speed_volume_models.json'; OUT.parent.mkdir(exist_ok=True)
OUT.write_text(json.dumps(m,indent=2))
print(json.dumps(m,indent=2)); print(OUT)
