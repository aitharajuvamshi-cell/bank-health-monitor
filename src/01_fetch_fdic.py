"""
Step 1: Pull real bank data from the FDIC BankFind Suite API.

Source: https://api.fdic.gov/banks  (public, no API key, run by the FDIC)
What we pull:
  1. financials  - one row per bank per quarter, taken from the Call Report
                   every FDIC-insured bank files with regulators. 2007 Q1 onward.
  2. failures    - every FDIC-insured bank failure since 1934.

Dollar amounts from the FDIC are in THOUSANDS of dollars.

Re-running is safe: quarters already on disk are skipped unless --refresh.
"""
import argparse
import csv
import io
import json
import re
import sys
import time
import urllib.request
from datetime import date
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
RAW = ROOT / "data" / "raw"
QDIR = RAW / "quarters"
API = "https://api.fdic.gov/banks"

# Every field we use, and why. Full definitions: data/raw/field_titles.json
FIELDS = [
    # identity
    "CERT", "NAME", "STALP", "CITY", "BKCLASS", "SPECGRP", "CB", "NAMEHCR", "REPDTE",
    # size and funding
    "ASSET", "DEP", "COREDEP", "BRO", "DEPUNINS", "DEPINS", "OFFDOM",
    # earnings
    "NETINC", "ROA", "ROAQ", "ROE", "NIMY", "EEFFR",
    # capital
    "EQ", "EQV", "RBC1AAJ", "RBC1RWAJ", "RBCT1J",
    # loans and credit quality
    "LNLSGR", "LNLSNET", "NCLNLS", "NCLNLSR", "NTLNLSR", "NTLNLSQR", "LNATRESR",
    "NPERFV", "LNLSDEPR",
    # credit cards
    "LNCRCD", "NTCRCDQ", "NTCRCDR", "P3CRCDR", "P9CRCDR",
    # commercial real estate concentration
    "LNRECONS", "LNRENRES", "LNRENROW", "LNREMULT",
    # securities: amortized cost vs fair value (unrealized losses)
    "SCHA", "SCHF", "SCAA", "SCAF",
]

FAIL_FIELDS = ["CERT", "NAME", "CITY", "PSTALP", "FAILDATE", "FAILYR", "QBFASSET",
               "QBFDEP", "COST", "RESTYPE", "RESTYPE1", "CHCLASS1", "BIDNAME"]


def get(url, tries=6):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "bank-health-monitor/1.0 (portfolio project)"})
            with urllib.request.urlopen(req, timeout=120) as r:
                return r.read().decode("utf-8")
        except Exception as e:  # network hiccup: back off and retry
            wait = 15 * (i + 1)  # the FDIC API returns 429 when busy; give it time
            print(f"   retry {i+1} after error: {e} (waiting {wait}s)")
            time.sleep(wait)
    raise RuntimeError(f"failed: {url}")


def quarter_ends(start_year=2007):
    today = date.today()
    for y in range(start_year, today.year + 1):
        for md in ("0331", "0630", "0930", "1231"):
            d = f"{y}{md}"
            if date(y, int(md[:2]), int(md[2:])) < today:
                yield d


def fetch_quarter(repdte):
    url = (f"{API}/financials?filters=REPDTE:{repdte}&fields={','.join(FIELDS)}"
           f"&limit=10000&format=csv")
    text = get(url)
    rows = list(csv.reader(io.StringIO(text)))
    return text, len(rows) - 1


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--refresh", action="store_true", help="re-download quarters already on disk")
    ap.add_argument("--start", type=int, default=2007)
    args = ap.parse_args()
    QDIR.mkdir(parents=True, exist_ok=True)

    log = {"pulled_at": date.today().isoformat(), "quarters": {}}
    for q in quarter_ends(args.start):
        out = QDIR / f"fin_{q}.csv"
        if out.exists() and not args.refresh:
            log["quarters"][q] = "cached"
            continue
        try:
            text, n = fetch_quarter(q)
        except RuntimeError as e:
            print(f"{q}: API busy, stopping here and using the quarters on disk ({e})")
            break
        if n <= 0:
            print(f"{q}: not published yet, stopping")
            break
        if n >= 10000:
            sys.exit(f"{q}: hit the 10,000 row page limit, add paging")
        out.write_text(text, encoding="utf-8")
        log["quarters"][q] = n
        print(f"{q}: {n:,} banks")
        time.sleep(0.5)  # be polite to a public API

    # failures: whole table, ~4,100 rows. If the API is busy, keep the copy on disk.
    try:
        fetch_failures()
    except RuntimeError as e:
        if not (RAW / "failures.csv").exists():
            raise
        print(f"failures: API busy, kept existing file ({e})")
    try:
        fetch_dictionary()
    except RuntimeError as e:
        if not (RAW / "field_titles.json").exists():
            raise
        print(f"field dictionary: API busy, kept existing file ({e})")

    (RAW / "fetch_log.json").write_text(json.dumps(log, indent=1))


def fetch_failures():
    parts, offset = [], 0
    while True:
        url = (f"{API}/failures?fields={','.join(FAIL_FIELDS)}&limit=10000&offset={offset}"
               f"&sort_by=FAILDATE&sort_order=DESC&format=csv")
        text = get(url)
        lines = text.strip().splitlines()
        if offset == 0:
            parts.append(text.strip())
        else:
            parts.append("\n".join(lines[1:]))
        if len(lines) - 1 < 10000:
            break
        offset += 10000
    (RAW / "failures.csv").write_text("\n".join(parts) + "\n", encoding="utf-8")
    print(f"failures: {len(chr(10).join(parts).splitlines()) - 1:,} rows")



def fetch_dictionary():
    """FDIC's own title for every financial field."""
    yaml_text = get(f"{API}/docs/risview_properties.yaml")
    (RAW / "risview_properties.yaml").write_text(yaml_text, encoding="utf-8")
    titles, cur = {}, None
    for line in yaml_text.splitlines():
        m = re.match(r"^ {6}([A-Za-z0-9_]+):\s*$", line)
        if m:
            cur = m.group(1)
            continue
        m = re.match(r"^ {8}title: (.*)", line)
        if m and cur:
            titles[cur] = m.group(1)
    (RAW / "field_titles.json").write_text(json.dumps(titles, indent=0))
    print(f"field dictionary: {len(titles):,} fields")


if __name__ == "__main__":
    main()
