---
description: Grade testcase outputs against hard requirements and goal predicates, and interpret failures. Use when asked whether outputs pass, why a testcase fails, or what the score is.
argument-hint: "[testNN | all]"
---

# check-results

Two independent evaluators, different jobs — run both when asked for "the score."

## scripts/check_results.py — hard requirements

```
python3 scripts/check_results.py --all
python3 scripts/check_results.py --case test26
python3 scripts/check_results.py --from 21 --to 30
```

Grades `testNN_out.v` against the hard requirements implied by `prompt.txt`.
Independent of the agent pipeline: it parses netlists with its own
self-contained mini-parser (does **not** call `src/eda_engine`), so a
structural check is a real double-check, not the engine grading itself. The
one place it reuses the real tools is equivalence: `parser_cpp --action
write_blif` on original and output, then `abc -q "cec a.blif b.blif"`
(flop-cut) — ABC does the actual math.

Per case: output exists and parses; functional equivalence; structural hard
requirements (max fanout, basis purity on whole design or a fanin cone,
forbidden gate types, per-signal buffer trees). Soft/ambiguous items
(renames, dedicated buffers, back-to-back inverters) print as `warn` and
never fail the case.

## scripts/eval_harness.py — ground-truth-free goal predicates

```
python3 scripts/eval_harness.py
python3 scripts/eval_harness.py --case 12
python3 scripts/eval_harness.py --skip-paths   # skip slow tool path checks
```

No external answer key; three self-generated sources of truth: (1) ABC `cec`
proving each output equivalent to the original, (2) invariants on the output
(flip-flop count preserved, max gate fanout, round-trip stability), and (3) a
differential check — an independent Python oracle in the script itself vs.
`parser_cpp` on the *original* netlist (gate counts, and combinational path
existence for any path query found in `prompt.txt`). Agreement is
confidence; disagreement is a real bug. A tool timeout where the oracle
answers instantly (test12) is itself a finding.

## Verdict semantics (check_results.py)

- `PASS` — equivalence proven and all hard checks passed.
- `PASS?` — hard checks passed but equivalence was inconclusive.
- `FAIL` — any hard check failed (NOT EQUIVALENT, or a hard
  structural/basis/fanout/rename requirement failed).
- `NO_OUTPUT` — `testNN_out.v` was never written.
- `warn` lines are soft — printed but never flip the verdict to FAIL.

## Extending: adding a case's hard requirements

Edit `case_checks(n, nl)` in `scripts/check_results.py`: append
`hard(label, check_fn(...))` or `warn(label, check_fn(...))` for the new
case number. Existing helpers: `check_max_fanout`, `check_net_tree_fanout`
(fanout), `check_basis` (whole `nl.gates` or a `fanin_cone(nl, root)`
slice), `check_no_type` (forbidden gate type), `check_no_b2b_inverters`,
`check_name_exists` (renames), `check_dedicated_buffers`. Match an existing
case's pattern before inventing a new check.

## Known intentional warns (not bugs)

- Renames dissolved by depth optimization (`docs/OPEN_QUESTIONS.md` D1) —
  accepted graceful "not found" failure.
- BUF exempt from basis-purity checks (D2) — fanout buffering wins over
  strict basis purity.
- test37: n8 and n9 fanin cones overlap; their basis requirements (NAND+NOT
  vs NOR+NOT) mathematically conflict on shared gates — n8 is `warn`, n9 is
  `hard`.
