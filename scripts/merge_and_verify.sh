#!/usr/bin/env bash
# Merge one branch into main, then run scoped testcase verification before/after.
#
# 「自動驗證」的意思：
#   腳本在 merge 前後各呼叫 verify_testcases.py，不需要你手動逐個跑 testcase。
#   驗證是 **step 級別**（prompt.txt 每一行），不是只有整包 PASS/FAIL。
#   預設只跑 tier=smoke（test01–02），可用環境變數放大範圍。
#
# Usage:
#   ./scripts/merge_and_verify.sh origin/feat/project-restructure
#   VERIFY_TIER=basic ./scripts/merge_and_verify.sh origin/feat/buffer-insertion
#
# 比較 merge 前後：
#   1. 先看 verification_runs/*_after-*/ISSUES.md（只有問題步驟）
#   2. 再比 before vs after 的 SUMMARY.md step FAIL 數
#   3. 深入某 case：testNN/report.md；ABC：testNN/abc/equivalence.log

set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

BRANCH="${1:?Usage: merge_and_verify.sh <branch> [merge-message]}"
MSG="${2:-Merge ${BRANCH##*/}}"
TIER="${VERIFY_TIER:-smoke}"
VERIFY_FLAGS=(--tier "$TIER" -v)

if ! git diff --quiet || ! git diff --cached --quiet; then
  echo "ERROR: working tree not clean. Commit or stash first." >&2
  exit 1
fi

echo "Verification tier: $TIER  (override with VERIFY_TIER=basic|analysis|transform|all)"
echo

echo "══════════════════════════════════════════════════════════"
echo " Step 0 — baseline verify on main (before merge)"
echo "══════════════════════════════════════════════════════════"
git checkout main
git pull origin main
python3 scripts/verify_testcases.py "${VERIFY_FLAGS[@]}" --label "before-${BRANCH##*/}" || true

echo
echo "══════════════════════════════════════════════════════════"
echo " Step 1 — merge ${BRANCH}"
echo "══════════════════════════════════════════════════════════"
git merge "$BRANCH" -m "$MSG"

echo
echo "══════════════════════════════════════════════════════════"
echo " Step 2 — verify after merge"
echo "══════════════════════════════════════════════════════════"
python3 scripts/verify_testcases.py "${VERIFY_FLAGS[@]}" --label "after-${BRANCH##*/}" || true

echo
echo "Done."
echo "  1. Open verification_runs/ — find latest before-* and after-* folders"
echo "  2. Read after-*/ISSUES.md first (problem steps only)"
echo "  3. Compare SUMMARY.md step-level FAIL counts before vs after"
echo "  4. Drill down: <case>/report.md, <case>/abc/equivalence.log"
echo
echo "Run a wider check manually:"
echo "  VERIFY_TIER=basic python3 scripts/verify_testcases.py -v --label manual-check"
