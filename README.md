# US Bank Health Monitor

An end-to-end analysis of **every FDIC-insured bank in the United States, every quarter from 2007 to 2026**, built from public regulatory filings.
It pulls the data from the FDIC's API, cleans it, answers ten business questions, backtests a bank-failure early-warning screen, and publishes an interactive dashboard that rebuilds itself each quarter.

**[Open the live dashboard](https://aitharajuvamshi-cell.github.io/bank-health-monitor/)** · **[Read the findings report](docs/REPORT.md)** · **[How it was built, step by step](docs/WALKTHROUGH.md)** ([Word version](docs/Bank_Health_Monitor_Walkthrough.docx))

## What the data says

| # | Question | Answer (data through 2026 Q2) |
|---|---|---|
| Q1 | How much has US banking consolidated? | 8,733 banks became 4,296 (-50.8%). Only 551 of 4,836 exits were failures; the rest were mostly mergers. The top 10 banks hold 54.1% of assets, up from 45.5%. |
| Q2 | Where is credit card stress? Does delinquency warn early? | Card charge-offs are 3.95%, back to the 2019 level (3.83%). Changes in 30-89 day delinquency lead changes in charge-offs by about 2 quarters (correlation 0.93). |
| Q3 | How do the big consumer and card banks compare? | Scorecard of 10 measures for JPMorgan Chase, Bank of America, Wells Fargo, Citi, Capital One, U.S. Bank, American Express, Synchrony and Western Alliance against the $100bn+ median. |
| Q4 | Did the Wells Fargo asset cap show up in the data? | Yes. Wells Fargo's bank assets moved -2.1% from 2017 Q4 to 2025 Q1 while JPMorgan Chase grew +70.2%. |
| Q5 | What did failed banks look like a year before failing? | Median noncurrent loans 9.4% vs 0.9%; 85% were losing money vs 11%; 78% had construction loans above 100% of capital vs 13%. |
| Q6 | Can public data warn a year ahead? | Trained on 2007-2011, tested on 2012-2025: 105 of 117 failed banks were flagged in their last year, a median 293 days ahead. A six-check rule gets most of the way. |
| Q7 | Why did the 2023 failures slip through? | The credit screen ranked Silicon Valley Bank safer than 77% of big banks. Its risk was 86% uninsured deposits and bond losses worth 104% of its Tier 1 capital. |
| Q8 | What does the screen say today? | 86 banks flagged, 0.44% of system assets, median size $374m. Names are deliberately kept off the public page. |
| Q9 | What have failures cost the deposit insurance fund? | About $107bn since 2007, $34.3bn of it from 2023. |
| Q10 | Local view: Arizona | Phoenix-based Western Alliance lost 11.3% of deposits in the March 2023 quarter, then cut its uninsured share from 55% to 29%. |

The numbers in this table are a snapshot. The dashboard and report are regenerated from the pipeline, so they always show the latest run.

## Data

- **Source:** [FDIC BankFind Suite API](https://api.fdic.gov/banks/docs/), public, no API key.
- **Financials:** 51 Call Report fields for every insured bank, 78 quarters, 487,729 bank-quarter rows.
- **Failures:** every FDIC bank failure since 1934 (4,117 records; 552 since 2007).
- Dollar amounts from the FDIC are in thousands; the pipeline converts them.

## How it works

```
01_fetch_fdic.py       pull 78 quarters of Call Reports + the failures table (skips quarters already on disk)
02_clean.py            one bank-quarter panel; every cleaning rule logged with a row count
03_analysis.py         Q1-Q5, Q9, Q10
04_early_warning.py    Q6-Q8: three screens, time-based backtest, 2023 case study
05_build_dashboard.py  docs/index.html, built from the JSON results (no number typed by hand)
07_write_report.py     docs/REPORT.md, same JSON
make_synthetic.py      a fake twin of the data with the same columns, for safe sharing and testing
06_claude_memo.py      Claude drafts a quarterly memo from aggregate numbers only
```

Run it:

```bash
pip install -r requirements.txt
python run_all.py              # pulls data (about 5 minutes), then builds everything
python run_all.py --no-fetch   # rebuild from data already downloaded
```

## Automation

| What | How |
|---|---|
| Quarterly refresh | `.github/workflows/quarterly-refresh.yml` runs on the 1st of March, June, September and December, pulls any new FDIC quarter and commits the rebuilt dashboard and report. |
| Numbers never drift | The dashboard and report read from `output/*.json`, so a new quarter updates every figure at once. |
| Memo drafting with Claude, without sharing data | `06_claude_memo.py` sends only summary numbers (about 11,000 characters), checks the payload before sending, and always writes the exact prompt to `output/memo_prompt.md` first. Row-level data never leaves the machine. |
| Working with Claude on confidential data | `make_synthetic.py` builds a fake dataset with the same columns and ranges but no real records. `prompts/schema_only_prompt.md` shows how to get code written from the schema alone, then run it locally on the real data. |

## Data quality decisions

- US branches of foreign banks dropped (1,324 rows): they hold no capital of their own, so capital ratios do not exist for them.
- Savings institutions before 2012 filed a different form; 15,495 rows with missing fields are flagged as unknown, not filled with zero.
- The FDIC's card delinquency "ratio" (`P3CRCDR`) is divided by total assets, not card loans. Caught when JPMorgan's rate came out at 0.05%, and corrected.
- Extreme ratios from tiny banks are capped at the 1st/99th percentile for modelling only.

## Limits

- Call Reports are per bank charter, not per holding company, so figures will not match earnings releases exactly.
- Public filings miss what examiners see: management, CAMELS ratings, enforcement actions, intra-quarter deposit flight.
- Only 117 failures in the test period, so hit rates carry real uncertainty.
- The 2023 funding check was designed after the outcome was known.
- A screen is a reason to look closer, not a prediction that any bank will fail. Not investment advice.

## Tools

Python (pandas, NumPy, scikit-learn), plain HTML/SVG/JavaScript for the dashboard (no chart library), GitHub Actions, the Claude API.
Built with AI assistance (Claude); data choices, questions and framing are mine.
