---
paths:
  - "src/**"
  - "main.py"
---

# Agent runtime invariants (load-bearing)

## Anti-fabrication gates (src/agent/planner.py)

Small eval models (haiku, 4o-mini) systematically fabricate success: they answer
"saved successfully" / "138 XOR replaced, 552 NAND added" with ZERO tool calls.
Before these gates existed, 23/40 testcases lost their output file and
`check_results.py` passed only 16/40. With the gates + timeout hierarchy below,
40/40 pass. Do not remove or weaken any of these without re-running the full
sweep + checker and comparing pass counts — a regression here is silent (the
run still reports "OK") until `check_results.py` is run.

- **Zero-tool gate**: if the LLM answers without calling any tool, it is
  rejected and re-prompted — nothing was actually done or measured.
- **Write gate**: a request with write/save/output/export intent (`_RE_WRITE_INTENT`)
  is only accepted once `engine.verified_writes` shows a new disk-verified write
  matching the requested filename (`_write_satisfied`).
- **Transform gate**: a request with transform intent (`_RE_TRANSFORM_INTENT`,
  not a question) must have executed at least one tool in `_TRANSFORM_TOOLS`
  before the answer is accepted.
- **Correction cap**: max 2 corrections per request (`corrections < 2`); after
  that a write request gets a hard failure answer instead of looping forever.

## Timeout hierarchy (outer must exceed inner)

| Level | Value | Constant | Reason |
|---|---|---|---|
| Request wall-clock | 270s | `planner._REQUEST_BUDGET_S` | spec limit is 300s/request; leaves margin to still emit `#END` |
| ABC call (cec / reduce_depth) | 180s | the two `subprocess.run([abc_path, ...], timeout=180)` sites in `engine.py` | ABC restructuring/cec can run long on bigger designs |
| Parser subprocess action | 150s | `engine._ACTION_TIMEOUT_S` | bounds e.g. exponential path enumeration (test12 needs this; the oracle in eval_harness.py answers instantly while the tool can time out) |
| check_const wall clock | 110s | `engine._CONST_BUDGET_S` | one functional-constancy verdict (sim + ABC sequential channel + SAT rounds + DFF fixed point) must leave request-budget room for the answer turn |
| functional report/tie batch | 80s | `engine._FUNC_BUDGET_S` | one `const_propagate semantics='functional'` scan/tie pass; SAT is skipped once exhausted (timeout proves nothing — only UNSAT counts as constant) |
| ABC pdr call | 30s `-T` (+15s subprocess grace) | `engine._PDR_TIMEOUT_S` | `-T` is clamped to `remaining - _PDR_RESERVE_S` (40s) so an UNDECIDED pdr never starves the comb-SAT fallback; UNDECIDED/timeout is never a proof |
| ABC scleanup pipeline | 30s | `engine._SEQ_ABC_TIMEOUT_S` | read+strash+scleanup+write of the sequential BLIF (measured ~0.7s wall at 16050 latches); clamped to the remaining check_const budget |
| single ABC SAT call | 20s | `engine._SAT_TIMEOUT_S` | clamped to the remaining batch/check_const budget so one slow instance cannot drag the pass past its deadline (check_const's final flop-cut pair included since the seq channel landed) |

Each level must stay strictly under the one above it or a slow inner call
silently eats the outer budget and the request never gets a chance to answer
before the grader's own timeout.

## Single-threaded execution (contest Q&A A21.5/6)

The contest allows **one request at a time, single-threaded only**. The
current architecture complies by construction: the planner executes tool
calls sequentially, the engine runs one subprocess per action and waits for
it, and ABC is invoked single-threaded. This is an invariant, not an
optimization opportunity — do NOT add parallel tool execution, concurrent
subprocess pools, or multi-threaded C++ actions, even where they would be
functionally safe.

## Protocol invariants (src/utils/io_manager.py, main.py)

- Nothing may print to stdout except `IOManager.write_response` — the
  `#RESPONSE <id>` / `#END <id>` protocol owns stdout exclusively. All logging
  (`logging.basicConfig`) goes to stderr.
- `#END <id>` must be followed by an immediate stdout flush — the grader only
  sends the next line after it sees `#END`.
- Response ids are monotonic per testcase, reset to 0 on each testcase-init line.
- Log file is `<case_name>.log` in the CWD; a second copy is written to
  `testcase/<case_name>/<case_name>.log` if that directory exists.

## Engine invariants (src/eda_engine/engine.py)

- `write_design` must stay disk-verified: it only appends to
  `verified_writes` after confirming `os.path.isfile(filepath)` post-write.
  This list is what powers the write gate above — do not report success
  before that check.
- `_max_fanout_constraint`, once set by an earlier buffering request, is
  re-enforced inside both `reduce_depth` and `write_design` (D3 in
  `docs/OPEN_QUESTIONS.md`) because ABC restructuring dissolves inserted
  buffers. Do not drop the re-enforcement call in either place.
- Transforms chain session files through `_loaded_filepath` (each transform
  writes to a new file under `_session_dir` and re-points `_loaded_filepath`
  at it). Never bypass `_loaded_filepath` by operating on a stale path —
  later actions and `write_design` read whatever it currently points to.
