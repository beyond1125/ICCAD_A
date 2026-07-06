---
paths:
  - "src/**"
  - "scripts/**"
  - "main.py"
  - "Dockerfile"
  - "cada1066_alpha"
---

# Documentation sync (code changes must update the matching docs)

The SDD/TSD were written from code reality on 2026-07-06 and are only useful
while they stay true. Any BEHAVIORAL change to code must land in the same
commit (or PR) as the matching doc update. Comment-only or formatting-only
changes are exempt.

## Change → doc mapping

| You changed | Update |
|---|---|
| Gates / budgets / context shrink in `src/agent/planner.py` | TSD §4.1/§4.2(5)(6) + SDD §5.1–5.3; `.claude/rules/agent-runtime.md` if a constant moved |
| Retry / provider logic in `src/agent/llm_client.py` | TSD §3.3, §6 錯誤處理表 + SDD §5.2 表 |
| Tools added/removed/renamed (`tool_spec.py` + planner dispatch) | TSD §3.4 工具表（四分類與總數）+ SDD §6.2 的數量 |
| Engine timeouts / write verification / session chain (`engine.py`) | TSD §5, §6 + SDD §5.4, §4.3 |
| C++ algorithms or CLI output strings (`src/eda_engine/parser/**`) | TSD §2 CLI 契約、§4 演算法表、§6.1 風險狀態 + SDD §6.3, §10 |
| Protocol / log paths (`io_manager.py`, `main.py`) | TSD §3.2 + SDD §6.1; CLAUDE.md if commands changed |
| Evaluation scripts (`scripts/check_*.py`, `eval_harness.py`, `run_all_llm.py`) | README Evaluation 段 + `.claude/rules/evaluation.md` + 對應 skill（run-sweep / check-results / debug-case） |
| Build / packaging (`Dockerfile`, `build_parser.py`, `cada1066_alpha`) | TSD §9 + README Setup/Usage |

## Rules

- A fixed risk listed in TSD §6.1 or SDD §10 must be re-marked（已修復 + 日期 +
  新行為）— never silently delete the entry; the history is the design record.
- New constants (timeouts, caps, thresholds) go into the TSD/SDD tables AND
  `.claude/rules/agent-runtime.md` if they participate in the timeout
  hierarchy invariant (outer must exceed inner).
- If you are unsure which section applies, grep the doc for the constant or
  function name you touched — both docs cite identifiers verbatim.
- Do not fabricate doc content beyond what the code change actually does.
