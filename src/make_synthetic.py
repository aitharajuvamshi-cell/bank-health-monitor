"""
Make a synthetic "twin" of the bank-quarter panel.

Why: when the real data is confidential (as it would be inside a bank), you
can still get help writing and testing code by sharing a file that has the
same columns, types and realistic ranges, but no real records.

How: every column is sampled INDEPENDENTLY from that column's real
distribution (random draws of real values, then lightly jittered). That keeps
column names, types and ranges, and deliberately breaks every relationship
between columns and between rows.

So the synthetic file is good for: writing code, testing the pipeline,
sharing the schema with Claude or a colleague.
It is useless for: findings. Any pattern in it is noise.

Output: data/synthetic/panel_synthetic.csv   (2,000 rows)
        data/synthetic/schema.json            (column, type, FDIC title, range)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
SYN = ROOT / "data" / "synthetic"
SYN.mkdir(parents=True, exist_ok=True)
rng = np.random.default_rng(42)
N = 2000

df = pd.read_pickle(ROOT / "data" / "processed" / "panel.pkl")
titles = json.loads((ROOT / "data" / "raw" / "field_titles.json").read_text())

cols = [c for c in df.columns if not c.endswith("_w")]          # skip the capped copies
out, schema = {}, []
for c in cols:
    s = df[c]
    if c in ("NAME", "NAMEHCR"):
        out[c] = [f"SYNTHETIC BANK {i:04d}" for i in range(N)]
    elif c == "CITY":
        out[c] = ["SYNTHETIC CITY"] * N
    elif c == "CERT":
        out[c] = rng.choice(np.arange(900000, 999999), N, replace=False)
    elif pd.api.types.is_bool_dtype(s):
        out[c] = rng.random(N) < s.mean()
    elif pd.api.types.is_numeric_dtype(s):
        vals = s.dropna().to_numpy()
        draw = rng.choice(vals, N) if len(vals) else np.full(N, np.nan)
        jitter = 1 + rng.normal(0, 0.05, N)                      # +/-5% so no real value is copied exactly
        draw = draw * jitter
        miss = rng.random(N) < s.isna().mean()
        draw = np.where(miss, np.nan, draw)
        out[c] = draw
    else:
        out[c] = rng.choice(s.dropna().astype(str).to_numpy(), N)
    schema.append({"column": c, "dtype": str(s.dtype), "fdic_title": titles.get(c, "derived in 02_clean.py"),
                   "missing_share": round(float(s.isna().mean()), 4),
                   "min": None if not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s) else round(float(np.nanmin(s)), 4),
                   "max": None if not pd.api.types.is_numeric_dtype(s) or pd.api.types.is_bool_dtype(s) else round(float(np.nanmax(s)), 4)})

syn = pd.DataFrame(out)
syn.to_csv(SYN / "panel_synthetic.csv", index=False)
(SYN / "schema.json").write_text(json.dumps(schema, indent=1))
print(f"wrote {len(syn):,} synthetic rows x {syn.shape[1]} columns to data/synthetic/")
