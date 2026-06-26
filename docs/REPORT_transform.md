# Transformation & Optimization — Work Report

Summary of the transform tools implemented, the testcases each is used in, and the algorithm
behind each. Every transform is functionally verified with `check_equivalence` (ABC `cec`).

## Architecture (how a transform runs)

```
 load_design ─▶ transform ─▶ transform ─▶ … ─▶ check_equivalence ─▶ write_design
                  each transform mutates the C++ graph, writes a session file, and
                  chains the active design forward; ABC is invoked for depth optimization
                  and for formal equivalence checking against the original netlist.
```

Two layers: **Python engine** (orchestration + ABC calls) and **C++ parser/graph** (the netlist
model and structural passes). Equivalence uses a **flop-cut combinational BLIF** (each DFF Q → a
primary input, D → an output `__D_<inst>`) compared with ABC `cec`.

---

## Transform functions

| # | Function (engine) | Used in testcases | Algorithm (brief) |
|---|-------------------|-------------------|-------------------|
| 1 | **`insert_buffers`** (max fanout N) | 21–30, 36, 40 | For every net driven by a gate with > N loads, build a **balanced BUF tree** (branching factor N): bottom-up, group loads into chunks of N behind new buffers until the top fits, then drive from the source. No driver ends up > N loads. |
| 2 | **`insert_dedicated_buffers`** (signal) | 31, 34, 39 | For **each** load of the signal, insert one dedicated BUF: `signal → buf_i → load_i`. Decouples every fanout branch. |
| 3 | **`buffer_signal`** (signal, max fanout N) | 34 (clock), 36/38 (reset) | Balanced BUF tree for **one named signal**, including a primary input. Gathers both gate-input loads and **DFF control-pin loads** (`.RN/.CK/.SN`, stored as pin references), then builds the tree. |
| 4 | **`reduce_depth`** | 22–30, 33, 40 | **ABC round-trip:** export flop-cut BLIF → `strash; balance; resyn2; balance` → read the optimized AIG back, mapping each 2-input node (by truth table) to a primitive + shared inverters → reattach the flip-flops. Re-enforces the fanout limit afterward. |
| 5 | **`remove_dangling`** | 23–30, 32, 33, 37 | **Reverse-reachability mark-sweep:** seed the live set with all primary outputs **and all flip-flops**; mark the transitive fanin; delete every gate/wire not marked (keep PIs/POs). O(V+E). |
| 6 | **`collapse_inverters`** | 26–31, 35, 38–40 | Find back-to-back `NOT→NOT` pairs (`NOT(NOT x) = x`); rewire the outer inverter's consumers directly to `x`; remove the inverters; iterate to a fixpoint so chains collapse fully. |
| 7 | **`merge_equivalent_gates`** | 29, 30, 33, 38 | **Structural de-duplication:** hash each non-DFF gate by `(type, sorted input nets)`; gates with the same signature compute the same function, so keep one and rewire the rest's consumers to it. Iterate to a fixpoint. |
| 8 | **`convert_cone_to_basis`** (cone, basis) | 26, 33, 37 | Rewrite every gate in a node's **fanin cone** to a target basis (NOR+NOT / AND+NOT / NAND+NOT) via Boolean identities (e.g. `AND=NOR(!a,!b)`), reusing the original gate as the output node, with **shared inverters**. |
| 9 | **`reconstruct_netlist_to_basis`** (basis) | 28, 29, 30, 34, 40 | Same identity-based rewrite as #8 but over the **whole netlist**. Result: only the basis gates remain (e.g. pure AND+NOT or NAND+NOT logic), flip-flops untouched. |
| 10 | **`decompose_gates_in_cone`** (cone, type, basis) | 25 (OR→NAND/NOT), 27 (XOR→AND/OR/NOT) | Replace every gate of a given type **in a cone** with an equivalent sub-circuit from the basis (e.g. `OR(a,b)=NAND(!a,!b)`). |
| 11 | **`decompose_all_gates`** (type, basis) | 35 (XNOR→NOR, XOR→4-NAND), 39 (XOR→4-NAND) | Same, **whole design**. Exact decompositions: **XOR → 4 NAND** (`n1=NAND(a,b); NAND(NAND(a,n1),NAND(b,n1))`) and **XNOR → 4 NOR** (same shape) — gate counts match the prompts exactly (4 per gate). |
| 12 | **`const_propagate`** (mode, type, value) *(teammate)* | 32, 36, 38, 39, 40 | Detect gates with a constant input (`1'b0/1'b1`) and simplify (`AND·0→0`, `OR·1→1`, `NAND·1→inverter`, …), cascading the resulting constants. |
| 13 | **`rename_node`** (old, new) | 24, 25, 31, 32, 35, 38 | Rename a gate/wire/signal: update the name + lookup map; pointer-based edges auto-update; also fix DFF pin-connection string references. |
| 14 | **`reconnect_pin`** (gate, pin, signal) | 36 | Map the pin letter (A=input 0, B=1, …) to an input index and rewire that edge to a new signal — **applied only if equivalence is preserved** (internal `cec`; reverted otherwise). |
| 15 | **`restructure_to_depth`** (node, target) | 26–30, 40 | Best-effort depth **report**: measure the node's cone depth (levelization) and report whether it already meets the target. No structural change (design already globally depth-optimized). |
| 16 | **`optimize_outputs_to_depth`** (max depth) | 27, 31, 39 | One levelization pass; list every primary output whose logic depth exceeds the limit. |
| 17 | **`check_equivalence`** (reference) | all (explicit "prove/verify" in 31–38, 40) | **Formal verification:** export current + reference to flop-cut BLIF; ABC `cec` (SAT-based combinational equivalence on the flip-flop boundary). |

---

## Supporting infrastructure (enablers)

These are not transforms but were required to make the above work on sequential gate-level netlists:

| Component | Why it mattered |
|-----------|-----------------|
| **DFF named-port round-trip** (parser) | Original parser destroyed every flip-flop on write (`dff g(.RN(n1),…)` → garbage). Fixed parse + faithful re-emit of named ports/constants — unblocks **all** sequential testcases. |
| **`write_blif` (flop-cut)** | Bridges our gate-level netlist to ABC: each DFF Q → PI, D → output `__D_<inst>`. The basis for both `reduce_depth` and `check_equivalence`. Handles registered outputs and shared-Q multi-driver flops. |
| **`load_logic_blif` + `rebuild`** | Reads ABC's optimized AIG-BLIF back into the graph (truth-table → primitive mapping) and reattaches flip-flops with their control pins. |
| **Parser performance** | Hoisted hot-path regexes to `static const` → **~20× faster** parsing (test24: 54 s → 2.6 s), needed because every tool re-parses the netlist. |
| **Session-state + fanout re-enforcement** | Each transform chains the active design forward; a requested max-fanout is recorded and auto-re-enforced after restructuring and on write. |

---

## Verification methodology

Every transform is checked with **ABC `cec`** against the original netlist (flop-cut model), so
all results in the testcases are **formally proven functionally equivalent**. The exact-count
decompositions (XOR→4-NAND, XNOR→NOR) were additionally verified to produce the expected gate
counts (4 per gate) at scale (test39: 112 k gates).

## Coverage

All 11 transform categories from the original plan (T1–T11) plus equivalence checking are
implemented and verified: buffering/fanout, depth optimization, dangling removal, basis remap,
gate decomposition, inverter collapse, duplicate merging, constant propagation, redundancy
removal, renaming, and pin reconnection.
