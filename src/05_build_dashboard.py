"""
Step 5: Build the interactive dashboard.

Input : output/findings_analysis.json, output/findings_model.json,
        output/data_quality.json, data/processed/panel.pkl
Output: docs/index.html          full standalone page (GitHub Pages serves /docs)
        output/dashboard_body.html  same page without the <html> wrapper (for the Claude artifact)

No number is typed into the page. The template reads everything from the
JSON blob this script injects, so re-running the pipeline after a new
quarter of FDIC data rebuilds the dashboard with no hand edits.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

def pretty_name(raw):
    """FDIC names are upper case; .title() mangles acronyms. Fix the common ones."""
    import re
    s = str(raw).replace("&", " & ").title()
    fixes = {"Na": "N.A.", "Nb": "N.B.", "Natl": "National", "Assn": "Association", "Usa": "USA",
             "Fsb": "FSB", "Bny": "BNY", "Hsbc": "HSBC", "Umb": "UMB", "Cibc": "CIBC", "Td": "TD",
             "Pnc": "PNC", "Tr": "Trust", "Co": "Co.", "Bmo": "BMO", "Ubs": "UBS", "Svb": "SVB",
             "Mufg": "MUFG", "Ny": "NY", "Us": "US"}
    words = [fixes.get(w, w) for w in s.split(" ")]
    s = " ".join(words).replace("Jpmorgan", "JPMorgan").replace("U S ", "U.S. ")
    return re.sub(r"\s+", " ", s).strip()


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"
DOCS = ROOT / "docs"
DOCS.mkdir(exist_ok=True)

A = json.loads((OUT / "findings_analysis.json").read_text())
M = json.loads((OUT / "findings_model.json").read_text())
DQ = json.loads((OUT / "data_quality.json").read_text())

# ---------------------------------------------------------------- bank explorer data
# Public dashboard: every bank that was ever $10bn+, plus every Arizona bank.
# Only reported facts are shown per bank. Model risk scores are NOT shown per
# named bank (see the report, section "Why names stay off the public page").
df = pd.read_pickle(ROOT / "data" / "processed" / "panel.pkl")
max_assets = df.groupby("CERT")["assets_bn"].max()
keep = set(max_assets[max_assets >= 10].index) | set(df.loc[df["STALP"] == "AZ", "CERT"])
sub = df[df["CERT"].isin(keep)]
quarters = sorted(df["quarter"].unique())
qpos = {q: i for i, q in enumerate(quarters)}
METRICS = {"assets_bn": 1, "ROA": 2, "NCLNLSR": 2, "NTLNLSR": 2, "RBC1AAJ": 2,
           "uninsured_share": 1, "unreal_loss_to_t1": 1, "dep_growth_yoy": 1}
banks, series = [], {}
for cert, g in sub.groupby("CERT"):
    g = g.sort_values("date")
    last = g.iloc[-1]
    banks.append({"c": int(cert), "n": pretty_name(last["NAME"]), "st": last["STALP"],
                  "city": str(last["CITY"]).title(), "last": last["quarter"],
                  "a": round(float(last["assets_bn"]), 1), "failed": bool(last["failed_ever"])})
    s = {}
    for m, nd in METRICS.items():
        arr = [None] * len(quarters)
        for q, v in zip(g["quarter"], g[m]):
            if pd.notna(v) and np.isfinite(v):
                arr[qpos[q]] = round(float(v), nd)
        s[m] = arr
    series[str(int(cert))] = s
banks.sort(key=lambda b: -b["a"])
EX = {"quarters": quarters, "banks": banks, "series": series}

# ---------------------------------------------------------------- inject
data = {"a": A, "m": M, "dq": DQ, "ex": EX}
blob = json.dumps(data, separators=(",", ":")).replace("</", "<\\/")
tpl = (ROOT / "src" / "dashboard_template.html").read_text(encoding="utf-8")
body = tpl.replace("/*__DATA__*/null", blob)
(OUT / "dashboard_body.html").write_text(body, encoding="utf-8")

full = ("<!doctype html>\n<html lang=\"en\">\n<head>\n<meta charset=\"utf-8\">\n"
        "<meta name=\"viewport\" content=\"width=device-width, initial-scale=1, viewport-fit=cover\">\n"
        "</head>\n<body>\n" + body + "\n</body>\n</html>\n")
(DOCS / "index.html").write_text(full, encoding="utf-8")
print(f"explorer banks: {len(banks)}  page size: {len(full)/1e6:.2f} MB")
