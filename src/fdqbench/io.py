from __future__ import annotations
import json
from pathlib import Path
import pandas as pd

def read_json(path):
    return json.loads(Path(path).read_text())

def write_json(obj,path):
    Path(path).write_text(json.dumps(obj,indent=2,allow_nan=False))

def read_csv(path): return pd.read_csv(path)
