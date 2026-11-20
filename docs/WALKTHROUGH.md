# Walkthrough: how the US Bank Health Monitor was built

This guide explains, in plain words, what the project does, how each step works, and why each decision was made. Read it until you can explain every section out loud without looking. Numbers are from the run with data through 2026 Q2.

## 1. The 30-second version (say this out loud)

"I wanted to work with real bank data, so I used the FDIC's public API, which has the quarterly Call Report for every insured bank in the US. I pulled 78 quarters, 2007 to 2026, about 487,000 bank-quarter records, and joined them to the FDIC's list of bank failures. I cleaned it in Python, answered ten business questions, and built a dashboard. The most interesting part was an early-warning screen. I trained it only on the 2008-2011 crisis and tested it on the years after. It flagged about 90% of the banks that later failed, around ten months ahead. Then I showed where it fails. It rated Silicon Valley Bank as low risk in 2022, because SVB's loans were fine. Its problem was uninsured deposits and losses on its bond portfolio, which a credit-based screen never looks at."

## 2. Where everything is

| File | What it does | What to remember |
|---|---|---|
| `src/01_fetch_fdic.py` | Downloads 78 quarters of Call Report data and the failures table from `api.fdic.gov` | Public API, no key. One request per quarter, CSV format. Skips quarters already on disk. |
| `src/02_clean.py` | Combines the files into one table, cleans it, builds 20 derived ratios | Every cleaning rule writes a count to `output/data_quality.json` |
| `src/03_analysis.py` | Answers Q1-Q5, Q9, Q10 | Writes `output/findings_analysis.json` |
| `src/04_early_warning.py` | Builds and tests the failure screens (Q6-Q8) | Writes `output/findings_model.json`; named watchlist goes to `output/local_only/` |
| `src/05_build_dashboard.py` | Builds `docs/index.html` from the JSON | No number is typed into the page |
| `src/07_write_report.py` | Builds `docs/REPORT.md` from the JSON | Same rule |
| `src/make_synthetic.py` | Makes a fake copy of the data with the same columns | For safe sharing and testing |
| `src/06_claude_memo.py` | Asks Claude to draft a memo from summary numbers only | Never sends row-level data |
| `run_all.py` | Runs every step in order | `--no-fetch` skips the download |
| `.github/workflows/quarterly-refresh.yml` | Re-runs everything each quarter on GitHub | Commits the new dashboard and report |

## 3. Concepts you must know cold

**Call Report.** Every FDIC-insured bank files one each quarter with its regulator: balance sheet, income, loan quality, capital. The FDIC publishes them. Each bank has a permanent ID called the **certificate number (CERT)**. JPMorgan Chase Bank is CERT 628.

**Bank charter vs holding company.** The data is for the bank itself (JPMorgan Chase Bank, N.A.), not the parent company (JPMorgan Chase & Co.). So numbers will not match an earnings release exactly. Say this before anyone asks.

**Dollar units.** The FDIC reports dollars in thousands. A value of 4,091,315,000 means $4.09 trillion.

| Measure | FDIC field | Plain meaning | Why a risk team cares |
|---|---|---|---|
| ROA | `ROA` | Net income as % of assets, annualized | Losing money (ROA below 0) is the strongest single warning sign in the data |
| Net interest margin | `NIMY` | What the bank earns on loans and bonds minus what it pays on deposits, as % of earning assets | Card lenders run high NIM (Synchrony 12.9%) because card rates are high |
| Efficiency ratio | `EEFFR` | Costs as % of revenue. Lower is better | 54% means 54 cents of cost per dollar of revenue |
| Net charge-off rate | `NTLNLSR` | Loans written off as uncollectible, minus recoveries, as % of loans | The real credit loss |
| Noncurrent loans | `NCLNLSR` | Loans 90+ days late or no longer accruing interest, as % of loans | Comes before charge-offs |
| Tier 1 leverage ratio | `RBC1AAJ` | Core capital as % of assets | The cushion. Regulators act when it gets thin |
| Uninsured deposits | `DEPUNINS` / `DEP` | Deposits above the $250,000 FDIC limit, as % of deposits | Uninsured depositors run first. SVB: 86% |
| Unrealized securities losses | (`SCHA` - `SCHF`) + (`SCAA` - `SCAF`) | What the bank paid for its bonds minus what they are worth now | When rates rise, bond prices fall. If depositors leave and the bank must sell, the loss becomes real |
| CRE concentration | construction + multifamily + non-owner-occupied commercial real estate, over Tier 1 capital | Commercial real estate exposure vs capital | Regulators flag above 300% (100% for construction alone) |
| Brokered deposits | `BRO` / `DEP` | Deposits gathered through brokers, as % of deposits | Classic 2009 warning sign. It did not predict anything after 2012 |

**HTM and AFS.** Banks hold bonds in two buckets. Available-for-sale (AFS) bonds are marked to market on the balance sheet. Held-to-maturity (HTM) bonds are carried at cost, so their losses are hidden unless you compare cost (`SCHA`) to fair value (`SCHF`). SVB's large HTM losses are the reason this measure matters.

## 4. What I did, step by step

### Step 1: Get the data

The FDIC BankFind API returns the Call Report for every bank for one quarter in a single request (about 4,300 to 8,700 rows). The script loops over 78 quarter-end dates and saves each as a CSV. It then downloads the failures table and the FDIC's own dictionary of field names.

What to say: "I picked 51 fields up front, grouped by what they measure: size and funding, earnings, capital, loan quality, credit cards, commercial real estate, and securities."

### Step 2: Clean and prepare

1. **Combine** 78 files into one table: 487,729 rows. No duplicate bank-quarters were found.
2. **Drop US branches of foreign banks** (1,324 rows). State Bank of India's New York branch files a Call Report but has no capital of its own, so capital ratios do not exist. Keeping them would add blanks to every capital measure.
3. **Blank vs zero.** For dollar amounts, a blank usually means the bank has none of that item, so blank becomes 0. But savings banks before 2012 filed a different form that did not have some fields. For those 15,495 rows a blank means "unknown", not zero. If I had filled them with zero, the unrealized-loss calculation would have shown huge fake gains.
4. **Derived measures.** Twenty new columns: uninsured share, brokered share, unrealized loss / Tier 1, CRE / Tier 1, card charge-off rate, year-over-year asset, loan and deposit growth. Growth is only computed if the bank's previous record is exactly a year earlier, so a bank with a gap in its history does not get a wrong number.
5. **Outliers.** Tiny or brand-new banks produce extreme ratios. For the model only, every ratio is capped at the 1st and 99th percentile of the whole table. The raw value is kept for reporting.
6. **Join failures.** Each bank-quarter gets the bank's failure date, if any, and a label: did it fail within 365 days of this report? 551 of 552 failures since 2007 matched by CERT.

### Step 3: Answer the business questions

Each question became a small calculation. The ones to understand well:

- **Q1 Consolidation.** Count banks per quarter. Rank banks by assets each quarter, sum the top 10. A bank "exits" if its last report is before the latest quarter; if its CERT is in the failures table, it failed, otherwise it almost always merged.
- **Q2 Card stress.** Industry rate = sum of every bank's quarterly card charge-offs times 4 (to annualize), divided by the sum of card balances. This is dollar-weighted, so big issuers count more, which is what you want for an industry number.
  - **Lead-lag:** I correlated the *change* in delinquency over a year with the *change* in charge-offs k quarters later, for k = 0 to 4. Using changes, not levels, matters: both series drift together over 20 years, and that shared drift would make any lag look correlated. The peak is at 2 quarters (0.93), which fits how cards work: a card 30-89 days late today gets charged off at 180 days.
- **Q4 Wells Fargo asset cap.** Index each bank's assets to 2017 Q4 = 100 and plot. The cap is visible: Wells flat, peers up 27% to 70%.
- **Q5 Failure profile.** For each failed bank, take the report closest to one year before failure (270 to 365 days). Compare medians with every bank that did not fail within three years, in the same quarters. Medians, because averages get pulled around by tiny banks.

### Step 4: The early-warning screen

**The question:** using only what is in the public filings, can we pick out banks that will fail within a year?

**The data shape:** one row per bank per quarter. The target is 1 if the bank failed within 365 days, else 0. Failure is rare: 0.125% of bank-quarters in the test period.

**Why a time-based split, not a random one.** If I shuffled rows randomly, the same bank's 2010 Q1 and 2010 Q2 reports could land on both sides, and the model would effectively see the answer. Training on 2007-2011 and testing on 2012 onward means the model is judged on years it never saw, in a calmer era. That is the honest test and what a bank would actually face.

**Label cut-off.** Reports from the last year are not scored, because we do not know yet whether those banks will fail within a year.

**Three screens, simplest first:**

1. **Red-flag rule.** Count six warning signs: noncurrent loans above 3%, ROA below 0, Tier 1 leverage below 8%, brokered deposits above 10%, construction loans above 100% of capital, non-owner CRE above 300% of capital. Anyone could do this in Excel.
2. **Logistic regression** on 14 capped ratios. Inputs standardized so weights can be compared. `class_weight="balanced"` because failures are so rare; without it the model can score well by predicting "no failure" every time. Missing values filled with the median plus a flag column, so "missing" can carry its own signal.
3. **Gradient boosting.** A more flexible model; harder to explain.

**How to read the results:**

- **AUC** (0.94 to 0.97): if you pick one failing and one healthy bank-quarter at random, the chance the model scores the failing one higher. 0.5 is a coin flip, 1.0 is perfect. With rare events AUC looks flattering, so I also report the next two.
- **Caught at top 2%** (83% to 88%): if examiners review the riskiest 2% of banks each quarter, the share of all failures in that group.
- **Hit rate at top 2%** (about 5%): of the flagged bank-quarters, the share that actually failed within a year. About 1 in 18. Low in absolute terms, but about 43 times better than random.

**The point to make:** the simple rule caught 83%, the logistic model 87%, gradient boosting 88%. The extra complexity buys about 4 points. In a real team I would ship the rule first and use the model to rank within it.

**The robustness check.** Regulators close a bank largely because its capital runs out. So "low capital predicts failure" is partly circular. I re-ran the model without the two capital ratios. It still caught 84% (AUC 0.918), so the earlier signals (bad loans, losses, construction exposure) carry real warning.

**Bank-level view.** 105 of 117 banks that failed after 2012 were flagged at least once in their last year, a median of 293 days ahead. The cost: 11% of banks that never failed were also flagged at some point over 13 years. That is the trade-off any screen has.

### Step 5: The 2023 case study (the best part of the project)

I scored the 2022 Q4 filings, the last ones before the March 2023 runs, with the same model. Among 158 banks over $10bn, it ranked SVB at the 23rd percentile of risk: safer than 77% of big banks. SVB had 0.19% noncurrent loans and was profitable.

What was different about SVB: 86% of deposits uninsured (99th percentile) and unrealized bond losses of 104% of Tier 1 capital (the highest of any big bank). Signature had 90% uninsured; First Republic 68%.

**Say this part carefully.** I designed the funding check after I knew who failed. That proves a blind spot in credit-only screens. It does not prove anyone could have predicted it. Of the 10 big banks with the highest uninsured share, 3 failed and 7 did not; most of the 7 were custody banks or US arms of foreign banks, whose big depositors are institutions that do not run like tech start-ups.

### Step 6: Dashboard and report

The dashboard is one HTML file with the data embedded. The charts are drawn with plain SVG and JavaScript, no chart library, so it works offline and on GitHub Pages. Every chart cites the FDIC field codes it was built from. Every chart has a hover tooltip and a "show as table" option.

The page and the report read every number from the JSON results. When a new quarter comes in, the numbers update everywhere at once, and nothing can be out of date by hand.

## 5. Three problems I caught (good interview stories)

1. **The card delinquency field was divided by the wrong thing.** The FDIC field `P3CRCDR` is labelled as a card delinquency ratio, but it is divided by total assets, not card loans. I noticed because JPMorgan came out at 0.05%, which is not believable for a card book. I confirmed it with the dollar field: $1.92bn past due / $4,091bn total assets = 0.047%, exactly the ratio. After the fix, JPMorgan is 0.89%, and the lead-lag result changed from "no lead" to a clear two-quarter lead. **Lesson: check a field's denominator against a dollar amount before trusting it.**
2. **Blank is not always zero.** Savings banks before 2012 used a form that lacked some fields. Filling those with zero would have created fake unrealized gains.
3. **Foreign bank branches have no capital.** 17 rows a quarter with blank equity turned out to be US branches of foreign banks. They were removed, with a count.

## 6. The Claude automation: what it does and what it does not do

**Does:**
- `06_claude_memo.py` builds a short summary of the results (about 11,000 characters of totals, rates and medians), checks it is not row-level (size limit, blocked keys, no long lists), writes the exact prompt to `output/memo_prompt.md`, and only with `--send` asks Claude to draft a one-page memo.
- `make_synthetic.py` makes 2,000 fake rows with the same columns and realistic ranges. Each column is drawn on its own, so every relationship in the real data is broken. Safe to share; useless for findings.
- `prompts/schema_only_prompt.md` shows the pattern: give Claude the column list and fake rows, have it write the code, run the code locally on the real data.

**Does not:**
- Send any bank-quarter record, the named watchlist, or anything in `output/local_only/`.
- Decide anything. The memo is a draft; every number must be checked against the dashboard.
- Run by default. The memo call costs money and needs an API key, so it is off unless you ask.

Why it matters for a bank: real customer and account data cannot be pasted into an AI tool. This is a way to still get help with the code and the write-up while the data stays inside.

## 7. Decisions you may be asked to defend

| Decision | Why |
|---|---|
| Time split, not random split | Prevents leakage between quarters of the same bank; matches how the screen would be used |
| Logistic regression as the main model | Every weight is readable; a regulator or model-risk team can review it |
| Report the simple rule next to the model | The model only adds about 4 points; hiding that would oversell it |
| Kept brokered deposits in the rule even though it did not work after 2012 | So the result stays visible instead of quietly dropping a failed signal |
| Top 2% per quarter as the flag threshold | Roughly 100 banks a quarter, a realistic review workload |
| Named watchlist kept off the public page | A screen is not evidence. Publicly naming small banks as flagged could cause real harm |
| Medians, not means, in the failure profile | Thousands of tiny banks would drag averages around |
| Bank charter level, not holding company | That is how Call Reports are filed; stated as a limit |

## 8. Questions you will likely get, with answers

**"Why did you pick this data?"** I wanted real bank data, not a Kaggle sample. Call Reports are what supervisors and bank analysts actually use, and they cover every bank, so I could compare the banks I am applying to.

**"What is AUC and why is it not enough here?"** The chance the model ranks a random failing bank above a random healthy one. With failures at 0.1%, AUC can look great while the flagged list is mostly false alarms, so I also report how many failures land in the top 2% and how many flagged banks actually failed.

**"Isn't low capital just a symptom of failing?"** Partly, which is why I re-ran without capital ratios. It still caught 84%.

**"How would you improve it?"** Add funding signals (uninsured share, unrealized losses, deposit outflows) as a separate liquidity screen; test it on a period after it was designed; add market data such as stock price for listed banks.

**"Your model missed SVB. Isn't that a failure?"** It is the most useful result. It shows exactly what a credit-only screen cannot see, and why liquidity and interest-rate risk need their own monitoring.

**"Why is Synchrony's charge-off rate so much higher than Amex's?"** Different customers and products. Synchrony is store cards for a broader credit range; Amex lends mostly to high-spend, high-credit customers. Comparing issuers' rates directly without that context is misleading.

**"What did you do about missing data?"** Separated "has none" (filled with 0) from "not reported" (left blank and flagged), and counted each.

**"How long would this take to refresh?"** About five minutes to pull a new quarter. GitHub runs it automatically every quarter.

**"Did you write all of this yourself?"** See section 9.

## 9. How to describe the AI-assisted part honestly

The code was written with Claude in one working session. Do not imply you hand-wrote it over weeks. A fair way to say it:

"I used Claude as a coding assistant. I chose the data source, the questions and how to frame the results, and I checked the outputs. Two of the most important catches came from checking numbers that looked wrong. I can walk you through every step of the method."

Only say the last sentence once it is true (see section 10).

## 10. Homework before you show this to anyone

- [ ] Read section 3 until you can explain each measure without looking.
- [ ] Open `docs/index.html` and click every tab. For each chart, say out loud what it shows and the one-line answer.
- [ ] Re-do the delinquency check yourself: in Excel, take JPMorgan's 2026 Q2 row and divide past-due card dollars by total assets.
- [ ] Explain the time split and why a random split would cheat.
- [ ] Explain the SVB result, including the hindsight limit, in under a minute.
- [ ] Practise the 30-second version in section 1 until it sounds like you.

## 11. How to run it

```bash
pip install -r requirements.txt
python run_all.py              # full run, pulls data first (about 5 minutes)
python run_all.py --no-fetch   # rebuild from data already downloaded
python src/06_claude_memo.py --send   # optional: Claude drafts the memo (needs an API key)
```
