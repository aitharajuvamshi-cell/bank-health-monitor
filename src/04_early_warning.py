"""
Step 4: Can public Call Report data warn us a year before a bank fails?

Question Q6: Build an early-warning screen, test it honestly on years it never saw.
Question Q7: Why did the 2023 failures (SVB, Signature, First Republic) slip through?
Question Q8: What does the screen say about the banking system today?

Unit of analysis : one bank in one quarter.
Target           : fails_within_1y  = the bank failed 1 to 365 days after that report.
Honest test      : train on reports from 2007-2011 (the crisis), test on 2012 onward,
                   so the model is judged on failures it never saw, in a calmer era.
Label cut-off    : reports after (last failure date in file - 365 days) are dropped from
                   scoring because their 1-year outcome is not yet known.

Three screens are compared, simplest first:
  A. Red-flag rule  : count of 6 textbook warning signs (anyone can do this in Excel)
  B. Logistic regression on 14 capped ratios (transparent, every weight readable)
  C. Gradient boosting (flexible, harder to explain)
"""
import json
from pathlib import Path

import numpy as np
import pandas as pd
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.impute import SimpleImputer
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import roc_auc_score
from sklearn.pipeline import make_pipeline
from sklearn.preprocessing import StandardScaler

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
PROC = ROOT / "data" / "processed"
OUT = ROOT / "output"
LOCAL = ROOT / "output" / "local_only"   # git-ignored: contains bank names
LOCAL.mkdir(parents=True, exist_ok=True)

df = pd.read_pickle(PROC / "panel.pkl")
fail = pd.read_csv(PROC / "failures_clean.csv", parse_dates=["faildate"])
F = {}


def r(x, n=3):
    return None if x is None or (isinstance(x, float) and np.isnan(x)) else round(float(x), n)


FEATURES = {
    "NCLNLSR_w": "Noncurrent loans % of loans",
    "NPERFV_w": "Nonperforming assets % of assets",
    "ROA_w": "Return on assets %",
    "RBC1AAJ_w": "Tier 1 leverage ratio %",
    "EQV_w": "Equity % of assets",
    "LNATRESR_w": "Loan loss reserve % of loans",
    "brokered_share_w": "Brokered deposits % of deposits",
    "constr_to_t1_w": "Construction loans % of Tier 1",
    "cre_to_t1_w": "Non-owner CRE % of Tier 1",
    "loan_growth_yoy_w": "Loan growth YoY %",
    "LNLSDEPR_w": "Loans % of deposits",
    "NIMY_w": "Net interest margin %",
    "EEFFR_w": "Efficiency ratio %",
    "log_assets": "Size (log assets)",
}
df["log_assets"] = np.log10(df["ASSET"])

# ---------------------------------------------------------------- A. red-flag rule
RULES = {
    "Noncurrent loans > 3%": df["NCLNLSR"] > 3,
    "Losing money (ROA < 0)": df["ROA"] < 0,
    "Tier 1 leverage < 8%": df["RBC1AAJ"] < 8,
    "Brokered deposits > 10%": df["brokered_share"] > 10,
    "Construction > 100% of capital": df["constr_to_t1"] > 100,
    "Non-owner CRE > 300% of capital": df["cre_to_t1"] > 300,
}
flags = pd.DataFrame(RULES).fillna(False)
df["red_flags"] = flags.sum(axis=1)

# ---------------------------------------------------------------- split
last_fail = fail["faildate"].max()
label_cutoff = last_fail - pd.Timedelta(days=365)
scored = df[df["date"] <= label_cutoff].copy()
train = scored[scored["date"] < "2012-01-01"]
test = scored[scored["date"] >= "2012-01-01"]
F["split"] = {
    "train_period": f"{train['quarter'].min()} to {train['quarter'].max()}",
    "test_period": f"{test['quarter'].min()} to {test['quarter'].max()}",
    "train_rows": int(len(train)), "test_rows": int(len(test)),
    "train_positive_rows": int(train["fails_within_1y"].sum()),
    "test_positive_rows": int(test["fails_within_1y"].sum()),
    "test_failed_banks": int(test.loc[test["fails_within_1y"], "CERT"].nunique()),
    "base_rate_test_pct": r(test["fails_within_1y"].mean() * 100, 3),
    "label_cutoff": label_cutoff.date().isoformat(),
}

X_cols = list(FEATURES)
y_tr, y_te = train["fails_within_1y"].astype(int), test["fails_within_1y"].astype(int)

logit = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                      LogisticRegression(max_iter=2000, C=0.5, class_weight="balanced"))
logit.fit(train[X_cols], y_tr)
gbm = HistGradientBoostingClassifier(max_depth=4, learning_rate=0.05, max_iter=300,
                                     l2_regularization=1.0, random_state=7)
gbm.fit(train[X_cols], y_tr)

test = test.copy()
test["s_rule"] = test["red_flags"] + test["NCLNLSR_w"] / 100  # tiny tie-breaker inside a flag count
test["s_logit"] = logit.predict_proba(test[X_cols])[:, 1]
test["s_gbm"] = gbm.predict_proba(test[X_cols])[:, 1]


def capture(score, y, top_pct):
    """Share of all failures caught if examiners review only the top X% riskiest bank-quarters."""
    n = int(np.ceil(len(score) * top_pct / 100))
    top = np.argsort(-score.values)[:n]
    caught = y.values[top].sum()
    return caught / y.sum() * 100, caught / n * 100


results = []
for key, name in [("s_rule", "A. Red-flag rule (6 checks)"), ("s_logit", "B. Logistic regression"),
                  ("s_gbm", "C. Gradient boosting")]:
    row = {"screen": name, "auc": r(roc_auc_score(y_te, test[key]))}
    for p in (1, 2, 5):
        cap, prec = capture(test[key], y_te, p)
        row[f"capture_top{p}"] = r(cap, 1)
        row[f"precision_top{p}"] = r(prec, 1)
    results.append(row)
F["model_results"] = results

# Robustness: regulators close a bank largely BECAUSE its capital has run out,
# so low capital is partly the outcome itself. Refit without the two capital
# ratios to see how much warning the earlier signals give on their own.
no_cap = [c for c in X_cols if c not in ("RBC1AAJ_w", "EQV_w")]
logit_nc = make_pipeline(SimpleImputer(strategy="median", add_indicator=True), StandardScaler(),
                         LogisticRegression(max_iter=2000, C=0.5, class_weight="balanced"))
logit_nc.fit(train[no_cap], y_tr)
s_nc = pd.Series(logit_nc.predict_proba(test[no_cap])[:, 1], index=test.index)
cap2, prec2 = capture(s_nc, y_te, 2)
F["no_capital_variant"] = {"auc": r(roc_auc_score(y_te, s_nc)), "capture_top2": r(cap2, 1),
                           "precision_top2": r(prec2, 1)}

# Per-quarter threshold: a bank is "flagged" if it is in that quarter's top 2%
# by logistic score. Quarter-relative avoids a crisis quarter swamping the list.
test["pct_rank"] = test.groupby("quarter")["s_logit"].rank(pct=True)
test["flagged"] = test["pct_rank"] >= 0.98

# Bank-level view: of banks that failed in the test era, how many were flagged at
# least once in the year before failure, and how far ahead was the first flag?
pos = test[test["fails_within_1y"]]
fb = pos.groupby("CERT").agg(any_flag=("flagged", "any"),
                             first_flag_days=("fail_date", "first"))
lead = []
for cert, g in pos.groupby("CERT"):
    g = g[g["flagged"]]
    if len(g):
        lead.append((g["fail_date"].iloc[0] - g["date"].min()).days)
never_failed = test[~test["failed_ever"]]
false_alarm_banks = never_failed.groupby("CERT")["flagged"].any()
F["bank_level"] = {
    "failed_banks_test": int(len(fb)),
    "flagged_before_failure": int(fb["any_flag"].sum()),
    "flagged_before_failure_pct": r(fb["any_flag"].mean() * 100, 1),
    "median_days_warning": int(np.median(lead)) if lead else None,
    "healthy_banks_test": int(len(false_alarm_banks)),
    "healthy_banks_ever_flagged_pct": r(false_alarm_banks.mean() * 100, 1),
    "flags_per_quarter": int(test.groupby("quarter")["flagged"].sum().median()),
}

# Which ratios drive the logistic model? (standardized coefficients)
coefs = logit.named_steps["logisticregression"].coef_[0][:len(X_cols)]
F["logit_weights"] = sorted([{"feature": FEATURES[c], "weight": r(w, 3)} for c, w in zip(X_cols, coefs)],
                            key=lambda d: -abs(d["weight"]))

# Red-flag rule: hit rate per flag in the test era
F["flag_lift"] = []
tflags = flags.loc[test.index]
for name in RULES:
    on = tflags[name]
    F["flag_lift"].append({"flag": name, "share_of_bank_quarters": r(on.mean() * 100, 1),
                           "fail_rate_if_on": r(test.loc[on, "fails_within_1y"].mean() * 100, 2),
                           "fail_rate_if_off": r(test.loc[~on, "fails_within_1y"].mean() * 100, 3)})
F["fail_rate_by_flag_count"] = (test.groupby(test["red_flags"].clip(upper=4))["fails_within_1y"]
                                .agg(["mean", "size"]).reset_index()
                                .assign(mean=lambda d: (d["mean"] * 100).round(2))
                                .rename(columns={"red_flags": "flags", "mean": "fail_rate_pct", "size": "bank_quarters"})
                                .to_dict("records"))

# ---------------------------------------------------------------- Q7: 2023
# Score every bank in 2022Q4 (the last report before the March 2023 run) with the
# SAME credit model, and rank SVB / Signature / First Republic among $10bn+ banks.
q = df[df["quarter"] == "2022Q4"].copy()
q["s_logit"] = logit.predict_proba(q[X_cols])[:, 1]
q["red_flags"] = q["red_flags"]
q10 = q[q["assets_bn"] >= 10].copy()
for c in ("s_logit", "uninsured_share", "unreal_loss_to_t1"):
    q10[c + "_pct"] = q10[c].rank(pct=True) * 100
# Liquidity screen built AFTER seeing 2023 (stated plainly in the report):
# both uninsured deposits and unrealized losses in the top quartile of big banks.
q10["liq_flag"] = (q10["uninsured_share_pct"] >= 75) & (q10["unreal_loss_to_t1_pct"] >= 75)
cases = {24735: "Silicon Valley Bank", 57053: "Signature Bank", 59017: "First Republic Bank",
         57512: "Western Alliance (Phoenix)"}
case_rows = []
for cert, name in cases.items():
    row = q10[q10["CERT"] == cert].iloc[0]
    case_rows.append({"name": name, "assets_bn": r(row["assets_bn"], 1), "red_flags": int(row["red_flags"]),
                      "credit_score_pct": r(row["s_logit_pct"], 0), "ROA": r(row["ROA"], 2),
                      "noncurrent": r(row["NCLNLSR"], 2), "uninsured_share": r(row["uninsured_share"], 1),
                      "unreal_loss_to_t1": r(row["unreal_loss_to_t1"], 1),
                      "uninsured_pct": r(row["uninsured_share_pct"], 0),
                      "unreal_pct": r(row["unreal_loss_to_t1_pct"], 0), "liq_flag": bool(row["liq_flag"])})
u_top = q10[q10["uninsured_share_pct"] >= 94].sort_values("uninsured_share", ascending=False)
F["q7_uninsured_only"] = {
    "threshold_pct": r(u_top["uninsured_share"].min(), 1), "n_banks": int(len(u_top)),
    "n_failed": int(u_top["CERT"].isin([24735, 57053, 59017]).sum()),
    "survivors": [pretty_name(x) for x in u_top.loc[~u_top["CERT"].isin([24735, 57053, 59017]), "NAME"]],
}
F["q7"] = {
    "n_banks_10bn": int(len(q10)), "cases": case_rows,
    "median_uninsured_10bn": r(q10["uninsured_share"].median(), 1),
    "median_unreal_10bn": r(q10["unreal_loss_to_t1"].median(), 1),
    "liq_flagged_count": int(q10["liq_flag"].sum()),
    "liq_flagged_failed": int(q10.loc[q10["liq_flag"], "CERT"].isin([24735, 57053, 59017]).sum()),
    "scatter": [{"x": r(a, 1), "y": r(b, 1), "failed": bool(c in (24735, 57053, 59017)), "label": cases.get(c, "")}
                for a, b, c in zip(q10["uninsured_share"], q10["unreal_loss_to_t1"], q10["CERT"])
                if pd.notna(a) and pd.notna(b)],
}

# ---------------------------------------------------------------- Q8: today
now = df[df["date"] == df["date"].max()].copy()
now["s_logit"] = logit.predict_proba(now[X_cols])[:, 1]
cut = now["s_logit"].quantile(0.98)
now["flagged"] = now["s_logit"] >= cut
fl = now[now["flagged"]]
now10 = now[now["assets_bn"] >= 10].copy()
for c in ("uninsured_share", "unreal_loss_to_t1"):
    now10[c + "_pct"] = now10[c].rank(pct=True) * 100
liq_cut_u = q10["uninsured_share"].quantile(0.75)   # SAME absolute cut-offs as 2022Q4
liq_cut_l = q10["unreal_loss_to_t1"].quantile(0.75)
now10["liq_flag"] = (now10["uninsured_share"] >= liq_cut_u) & (now10["unreal_loss_to_t1"] >= liq_cut_l)
flag_counts = flags.loc[fl.index].sum().sort_values(ascending=False)
F["q8"] = {
    "quarter": now["quarter"].iloc[0], "banks_scored": int(len(now)),
    "flagged": int(len(fl)), "flagged_assets_bn": r(fl["assets_bn"].sum(), 1),
    "flagged_share_of_system_assets_pct": r(fl["ASSET"].sum() / now["ASSET"].sum() * 100, 2),
    "flagged_median_assets_m": r(fl["ASSET"].median() / 1e3, 0),
    "flagged_largest_bn": r(fl["assets_bn"].max(), 1),
    "flagged_by_state": fl["STALP"].value_counts().head(8).to_dict(),
    "flagged_flag_counts": {k: int(v) for k, v in flag_counts.items()},
    "flagged_with_neg_roa_pct": r((fl["ROA"] < 0).mean() * 100, 0),
    "system_median_noncurrent": r(now["NCLNLSR"].median(), 2),
    "liq_cut_uninsured": r(liq_cut_u, 1), "liq_cut_unreal": r(liq_cut_l, 1),
    "liq_flag_10bn_now": int(now10["liq_flag"].sum()), "n_banks_10bn_now": int(len(now10)),
    "median_unreal_10bn_now": r(now10["unreal_loss_to_t1"].median(), 1),
    "median_uninsured_10bn_now": r(now10["uninsured_share"].median(), 1),
}
# Names stay local. A public post that lists named small banks as "at risk of
# failing" could do real harm and is not something a screen can justify.
keep = ["CERT", "NAME", "CITY", "STALP", "assets_bn", "s_logit", "red_flags", "NCLNLSR", "ROA", "RBC1AAJ",
        "brokered_share", "constr_to_t1", "cre_to_t1"]
fl.sort_values("s_logit", ascending=False)[keep].to_csv(LOCAL / "watchlist_latest.csv", index=False)
now10[now10["liq_flag"]][["CERT", "NAME", "STALP", "assets_bn", "uninsured_share", "unreal_loss_to_t1"]] \
    .to_csv(LOCAL / "liquidity_watch_latest.csv", index=False)
now[["CERT", "quarter", "s_logit", "flagged"]].to_csv(LOCAL / "scores_latest.csv", index=False)

# Explorer score history for big banks (public dashboard shows big banks only)
hist = df[(df["date"] >= "2012-01-01")].copy()
hist["s_logit"] = logit.predict_proba(hist[X_cols])[:, 1]
hist["pct_rank"] = hist.groupby("quarter")["s_logit"].rank(pct=True) * 100
hist[["CERT", "quarter", "pct_rank"]].to_pickle(PROC / "score_history.pkl")

(OUT / "findings_model.json").write_text(json.dumps(F, indent=1))
print(json.dumps({k: v for k, v in F.items() if k not in ("q7",)}, indent=1)[:6000])
print(json.dumps(F["q7"]["cases"], indent=1))
print({k: v for k, v in F["q7"].items() if k not in ("scatter", "cases")})
