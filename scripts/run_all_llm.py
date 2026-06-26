#!/usr/bin/env python3
"""Run testcases through the LLM agent end-to-end (main.py + OpenAI per config.yaml).

For each testcase it pipes the whole prompt.txt into

    python3 main.py -config config.yaml

(main.py reads requests line by line and drives the LLM Planner), captures the
#RESPONSE/#END transcript, and reports per-case status + timing + a summary.

Each case is one fully LLM-driven run; large cases (e.g. test39/40) take minutes
and the whole sweep costs real API tokens, so a per-case timeout is enforced.

Usage:
    python3 scripts/run_all_llm.py                  # all 40
    python3 scripts/run_all_llm.py --from 21 --to 30
    python3 scripts/run_all_llm.py --case 35
    python3 scripts/run_all_llm.py --timeout 900    # 15 min/case

Outputs (per case, under testcase/testNN/):
    testNN_llm_run.log   full stdout transcript (#RESPONSE/#END)
    testNN.log           the agent's own log (written by main.py)
    testNN_out.v         the written design (if the run reached the write step)
"""
from __future__ import annotations

import argparse
import subprocess
import sys
import time
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def prompt_turns(prompt_path: Path) -> int:
    """Number of non-empty prompt lines = expected #END tags."""
    return sum(1 for ln in prompt_path.read_text().splitlines() if ln.strip())


def run_case(n: int, config: str, timeout: int) -> dict:
    name = f"test{n:02d}"
    pdir = ROOT / "testcase" / name
    prompt = pdir / "prompt.txt"
    if not prompt.is_file():
        return {"name": name, "status": "MISSING", "secs": 0.0, "ends": 0, "turns": 0}

    turns = prompt_turns(prompt)
    out_log = pdir / f"{name}_llm_run.log"
    t0 = time.time()
    try:
        with open(prompt, "r") as fin:
            r = subprocess.run(
                [sys.executable, "main.py", "-config", config],
                stdin=fin, capture_output=True, text=True,
                cwd=str(ROOT), timeout=timeout,
            )
        secs = time.time() - t0
        out_log.write_text(r.stdout)
        ends = r.stdout.count("#END")
        wrote_v = (pdir / f"{name}_out.v").is_file()
        # Detect LLM/API failures that still produce #END (e.g. a 401 bad key makes
        # every turn return an error message), so we don't falsely report success.
        blob = r.stdout + "\n" + r.stderr
        api_fail = any(s in blob for s in (
            "LLM API error", "Error communicating with the LLM",
            "Incorrect API key", "401", "AuthenticationError", "RateLimitError"))
        if api_fail:
            status = "APIERR"       # key invalid / rate-limited / LLM unreachable
        elif r.returncode != 0:
            status = "ERR"
        elif ends >= turns and wrote_v:
            status = "OK"
        elif ends >= turns:
            status = "OK*"          # all turns answered, no output .v detected
        else:
            status = "PARTIAL"      # ran out of turns / stopped early
        msg = r.stderr.strip()
        if api_fail and "API error" in blob:
            line = next((l for l in blob.splitlines() if "API error" in l), "")
            msg = line.strip()[:160] or msg
        return {"name": name, "status": status, "secs": secs, "ends": ends,
                "turns": turns, "stderr": msg[:200]}
    except subprocess.TimeoutExpired:
        return {"name": name, "status": "TIMEOUT", "secs": time.time() - t0,
                "ends": 0, "turns": turns, "stderr": ""}
    except Exception as exc:  # noqa: BLE001
        return {"name": name, "status": "CRASH", "secs": time.time() - t0,
                "ends": 0, "turns": turns, "stderr": str(exc)[:200]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=40)
    ap.add_argument("--case", type=int, help="run a single testcase number")
    ap.add_argument("--config", default="config.yaml")
    ap.add_argument("--timeout", type=int, default=600, help="per-case timeout (s)")
    a = ap.parse_args()

    nums = [a.case] if a.case else list(range(a.lo, a.hi + 1))
    print(f"Running {len(nums)} testcase(s) via the LLM agent "
          f"(config={a.config}, timeout={a.timeout}s/case)\n")

    results = []
    for n in nums:
        res = run_case(n, a.config, a.timeout)
        note = "" if res["status"] in ("OK", "MISSING") else \
               f"  ({res['ends']}/{res['turns']} turns" + \
               (f"; {res['stderr']}" if res.get("stderr") else "") + ")"
        print(f"  {res['name']}: {res['status']:8s} {res['secs']:7.1f}s{note}", flush=True)
        results.append(res)

    print("\n=== summary ===")
    counts = Counter(r["status"] for r in results)
    total = sum(r["secs"] for r in results)
    print(" ".join(f"{k}={v}" for k, v in sorted(counts.items())),
          f"| total {total:.0f}s ({total/60:.1f} min)")
    ok = all(r["status"] in ("OK", "OK*") for r in results)
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
