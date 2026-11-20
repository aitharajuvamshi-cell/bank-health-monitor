# Prompt pattern: getting Claude's help without sharing the data

Use this when the data is confidential. Claude sees the columns and a few
synthetic rows, writes the code, and the code runs on your machine against
the real data.

---

I have a table of bank-quarter records. Here is the schema
(column, type, meaning, typical range):

<paste data/synthetic/schema.json, or the relevant rows of it>

Here are 5 SYNTHETIC rows with the same columns (not real data):

<paste 5 rows of data/synthetic/panel_synthetic.csv>

Write a pandas function `card_stress_by_quarter(df)` that returns, for each
quarter, the dollar-weighted credit card net charge-off rate (annualized) and
the share of card issuers whose rate rose versus a year earlier.
Use only the columns listed. Do not assume any column I did not list.
Return a DataFrame and include a short test that runs on the synthetic rows.

---

What goes to Claude: column names, meanings, 5 fake rows.
What stays local: every real record, the results.
Check: run the function on the synthetic file first, then on the real panel,
then compare one quarter by hand.
