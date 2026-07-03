---
description: Reproduce and debug a single failing ICCAD testcase with the faithful pipe-gated grader simulator and tool-call tracing. Use when one testcase fails, times out, or gives a wrong/fabricated answer.
argument-hint: "[testNN]"
---

# debug-case

## Reproduce

```
python3 scripts/grader_sim.py testNN
```

The most faithful reproduction of the real grader: plain pipes (not a pty),
one prompt line at a time, gated on the exact `#END <n>` on stdout — the
same contract the real harness relies on, so pty line-buffering can't mask
a stdout-buffering bug here.

```
DEBUG=1 python3 scripts/grader_sim.py testNN
```

Same run, but `main.py` inherits `DEBUG=1` and logs full LLM request/tool-call
tracing to stderr. Transcript and stderr land in `/tmp/grader_sim/`
(`testNN_grader_sim.log`, `testNN_grader_sim.stderr`).

## Diagnosis tree

**1. Answer claims success but the checker fails.** Grep tool-call blocks:

```
grep -A2 "Anthropic ToolCall" /tmp/grader_sim/testNN_grader_sim.stderr | grep -E "^(Name|Args):"
```

(swap `Anthropic` for `OpenAI` per `config.yaml`'s provider). Zero tool
calls for that turn = model fabrication — the planner's answer gates
(`src/agent/planner.py`) should catch and re-prompt this; check the same
stderr for `Answer gate correction` warnings to see if a gate fired.

**2. A tool was called but returned the wrong result.** Engine/parser bug,
not an LLM bug — reproduce directly, bypassing the LLM:

```
src/eda_engine/parser/parser_cpp --in <file.v> --action <action> [options]
```

**3. A turn exceeds its time limit.** Check the transcript/stderr for the
150s parser-action timeout (`engine._ACTION_TIMEOUT_S`) or the 180s ABC
`cec`/`reduce_depth` timeout — path enumeration hits the former, heavy ABC
restructuring the latter.

**4. The checker itself looks wrong.** `scripts/check_results.py` uses its
own independent mini-parser, not `src/eda_engine`. Cross-check any
structural claim by hand with `parser_cpp` (e.g. `--action count_gates` or
`--action write_blif`) before assuming the checker is right.

## Before touching planner or engine timeouts/gates

Read `.claude/rules/agent-runtime.md` first — it documents the
anti-fabrication gates (zero-tool / write / transform gates, 2-correction
cap) and the timeout hierarchy (270s request budget > 180s ABC > 150s parser
action) that keep 40/40 cases passing. Revalidate any change here with a
sweep + `check_results.py` — a regression can silently drop the pass count
while `run_all_llm.py` still reports `OK`.
