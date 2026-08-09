"""Template: raw multi-day detector/TMC data -> one average-weekday CSV."""
from pathlib import Path
import sys,pandas as pd
ROOT=Path(__file__).resolve().parents[1]; sys.path.insert(0,str(ROOT/'src'))
from fdqbench.preprocess import average_weekday
INPUT=ROOT/'data/synthetic_full_day/raw_weekdays.csv'
OUTPUT=ROOT/'outputs/jinxi_average_weekday.csv'
GROUP=['link_id','tmc_id']
raw=pd.read_csv(INPUT)
average_weekday(raw,group_cols=GROUP).to_csv(OUTPUT,index=False)
print(OUTPUT)
