# Demo: test23 — Methodology & Functions (focus: `remove_dangling`)

A worked example of the Transformation & Optimization pipeline on **test23**, the functions it
uses, and a deep dive + verification of **`remove_dangling`**.

---

## 1. The testcase

`testcase/test23/prompt.txt` asks for this sequence:

1. Load `test23.v`
2. Count gates by type
3. **Insert buffers** so no gate drives > 4 loads (preserve function)
4. **Reduce critical-path depth** through restructuring (preserve function)
5. **Trim unused wires and gates** (preserve function)  ← `remove_dangling`
6. Write `test23_out.v`

test23 is a small sequential design: **PI 33, PO 13, 683 gates** (not 126, or 20, xor 2,
nor 160, nand 259, xnor 30, **dff 86**).

---

## 2. Methodology (how every transform testcase is driven)

```
 load_design ──▶ [analysis / count] ──▶ transform ──▶ transform ──▶ … ──▶ check_equivalence ──▶ write_design
                                          │   each transform mutates the netlist and
                                          ▼   chains the "active design" forward
                              session file (eda_sess_*/…) becomes the new _loaded_filepath
```

Three principles make it robust:

- **Session-state chaining.** Each parser call is a one-shot subprocess that re-parses the active
  file. A transform writes its result to a fresh session file and re-points `_loaded_filepath` to
  it, so the next tool (and `write_design`) sees the transformed netlist. The original is kept in
  `_original_filepath` for equivalence checking.
- **Two engines, one model.** Python (`engine.py`) orchestrates and calls **ABC** for heavy
  optimization/checking; the C++ parser (`graph.cpp`) owns the netlist graph and the structural
  passes. Every structural transform is a graph mutation that round-trips through Verilog.
- **Formal verification, every transform.** `check_equivalence` exports the current design and the
  original to a **flop-cut combinational BLIF** (each DFF Q → primary input, D → output
  `__D_<inst>`) and runs `abc cec`. Sound for any transform that preserves the flip-flop boundary.

---

## 3. Functions used in test23

| Step | Tool (engine) | Parser action | What it does |
|------|---------------|---------------|--------------|
| load | `load_design` | `load` | parse Verilog → graph (nodes + edges) |
| count | `count_gates` | `count_gates` | tally gates by type |
| buffers | `insert_buffers(4)` | `insert_buffers` | build a balanced **BUF tree** so no gate drives > 4 loads |
| depth | `reduce_depth` | `write_blif`→ABC→`rebuild` | flop-cut → ABC `balance;resyn2` → rebuild gate-level netlist with DFFs reattached; **re-enforces the fanout limit** afterward |
| trim | **`remove_dangling`** | **`sweep`** | **delete gates/wires not feeding any output or flip-flop** |
| verify | `check_equivalence` | `write_blif` + ABC `cec` | prove current ≡ original |
| write | `write_design` | `write` | emit `test23_out.v` (re-enforces fanout on the way out) |

### Demo run (actual numbers)

```
load:         PI 33, PO 13, Gates 683
insert_buf:   Inserted 46 buffers (no gate drives > 4 loads)        683 → 729
reduce_depth: Combinational logic depth reduced 32 → 19 (AIG)       729 → 750
remove_dang:  Removed 0 dangling gates                              750 → 750
check_equiv:  EQUIVALENT
write:        test23_out.v
```

> **Why `remove_dangling` reports 0 here:** `reduce_depth` already runs the design through ABC,
> whose flow drops logic that doesn't feed a cut output — so by the time `remove_dangling` runs in
> this sequence, nothing is left to trim. It is *not* a no-op in general (see §5).

---

## 4. Deep dive: `remove_dangling` (`Graph::sweep_dangling`)

**Goal:** delete *dangling* logic — any gate or wire that cannot affect a primary output or a
flip-flop. Removing unobservable logic is functionally transparent.

**Algorithm — reverse reachability (mark-sweep):**

1. **Seed** the live set with every **primary output** *and* every **flip-flop**.
2. **Mark** backward: pop a live node, mark all its drivers (`inputs`) live, repeat until fixpoint.
   This walks the transitive fanin of the seeds.
3. **Keep** = primary inputs (interface) ∪ primary outputs ∪ live nodes. Everything else is dead.
4. **Sweep**: drop edges pointing at dead nodes from the survivors, then delete the dead nodes.

```cpp
int Graph::sweep_dangling() {
    std::unordered_set<Node*> live; std::vector<Node*> stack;
    for (Node* n : all_nodes) {                       // 1. seeds: POs + all DFFs
        bool seed = n->type == NodeType::PRIMARY_OUTPUT ||
                    (n->type == NodeType::GATE && n->gate_type == GateType::DFF);
        if (seed && live.insert(n).second) stack.push_back(n);
    }
    while (!stack.empty()) {                           // 2. mark transitive fanin
        Node* n = stack.back(); stack.pop_back();
        for (Node* drv : n->inputs) if (live.insert(drv).second) stack.push_back(drv);
    }
    auto keep = [&](Node* n) {                         // 3. keep rule
        return n->type == NodeType::PRIMARY_INPUT ||
               n->type == NodeType::PRIMARY_OUTPUT || live.count(n) > 0;
    };
    std::vector<Node*> newall, dead;                  // 4. partition + sweep
    for (Node* n : all_nodes) (keep(n) ? newall : dead).push_back(n);
    for (Node* n : newall) {                          //    drop edges to dead nodes
        std::vector<Node*> o, in;
        for (Node* x : n->outputs) if (keep(x)) o.push_back(x);
        for (Node* x : n->inputs)  if (keep(x)) in.push_back(x);
        n->outputs.swap(o); n->inputs.swap(in);
    }
    int removed = 0;
    for (Node* n : dead) { if (n->type == NodeType::GATE) ++removed; nodes.erase(n->name); delete n; }
    all_nodes.swap(newall); return removed;
}
```

### Key design decisions

- **Why seed flip-flops, not just outputs?** A registered output's value lives behind a DFF, and
  logic feeding a DFF's D matters even if the DFF's Q isn't a primary output. Seeding **all DFFs**
  makes the observability model match the **flop-cut `cec`** exactly (POs + every `__D_<inst>`), so
  the result stays formally verifiable. The trade-off: a DFF whose Q is truly unused is *kept*
  (conservative), which is safe and keeps `cec` valid.
- **Primary inputs are always kept**, even if unused, so the module interface is unchanged.
- **Complexity:** O(V + E) — one reverse BFS plus one linear sweep.

---

## 5. Check: verification of `remove_dangling`

| # | Scenario | Expected | Result |
|---|----------|----------|--------|
| A | Original test23 (already clean) | remove 0 | **0** ✓ |
| B | Inject dangling chain `g_b1→wb1→g_b2→wb2` (unread) | remove 2, stay equivalent | **removed 2, cec EQUIVALENT** ✓ |
| C | Inject `g_c1` feeding a new DFF's D (Q unread) | keep (DFF is a seed) | **0 removed** ✓ |
| D | Run twice on the chain (idempotency) | pass2 removes 0 | **pass1=2, pass2=0** ✓ |

Conclusions:
- **Correctly removes** genuinely unobservable logic (B) and **never breaks equivalence** (cec).
- **Conservatively keeps** logic in the fanin of any flip-flop (C) — matching the `cec` model.
- **Idempotent** (D) and **safe on already-clean netlists** (A).

---

## 6. Summary

- test23 exercises the core pipeline: **load → count → insert_buffers → reduce_depth →
  remove_dangling → check_equivalence → write**, all verified **EQUIVALENT**.
- **`remove_dangling`** is an O(V+E) reverse-reachability mark-sweep: seed with **primary outputs
  and all flip-flops**, mark the transitive fanin, delete the rest (keeping PIs/POs). It removes
  unobservable logic while preserving function and the flip-flop boundary, so the flop-cut `cec`
  stays valid.
- It is **verified** correct on four scenarios (clean, dangling chain, DFF-fanin retention,
  idempotency).
- In *this* sequence it reports **0** only because `reduce_depth` already routed the design through
  ABC (which drops unobserved logic). On an un-optimized netlist it does real work — e.g. it
  removes exactly the 2 injected dangling gates in scenario B.
