# Demo: test28 — Whole-Netlist Reconstruction to AND+NOT

A worked example of the Transformation & Optimization pipeline on **test28**, the functions it
uses, the **full prompt → response transcript**, and a deep dive + verification of
**`reconstruct_netlist_to_basis`**.

test28 is the flagship demo: a **15,581-gate** sequential design is buffered, depth-optimized,
and **reconstructed into only AND and NOT gates** — all verified functionally equivalent.

---

## 1. Input prompts and responses

The grader feeds one request per line; each is handled by the LLM agent calling engine tools.
Below is each **prompt** with the agent's **response** (from the actual run).

> **#1 — Init:** `This is the beginning of a new testcase. The case name is test28.`
> **Response:** Acknowledged. Initialized testcase "test28". Design state is empty and ready.

> **#2 — Prompt:** `Please load the design from the file test28.v located in the directory testcase/test28/.`
> **Response:** Loaded. The design has **40 primary inputs, 50 primary outputs, and 15,581 gates**.

> **#3 — Prompt:** `Please count all the gates ... broken down by gate type (AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF).`
> **Response:** NOT 1064, AND 0, OR 970, XOR 110, NOR 4373, NAND 4782, XNOR 3422, BUF 23, **DFF 837**.

> **#4 — Prompt:** `Insert buffers wherever needed so that no gate drives more than 4 loads. Make sure nothing changes functionally.`
> **Response:** **Inserted 1,849 buffers** so no gate drives more than 4 loads. Verified functionally equivalent.

> **#5 — Prompt:** `Optimize the logic depth of the design. Make sure nothing changes functionally.`
> **Response:** Restructured the combinational logic for depth via ABC (balance/resyn2) and
> re-applied the max-fanout-4 limit (2,405 buffers). Verified functionally equivalent.

> **#6 — Prompt:** `Sweep out dangling gates. Make sure nothing changes functionally.`
> **Response:** **Removed 0 dangling gates** — none were left (the depth-optimization step already
> dropped logic that does not feed an output).

> **#7 — Prompt:** `Reconstruct the entire netlist using only AND and NOT gates while preserving functional equivalence.`
> **Response:** **Reconstructed the netlist: converted 11,569 gates to AND+NOT logic.** Verified functionally equivalent.

> **#8 — Prompt:** `Try to optimize n9 to at most 4 levels deep. Make sure nothing changes functionally.`
> **Response:** The cone of n9 has logic depth 0 (n9 is a registered output), already within the
> target of 4 — already optimal, reporting original.

> **#9 — Prompt:** `Find all back-to-back inverter pairs and collapse them into a wire. Ensure functional equivalence is preserved.`
> **Response:** **Collapsed 3,435 redundant inverters** from back-to-back pairs. Verified functionally equivalent.

> **#10 — Prompt:** `Please write the current design to the output file test28_out.v.`
> **Response:** Design written to `testcase/test28/test28_out.v`.

Equivalence is verified after each transform with `check_equivalence`:
**`EQUIVALENT: the current design is functionally equivalent to the reference netlist (ABC cec on a flop-cut combinational model).`**

---

## 2. The headline: gate-type histogram before vs. after

| Gate | Before (#3) | After reconstruct + collapse |
|------|------------:|-----------------------------:|
| NOT  | 1,064 | **19,671** |
| AND  | 0 | **18,167** |
| OR   | 970 | **0** |
| XOR  | 110 | **0** |
| NOR  | 4,373 | **0** |
| NAND | 4,782 | **0** |
| XNOR | 3,422 | **0** |
| BUF  | 23 | 0 in-memory → re-added for fanout on write |
| DFF  | 837 | 837 (unchanged) |

The entire combinational logic is now **AND + NOT only**, and still cec-EQUIVALENT to the original.
(The written `test28_out.v` re-adds BUF gates *only for the fanout limit* — buffers are exempt from
the logic basis; see the policy note in `OPEN_QUESTIONS.md` D2.)

---

## 3. Methodology

```
 load ──▶ count ──▶ insert_buffers ──▶ reduce_depth ──▶ sweep ──▶ reconstruct(AND+NOT) ──▶ collapse ──▶ check ──▶ write
                                          each transform mutates the netlist and chains the active
                                          design forward; equivalence is proven against the original
```

- **Session-state chaining** — each transform writes to a fresh session file and re-points the
  active design; the original is kept for equivalence checking.
- **Two engines, one model** — Python orchestrates and calls **ABC** for depth optimization and
  equivalence; the C++ parser owns the graph and the structural passes (basis reconstruction,
  inverter collapse).
- **Formal verification every transform** — `check_equivalence` exports current + original to a
  **flop-cut combinational BLIF** (DFF Q → PI, D → output `__D_<inst>`) and runs `abc cec`.

---

## 4. Functions used

| Step | Tool | Parser action | Role |
|------|------|---------------|------|
| load | `load_design` | `load` | parse Verilog → graph |
| count | `count_gates` | `count_gates` | gate tally by type |
| buffers | `insert_buffers(4)` | `insert_buffers` | balanced BUF tree, fanout ≤ 4 |
| depth | `reduce_depth` | `write_blif`→ABC→`rebuild` | flop-cut → ABC `balance;resyn2` → rebuild w/ DFFs reattached |
| sweep | `remove_dangling` | `sweep` | delete logic not feeding an output/flop (here: 0, ABC already did it) |
| **basis** | **`reconstruct_netlist_to_basis`** | **`remap_all`** | **rewrite every gate to AND+NOT** |
| depth-target | `restructure_to_depth` | `calc_depth` | best-effort depth report for n9 |
| collapse | `collapse_inverters` | `collapse_inv` | remove back-to-back `NOT(NOT x)=x` |
| verify | `check_equivalence` | `write_blif` + ABC `cec` | prove current ≡ original |
| write | `write_design` | `write` | emit `test28_out.v` (re-enforces fanout) |

---

## 5. Deep dive: `reconstruct_netlist_to_basis` (`Graph::remap_cone_to_basis`, whole-netlist mode)

**Goal:** rewrite every combinational gate so the design uses **only AND and NOT** (or NOR+NOT),
preserving function. Flip-flops are left untouched.

**How:** each gate is replaced in place by an equivalent built from the target basis, using
**Boolean identities**, with **shared inverters** (one `NOT` per net, reused) to limit blow-up.

For the **AND+NOT** basis:

| Original | AND+NOT equivalent |
|----------|--------------------|
| `AND`, `NOT` | kept as-is |
| `NAND(a,b)` | `NOT(AND(a,b))` |
| `NOR(a,b)`  | `AND(!a,!b)` |
| `OR(a,b)`   | `NOT(AND(!a,!b))` |
| `BUF(a)`    | `NOT(!a)` |
| `XOR(a,b)`  | `NOT(AND( !(a·!b), !(!a·b) ))` |
| `XNOR(a,b)` | `AND( !(a·!b), !(!a·b) )` |

```cpp
int Graph::remap_cone_to_basis(const std::string& root, const std::string& basis) {
    bool nor_b = (basis=="nor_not"), and_b = (basis=="and_not");
    if (!nor_b && !and_b) return -1;

    std::vector<Node*> scope;                      // whole netlist when root is empty
    if (root.empty()) { for (Node* n : all_nodes)
        if (n->type==NodeType::GATE && n->gate_type!=GateType::DFF) scope.push_back(n); }
    else { auto c = fanin_cone_gates(root); scope.assign(c.begin(), c.end()); }

    std::vector<Node*> targets;                    // skip gates already in the basis
    for (Node* g : scope) { GateType t=g->gate_type;
        bool kept = (t==GateType::NOT)||(nor_b&&t==GateType::NOR)||(and_b&&t==GateType::AND);
        if (!kept && t!=GateType::DFF && t!=GateType::UNKNOWN) targets.push_back(g); }

    /* helpers: fresh() unique names, inv(x) shared inverter, mk2(type,a,b) new 2-input gate */
    for (Node* g : targets) {                      // rewrite each gate in place
        Node* a=g->inputs[0], *b=(g->inputs.size()>1?g->inputs[1]:nullptr);
        /* detach g from a,b; rebuild as the basis equivalent above; reuse g as the output gate */
    }
    return (int)targets.size();
}
```

### Why this design

- **In-place reuse** — the original gate node is reused as the final output gate (e.g. an `OR`
  becomes the `NOT` of a new `AND`), so the output net name and its consumers are untouched.
- **Shared inverters** — `inv(x)` caches one `NOT` per source net, so converting many gates that
  need `!a` adds a single inverter for `a`, not one per use.
- **Flip-flops untouched** — the flop boundary is preserved, so the flop-cut `cec` stays valid.
- **Back-to-back inverters are expected** — the identities (`BUF=NOT(!a)`, etc.) create `NOT(NOT)`
  pairs on purpose; the subsequent `collapse_inverters` removed **3,435** of them here.

---

## 6. Check: verification of `reconstruct_netlist_to_basis`

| # | Scenario | Expected | Result |
|---|----------|----------|--------|
| A | Reconstruct ORIGINAL test28 to AND+NOT (has OR/XOR/NOR/NAND/XNOR/BUF) | only AND/NOT/DFF remain, equivalent | **converted 13,680 gates → NOT 23,972 / AND 20,721 / DFF 837, cec EQUIVALENT** ✓ |
| B | In-pipeline (post-ABC) reconstruct | only AND/NOT remain, equivalent | **converted 11,569 → AND/NOT only, cec EQUIVALENT** ✓ |
| C | Every non-basis gate type eliminated | OR=XOR=NOR=NAND=XNOR = 0 | **all 0** ✓ |
| D | Flip-flop count unchanged | 837 → 837 | **837** ✓ |

Scenario A is the strongest check: the *original* netlist contains all six convertible gate types,
and every one is eliminated while ABC `cec` confirms equivalence — exercising all seven identities.

---

## 7. Summary

- test28 runs the full pipeline on a 15.5k-gate sequential design and reconstructs the **entire
  combinational netlist into AND + NOT only** — verified **EQUIVALENT** at every step.
- **`reconstruct_netlist_to_basis`** rewrites each gate via Boolean identities (AND+NOT or NOR+NOT)
  with shared inverters, in place, leaving flip-flops untouched so the flop-cut `cec` stays valid.
  It is verified to eliminate every non-basis gate type and preserve function.
- **Note on `remove_dangling`:** in this pipeline it reports **0** because `reduce_depth` already
  routes the design through ABC, which drops unobserved logic — so the explicit sweep is redundant
  once depth optimization has run. The transforms that do the real, visible work here are
  `reduce_depth`, `reconstruct_netlist_to_basis` (11,569 gates), and `collapse_inverters` (3,435).
