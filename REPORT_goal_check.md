# Transform-Goal Verification Report

_ICCAD 2026 · Problem A — generated from `goal_check.py` + `eval_harness.py`._

Equivalence (ABC `cec`) proves a transform did not **break** the netlist; it cannot prove the transform did its **job** — a no-op passes `cec` perfectly. Every instruction below is scored on both axes: **equivalent** *and* **goal achieved** (an independent structural oracle, not the tool under test).

## Summary

| Metric | Value |
|---|---|
| Combined pass (equiv **and** goal) | **26 / 38** |
| Goals achieved (scored predicates) | 51 / 68 |
| Proven equivalent (ABC `cec`) | 38 / 38 |
| **Equivalent but goal unmet** | **12** |

Legend: ✅ goal achieved · ❌ goal not achieved in output · 🔹 advisory (not scored)

## Cases equivalent but goal-unmet

These outputs are formally equivalent yet miss at least one transform goal — the gap pure equivalence checking cannot see.

| Case | Equiv | Goals | Unmet goals |
|---|---|---|---|
| test24 | EQUIV | 2/3 | `rename` rename incomplete: g0 absent, renamed_gate MISSING |
| test25 | EQUIV | 1/3 | `rename` rename incomplete: g0 absent, renamed_gate MISSING; `rename` rename incomplete: n74 absent, renamed_wire MISSING |
| test26 | EQUIV | 3/5 | `depth-node` depth(n10) = 35 (target <= 4, logic-level def); `inverter-collapse` 657 back-to-back NOT->NOT pair(s) remain |
| test27 | EQUIV | 4/5 | `depth-outputs` 132 output(s) exceed depth 4 (worst 14) |
| test29 | EQUIV | 3/4 | `depth-node` depth(n8) = 141 (target <= 4, logic-level def) |
| test30 | EQUIV | 4/5 | `inverter-collapse` 193 back-to-back NOT->NOT pair(s) remain |
| test34 | EQUIV | 2/5 | `dedicated-buf` 0 dedicated BUF(s) on n2 (expect 1 = its loads); 1 load(s) still driven directly; `fanout` max fanout 47 (limit 4); `basis-netlist` netlist: 22066 gate(s) outside ['and', 'not']: {'nor': 4869, 'nand': 16982, 'or': 178, 'xor': 37} |
| test35 | EQUIV | 2/4 | `inverter-collapse` 3 back-to-back NOT->NOT pair(s) remain; `type-replace` XOR remaining 138; NAND added 0 (expect 4x138=552) |
| test36 | EQUIV | 2/3 | `signal-fanout` fanout(n1) = 690 (limit 4, incl. flop control pins) |
| test37 | EQUIV | 1/2 | `basis-cone` cone(n9): 7 gate(s) outside ['nor', 'not']: {'nand': 7} |
| test38 | EQUIV | 4/5 | `redundant` 126 redundant gate(s) share (type,inputs) with another |
| test40 | EQUIV | 3/4 | `inverter-collapse` 9118 back-to-back NOT->NOT pair(s) remain |

## Per-case detail

<details><summary>`test24` — GOAL-FAIL · equiv EQUIV · goals 2/3</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate in the design drives more than 4 loads. Ensure functional equivalence is preserved. |
| 🔹 | `depth-global` | max logic depth 22 -> 23 (advisory: not scored) | Optimize the logic to minimize maximum path depth while preserving functionality. Ensure functional equivalence is preserved. |
| ✅ | `dangling` | no dangling gates (all reach a PO/flop) | Remove all dangling gates that do not contribute to any primary output. Ensure functional equivalence is preserved. |
| ❌ | `rename` | rename incomplete: g0 absent, renamed_gate MISSING | Rename gate g0 to renamed_gate. Ensure functional equivalence is preserved. |

</details>

<details><summary>`test25` — GOAL-FAIL · equiv EQUIV · goals 1/3</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ❌ | `rename` | rename incomplete: g0 absent, renamed_gate MISSING | Change the identifier of gate g0 to renamed_gate and update all references. Ensure the design functionality does not change. |
| ❌ | `rename` | rename incomplete: n74 absent, renamed_wire MISSING | Change the identifier of wire n74 to renamed_wire and update all references. Ensure the design functionality does not change. |
| ✅ | `decompose-cone` | no OR gates in cone(n11[0]) (234 gates) | Replace all 2-input OR gates in the cone of n11[0] with equivalent logic built only from NAND and NOT gates. Ensure the design functionality does not change. |

</details>

<details><summary>`test26` — GOAL-FAIL · equiv EQUIV · goals 3/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Perform fanout optimization across the netlist with maximum fanout 4. Ensure functional equivalence is preserved. |
| 🔹 | `depth-global` | max logic depth 40 -> 39 (advisory: not scored) | Reduce critical path depth through logic restructuring. Ensure functional equivalence is preserved. |
| ✅ | `dangling` | no dangling gates (all reach a PO/flop) | Remove all dangling gates and nets not connected to any primary output. Make sure nothing changes functionally. |
| ✅ | `basis-cone` | cone(n10): all 517 gates in ['nor', 'not'] | Convert the logic cone of n10 to use only NOR and NOT gates while preserving functional equivalence. |
| ❌ | `depth-node` | depth(n10) = 35 (target <= 4, logic-level def) | Try to restructure n10 with a target depth of 4, preserving functionality. Report original if already optimal. |
| ❌ | `inverter-collapse` | 657 back-to-back NOT->NOT pair(s) remain | Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved. |

</details>

<details><summary>`test27` — GOAL-FAIL · equiv EQUIV · goals 4/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| 🔹 | `depth-global` | max logic depth 25 -> 26 (advisory: not scored) | Optimize the logic to minimize maximum path depth. Make sure nothing changes functionally. |
| ✅ | `decompose-cone` | no XOR gates in cone(n15) (6 gates) | Decompose all XOR gates in the fanin cone of n15 into AND, OR, and NOT gates without changing functionality. |
| ✅ | `depth-node` | depth(n15) = 3 (target <= 4, logic-level def) | Try to optimize n15 to at most 4 levels deep. Make sure nothing changes functionally. |
| ✅ | `inverter-collapse` | no NOT->NOT adjacency | Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved. |
| ❌ | `depth-outputs` | 132 output(s) exceed depth 4 (worst 14) | For each output with depth greater than 4, optimize its cone to meet the depth constraint. Ensure the design functionality does not change. |

</details>

<details><summary>`test29` — GOAL-FAIL · equiv EQUIV · goals 3/4</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| 🔹 | `depth-global` | max logic depth 177 -> 147 (advisory: not scored) | Reduce the critical path depth through restructuring. Make sure nothing changes functionally. |
| ✅ | `basis-netlist` | netlist: all 4035 gates in ['and', 'not'] | Reconstruct the entire netlist using only AND and NOT gates while preserving functional equivalence. |
| ❌ | `depth-node` | depth(n8) = 141 (target <= 4, logic-level def) | Try to optimize n8 to at most 4 levels deep. Make sure nothing changes functionally. |
| ✅ | `inverter-collapse` | no NOT->NOT adjacency | Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved. |

</details>

<details><summary>`test30` — GOAL-FAIL · equiv EQUIV · goals 4/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| 🔹 | `depth-global` | max logic depth 17 -> 13 (advisory: not scored) | Reduce the critical path depth through restructuring. Make sure nothing changes functionally. |
| ✅ | `dangling` | no dangling gates (all reach a PO/flop) | Remove floating nodes that do not affect outputs. Make sure nothing changes functionally. |
| ✅ | `basis-netlist` | netlist: all 1706 gates in ['and', 'not'] | Reconstruct the entire netlist using only AND and NOT gates while preserving functional equivalence. |
| ✅ | `depth-node` | depth(n8) = 3 (target <= 4, logic-level def) | Try to optimize n8 to at most 4 levels deep. Make sure nothing changes functionally. |
| ❌ | `inverter-collapse` | 193 back-to-back NOT->NOT pair(s) remain | Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved. |

</details>

<details><summary>`test34` — GOAL-FAIL · equiv EQUIV · goals 2/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `signal-fanout` | fanout(n0) = 4 (limit 4, incl. flop control pins) | Try to insert buffers on the clock signal n0 to reduce its fanout so no single driver has more than 4 loads. Ensure the design functionality does not change. |
| ✅ | `type-replace` | XNOR remaining 0 | Rewrite all XNOR gates using only NOR and NOT gates. Ensure the design functionality does not change. |
| ❌ | `dedicated-buf` | 0 dedicated BUF(s) on n2 (expect 1 = its loads); 1 load(s) still driven directly | Please insert a BUF gate on signal n2 so that each load of n2 is driven through a dedicated buffer. Ensure the design functionality does not change. |
| ❌ | `fanout` | max fanout 47 (limit 4) | Perform fanout optimization across the netlist with maximum fanout 4. Ensure functional equivalence is preserved. |
| ❌ | `basis-netlist` | netlist: 22066 gate(s) outside ['and', 'not']: {'nor': 4869, 'nand': 16982, 'or': 178, 'xor': 37} | Reconstruct the entire netlist using only AND and NOT gates while preserving functional equivalence. Ensure the design functionality does not change. |

</details>

<details><summary>`test35` — GOAL-FAIL · equiv EQUIV · goals 2/4</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `type-replace` | XNOR remaining 0 | Try to replace all XNOR gates in this design with equivalent NOR-only implementations. Ensure the design functionality does not change. |
| ✅ | `rename` | n7431 -> renamed_wire (old absent, new present) | Update the name of signal n7431 to renamed_wire throughout the netlist. Ensure the design functionality does not change. |
| ❌ | `inverter-collapse` | 3 back-to-back NOT->NOT pair(s) remain | Find all pairs of back-to-back inverters (NOT followed by NOT) in this design and collapse them into direct wire connections. Ensure the design functionality does not change. |
| ❌ | `type-replace` | XOR remaining 138; NAND added 0 (expect 4x138=552) | Try to replace all XOR gates in this design with equivalent NAND-only implementations. Each 2-input XOR can be realized with 4 NAND gates. Ensure the design functionality does not change. |

</details>

<details><summary>`test36` — GOAL-FAIL · equiv EQUIV · goals 2/3</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| ✅ | `const-prop` | no AND gate retains a constant-0 input | Simplify the reported AND gates by propagating their constant 0 input. Ensure the design functionality does not change. |
| ❌ | `signal-fanout` | fanout(n1) = 690 (limit 4, incl. flop control pins) | Try to insert buffers on the reset signal n1 to reduce its fanout to at most 4 loads per driver. Ensure the design functionality does not change. |

</details>

<details><summary>`test37` — GOAL-FAIL · equiv EQUIV · goals 1/2</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `basis-cone` | cone(n8): all 6 gates in ['nand', 'not'] | Try to restructure the logic cone of output n8 using only NAND and NOT gates while preserving functional equivalence. Ensure the design functionality does not change. |
| ❌ | `basis-cone` | cone(n9): 7 gate(s) outside ['nor', 'not']: {'nand': 7} | Try to restructure the logic cone of output n9 using only NOR and NOT gates while preserving functional equivalence. Ensure the design functionality does not change. |

</details>

<details><summary>`test38` — GOAL-FAIL · equiv EQUIV · goals 4/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `signal-fanout` | fanout(n1) = 2 (limit 4, incl. flop control pins) | Try to insert buffers on the reset signal n1 to reduce its fanout to at most 4 loads per driver. Ensure the design functionality does not change. |
| ✅ | `inverter-collapse` | no NOT->NOT adjacency | Find all pairs of back-to-back inverters (NOT followed by NOT) in this design and collapse them into direct wire connections. Ensure the design functionality does not change. |
| ❌ | `redundant` | 126 redundant gate(s) share (type,inputs) with another | Are there any redundant gates in this design that can be removed without changing functionality? Remove them if found. Ensure the design functionality does not change. |
| ✅ | `rename` | n440 -> renamed_wire (old absent, new present) | Update the name of signal n440 to renamed_wire throughout the netlist. Ensure the design functionality does not change. |
| ✅ | `const-prop` | no NAND gate retains a constant input | Simplify the reported NAND gates by propagating their constant inputs. Ensure the design functionality does not change. |

</details>

<details><summary>`test40` — GOAL-FAIL · equiv EQUIV · goals 3/4</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate in the design drives more than 4 loads. Ensure functional equivalence is preserved. |
| ✅ | `depth-node` | depth(n14) = 1 (target <= 4, logic-level def) | Try to optimize the logic cone of output n14 targeting depth 4 or less. Ensure the design functionality does not change. Report original if already optimal. |
| ✅ | `const-prop` | no NAND gate retains a constant-1 input | Try to replace all 2-input NAND gates that have one input tied to constant 1 with inverters. Ensure the design functionality does not change. |
| ❌ | `inverter-collapse` | 9118 back-to-back NOT->NOT pair(s) remain | Find all pairs of back-to-back inverters (NOT followed by NOT) in this design and collapse them into direct wire connections. Ensure the design functionality does not change. |

</details>

<details><summary>`test21` — PASS · equiv EQUIV · goals 1/1</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |

</details>

<details><summary>`test22` — PASS · equiv EQUIV · goals 1/1</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| 🔹 | `depth-global` | max logic depth 39 -> 25 (advisory: not scored) | Reduce the critical path depth through restructuring. Make sure nothing changes functionally. |

</details>

<details><summary>`test23` — PASS · equiv EQUIV · goals 1/1</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| 🔹 | `depth-global` | max logic depth 32 -> 19 (advisory: not scored) | Reduce the critical path depth through restructuring. Make sure nothing changes functionally. |

</details>

<details><summary>`test28` — PASS · equiv EQUIV · goals 5/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `fanout` | max fanout 4 (limit 4) | Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally. |
| 🔹 | `depth-global` | max logic depth 64 -> 65 (advisory: not scored) | Optimize the logic depth of the design. Make sure nothing changes functionally. |
| ✅ | `dangling` | no dangling gates (all reach a PO/flop) | Sweep out dangling gates. Make sure nothing changes functionally. |
| ✅ | `basis-netlist` | netlist: all 40281 gates in ['and', 'not'] | Reconstruct the entire netlist using only AND and NOT gates while preserving functional equivalence. |
| ✅ | `depth-node` | depth(n9) = 0 (target <= 4, logic-level def) | Try to optimize n9 to at most 4 levels deep. Make sure nothing changes functionally. |
| ✅ | `inverter-collapse` | no NOT->NOT adjacency | Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved. |

</details>

<details><summary>`test31` — PASS · equiv EQUIV · goals 3/3</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `inverter-collapse` | no NOT->NOT adjacency | Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved. |
| ✅ | `rename` | n1289 -> renamed_sig (old absent, new present) | Try to rename internal signal n1289 to renamed_sig and update all references to it. Ensure the design functionality does not change. |
| ✅ | `dedicated-buf` | 2 dedicated BUF(s) on n2 (expect 2 = its loads) | Please insert a BUF gate on signal n2 so that each load of n2 is driven through a dedicated buffer. Ensure the design functionality does not change. |

</details>

<details><summary>`test32` — PASS · equiv EQUIV · goals 4/4</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `const-prop` | no NAND gate retains a constant-1 input | Try to replace all 2-input NAND gates that have one input tied to constant 1 with inverters. Ensure the design functionality does not change. |
| ✅ | `rename` | n1214 -> renamed_wire (old absent, new present) | Rename wire n1214 to renamed_wire. Ensure functional equivalence is preserved. |
| ✅ | `dangling` | no dangling gates (all reach a PO/flop) | Check if there are any dangling gates in this design that do not contribute to any primary output. Remove them if found. Ensure the design functionality does not change. |
| ✅ | `const-prop` | no NAND gate retains a constant input | Simplify the reported NAND gates by propagating their constant inputs. Ensure the design functionality does not change. |

</details>

<details><summary>`test39` — PASS · equiv EQUIV · goals 5/5</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| ✅ | `const-prop` | no OR gate retains a constant-1 input | Simplify the reported OR gates by propagating their constant 1 input. Ensure the design functionality does not change. |
| ✅ | `inverter-collapse` | no NOT->NOT adjacency | Find all pairs of back-to-back inverters (NOT followed by NOT) in this design and collapse them into direct wire connections. Ensure the design functionality does not change. |
| ✅ | `dedicated-buf` | 2 dedicated BUF(s) on n2 (expect 2 = its loads) | Please insert a BUF gate on signal n2 so that each load of n2 is driven through a dedicated buffer. Ensure the design functionality does not change. |
| ✅ | `const-prop` | no NOR gate retains a constant input | Simplify the reported NOR gates by propagating their constant inputs. Ensure the design functionality does not change. |
| ✅ | `type-replace` | XOR remaining 0; NAND added 340 (expect 4x85=340) | Convert every XOR gate in this design to an equivalent 4-NAND circuit. Ensure the design functionality does not change. |

</details>

<details><summary>`test33` — NO-OUTPUT · equiv NO-OUTPUT · goals 0/4</summary>

| | Goal | Result | Instruction |
|---|---|---|---|
| 🔹 | `type-replace` | no output netlist | Convert every XNOR gate in this design to an equivalent NOR-only circuit. Ensure the design functionality does not change. |
| 🔹 | `dangling` | no output netlist | Check if there are any dangling gates in this design that do not contribute to any primary output. Remove them if found. Ensure the design functionality does not change. |
| 🔹 | `basis-cone` | no output netlist | Try to restructure the logic cone of output n8 using only NAND and NOT gates while preserving functional equivalence. Ensure the design functionality does not change. |
| 🔹 | `depth-node` | no output netlist | Attempt to reduce the depth of the cone of n8 to 4. If no improvement is possible, report the cone is already optimized. |

</details>

## Analysis-only testcases

No transform goals (queries only); equivalence still checked: test01, test02, test03, test04, test05, test06, test07, test08, test09, test10, test11, test13, test14, test15, test16, test17, test18, test19, test20.
