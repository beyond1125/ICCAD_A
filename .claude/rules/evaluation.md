---
paths:
  - "scripts/**"
  - "testcase/**"
---

# Evaluation layers

Three independent layers; run in this order, never trust just the first.

## 1. `scripts/run_all_llm.py` — protocol runner

Drives `main.py` end-to-end through the real LLM; reports a status, not a
score. `OK` = all turns answered (`#END` count >= expected turns) and the
output `.v` exists. `OK*` = all turns answered but no output file detected.
`PARTIAL` = ran out of turns. `APIERR` = LLM/API failure seen in
stdout+stderr (bad key, 401, rate limit) despite `#END` tags still being
produced — the sweep aborts here so a dead key can't silently burn through
all 40 cases. `ERR`/`TIMEOUT`/`CRASH` = non-zero exit, per-case timeout, or
runner exception. Token columns come from the `[TOKENS] ... total=N
api_calls=N` line `main.py` prints to stderr on exit. `OK` only means the
protocol completed and a file exists — never a substitute for correctness.

## 2. `scripts/check_results.py` — hard-requirement checker

Independent of the pipeline: re-parses `<case>_out.v` with its own
self-contained mini-parser (not `parser_cpp`) and checks the hard
requirements implied by `prompt.txt` (equivalence via `write_blif` + ABC
`cec`, max fanout, gate-basis purity, forbidden gate types, dedicated buffer
trees) per the `case_checks(n, nl)` table in that file. `PASS` = equivalence
proven, no hard check failed. `PASS?` = no hard check failed but equivalence
was inconclusive (ABC/parser unavailable or timed out) — investigate, don't
treat as clean. `FAIL` = a hard requirement failed (incl. NOT EQUIVALENT).
`warn` = a soft/ambiguous requirement (renames, back-to-back inverters,
dedicated buffers) failed; does not fail the case. To add a new testcase's
hard requirements, extend `case_checks` in `scripts/check_results.py` (it
dispatches on testcase number `n`, appends `(label, is_hard, ok, detail)` via
its local `hard(...)`/`warn(...)` helpers) — don't bolt requirements on
elsewhere.

## 3. `scripts/eval_harness.py` — ground-truth-free goal harness

No external answer key. Equivalence (ABC `cec` vs original), invariants
(flip-flop count preserved, max fanout, round-trip gate-count stability),
and differential checks (independent Python oracle in the script vs
`parser_cpp`'s own `count_gates`/`list_paths` on the *original* netlist —
disagreement is a real bug; a tool timeout where the oracle answers
instantly is itself a finding). See `docs/EVAL_HARNESS.md` for design notes.

## The staleness trap

`run_all_llm.py` deletes each case's `<case>_out.v` before running
(`out_v.unlink(missing_ok=True)`) so a stale file can never be mistaken for
this run's output. Never weaken this — cautionary tale: an earlier bogus run
against 4o-mini (no API quota, every call 429ing) still reported "40/40"
because old output files from a prior successful sweep were left in place
and re-graded. Always start from a clean sweep when the provider/config
changed.

## Timing sanity table

| Case | Expected time | Note |
|---|---|---|
| test02 | ~12s | cheap canary for `--case` smoke tests |
| test12 | ~10 min | bounded path enumeration, legitimately slow |
| full haiku sweep (40 cases) | ~50–65 min | costs real API tokens |

Suspiciously fast or uniform results mean provider failure or stale
artifacts, not success.

## Known intentional warns (docs/OPEN_QUESTIONS.md)

- **D1** — renames dissolved by depth optimization are an accepted loss;
  `rename_node` reports "not found," equivalence still holds.
- **D2** — BUF is exempt from logic-basis purity (buffers aren't logic
  gates); fanout limits win over strict basis purity when they conflict.
- **test37** — `n8` (NAND+NOT) and `n9` (NOR+NOT) cone requirements overlap
  on shared gates and cannot both hold; `check_results.py` marks `n8` as
  `warn`, `n9` as the hard check.
