#!/usr/bin/env python3
"""Verify official testcases — step-by-step, scoped runs (no LLM API key).

Each line in prompt.txt is one **step**.  Steps are scored independently:
  PASS        tool ran without error
  FAIL        tool error (case marked FAIL)
  UNSUPPORTED no dispatch rule yet (case marked PARTIAL if no FAIL)
  SKIP        testcase init line

Default scope is tier ``smoke`` (test01–02 only), NOT all 40 cases.

Examples:
    python3 scripts/verify_testcases.py
    python3 scripts/verify_testcases.py --tier basic
    python3 scripts/verify_testcases.py --case test03
    python3 scripts/verify_testcases.py --case test08 --steps 2 3 4
    python3 scripts/verify_testcases.py --from test01 --to test05 -v
    python3 scripts/verify_testcases.py --list-tiers
    python3 scripts/verify_testcases.py --show-prompts test03

Logs: verification_runs/<timestamp>_<label>/
  ISSUES.md     ← start here: only FAIL / UNSUPPORTED steps
  SUMMARY.md    overview table + totals
  steps.csv     all steps (for diff / spreadsheet)
  testNN/report.md   full debug per prompt line
  testNN/abc/        ABC cec output (transform cases only)
"""

from __future__ import annotations

import argparse
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional, Set

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from verify_lib import (  # noqa: E402
    DEFAULT_TIER,
    ROOT as _ROOT,
    CaseResult,
    RunLogger,
    VERIFY_TIERS,
    aggregate_step_stats,
    available_engine_tools,
    find_abc_binary,
    find_parser_binary,
    load_prompt_lines,
    resolve_case_list,
    run_case,
)


def build_parser() -> None:
    subprocess.run(
        [sys.executable, str(_ROOT / "scripts" / "build_parser.py")],
        check=True,
        cwd=_ROOT,
    )


def show_prompts(case_id: str) -> None:
    print(f"=== {case_id}/prompt.txt ===")
    for line_no, text in load_prompt_lines(case_id):
        kind = "init" if "beginning of a new testcase" in text.lower() else "prompt"
        print(f"  L{line_no:2d} [{kind}] {text}")


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Step-level testcase verification for ICCAD_A.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Tiers:\n"
            + "\n".join(f"  {name:12s} {', '.join(ids)}" for name, ids in VERIFY_TIERS.items())
        ),
    )
    scope = parser.add_argument_group("scope (pick one style; default: tier smoke)")
    scope.add_argument(
        "--tier",
        default=None,
        help=f"Preset case list (default: {DEFAULT_TIER}). Use --tier all for test01–40.",
    )
    scope.add_argument(
        "--cases",
        nargs="+",
        metavar="CASE",
        help="Explicit list, e.g. test01 test03 test21",
    )
    scope.add_argument("--case", metavar="CASE", help="Single testcase shorthand")
    scope.add_argument("--from", dest="case_from", metavar="CASE", help="Range start, e.g. test01")
    scope.add_argument("--to", dest="case_to", metavar="CASE", help="Range end, e.g. test08")
    scope.add_argument(
        "--steps",
        nargs="+",
        type=int,
        metavar="N",
        help="Only run these prompt.txt line numbers (with --case)",
    )
    parser.add_argument("--label", default="run", help="Tag for verification_runs/ folder name")
    parser.add_argument("--no-build", action="store_true", help="Skip parser build")
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print each step as it runs",
    )
    parser.add_argument(
        "--stop-on-fail",
        action="store_true",
        help="Stop remaining steps in a case after the first FAIL",
    )
    parser.add_argument(
        "--strict",
        action="store_true",
        help="Exit 1 if any step FAIL (default: exit 1 only on script errors)",
    )
    parser.add_argument("--list-tiers", action="store_true", help="Print tier presets and exit")
    parser.add_argument(
        "--show-prompts",
        metavar="CASE",
        help="Print numbered prompt lines for one case and exit",
    )
    args = parser.parse_args()

    if args.list_tiers:
        for name, ids in VERIFY_TIERS.items():
            print(f"{name:12s} ({len(ids)} cases): {', '.join(ids)}")
        return 0

    if args.show_prompts:
        show_prompts(args.show_prompts)
        return 0

    if args.steps and not args.case:
        parser.error("--steps requires --case")

    if not args.no_build:
        print("Building parser…")
        build_parser()

    from eda_engine.engine import EDAEngine  # noqa: E402

    # Resolve scope
    tier_label = args.tier or (
        DEFAULT_TIER
        if not args.cases and not args.case and not args.case_from and not args.case_to
        else "custom"
    )
    case_list: List[str]
    if args.case:
        case_list = resolve_case_list(cases=[args.case])
    elif args.cases:
        case_list = resolve_case_list(cases=args.cases)
    elif args.case_from or args.case_to:
        case_list = resolve_case_list(
            case_from=args.case_from,
            case_to=args.case_to,
        )
    else:
        case_list = resolve_case_list(tier=args.tier or DEFAULT_TIER)

    step_filter: Optional[Set[int]] = set(args.steps) if args.steps else None

    engine = EDAEngine()
    engine_tools = available_engine_tools(engine)
    parser_bin = find_parser_binary()
    abc_bin = find_abc_binary()

    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    run_dir = _ROOT / "verification_runs" / f"{ts}_{args.label}"
    logger = RunLogger(run_dir, tier=tier_label, case_list=case_list)

    print(f"Run directory : {run_dir}")
    print(f"Tier / scope  : {tier_label} → {', '.join(case_list)}")
    print(f"Engine tools  : {', '.join(engine_tools) or '(none)'}")
    print(f"Parser        : {parser_bin or 'MISSING'}")
    print(f"ABC           : {abc_bin or 'MISSING'}")
    if step_filter:
        print(f"Step filter   : lines {sorted(step_filter)}")
    print()

    results: List[CaseResult] = []
    for case_id in case_list:
        if not args.verbose:
            print(f"  {case_id} …", end=" ", flush=True)
        res = run_case(
            case_id,
            engine,
            parser_bin,
            abc_bin,
            logger,
            step_filter=step_filter,
            stop_on_fail=args.stop_on_fail,
            verbose=args.verbose,
        )
        results.append(res)
        if not args.verbose:
            c = res.step_counts
            print(f"{res.status}  (steps {c.get('PASS',0)}P/{c.get('FAIL',0)}F/{c.get('UNSUPPORTED',0)}U)")

    logger.finalize(results, engine_tools)

    passed = sum(1 for r in results if r.status == "PASS")
    partial = sum(1 for r in results if r.status == "PARTIAL")
    failed = sum(1 for r in results if r.status == "FAIL")
    step_totals = aggregate_step_stats(results)

    print()
    print(
        f"CASES   PASS={passed}  PARTIAL={partial}  FAIL={failed}  TOTAL={len(results)}"
    )
    print(
        f"STEPS   PASS={step_totals.get('PASS',0)}  FAIL={step_totals.get('FAIL',0)}  "
        f"UNSUPPORTED={step_totals.get('UNSUPPORTED',0)}  SKIP={step_totals.get('SKIP',0)}"
    )
    print(f"Details {run_dir / 'SUMMARY.md'}")
    print(f"Issues  {run_dir / 'ISSUES.md'}  ← read first if anything broke")
    print(f"CSV     {run_dir / 'steps.csv'}")

    if args.strict and step_totals.get("FAIL", 0) > 0:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
