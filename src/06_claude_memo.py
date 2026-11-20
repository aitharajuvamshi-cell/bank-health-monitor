"""
Step 6 (optional): Have Claude draft the quarterly bank-health memo, without
sending it any row-level data.

How the privacy boundary works
  1. The pipeline (steps 1-5) runs entirely on this machine.
  2. This script builds a SMALL payload of aggregate results only: industry
     totals, rates, model scores, peer medians. No bank-quarter rows, no
     watchlist names, nothing from output/local_only/.
  3. check_payload() refuses to send anything that looks row-level
     (too large, or containing a blocked key).
  4. The prompt is always written to output/memo_prompt.md so you can read
     exactly what would be sent. Only with --send does it go to the API.

In a bank, the same pattern lets an analyst use Claude on confidential data:
Claude sees the shape of the data and the summary statistics, never the
customer or account records.

Usage
  python src/06_claude_memo.py            # write the prompt only (free, no API call)
  python src/06_claude_memo.py --send     # also call Claude (needs `pip install anthropic`
                                          # and an ANTHROPIC_API_KEY; costs a few cents)
"""
import argparse
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "output"

MAX_PAYLOAD_CHARS = 20_000          # a few pages of numbers; row-level data would be far larger
BLOCKED_KEYS = {"scatter", "series", "wa_series", "by_year", "local_only", "watchlist", "CERT"}


def build_payload():
    A = json.loads((OUT / "findings_analysis.json").read_text())
    M = json.loads((OUT / "findings_model.json").read_text())

    def strip(d):
        """Drop chart series (long arrays) and keep headline numbers only."""
        if isinstance(d, dict):
            return {k: strip(v) for k, v in d.items() if k not in BLOCKED_KEYS}
        if isinstance(d, list):
            return [strip(x) for x in d]
        return d

    return {
        "latest_quarter": A["latest_quarter"],
        "industry": strip(A["q1"]),
        "credit_cards": strip(A["q2"]),
        "big_bank_scorecard": strip(A["q3"]),
        "wells_fargo_asset_cap": strip(A["q4"]),
        "failure_profile": strip(A["q5"]),
        "failure_costs": strip(A["q9"]),
        "arizona": strip(A["q10"]),
        "early_warning_backtest": {"split": M["split"], "results": M["model_results"],
                                   "bank_level": M["bank_level"], "no_capital_variant": M["no_capital_variant"]},
        "runs_2023": strip({k: v for k, v in M["q7"].items()}),
        "screen_today_aggregate": strip({k: v for k, v in M["q8"].items()}),
    }


def check_payload(payload):
    text = json.dumps(payload)
    if len(text) > MAX_PAYLOAD_CHARS:
        raise SystemExit(f"Refusing to send: payload is {len(text):,} chars, limit {MAX_PAYLOAD_CHARS:,}. "
                         "That is too large to be aggregate-only.")

    def walk(d, path=""):
        if isinstance(d, dict):
            for k, v in d.items():
                if k in BLOCKED_KEYS:
                    raise SystemExit(f"Refusing to send: blocked key '{path}/{k}'")
                walk(v, f"{path}/{k}")
        elif isinstance(d, list):
            if len(d) > 60:
                raise SystemExit(f"Refusing to send: list of {len(d)} items at '{path}' looks row-level")
            for x in d:
                walk(x, path)
    walk(payload)
    return text


SYSTEM = """You are a bank supervision analyst writing a short internal memo.
Use only the numbers in the JSON you are given. Do not add facts from memory.
If a number is not in the JSON, say it is not available.
Do not say or imply that any named bank is likely to fail.
Plain English, short sentences, no em dashes, no buzzwords such as leverage, robust or actionable."""

TASK = """Draft a one-page quarterly bank-health memo for {quarter} from the JSON below.

Structure:
1. Three-sentence summary.
2. Credit cards: where charge-offs and delinquency stand versus 2019, and what the
   delinquency lead time suggests for the next two quarters.
3. Early-warning screen: how many banks it flags and what it caught in the backtest,
   with its limits.
4. Three questions a reviewer should ask next quarter.

JSON:
{payload}"""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--send", action="store_true", help="call the Claude API (costs money)")
    args = ap.parse_args()

    payload = build_payload()
    text = check_payload(payload)
    prompt = TASK.format(quarter=payload["latest_quarter"], payload=text)
    (OUT / "memo_prompt.md").write_text(f"# System\n\n{SYSTEM}\n\n# User\n\n{prompt}\n", encoding="utf-8")
    print(f"Prompt written to output/memo_prompt.md ({len(text):,} chars of aggregate data).")

    if not args.send:
        print("Not sent. Re-run with --send to have Claude draft the memo.")
        return

    import anthropic  # imported here so the pipeline runs without the SDK installed

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from the environment
    try:
        response = client.beta.messages.create(
            model="claude-opus-5-5",
            max_tokens=16000,
            output_config={"effort": "medium"},
            betas=["server-side-fallback-2026-07-01"],
            fallbacks="default",
            system=SYSTEM,
            messages=[{"role": "user", "content": prompt}],
        )
    except anthropic.AuthenticationError:
        raise SystemExit("No valid API key. Set ANTHROPIC_API_KEY and try again.")
    except anthropic.RateLimitError:
        raise SystemExit("Rate limited. Try again in a minute.")
    except anthropic.APIConnectionError:
        raise SystemExit("Could not reach the API. Check the internet connection.")

    if response.stop_reason == "refusal":
        raise SystemExit("Claude declined this request; no memo written.")
    memo = "".join(b.text for b in response.content if b.type == "text")
    (OUT / "quarterly_memo.md").write_text(memo, encoding="utf-8")
    print("Memo written to output/quarterly_memo.md. Check every number against the dashboard before using it.")


if __name__ == "__main__":
    main()
