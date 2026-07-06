# ICCAD 2026 Problem A — cada1066 (team 1066)

LLM agent that drives a C++ netlist engine + Berkeley ABC over gate-level Verilog
netlists, evaluated with claude-haiku-4-5 / gpt-4o-mini. Requests arrive one per
line on stdin; every response is wrapped in `#RESPONSE <id>` / `#END <id>` on
stdout; a log copy goes to `<case_name>.log`. Entry point: `./cada1066_alpha
-config config.yaml`. Spec: `A_20260212.pdf`. Hard-requirement violations
(functional equivalence, fanout/depth bounds) = zero credit for that testcase.

## Commands

```bash
python3 scripts/build_parser.py                       # build the C++ parser
cat testcase/test02/prompt.txt | python3 main.py -config config.yaml   # single case, manual
python3 scripts/run_all_llm.py --case 2                # single case via harness (cheap canary)
python3 scripts/run_all_llm.py                         # full sweep, ~40 cases, costs API $
python3 scripts/check_results.py --all                  # hard-requirement grading checker
python3 scripts/eval_harness.py                         # ground-truth-free goal harness
python3 scripts/grader_sim.py test02                    # faithful single-case reproduction
```

Debug a single case: `DEBUG=1 python3 scripts/grader_sim.py <case>` — pipe-based
and gated on `#END` exactly like the real grader; full LLM/tool-call trace lands
in /tmp/grader_sim/. See the `debug-case` skill.

## Hard rules

1. Use system `python3`. `./venv` is broken (missing deps) — do not use it.
2. `run_all_llm.py` "OK" means protocol completed + output file exists. It is
   NOT a score. Always follow with `scripts/check_results.py`, and optionally
   `scripts/eval_harness.py`, before believing anything passed.
3. Run `--case <n>` first after any change, not a full sweep. Sweeps cost real
   API money (~40 cases ≈ 50–65 min on haiku) and test12 alone legitimately
   takes ~10 min. Suspiciously fast or uniform results mean provider failure
   or stale artifacts, not success.
4. Never edit runtime files (`src/**`, `main.py`) while a sweep is running —
   each case spawns a fresh `main.py` from the working tree.
5. The anti-fabrication gates and timeout hierarchy in `src/agent/planner.py`
   are load-bearing. Read `.claude/rules/agent-runtime.md` before touching
   anything under `src/`.
6. Functional equivalence is sacred: any hard-requirement violation is
   zero credit for that testcase, no partial credit.
7. Shared machine, no docker group (don't attempt docker build/run — ask an
   admin), OpenAI key currently has no quota (4o-mini runs fail 429; use the
   Anthropic key/config).
8. Never work on `main`. Use feature/fix branches, merge via PR.

## Architecture

```
main.py -> src/utils/io_manager.py (protocol + logging)
        -> src/agent/planner.py (LLM tool-calling loop, anti-fabrication gates)
        -> src/eda_engine/engine.py (one subprocess per action)
        -> src/eda_engine/parser/parser_cpp (C++ netlist engine)
        -> tools/abc/abc (equivalence `cec` + depth optimization)
```

## Key docs

- `docs/System_design_document.md` — architecture, interfaces, design decisions.
- `docs/Technical_specification_document.md` — classes, algorithms, data
  structures, known silent-failure risks.
- `docs/OPEN_QUESTIONS.md` — spec-ambiguity decisions; read before changing
  transform semantics.
- `docs/REPORT_transform.md` — transform tools, testcases, algorithms.
- `docs/EVAL_HARNESS.md` — evaluation harness design notes.
- `docs/archive/` — historical reports.
