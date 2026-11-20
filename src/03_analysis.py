"""
Step 3: Answer the business questions (everything except the early-warning model).

Input : data/processed/panel.pkl, data/processed/failures_clean.csv
Output: output/findings_analysis.json   (every number the report and dashboard use)

Questions answered here
  Q1  How much has US banking consolidated since 2007, and how do banks leave?
  Q2  Where is credit card credit stress now vs history, and does delinquency
      give advance warning of charge-offs?
  Q3  How do the big banks I am targeting compare right now?
  Q4  Did the Wells Fargo asset cap (Feb 2018 to Jun 2025) show up in the data?
  Q5  What did banks that failed look like a year before they failed?
  Q9  What have bank failures cost the FDIC's insurance fund, by year?
  Q10 Local view: Arizona banks and the March 2023 deposit run.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"

df = pd.read_pickle(PROC / "panel.pkl")
fail = pd.read_csv(PROC / "failures_clean.csv", parse_dates=["faildate"])
F = {}
LATEST = df["date"].max()
LATEST_Q = df.loc[df["date"] == LATEST, "quarter"].iloc[0]
F["latest_quarter"] = LATEST_Q
F["first_quarter"] = df["quarter"].min()


def r(x, n=2):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


# Banks referenced by name. CERT is the FDIC's permanent ID for a charter.
PEERS = {
    628: "JPMorgan Chase", 3510: "Bank of America", 3511: "Wells Fargo", 7213: "Citibank",
    4297: "Capital One", 6548: "U.S. Bank", 27471: "American Express", 27314: "Synchrony",
    5649: "Discover", 57512: "Western Alliance (Phoenix)",
}
F["peer_names"] = {str(k): v for k, v in PEERS.items()}

# ====================================================================== Q1
by_q = df.groupby("quarter").agg(banks=("CERT", "nunique"), assets=("ASSET", "sum")).reset_index()
top10 = (df.sort_values("ASSET", ascending=False).groupby("quarter").head(10)
         .groupby("quarter")["ASSET"].sum().rename("top10_assets"))
top4 = (df.sort_values("ASSET", ascending=False).groupby("quarter").head(4)
        .groupby("quarter")["ASSET"].sum().rename("top4_assets"))
by_q = by_q.join(top10, on="quarter").join(top4, on="quarter")
by_q["top10_share"] = by_q["top10_assets"] / by_q["assets"] * 100
by_q["top4_share"] = by_q["top4_assets"] / by_q["assets"] * 100
first, last = by_q.iloc[0], by_q.iloc[-1]

# New charters per year: first appearance after the first quarter in the panel
first_seen = df.groupby("CERT")["date"].min()
denovo = first_seen[first_seen > df["date"].min()].dt.year.value_counts().sort_index()
fail_by_year = fail[fail["faildate"].dt.year >= 2007].groupby(fail["faildate"].dt.year).size()

# Exits by year and reason
last_seen = df.groupby("CERT")["date"].max()
exited = last_seen[last_seen < LATEST]
exit_df = pd.DataFrame({"year": (exited + pd.offsets.QuarterEnd(1)).dt.year,
                        "failed": exited.index.isin(fail["CERT"])})
exits = exit_df.groupby(["year", "failed"]).size().unstack(fill_value=0)

F["q1"] = {
    "banks_first": int(first["banks"]), "banks_latest": int(last["banks"]),
    "banks_pct_change": r((last["banks"] / first["banks"] - 1) * 100, 1),
    "assets_first_tn": r(first["assets"] / 1e9, 2), "assets_latest_tn": r(last["assets"] / 1e9, 2),
    "top10_share_first": r(first["top10_share"], 1), "top10_share_latest": r(last["top10_share"], 1),
    "top4_share_first": r(first["top4_share"], 1), "top4_share_latest": r(last["top4_share"], 1),
    "exits_total": int(len(exited)), "exits_failed": int(exit_df["failed"].sum()),
    "exits_other": int((~exit_df["failed"]).sum()),
    "denovo_2007_2009": int(denovo.loc[2007:2009].sum()),
    "denovo_2011_2021": int(denovo.loc[2011:2021].sum()),
    "denovo_2022_latest": int(denovo.loc[2022:].sum()),
    "series": {
        "quarter": by_q["quarter"].tolist(),
        "banks": by_q["banks"].astype(int).tolist(),
        "top10_share": [r(x, 2) for x in by_q["top10_share"]],
        "top4_share": [r(x, 2) for x in by_q["top4_share"]],
    },
    "by_year": {
        "year": list(range(2007, LATEST.year + 1)),
        "denovo": [int(denovo.get(y, 0)) for y in range(2007, LATEST.year + 1)],
        "failures": [int(fail_by_year.get(y, 0)) for y in range(2007, LATEST.year + 1)],
        "exits_other": [int(exits.loc[y, False]) if y in exits.index and False in exits.columns else 0
                        for y in range(2007, LATEST.year + 1)],
    },
}

# ====================================================================== Q2
card = df[df["LNCRCD"] > 0].copy()
# TRAP: the FDIC's P3CRCDR / P9CRCDR "ratio" fields are past-due card loans
# divided by TOTAL ASSETS, not by card balances. Verified against the dollar
# fields (JPMorgan 2026Q2: P3CRCD $1.92bn / ASSET $4,091bn = 0.047% = P3CRCDR).
# Convert back to dollars, then divide by card balances ourselves.
card["p3_amt"] = card["P3CRCDR"] / 100 * card["ASSET"]
card["p9_amt"] = card["P9CRCDR"] / 100 * card["ASSET"]
card["dq30_card"] = card["p3_amt"] / card["LNCRCD"] * 100
ind = card.groupby("quarter").agg(nco=("NTCRCDQ", "sum"), bal=("LNCRCD", "sum"),
                                  p3=("p3_amt", "sum"), p9=("p9_amt", "sum"),
                                  issuers=("CERT", "nunique")).reset_index()
ind["nco_rate"] = ind["nco"] * 4 / ind["bal"] * 100      # annualized
ind["dq30_rate"] = ind["p3"] / ind["bal"] * 100           # 30-89 days past due
ind["dq90_rate"] = ind["p9"] / ind["bal"] * 100
ind = ind.set_index("quarter")

# Lead-lag: correlate delinquency now with charge-offs k quarters later.
# Use year-over-year changes so the shared long-run trend does not inflate it.
dq_chg = ind["dq30_rate"].diff(4)
nco_chg = ind["nco_rate"].diff(4)
lag_corr = {k: r(dq_chg.corr(nco_chg.shift(-k)), 3) for k in range(0, 5)}
best_lag = max(lag_corr, key=lambda k: lag_corr[k] if lag_corr[k] is not None else -9)

peak_q = ind["nco_rate"].idxmax()
low_q = ind.loc["2015Q1":, "nco_rate"].idxmin()
prepandemic = ind.loc["2019Q1":"2019Q4", "nco_rate"].mean()
last4 = ind["nco_rate"].iloc[-4:].mean()

# Issuer-level: trailing 4 quarters (dollar-weighted) so one noisy quarter does not dominate
iss_rows = []
for cert, name in PEERS.items():
    b = card[card["CERT"] == cert].sort_values("date")
    if b.empty:
        continue
    t4 = b.iloc[-4:]
    if t4["date"].max() < LATEST - pd.Timedelta(days=400):
        continue  # charter no longer reporting (Discover merged into Capital One)
    iss_rows.append({"cert": cert, "name": name, "quarter": t4["quarter"].iloc[-1],
                     "card_bal_bn": r(t4["LNCRCD"].iloc[-1] / 1e6, 1),
                     "nco_rate_t4": r(t4["NTCRCDQ"].sum() / t4["LNCRCD"].mean() * 100, 2),
                     "dq30_latest": r(t4["dq30_card"].iloc[-1], 2),
                     "card_share_of_loans": r(t4["card_share_of_loans"].iloc[-1], 1)})
iss = pd.DataFrame(iss_rows).query("card_bal_bn >= 20").sort_values("nco_rate_t4", ascending=False)

issuer_series = {}
for cert in iss["cert"]:
    b = card[card["CERT"] == cert].set_index("quarter")["card_nco_q_ann"]
    issuer_series[PEERS[cert]] = [r(b.get(q), 2) for q in ind.index]

F["q2"] = {
    "peak_quarter": peak_q, "peak_rate": r(ind.loc[peak_q, "nco_rate"]),
    "low_quarter_since_2015": low_q, "low_rate": r(ind.loc[low_q, "nco_rate"]),
    "rate_2019_avg": r(prepandemic), "rate_last4_avg": r(last4),
    "rate_latest": r(ind["nco_rate"].iloc[-1]), "dq30_latest": r(ind["dq30_rate"].iloc[-1]),
    "dq30_2019_avg": r(ind.loc["2019Q1":"2019Q4", "dq30_rate"].mean()),
    "card_balances_latest_bn": r(ind["bal"].iloc[-1] / 1e6, 0),
    "card_balances_2019q4_bn": r(ind.loc["2019Q4", "bal"] / 1e6, 0),
    "issuers_latest": int(ind["issuers"].iloc[-1]),
    "lag_corr": lag_corr, "best_lag_quarters": int(best_lag),
    "issuers": iss.to_dict("records"),
    "series": {"quarter": ind.index.tolist(),
               "nco_rate": [r(x) for x in ind["nco_rate"]],
               "dq30_rate": [r(x) for x in ind["dq30_rate"]],
               "dq90_rate": [r(x) for x in ind["dq90_rate"]],
               "issuers": issuer_series},
}

# ====================================================================== Q3
lat = df[df["date"] == LATEST].copy()
big = lat[lat["assets_bn"] >= 100]
cols = {"assets_bn": "Assets ($bn)", "dep_growth_yoy": "Deposit growth YoY %", "ROA": "ROA %",
        "NIMY": "Net interest margin %", "EEFFR": "Efficiency ratio %", "NTLNLSR": "Net charge-off rate %",
        "NCLNLSR": "Noncurrent loans %", "RBC1AAJ": "Tier 1 leverage %", "uninsured_share": "Uninsured deposits %",
        "unreal_loss_to_t1": "Unrealized securities loss / Tier 1 %"}
score = []
for cert, name in PEERS.items():
    row = lat[lat["CERT"] == cert]
    if row.empty:
        continue
    row = row.iloc[0]
    score.append({"cert": cert, "name": name, **{k: r(row[k], 2) for k in cols}})
peer_median = {k: r(big[k].median(), 2) for k in cols}
F["q3"] = {"columns": cols, "rows": score, "median_100bn_plus": peer_median,
           "n_banks_100bn_plus": int(len(big)), "quarter": LATEST_Q,
           "note": "ROA, NIM, efficiency and charge-off rate are year-to-date annualized, as published by the FDIC."}

# ====================================================================== Q4
base_q = "2017Q4"
cap_end_q = "2025Q1"   # last full quarter-end before the Fed lifted the cap on 3 Jun 2025
idx = {}
for cert in (3511, 628, 3510, 7213):
    s = df[df["CERT"] == cert].set_index("quarter")["ASSET"]
    idx[PEERS[cert]] = s / s.loc[base_q] * 100
idxdf = pd.DataFrame(idx).loc["2015Q1":]
growth = {k: r(idxdf.loc[cap_end_q, k] - 100, 1) for k in idxdf.columns}
since_lift = {k: r((idxdf.loc[LATEST_Q, k] / idxdf.loc[cap_end_q, k] - 1) * 100, 1) for k in idxdf.columns}
F["q4"] = {"base_quarter": base_q, "cap_end_quarter": cap_end_q,
           "growth_during_cap_pct": growth, "growth_since_lift_pct": since_lift,
           "series": {"quarter": idxdf.index.tolist(), **{k: [r(x, 1) for x in idxdf[k]] for k in idxdf.columns}},
           "caveat": ("Bank-level charter assets, not the holding company the Fed order applied to. "
                      "Direction matches; exact levels differ.")}

# ====================================================================== Q5
# Snapshot each failed bank at the report closest to 1 year before failure
# (270 to 365 days ahead), and compare with every bank that did NOT fail
# within the next 3 years, in the same quarters.
d = df.copy()
d["days_to_fail"] = (d["fail_date"] - d["date"]).dt.days
snap = d[d["days_to_fail"].between(270, 365)].sort_values("days_to_fail").drop_duplicates("CERT")
snap = snap[snap["fail_date"] >= "2008-01-01"]
qs = snap["quarter"].unique()
surv = d[d["quarter"].isin(qs) & ~(d["days_to_fail"].between(1, 3 * 365))]
metrics = {"NCLNLSR": "Noncurrent loans % of loans", "ROA": "Return on assets %",
           "RBC1AAJ": "Tier 1 leverage ratio %", "brokered_share": "Brokered deposits % of deposits",
           "constr_to_t1": "Construction loans % of Tier 1", "cre_to_t1": "Non-owner CRE % of Tier 1",
           "loan_growth_yoy": "Loan growth YoY %", "LNATRESR": "Loan loss reserve % of loans",
           "uninsured_share": "Uninsured deposits %"}
prof = []
for k, label in metrics.items():
    prof.append({"metric": k, "label": label, "failed_median": r(snap[k].median(), 2),
                 "survivor_median": r(surv[k].median(), 2)})
F["q5"] = {"n_failed": int(len(snap)), "n_survivor_rows": int(len(surv)), "profile": prof,
           "share_failed_negative_roa": r((snap["ROA"] < 0).mean() * 100, 1),
           "share_surv_negative_roa": r((surv["ROA"] < 0).mean() * 100, 1),
           "share_failed_constr_over_100": r((snap["constr_to_t1"] > 100).mean() * 100, 1),
           "share_surv_constr_over_100": r((surv["constr_to_t1"] > 100).mean() * 100, 1)}

# ====================================================================== Q9
fy = fail[fail["faildate"].dt.year >= 2007].copy()
fy["year"] = fy["faildate"].dt.year
cost = fy.groupby("year").agg(n=("CERT", "size"), assets=("QBFASSET", "sum"), cost=("COST", "sum")).reindex(
    range(2007, LATEST.year + 1), fill_value=0)
cost["cost_pct_assets"] = np.where(cost["assets"] > 0, cost["cost"] / cost["assets"] * 100, np.nan)
# Signature Bank shows COST = 0 in the FDIC file even though it was resolved at
# a loss, so recent-year totals are a LOWER BOUND. Flag zero-cost failures.
zero_cost = fy[(fy["COST"].fillna(0) == 0)]
big3 = fy[fy["year"] == 2023].sort_values("QBFASSET", ascending=False).head(3)
small = fy[fy["QBFASSET"] < 1e6]
large = fy[fy["QBFASSET"] >= 1e6]
F["q9"] = {
    "failures_2007_latest": int(cost["n"].sum()),
    "cost_total_bn": r(cost["cost"].sum() / 1e6, 1),
    "cost_2023_bn": r(cost.loc[2023, "cost"] / 1e6, 1),
    "assets_2023_bn": r(cost.loc[2023, "assets"] / 1e6, 1),
    "cost_2009_2011_bn": r(cost.loc[2009:2011, "cost"].sum() / 1e6, 1),
    "n_2009_2011": int(cost.loc[2009:2011, "n"].sum()),
    "loss_rate_small_banks": r(small["COST"].sum() / small["QBFASSET"].sum() * 100, 1),
    "loss_rate_large_banks": r(large["COST"].sum() / large["QBFASSET"].sum() * 100, 1),
    "n_small": int(len(small)), "n_large": int(len(large)),
    "biggest_2023": [{"name": x.NAME.title(), "assets_bn": r(x.QBFASSET / 1e6, 1), "cost_bn": r(x.COST / 1e6, 1),
                      "date": x.faildate.date().isoformat()} for x in big3.itertuples()],
    "by_year": {"year": cost.index.tolist(), "n": cost["n"].astype(int).tolist(),
                "assets_bn": [r(x / 1e6, 1) for x in cost["assets"]],
                "cost_bn": [r(x / 1e6, 2) for x in cost["cost"]],
                "cost_pct_assets": [r(x, 1) for x in cost["cost_pct_assets"]]},
    "zero_cost_failures": int(len(zero_cost)),
    "zero_cost_names": [f"{x.NAME.title()} ({x.faildate.year})" for x in zero_cost.itertuples()][:10],
    "note": "COST is the FDIC's estimated loss to the Deposit Insurance Fund; recent years are still estimates.",
}

# ====================================================================== Q10
az = df[df["STALP"] == "AZ"]
az_by_q = az.groupby("quarter").agg(n=("CERT", "nunique"), assets=("ASSET", "sum"))
wa = df[df["CERT"] == 57512].set_index("quarter")
wa_dep = wa["DEP"]
wa_unins = wa["uninsured_share"]
az_fail = fail[(fail["PSTALP"] == "AZ") & (fail["faildate"] >= "2007-01-01")]
F["q10"] = {
    "az_banks_first": int(az_by_q["n"].iloc[0]), "az_banks_latest": int(az_by_q["n"].iloc[-1]),
    "az_failures_since_2007": int(len(az_fail)),
    "wa_dep_2022q4_bn": r(wa_dep.loc["2022Q4"] / 1e6, 1), "wa_dep_2023q1_bn": r(wa_dep.loc["2023Q1"] / 1e6, 1),
    "wa_dep_change_pct": r((wa_dep.loc["2023Q1"] / wa_dep.loc["2022Q4"] - 1) * 100, 1),
    "wa_unins_2022q4": r(wa_unins.loc["2022Q4"], 1), "wa_unins_2023q4": r(wa_unins.loc["2023Q4"], 1),
    "wa_unins_latest": r(wa_unins.iloc[-1], 1),
    "wa_dep_latest_bn": r(wa_dep.iloc[-1] / 1e6, 1),
    "wa_series": {"quarter": wa.loc["2021Q1":].index.tolist(),
                  "deposits_bn": [r(x / 1e6, 1) for x in wa_dep.loc["2021Q1":]],
                  "uninsured_share": [r(x, 1) for x in wa_unins.loc["2021Q1":]]},
}

(OUT / "findings_analysis.json").write_text(json.dumps(F, indent=1))
for k in ["q1", "q2", "q4", "q5", "q9", "q10"]:
    print(k, {a: b for a, b in F[k].items() if a not in ("series", "by_year", "wa_series", "issuers", "profile")})
print("issuers", F["q2"]["issuers"])
print("profile", F["q5"]["profile"])
