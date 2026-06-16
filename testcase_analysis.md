# Testcase Analysis — Tool Requirements per Testcase

> Companion to [partC.md](partC.md). This file records, for each of the 40 official testcases,
> **which engine tools each prompt needs** and **whether that capability already exists**.
> Use it to see what already works, and to scope the Transformation & Optimization work that is
> still missing (the part owned by this engineer).

## Current state (as of commit `e05dc19 "test 6~8 OK"`, by PinShiang)

The C++ parser + planner currently expose **9 tools** (10 parser actions — `find_paths` now backs
both path-existence and full enumeration via the new `list_paths`/`find_all_paths`). Reading the
prompts, that set is enough to clear **testcase 01–14**. The first *analysis* gap is **test15**
(transitive cones); the first *transformation* gap — i.e. **our part** — is **test21** (buffer
insertion). ABC is cloned under `tools/abc` but **not integrated**; no transformation beyond
single-gate `replace_gate` works yet.

> ⚠️ **Risk in the new `find_all_paths`:** enumeration is hard-capped at **100 paths** to bound
> output. Prompts asking for a *"complete enumeration of paths"* (test09–20) will be silently
> truncated on wide cones — verify whether the grader expects exhaustive lists before relying on it.

### Tool legend

**✅ Implemented** (in `parser.cpp` / `engine.py` today)

| Code | Tool | Covers |
|------|------|--------|
| `LOAD` | load_design | read `.v` |
| `WRITE` | write_design | emit `testNN_out.v` |
| `CNT` | count_gates | gate counts by type |
| `FIC` | count_fanin_gates | # gates in a fanin cone |
| `DEP` | analyze_depth | max / critical / point-to-point logic depth |
| `PATH` | find_paths | path existence, avoid-node, full enumeration (`list_paths`, capped at 100) |
| `INFO` | get_node_info | gate type, fanin/fanout count, drivers, immediate successors |
| `LST` | list_nodes | list signals/gates |
| `RGATE` | replace_gate | change one gate's type |

**🟡 Analysis TODO** (not our part, but needed by mid/late testcases — flag to the Analysis owner)

| Code | Capability | First needed |
|------|------------|--------------|
| `CONE` | transitive fanin / fanout cone | test15 |
| `EQV` | functional equivalence of two internal signals (SAT/BDD) | test17 |
| `BEQ` | Boolean equation / function in terms of PIs | test31 |
| `CONST0` | "is output always 0 / constant?" | test31 |
| `SYM` | input symmetry check | test36 |
| `SHARE` | gates shared between two cones | test31 |
| `R2R` | register-to-register path listing / depth | test32 |
| `ART` | articulation points in a sub-graph | test38 |
| `CUT` | is a wire a cut between PI and PO | test33 |
| `PIPO` | list PIs/POs with bit widths, PI/PO counts | test33 |
| `DFFQ` | clock/reset/flip-flop queries, depth-to-DFF-D-pin, enable/hold detect | test31 |
| `MISC` | deepest cone, highest-fanout PI, gates tied to const, floating-port check, list gates of a type | test31 |

**🔴 Transformation TODO — OUR PART** (needs ABC + custom passes; see partC.md T-codes)

| Code | Transformation | First needed |
|------|----------------|--------------|
| `T1` | buffer insertion / fanout-limit ≤4 | test21 |
| `T2` | depth / critical-path optimization (incl. "≤4 levels") | test22 |
| `T3` | dangling / unused / floating gate removal (sweep) | test23 |
| `T4` | technology remap to a basis (AND+NOT / NAND+NOT / NOR+NOT) | test25 |
| `T5` | gate decomposition / conversion (XOR→4NAND, XNOR→NOR, OR→NAND…) | test25 |
| `T6` | back-to-back inverter collapse | test26 |
| `T7` | structural + functional duplicate merge | test29 |
| `T8` | constant propagation (NAND·1→INV, AND·0, OR·1, NOR·const) | test32 |
| `T9` | redundancy removal | test38 |
| `T10` | rename gate / wire / signal + update refs | test24 |
| `T11` | pin reconnection | test36 |
| `CEC` | **equivalence verify after every transform** (`cec`/`dsec`) | test21 |

---

## Per-testcase tool map

Status column: **✅ passable now** · **🟡 blocked on analysis tool** · **🔴 blocked on our transform tool**.

| TC | Operations → tools | New capability needed | Status |
|----|--------------------|-----------------------|--------|
| 01 | LOAD, WRITE | — | ✅ |
| 02 | CNT, WRITE | — | ✅ |
| 03 | FIC, WRITE | — | ✅ |
| 04 | DEP (fanin-cone), WRITE | — | ✅ |
| 05 | INFO (fanout list), WRITE | — | ✅ |
| 06 | CNT, PATH(avoid), WRITE | — | ✅ |
| 07 | CNT, PATH(avoid)×2, WRITE | — | ✅ |
| 08 | CNT, PATH(avoid), PATH(enumerate) | — | ✅ |
| 09 | CNT, PATH(avoid/enumerate) | — | ✅ |
| 10 | CNT, PATH, DEP | — | ✅ |
| 11 | CNT, PATH, DEP(longest) | — | ✅ |
| 12 | CNT, PATH, DEP, INFO(gates driven by g0) | — | ✅ |
| 13 | CNT, PATH, DEP(critical), INFO | — | ✅ |
| 14 | CNT, PATH, DEP, INFO(successors of g0) | — | ✅ |
| 15 | CNT, PATH, DEP, INFO, **CONE**(fanin+fanout) | CONE | 🟡 |
| 16 | + DEP(critical), CONE | CONE | 🟡 |
| 17 | + CONE, **EQV** | CONE, EQV | 🟡 |
| 18 | + CONE, EQV×3 | CONE, EQV | 🟡 |
| 19 | + CONE, EQV×3 | CONE, EQV | 🟡 |
| 20 | + CONE, EQV×3, CNT(total) | CONE, EQV | 🟡 |
| 21 | CNT, **T1**(fanout≤4), **CEC**, WRITE | **T1, CEC** | 🔴 |
| 22 | + **T2**(reduce critical path) | T1, T2, CEC | 🔴 |
| 23 | + **T3**(trim unused) | T1, T2, T3, CEC | 🔴 |
| 24 | CNT, **T1**, **T2**(min depth), **T3**(dangling), **T10**(rename g0), CEC | T1,T2,T3,T10,CEC | 🔴 |
| 25 | CNT, **T2**, **T3**, **T10**(gate+wire), **T5**(OR→NAND/NOT in cone), CEC | T2,T3,T10,T5,CEC | 🔴 |
| 26 | CNT, **T1**, **T2**(+target depth 4), **T3**, **T4**(NOR/NOT), **T6**, CEC | T1,T2,T3,T4,T6,CEC | 🔴 |
| 27 | CNT, **T1**, **T2**(≤4, per-output), **T3**, **T5**(XOR→AND/OR/NOT), **T6**, CEC | T1,T2,T3,T5,T6,CEC | 🔴 |
| 28 | CNT, **T1**, **T2**, **T3**(sweep), **T4**(AND/NOT), **T6**, CEC | T1,T2,T3,T4,T6,CEC | 🔴 |
| 29 | CNT, **T1**, **T2**, **T3**, **T4**(AND/NOT), **T6**, **T7**(func-equiv merge), CEC | T1–T4,T6,T7,CEC | 🔴 |
| 30 | CNT, **T1**, **T2**, **T3**(floating), **T4**, **T6**, **T7**, CEC | T1–T4,T6,T7,CEC | 🔴 |
| 31 | CNT, INFO(fanout), **T6**, **CEC**(prove equiv), **T10**(rename sig), **T1**(BUF n2), DFFQ(depth→D), CONST0, SHARE, BEQ, EQV, MISC(depth>4) | T6,T10,T1,CEC + 🟡 mix | 🔴+🟡 |
| 32 | CNT, **T5/T8**(NAND·1→INV), **T8**(const-prop), **T3**(dangling), **T10**(rename wire), **CEC**, PATH, DFFQ(g0 on max path), R2R, MISC, PIPO | T5,T8,T3,T10,CEC + 🟡 | 🔴+🟡 |
| 33 | CNT, **T5**(XNOR→NOR), **T3**, **T4**(cone→NAND/NOT), **T2**(depth4), **T7**(dup merge), **CEC**, CUT, PIPO, PATH, MISC, EQV | T5,T3,T4,T2,T7,CEC + 🟡 | 🔴+🟡 |
| 34 | CNT, **T1**(clock+reset+general), **T5**(XNOR→NOR/NOT), **T4**(AND/NOT), **CEC**, INFO(fanout), PATH(avoid), BEQ, MISC(deepest cone), DFFQ | T1,T5,T4,CEC + 🟡 | 🔴+🟡 |
| 35 | CNT, **T5**(XNOR→NOR, XOR→4NAND), **T6**, **T10**(rename sig), **CEC**, PATH, INFO, MISC, EQV, BEQ, DFFQ | T5,T6,T10,CEC + 🟡 | 🔴+🟡 |
| 36 | CNT, **T1**(general+reset buffers), **T8**(AND·0 prop), **T11**(reconnect pin A of g0), CEC, INFO(fanout/driven), CUT, DFFQ, SYM, MISC | T1,T8,T11,CEC + 🟡 | 🔴+🟡 |
| 37 | CNT, **T4**(cone→NAND/NOT, cone→NOR/NOT), **T3**(prune), CEC, R2R, PIPO, BEQ, SYM, MISC(tied-to-1, floating), INFO | T4,T3,CEC + 🟡 | 🔴+🟡 |
| 38 | CNT, **T1**(reset buffers), **T6**, **T9**(redundant), **T8**(NAND const-prop), **T10**(rename sig), CEC, ART, PIPO(path len0), MISC | T1,T6,T9,T8,T10,CEC + 🟡 | 🔴+🟡 |
| 39 | CNT, **T8**(OR·1, NOR const prop), **T6**, **T1**(BUF n2), **T5**(XOR→4NAND), PIPO, BEQ, MISC(depth>4, list XOR) | T8,T6,T1,T5 + 🟡 | 🔴+🟡 |
| 40 | CNT, **T1**(fanout≤4), **T4**(NAND/NOT remap), **T2**(cone≤4), **T5**(NAND·1→INV), **T6**, CEC, R2R, PIPO, MISC, DFFQ(enable/hold) | T1,T4,T2,T5,T6,CEC + 🟡 | 🔴+🟡 |

---

## What we can do already

- **Fully passable today (no new code): test01–test14.** These use only the 9 implemented tools
  (LOAD/WRITE/CNT/FIC/DEP/PATH/INFO/LST). Good regression baseline — lock these in with a test
  harness before refactoring.
- **test15–test20** are *pure analysis* gaps (`CONE`, `EQV`). Not our part, but they block the
  transformation testcases too, since many later prompts re-use cones/equivalence. Coordinate with
  the Analysis owner.

## What WE (Transformation & Optimization) must build

Every testcase from **test21 onward needs at least one 🔴 transform tool**, and all of them need
**`CEC`** (post-transform equivalence proof — `cec` for combinational, `dsec` for the DFF designs).
Priority order by how many testcases each unlocks:

1. **`CEC` (equivalence verify)** — required by *every* transform testcase; build first, it's also a
   standalone deliverable ("prove the transformed design is equivalent").
2. **`T1` buffer/fanout ≤4** — test21,22,23,24,26,27,28,29,30,31,34,36,38,39,40 (widest reuse).
3. **`T3` sweep/dangling** + **`T2` depth-opt** — the core ABC `sweep; cleanup` / `balance; resyn2; if -K 4` flow.
4. **`T5` decompose/convert** + **`T6` inverter-collapse** + **`T4` remap-basis** — gate-rewrite family.
5. **`T8` constant-prop**, **`T7` merge-equiv**, **`T9` redundancy** — ABC `sweep`/`fraig`/`dch`.
6. **`T10` rename**, **`T11` pin-reconnect** — pure in-house graph edits, no ABC; quick wins.

See partC.md for the exact ABC scripts / custom-pass plan behind each T-code.
