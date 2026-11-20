"""
Run the whole pipeline in order.

  python run_all.py              # pull any new FDIC quarters, then rebuild everything
  python run_all.py --no-fetch   # rebuild from data already on disk
  python run_all.py --memo       # also ask Claude for the quarterly memo (needs an API key)

Each step reads the previous step's files, so a step can also be run alone.
"""
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
args = set(sys.argv[1:])

steps = []
if "--no-fetch" not in args:
    steps.append(["src/01_fetch_fdic.py"])
steps += [["src/02_clean.py"], ["src/03_analysis.py"], ["src/04_early_warning.py"],
          ["src/05_build_dashboard.py"], ["src/07_write_report.py"], ["src/make_synthetic.py"],
          ["src/06_claude_memo.py"] + (["--send"] if "--memo" in args else [])]

for step in steps:
    print(f"\n=== {' '.join(step)} ===", flush=True)
    r = subprocess.run([sys.executable, *step], cwd=ROOT, stdout=subprocess.DEVNULL if "02_clean" in step[0] else None)
    if r.returncode != 0:
        sys.exit(f"Stopped: {step[0]} failed with exit code {r.returncode}")
print("\nDone. Open docs/index.html to see the dashboard.")
