# Evaluation Harness — Report

`scripts/eval_harness.py` scores the netlist system **objectively without any external
answer key**. It generates its own "ground truth" three ways and reports per-testcase results.

## What it checks

### 1. Equivalence (validates transforms)
For each `testNN_out.v`, it builds a flop-cut BLIF of both the output and the original and runs
**ABC `cec`**. This is a formal *proof* that the transformed netlist is functionally equivalent to
the original — a non-equivalent output is a definite failure. No answer key needed.

### 2. Invariants (properties that must always hold)
On each output netlist:
- **Flip-flop count preserved** — transforms must not add/remove flops.
- **Max gate fanout** — reported (and checkable against a `≤N` requirement).
- **Round-trip stable** — `load → write → load` reproduces the same gate count.

Any violation is a bug, regardless of the "right" answer.

### 3. Differential testing (validates analysis tools)
An **independent Python oracle** in the same file (regex netlist parser + BFS reachability)
computes answers a second, different way and compares them to the C++ tools on each netlist:
- **Gate counts** — oracle vs `count_gates`. Disagreement = a parser/counter bug.
- **Combinational path existence** — oracle vs `find_paths`. Disagreement = a logic bug;
  a **tool timeout while the oracle answers instantly** is itself a finding (a tool that
  doesn't scale).

The netlist *is* the ground truth; two independent implementations agreeing is strong evidence.

## Usage

```bash
python3 scripts/eval_harness.py                 # every testcase found
python3 scripts/eval_harness.py --from 21 --to 30 --skip-paths   # fast equivalence sweep
python3 scripts/eval_harness.py --case 12        # includes the slower path-tool checks
```

## Output

A per-case table — `status | equiv | count-match | dff-ok | maxFO | notes` — then a summary with
the **equivalence pass-rate**, the **differential gate-count match rate**, and any **path-tool
timeouts**. Example:

```
test21  PASS   EQUIV   ok   ok   4
...
EQUIVALENCE (transforms): 10/10 outputs proven equivalent
DIFFERENTIAL gate-count: 10/10 match the independent oracle
```

Verified in practice: test21–30 → **10/10 proven equivalent, 10/10 counts match, flops preserved**;
test12 → count matches but `find_paths` **times out** on 3 path queries the oracle answers in <1 s
(surfacing the path-enumeration scaling bug that blocks test12).

## Limits (what it deliberately does not score)
- Exact answer **phrasing/format** the grader expects.
- Ambiguous semantic choices (which cone definition, whether BUF counts in a basis) — these need
  the contest rubric, not a harness (see `OPEN_QUESTIONS.md`).
