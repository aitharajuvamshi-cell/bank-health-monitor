"""
Step 2: Clean and prep the raw FDIC files into one bank-quarter panel.

Input : data/raw/quarters/fin_YYYYMMDD.csv  (78 files, one per quarter)
        data/raw/failures.csv
Output: data/processed/panel.pkl        (all bank-quarters, cleaned, with derived metrics)
        data/processed/failures_clean.csv
        output/data_quality.json       (every cleaning decision, with counts)

Every cleaning rule below is logged with how many rows it touched, so the
report can say exactly what was changed and why.
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"
PROC.mkdir(parents=True, exist_ok=True)
OUT.mkdir(parents=True, exist_ok=True)

dq = {}  # data-quality log
log_path = RAW / "fetch_log.json"
dq["pulled_at"] = json.loads(log_path.read_text())["pulled_at"] if log_path.exists() else None

# ---------------------------------------------------------------- load
files = sorted((RAW / "quarters").glob("fin_*.csv"))
df = pd.concat((pd.read_csv(f, dtype={"REPDTE": str, "CB": str}) for f in files), ignore_index=True)
dq["raw_rows"] = len(df)
dq["quarters"] = len(files)
dq["first_quarter"] = df["REPDTE"].min()
dq["last_quarter"] = df["REPDTE"].max()

# ---------------------------------------------------------------- types
df["date"] = pd.to_datetime(df["REPDTE"], format="%Y%m%d")
df["quarter"] = df["date"].dt.to_period("Q").astype(str)          # e.g. 2023Q1
df["CB"] = df["CB"].fillna("0").astype(str).str.strip().eq("1")    # community bank flag
df = df.drop(columns=["ID"])

# ---------------------------------------------------------------- duplicates
dupes = df.duplicated(["CERT", "REPDTE"]).sum()
dq["duplicate_bank_quarters_removed"] = int(dupes)
df = df.drop_duplicates(["CERT", "REPDTE"])

# ---------------------------------------------------------------- impossible values
# Total assets must be positive. A zero/negative asset row is a shell filing.
bad_assets = (df["ASSET"].isna() | (df["ASSET"] <= 0)).sum()
dq["rows_dropped_nonpositive_assets"] = int(bad_assets)
df = df[df["ASSET"] > 0].copy()

# U.S. branches of foreign banks (e.g. State Bank of India, New York) file a
# Call Report but carry no equity capital of their own, so capital ratios do
# not exist for them. They are not comparable to US-chartered banks.
foreign_branch = df["EQ"].isna() & df["RBCT1J"].isna()
dq["rows_dropped_foreign_bank_branches_no_capital"] = int(foreign_branch.sum())
df = df[~foreign_branch].copy()

# Savings institutions filed a different form (the OTS Thrift Financial
# Report) until 2012. On that form some fields we need did not exist, so
# they come through blank. Flag them so they are treated as unknown, not 0.
pre2012_thrift_gap = df["SCAA"].isna() | df["LNRENROW"].isna()
dq["rows_with_pre2012_thrift_form_gaps"] = int(pre2012_thrift_gap.sum())
df["sec_detail_reported"] = df["SCAA"].notna() & df["SCHF"].notna()
df["cre_detail_reported"] = df["LNRENROW"].notna()

# Missing-value profile before any filling (share of rows missing each field)
miss = df.isna().mean().sort_values(ascending=False)
dq["missing_share_top10"] = {k: round(float(v), 4) for k, v in miss.head(10).items()}

# Balance-sheet line items: blank means the bank had none of that item.
# The FDIC leaves zero-balance lines empty for some forms, so blank -> 0.
# Ratios are NOT filled: a blank ratio means "not computable", not zero.
amount_cols = ["DEP", "COREDEP", "BRO", "DEPUNINS", "DEPINS", "NETINC", "EQ", "RBCT1J",
               "LNLSGR", "LNLSNET", "NCLNLS", "LNCRCD", "NTCRCDQ", "LNRECONS", "LNRENRES",
               "LNRENROW", "LNREMULT", "SCHA", "SCHF", "SCAA", "SCAF"]
filled = {c: int(df[c].isna().sum()) for c in amount_cols if df[c].isna().any()}
dq["amount_blanks_filled_with_zero"] = filled
df[amount_cols] = df[amount_cols].fillna(0)

# Uninsured deposits are only reported in full by larger banks for part of
# the period. Track whether the field is genuinely reported.
df["uninsured_reported"] = df["DEPUNINS"] > 0

# ---------------------------------------------------------------- derived metrics
def safe_div(a, b):
    return np.where(b > 0, a / b, np.nan)

df["assets_bn"] = df["ASSET"] / 1e6                     # thousands -> billions
df["uninsured_share"] = safe_div(df["DEPUNINS"], df["DEP"]) * 100
df["brokered_share"] = safe_div(df["BRO"], df["DEP"]) * 100
df["core_dep_share"] = safe_div(df["COREDEP"], df["DEP"]) * 100

# Unrealized securities losses: amortized cost minus fair value, HTM + AFS.
# Positive = the bank's bonds are worth less than it paid. This is the
# number that sank Silicon Valley Bank in 2023.
df["unreal_loss"] = np.where(df["sec_detail_reported"],
                             (df["SCHA"] - df["SCHF"]) + (df["SCAA"] - df["SCAF"]), np.nan)
df["unreal_loss_to_t1"] = safe_div(df["unreal_loss"], df["RBCT1J"]) * 100

# Commercial real estate concentration, per the 2006 interagency guidance:
# non-owner-occupied CRE (construction + multifamily + other nonfarm nonres)
# over total capital. Guidance thresholds: 300% total CRE, 100% construction.
df["cre_noo"] = df["LNRECONS"] + df["LNREMULT"] + (df["LNRENRES"] - df["LNRENROW"]).clip(lower=0)
df["cre_to_t1"] = np.where(df["cre_detail_reported"], safe_div(df["cre_noo"], df["RBCT1J"]) * 100, np.nan)
df["constr_to_t1"] = safe_div(df["LNRECONS"], df["RBCT1J"]) * 100

# Credit cards: quarterly net charge-offs, annualized, over card balances
df["card_nco_q_ann"] = safe_div(df["NTCRCDQ"] * 4, df["LNCRCD"]) * 100
df["card_share_of_loans"] = safe_div(df["LNCRCD"], df["LNLSGR"]) * 100

# Year-over-year growth (same bank, 4 quarters earlier)
df = df.sort_values(["CERT", "date"])
for col, name in [("ASSET", "asset_growth_yoy"), ("LNLSGR", "loan_growth_yoy"), ("DEP", "dep_growth_yoy")]:
    prev = df.groupby("CERT")[col].shift(4)
    prev_date = df.groupby("CERT")["date"].shift(4)
    ok = (df["date"] - prev_date).dt.days.between(360, 370)  # guard against gaps in a bank's history
    df[name] = np.where(ok & (prev > 0), (df[col] / prev - 1) * 100, np.nan)
df["dep_growth_qoq"] = df.groupby("CERT")["DEP"].pct_change(fill_method=None) * 100

# ---------------------------------------------------------------- outliers
# Tiny or brand-new banks produce extreme ratios (ROA of -300% on a bank with
# $5M of assets). Keep the raw value, add a capped copy for modelling, and
# log how many were capped. Caps = 1st / 99th percentile of the whole panel.
cap_cols = ["ROA", "ROAQ", "NCLNLSR", "NTLNLSR", "EQV", "RBC1AAJ", "LNLSDEPR", "brokered_share",
            "uninsured_share", "unreal_loss_to_t1", "cre_to_t1", "constr_to_t1",
            "asset_growth_yoy", "loan_growth_yoy", "NIMY", "EEFFR", "LNATRESR", "NPERFV"]
dq["capped_values"] = {}
for c in cap_cols:
    lo, hi = df[c].quantile([0.01, 0.99])
    n = int(((df[c] < lo) | (df[c] > hi)).sum())
    df[c + "_w"] = df[c].clip(lo, hi)
    dq["capped_values"][c] = {"p01": round(float(lo), 3), "p99": round(float(hi), 3), "rows_capped": n}

# ---------------------------------------------------------------- failures
fail = pd.read_csv(RAW / "failures.csv")
dq["failures_raw"] = len(fail)
fail["faildate"] = pd.to_datetime(fail["FAILDATE"], format="%m/%d/%Y")
fail_only = fail[fail["RESTYPE"].eq("FAILURE")].copy()   # drop open-bank assistance deals
dq["assistance_transactions_excluded"] = int(len(fail) - len(fail_only))
dq["failures_missing_cert"] = int(fail_only["CERT"].isna().sum())  # mostly pre-1990 records
fail_only = fail_only.dropna(subset=["CERT"]).sort_values("faildate").drop_duplicates("CERT", keep="first")
fail_only["CERT"] = fail_only["CERT"].astype(int)
fail_only.to_csv(PROC / "failures_clean.csv", index=False)
dq["failures_clean"] = len(fail_only)
dq["failures_since_2007"] = int((fail_only["faildate"] >= "2007-01-01").sum())

# Label: did this bank fail within 365 days after this quarter's report date?
fd = fail_only.set_index("CERT")["faildate"]
df["fail_date"] = df["CERT"].map(fd)
days = (df["fail_date"] - df["date"]).dt.days
df["fails_within_1y"] = days.between(1, 365)
df["failed_ever"] = df["fail_date"].notna()

matched = df.loc[df["failed_ever"], "CERT"].nunique()
dq["failed_banks_matched_to_call_reports"] = int(matched)
dq["failed_since_2007_not_matched"] = int(dq["failures_since_2007"] - matched)

# How banks leave the panel (needed to explain the consolidation story)
last = df.groupby("CERT")["date"].max()
latest = df["date"].max()
exited = last[last < latest]
exit_fail = exited.index.isin(fail_only["CERT"])
dq["banks_seen"] = int(df["CERT"].nunique())
dq["banks_exited"] = int(len(exited))
dq["banks_exited_by_failure"] = int(exit_fail.sum())
dq["banks_exited_other_mostly_mergers"] = int((~exit_fail).sum())

dq["clean_rows"] = len(df)
dq["clean_columns"] = df.shape[1]

df.to_pickle(PROC / "panel.pkl")
(OUT / "data_quality.json").write_text(json.dumps(dq, indent=1, default=str))
print(json.dumps(dq, indent=1, default=str))
