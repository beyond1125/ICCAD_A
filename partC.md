# Part C — Transformation & Optimization (EDA Tooling Guide)

> **Scope:** This document is for the engineer owning the **Transformation & Optimization**
> operations of ICCAD 2026 Problem A. It identifies, from the 40 official testcases, exactly
> which prompts are *transformations* (your responsibility) vs. *analysis/queries* (someone
> else's), and tells you **which EDA tool to use** and **which command** implements each one.

---

## TL;DR — what tool do I need?

| Need | Tool | Why |
|------|------|-----|
| **Logic optimization, depth reduction, tech-remap, gate decomposition, sweep/cleanup, structural & functional merge, constant propagation** | **Berkeley ABC** (`tools/abc`, already in README setup) | Industry-standard AIG-based synthesis engine; one binary covers ~80% of the transformation prompts |
| **Verilog ⇄ ABC bridge (read gate-level `.v`, write back), sequential/DFF handling** | **Yosys** *(recommended to add)* **or** the in-house `parser/parser.cpp` | ABC's own `read_verilog` only accepts a tiny structural subset; you need a clean front/back-end for these netlists (they contain `dff`, buses, `XNOR`, etc.) |
| **Functional equivalence checking (MANDATORY after every transform)** | **ABC** `cec` / `dsec` / `&cec` (SAT-based) | **Every** transformation prompt says *"Ensure functional equivalence is preserved"* — you must prove it, not assume it |
| Buffer insertion / fanout-limit (≤4 loads) | **Custom pass** (in `parser.cpp` / a Python pass) + ABC for verify | This is a physical/structural rule ABC doesn't do natively; do it ourselves, then `cec` to confirm |

**Bottom line: install and drive Berkeley ABC. It is the core engine for your part.** Wrap it
behind `eda_engine/engine.py` so the LLM planner can call it as a tool.

---

## Which prompts are MINE (Transformation & Optimization)?

Across `testcase/test01 … test40`, prompts fall into two buckets. **Bolded = your scope.**
Everything else (gate counting, fanin/fanout cones, path enumeration, depth *reporting*,
Boolean-equation extraction, symmetry, "is output always 0", etc.) is **analysis/query** and
belongs to the Analysis owner — you only *consume* their depth/fanout numbers to know when to
stop optimizing.

### Your 11 transformation categories

| # | Transformation (verbatim phrasings seen in prompts) | Appears in | EDA tool / command |
|---|------|-----------|--------------------|
| **T1** | **Buffer insertion / fanout optimization** — *"insert buffers so no gate drives more than 4 loads"*, *"fanout optimization with max fanout 4"*, *"insert BUF on signal n2 / clock n0 / reset n1 so each load is driven through a dedicated buffer"* | 21,22,23,24,26,27,28,29,30,31,34,36,38,40 | **Custom pass** (split fanout into a buffer tree, BUF = `buf`); verify with ABC `cec` |
| **T2** | **Depth / critical-path optimization** — *"reduce critical path depth through restructuring"*, *"minimize maximum path depth"*, *"optimize n8 to ≤4 levels"*, *"target depth 4"* | 22,23,24,25,26,27,28,29,30,33,40 | **ABC**: `strash; balance; resyn2` (depth-oriented `balance`/`dch`), then `if -K …`; report original if no gain |
| **T3** | **Dead / dangling / unused gate removal** — *"trim unused wires and gates"*, *"remove dangling gates"*, *"sweep out dangling gates"*, *"prune the netlist"*, *"remove floating nodes"* | 23,24,25,26,27,28,29,30,32,33,37 | **ABC**: `sweep` + `cleanup` (+ `trim`) |
| **T4** | **Technology re-mapping to a gate basis** — *"reconstruct using only AND+NOT"*, *"remap to NAND+NOT only"*, *"restructure cone of nX with only NAND/NOT (or NOR/NOT)"* | 25,26,28,29,30,33,34,37,40 | **ABC**: `strash` (AIG = AND+INV natively) → for NAND/NOR-only use targeted mapping / DeMorgan rewrite then `write_verilog` |
| **T5** | **Gate decomposition / type conversion** — *"decompose XOR into AND/OR/NOT"*, *"convert XOR → 4-NAND"*, *"convert XNOR → NOR-only"*, *"replace 2-input OR with NAND+NOT"* | 25,27,33,34,35,39 | **ABC** mapping, **or** a deterministic rule-based rewrite pass (these are fixed identities — exact gate counts are checked, e.g. *"4 NANDs per XOR"*) |
| **T6** | **Back-to-back inverter collapse** — *"find NOT→NOT pairs and collapse into a wire"* | 26,27,28,29,30,31,35,38,39,40 | **ABC** `strash`/`cleanup` removes double-inverters automatically; or trivial custom pass |
| **T7** | **Gate merging — structural & functional duplicates** — *"merge gate pairs that compute the same function"*, *"merge structural duplicates"* | 29,30,33,35 | **ABC**: `strash` (structural hashing) → `fraig` / `dch` (functionally-reduced AIG merges SAT-equivalent nodes) |
| **T8** | **Constant propagation / simplification** — *"NAND with input tied to 1 → inverter"*, *"AND with const-0 input"*, *"OR with const-1 input"*, *"NOR with constant inputs"* | 32,36,38,39,40 | **ABC** `sweep`/`strash` does constant propagation; the *counts* asked for may need a custom counting pass |
| **T9** | **Redundancy removal** — *"remove redundant gates without changing functionality"* | 38 | **ABC**: `dch; fraig` (don't-care + SAT-based redundancy removal) |
| **T10** | **Rename gate / wire / signal & update all references** | 24,25,31,32,35,38 | **In-house parser pass** (pure naming; no logic change) — do *not* route through ABC, it discards names |
| **T11** | **Pin reconnection** — *"reconnect input pin A of g0 to internal signal n24[0]"* | 36 | **In-house parser pass** (structural edit) + ABC `cec` to confirm intent preserved |

### The verification obligation (do not skip)

Nearly every transformation prompt is followed (now or later in the same testcase) by one of:

- *"Ensure functional equivalence is preserved" / "Make sure nothing changes functionally"*
- *"Verify functional equivalence between the current design and the original loaded netlist"*
- *"Prove that the transformed design is equivalent to the pre-transformation netlist"*
- *"Confirm the design is still functionally equivalent to the original"*

→ **Keep a saved copy of the netlist as last loaded from disk (the "golden")**, and after every
transform run **`abc -c "cec golden.v current.v"`** (or `dsec` for sequential/DFF designs).
This is itself one of your deliverables, not just an internal check.

---

## How ABC fits the flow

These netlists are **gate-level, sequential** (`dff g0(.RN, .SN, .CK, .D, .Q)`), with buses
(`n0[7:0]`), and primitives `AND OR NOT NAND NOR XOR XNOR BUF DFF`. ABC's native `read_verilog`
will *not* swallow this directly. Use this pipeline:

```
            (in-house parser.cpp  OR  Yosys)        ABC                (in-house parser.cpp)
 test.v  ───────────────────────────────────►  .blif/.aig  ──optimize──►  out.aig  ──────────────►  testNN_out.v
            front-end: parse + flatten buses,                 T2–T9                back-end: emit
            map dff to ABC latch                                                  Verilog-1995
```

Recommended concretely:

1. **Front-end → BLIF/AIGER.** Either teach `parser.cpp` to emit BLIF, or add **Yosys**:
   `yosys -p "read_verilog test.v; flatten; aigmap; write_blif test.blif"`. Yosys handles the
   buses, XNOR, and DFFs cleanly. (Yosys can even call ABC internally via `abc -script`, which
   may save you the round-trip for T2/T3/T6/T7.)
2. **Optimize in ABC.** A solid general script for depth+area (T2/T3/T6/T7/T9):
   `strash; sweep; cleanup; dc2; resyn2; dch -f; if -K 4; sweep; cleanup`
   (`if -K 4` is the lever for the recurring *"≤4 levels deep"* depth targets).
3. **Equivalence-check** before trusting output: `cec golden.blif optimized.blif` (combinational)
   or `dsec` (with DFFs).
4. **Back-end → Verilog-1995** via the in-house writer (the parser already targets Verilog-1995),
   so the output matches the grader's expected `testNN_out.v` format.

### Where ABC is *not* the right tool

- **T1 (buffer/fanout ≤4)** and **T10/T11 (rename / pin reconnect)** are structural/physical
  edits that ABC will undo or rename away. Implement these as **custom passes over the in-house
  graph (`parser.hpp` Graph/Node)**, then use ABC only to *verify* equivalence.
- **Exact-count conversions** (T5: *"4 NANDs per XOR"*, *"how many NORs after XNOR conversion"*)
  expect a *specific* decomposition. ABC's mapper may produce a different (equivalent) structure,
  so for the counted ones use **deterministic identity-based rewrites** and let ABC only verify.

---

## Action items for you

1. **Add ABC to the repo build** (README already has the clone/make steps under `tools/abc`).
   Smoke-test: `tools/abc/abc -c "version"`.
2. **Decide the front/back-end bridge:** quickest is adding **Yosys** for `read_verilog`→`blif`;
   otherwise extend `parser.cpp` to emit/ingest BLIF. (Yosys recommended — saves weeks on bus/DFF
   parsing.)
3. **Expose transformation tools** in `agent/tool_spec.py` + `eda_engine/engine.py`, e.g.
   `optimize_depth`, `remove_dangling`, `remap_to_basis(basis)`, `decompose_gate(type)`,
   `merge_equivalent`, `propagate_constants`, `collapse_inverters`, `check_equivalence`,
   `insert_buffers(max_fanout)`. Each wraps an ABC script or a custom pass.
4. **Wire in mandatory `cec`/`dsec`** after every transform and surface the result (the prompts
   explicitly grade *"prove equivalence"*).
5. Keep T1/T10/T11 as in-house graph passes; everything T2–T9 goes through ABC.
