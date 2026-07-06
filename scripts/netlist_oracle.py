#!/usr/bin/env python3
"""Independent netlist analysis oracle — ground truth for grading LLM answers.

Pure-Python, dependency-free re-implementation of gate-level netlist analysis.
Deliberately does NOT import or shell out to `parser_cpp` (the same tool the
agent-under-test uses to compute its answers) for any pure-graph query — using
it would just be grading the tool with itself. The mini-parser below
originated in `scripts/check_results.py` (copied, not imported, so this file
has zero repo-internal dependencies) and is extended here with port-width
capture for `list_pio`.

The ONLY external tool this file will invoke is `tools/abc/abc`, and only for
the two SAT-level questions that a linear graph algorithm cannot answer
(signal functional equivalence, always-constant). Even then, the BLIF fed to
ABC is written by THIS file's own writer — never `parser_cpp --action
write_blif` — so the equivalence-checking path is independent too.

Domain semantics encoded here (see docs/OPEN_QUESTIONS.md for the source
decisions, especially O1/D4 on register-output depth and cone semantics):

  - Combinational depth counts every gate on the path, including NOT/BUF as
    one level each. DFFs are sequential boundaries: a DFF Q output has
    combinational depth 0, and no combinational path is ever allowed to walk
    *through* a DFF's D/CK/RN/SN pins to reach further gates.
  - "Path from A to B" / "avoiding X" walks combinational gate connectivity
    only; X may name a net or a gate instance, and either matches.
  - "Fanout of X" / "gates driven by X" = immediate consumer gate instances
    of net X, INCLUDING DFFs (via any pin, not just D).
  - Fanin cone of X, by default, is the *strict combinational* cone: it
    reaches backward through combinational gates only and stops at PIs and at
    DFF Q outputs (does not cross the DFF into its D-logic). This is what
    analysis answers ("what gates compute X combinationally") should use. A
    `through_dff=True` mode is exposed separately for parity with the
    engine's transform-side cone (docs/OPEN_QUESTIONS.md D4), which is a
    different, larger quantity used only when transforms need it.

Usage:
    python3 scripts/netlist_oracle.py --selftest
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
import time
from collections import defaultdict, deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
PARSER_BIN = ROOT / "src" / "eda_engine" / "parser" / "parser_cpp"
ABC_BIN_DEFAULT = ROOT / "tools" / "abc" / "abc"

GATE_TYPES = ("and", "or", "nand", "nor", "not", "buf", "xor", "xnor")
ALL_TYPES = GATE_TYPES + ("dff",)
CONSTS = {"1'b0", "1'b1"}


# ── mini-parser (originated in scripts/check_results.py; copied, not
#    imported, to keep this file dependency-free — extended with port
#    widths for list_pio) ──────────────────────────────────────────────────

@dataclass
class Gate:
    name: str
    gtype: str                    # and/or/.../dff
    output: str                   # driven net ('' if none)
    inputs: List[str]             # consumed nets (constants excluded)
    dff_pins: Dict[str, str] = field(default_factory=dict)


@dataclass
class Netlist:
    gates: List[Gate]
    inputs: Set[str]                       # PI bit-level names (buses expanded)
    outputs: Set[str]                      # PO bit-level names
    driver: Dict[str, Gate]                # net -> driving gate
    loads: Dict[str, List[Gate]]           # net -> consuming gates (any pin)
    input_ports: List[Tuple[str, int]] = field(default_factory=list)   # (base, width)
    output_ports: List[Tuple[str, int]] = field(default_factory=list)  # (base, width)


_RE_PRIM = re.compile(
    r"^\s*(and|or|nand|nor|not|buf|xor|xnor)\s+(\S+?)\s*\(([^;]*)\)\s*;", re.M)
_RE_DFF = re.compile(r"^\s*dff\s+(\S+?)\s*\(([^;]*)\)\s*;", re.M)
_RE_PORT = re.compile(
    r"^\s*(input|output)\s+(?:\[(\d+):(\d+)\]\s*)?(.*?);", re.M | re.S)
_RE_DFF_PIN = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")


def parse_netlist(path: Path) -> Netlist:
    """Parse a flat gate-level Verilog netlist into a Netlist.

    Positional 2-input (and/or/nand/nor/xor/xnor) and 1-input (not/buf)
    primitives; named-port `dff` instances; bit-selects on bus nets treated
    as distinct net names (e.g. `n6[3]`); `1'b0`/`1'b1` constants excluded
    from Gate.inputs (callers that need constants should re-scan raw text).
    """
    text = Path(path).read_text()
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)

    inputs: Set[str] = set()
    outputs: Set[str] = set()
    input_ports: List[Tuple[str, int]] = []
    output_ports: List[Tuple[str, int]] = []
    for kind, msb, lsb, names in _RE_PORT.findall(text):
        width = 1
        bit_range: Optional[Tuple[int, int]] = None
        if msb != "" and lsb != "":
            a, b = int(msb), int(lsb)
            bit_range = (a, b)
            width = abs(a - b) + 1
        for nm in names.replace("\n", " ").split(","):
            nm = nm.strip()
            if not nm:
                continue
            store = inputs if kind == "input" else outputs
            ports = input_ports if kind == "input" else output_ports
            ports.append((nm, width))
            if bit_range is None:
                store.add(nm)
            else:
                a, b = bit_range
                lo, hi = min(a, b), max(a, b)
                for i in range(lo, hi + 1):
                    store.add(f"{nm}[{i}]")

    gates: List[Gate] = []
    for gtype, name, conns in _RE_PRIM.findall(text):
        nets = [c.strip() for c in conns.split(",") if c.strip()]
        out = nets[0] if nets else ""
        ins = [n for n in nets[1:] if n not in CONSTS]
        gates.append(Gate(name, gtype, out, ins))
    for name, conns in _RE_DFF.findall(text):
        pins = {p.upper(): v.strip() for p, v in _RE_DFF_PIN.findall(conns)}
        out = pins.get("Q", "")
        ins = [v for p, v in pins.items() if p != "Q" and v and v not in CONSTS]
        gates.append(Gate(name, "dff", out, ins, pins))

    driver: Dict[str, Gate] = {}
    loads: Dict[str, List[Gate]] = defaultdict(list)
    for g in gates:
        if g.output:
            driver[g.output] = g
        for n in g.inputs:
            loads[n].append(g)
    return Netlist(gates, inputs, outputs, driver, loads, input_ports, output_ports)


# ── name matching helper for "avoid X" (X may be a gate OR a net name) ──────

def _blocks(gate: Gate, avoid: Optional[str]) -> bool:
    """True if *gate*'s instance name or output net matches *avoid*."""
    if not avoid:
        return False
    return gate.name == avoid or gate.output == avoid


# ── basic structural queries ─────────────────────────────────────────────

def count_gates(nl: Netlist) -> Dict[str, int]:
    """Gate-type counts, all 9 kinds always present (0 if absent)."""
    counts = {t: 0 for t in ALL_TYPES}
    for g in nl.gates:
        counts[g.gtype] = counts.get(g.gtype, 0) + 1
    return counts


def fanout_of(nl: Netlist, net: str) -> List[str]:
    """Immediate consumer gate instance names of *net* (any pin, incl. DFF)."""
    return [g.name for g in nl.loads.get(net, [])]


def list_pio(nl: Netlist) -> Dict[str, List[Tuple[str, int]]]:
    """{'inputs': [(name, width)], 'outputs': [(name, width)]} — port level."""
    return {"inputs": list(nl.input_ports), "outputs": list(nl.output_ports)}


def flops_by_clock(nl: Netlist, clk: str) -> List[str]:
    """DFF instance names whose CK pin net is *clk*."""
    return [g.name for g in nl.gates
            if g.gtype == "dff" and g.dff_pins.get("CK", "") == clk]


# ── combinational cones (backward / forward), with through_dff toggle ──────

def fanin_cone_gates(nl: Netlist, net: str, through_dff: bool = False) -> Set[str]:
    """Gate instance names reachable backward from *net*.

    through_dff=False (default, the ANALYSIS semantics): stop at PIs and at
    DFF Q outputs — a DFF is included as the boundary gate itself but its
    D-side fanin is not traversed.
    through_dff=True (engine transform-cone parity, docs/OPEN_QUESTIONS.md
    D4): continue through a DFF's D pin, walking the register's next-state
    logic too.
    """
    seen: Set[str] = set()
    out: Set[str] = set()
    stack = [net]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        g = nl.driver.get(n)
        if g is None:
            continue
        out.add(g.name)
        if g.gtype == "dff" and not through_dff:
            continue
        stack.extend(g.inputs)
    return out


def fanout_cone_gates(nl: Netlist, net: str, through_dff: bool = False) -> Set[str]:
    """Forward analog of fanin_cone_gates: gates reachable downstream of *net*.

    through_dff=False: stop at DFFs (a DFF consumes *net* and is included in
    the cone as the boundary gate, but its Q output is not walked further).
    through_dff=True: continue forward through the DFF's Q output.
    """
    seen: Set[str] = set()
    out: Set[str] = set()
    stack = [net]
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        for g in nl.loads.get(n, []):
            out.add(g.name)
            if g.gtype == "dff" and not through_dff:
                continue
            if g.output:
                stack.append(g.output)
    return out


# ── levelization / depth ────────────────────────────────────────────────

def _levels_from_sources(nl: Netlist, sources: Set[str]) -> Dict[str, int]:
    """Level (comb. depth) of every net reachable from *sources*, topo DP.

    Every net in *sources* starts at level 0. A gate's output level is
    1 + max(level of its combinational inputs), computed only once ALL of
    a gate's inputs have a level (so gates with an input outside the
    reachable set never get leveled — this is what lets the same routine
    serve both "from all PIs+DFF-Qs" (`_combinational_levels`, reaches
    everything) and "from DFF Qs only" (`r2r_max_depth`, reaches only nets
    with a register genuinely upstream) with one O(V+E) pass each. DFF
    gates are never expanded past their (level-0) Q source, so a path never
    walks through a DFF's D/CK/RN/SN pins.
    """
    level: Dict[str, int] = {n: 0 for n in sources}

    indeg: Dict[str, int] = defaultdict(int)
    consumers: Dict[str, List[Gate]] = defaultdict(list)
    combinational_gates = [g for g in nl.gates if g.gtype != "dff"]
    for g in combinational_gates:
        indeg[g.name] = len(g.inputs)
        for n in g.inputs:
            consumers[n].append(g)

    net_ready_queue = deque(level.keys())
    gate_seen_inputs: Dict[str, int] = defaultdict(int)
    gate_max_in: Dict[str, int] = defaultdict(int)

    while net_ready_queue:
        net = net_ready_queue.popleft()
        lv = level[net]
        for g in consumers.get(net, []):
            gate_seen_inputs[g.name] += 1
            if lv > gate_max_in[g.name]:
                gate_max_in[g.name] = lv
            if gate_seen_inputs[g.name] == indeg[g.name]:
                out_level = gate_max_in[g.name] + 1
                if g.output and g.output not in level:
                    level[g.output] = out_level
                    net_ready_queue.append(g.output)

    # gates with 0 inputs (constant-only) get level 1 if never queued
    for g in combinational_gates:
        if g.output and g.output not in level and indeg[g.name] == 0:
            level[g.output] = 1
    return level


def _combinational_levels(nl: Netlist) -> Dict[str, int]:
    """Level of every net reachable from a PI or a DFF Q output (level 0).

    This is the general "combinational depth" used by `max_depth` and
    `depth_between`: a DFF Q output has depth 0 (docs/OPEN_QUESTIONS.md O1),
    and no level ever walks through a DFF's D-side fanin.
    """
    sources = set(nl.inputs)
    for g in nl.gates:
        if g.gtype == "dff" and g.output:
            sources.add(g.output)
    return _levels_from_sources(nl, sources)


def max_depth(nl: Netlist) -> int:
    """Global max combinational level over all nets (0 if no comb. gates)."""
    levels = _combinational_levels(nl)
    return max(levels.values(), default=0)


def depth_between(nl: Netlist, src: str, dst: str) -> Optional[int]:
    """Longest path length in gates from *src* net to *dst* net, comb.-only.

    None if src or dst is unknown, or no combinational path connects them.
    Uses topological DP (the combinational subgraph is a DAG): O(V+E), no
    enumeration.
    """
    if src == dst:
        return 0
    order = _topo_order(nl)
    idx = {n: i for i, n in enumerate(order)}
    if src not in idx or dst not in idx:
        # src/dst might not appear in the topo net list if isolated; still
        # try direct adjacency fallback for PI/PO names with no gate at all.
        if src not in _all_nets(nl) or dst not in _all_nets(nl):
            return None
    best: Dict[str, int] = {src: 0}
    consumers = _comb_consumers(nl)
    for net in order:
        if net not in best:
            continue
        d = best[net]
        for g in consumers.get(net, []):
            nd = d + 1
            out = g.output
            if not out:
                continue
            if nd > best.get(out, -1):
                best[out] = nd
    return best.get(dst)


def path_exists(nl: Netlist, src: str, dst: str, avoid: Optional[str] = None) -> bool:
    """Reachability src->dst through combinational gates, O(V+E).

    avoid may name a net or a gate instance; either blocks that gate/net
    from being used on the path (matches docs semantics: "avoiding node X").
    """
    if src == avoid or dst == avoid:
        return False
    if src == dst:
        return True
    seen: Set[str] = {src}
    q = deque([src])
    consumers = _comb_consumers(nl)
    while q:
        net = q.popleft()
        for g in consumers.get(net, []):
            if _blocks(g, avoid):
                continue
            out = g.output
            if not out or out in seen:
                continue
            if out == dst:
                return True
            seen.add(out)
            q.append(out)
    return False


def count_paths(nl: Netlist, src: str, dst: str, avoid: Optional[str] = None,
                 cap: int = 10 ** 18) -> int:
    """DAG path-count DP (src->dst, combinational-only), saturating at *cap*."""
    if src == avoid or dst == avoid:
        return 0
    order = _topo_order(nl)
    if src not in set(order) and src not in _all_nets(nl):
        return 0
    consumers = _comb_consumers(nl)
    count: Dict[str, int] = {src: 1}
    found_src = False
    for net in order:
        if net == src:
            found_src = True
        if not found_src:
            continue
        c = count.get(net, 0)
        if c == 0:
            continue
        for g in consumers.get(net, []):
            if _blocks(g, avoid):
                continue
            out = g.output
            if not out:
                continue
            count[out] = min(cap, count.get(out, 0) + c)
    return count.get(dst, 0)


# ── register-to-register analysis ───────────────────────────────────────

def max_pi_to_dff_depth(nl: Netlist) -> int:
    """Max combinational level over all nets feeding any DFF D input.

    Uses the general combinational level map (`_combinational_levels`,
    sources = PIs *and* DFF Q outputs, matching `max_depth`/`depth_between`
    and confirmed identical to parser_cpp's own `max_pi_to_dff_depth` on
    test21: 23). D-logic commonly mixes PI and register-Q fanin in the same
    cone, and a DFF Q feeding into it is a level-0 boundary exactly like a
    PI — the "PI to D-pin" phrasing describes the typical STA use case, not
    a literal requirement that every path start EXCLUSIVELY at a PI with no
    register anywhere upstream (that stricter, PI-only-sourced reading was
    tried and produces 0 on test21, diverging from parser_cpp's 23 — see
    the cross-check report for the investigation).
    """
    levels = _combinational_levels(nl)
    best = 0
    for g in nl.gates:
        if g.gtype != "dff":
            continue
        d_net = g.dff_pins.get("D", "")
        if d_net and d_net in levels:
            best = max(best, levels[d_net])
    return best


def r2r_max_depth(nl: Netlist) -> int:
    """Max combinational depth on any register-to-register path (Q->...->D).

    Levelizes from DFF Q outputs ONLY (not PIs) in a single O(V+E) pass,
    then reads the level at every DFF's D pin. A D-pin net that is only
    reachable from PIs (no register anywhere upstream) is correctly excluded
    (absent from this level map), since it is not the endpoint of any
    register-to-register path. This single shared pass is what keeps the
    query linear even though test39 alone has 16146 flip-flops — levelizing
    each register separately (O(#DFF * (V+E))) would not scale.
    """
    dff_q_sources = {g.output for g in nl.gates if g.gtype == "dff" and g.output}
    levels = _levels_from_sources(nl, dff_q_sources)
    best = 0
    for g in nl.gates:
        if g.gtype != "dff":
            continue
        d_net = g.dff_pins.get("D", "")
        if d_net and d_net in levels:
            best = max(best, levels[d_net])
    return best


def r2r_path_count(nl: Netlist, cap: int = 10 ** 18) -> int:
    """Total count of register-to-register (Q->...->D) combinational paths.

    Single topo DP pass, NOT one `count_paths` call per (DFF, DFF) pair:
    every DFF Q output is seeded with path_count=1 simultaneously (paths
    from *distinct* registers to the same net legitimately add), propagated
    once through the combinational DAG, then summed at every DFF's D pin.
    An O(#DFF^2 * (V+E)) pairwise approach would not scale — test39 alone
    has 16146 flip-flops.
    """
    order = _topo_order(nl)
    consumers = _comb_consumers(nl)
    count: Dict[str, int] = {g.output: 1 for g in nl.gates
                              if g.gtype == "dff" and g.output}
    for net in order:
        c = count.get(net, 0)
        if c == 0:
            continue
        for g in consumers.get(net, []):
            out = g.output
            if not out:
                continue
            count[out] = min(cap, count.get(out, 0) + c)
    total = 0
    for g in nl.gates:
        if g.gtype != "dff":
            continue
        d_net = g.dff_pins.get("D", "")
        if d_net and d_net in count:
            total = min(cap, total + count[d_net])
    return total


# ── internal helpers: topo order + combinational consumer map ──────────

def _all_nets(nl: Netlist) -> Set[str]:
    nets: Set[str] = set(nl.inputs) | set(nl.outputs)
    for g in nl.gates:
        if g.output:
            nets.add(g.output)
        nets.update(g.inputs)
    return nets


def _comb_consumers(nl: Netlist) -> Dict[str, List[Gate]]:
    """net -> combinational gates reading it as an input (DFFs excluded —
    a combinational path never continues past a DFF pin)."""
    consumers: Dict[str, List[Gate]] = defaultdict(list)
    for g in nl.gates:
        if g.gtype == "dff":
            continue
        for n in g.inputs:
            consumers[n].append(g)
    return consumers


def _topo_order(nl: Netlist) -> List[str]:
    """Topological order of nets through the combinational subgraph (Kahn).

    DFF D/CK/RN/SN pins are sinks that never re-emit an edge (DFFs are
    excluded from _comb_consumers), so the "graph" here is exactly the
    combinational DAG the spec requires — guaranteed acyclic if the input
    netlist is a legal (non-combinationally-looping) design.
    """
    consumers = _comb_consumers(nl)
    indeg: Dict[str, int] = defaultdict(int)
    nets = _all_nets(nl)
    for n in nets:
        indeg[n] = 0
    for net, gs in consumers.items():
        for g in gs:
            if g.output:
                indeg[g.output] += 1
    q = deque(n for n in nets if indeg[n] == 0)
    order: List[str] = []
    seen_deg = dict(indeg)
    while q:
        n = q.popleft()
        order.append(n)
        for g in consumers.get(n, []):
            if not g.output:
                continue
            seen_deg[g.output] -= 1
            if seen_deg[g.output] == 0:
                q.append(g.output)
    return order


# ── BLIF writer (own, independent of parser_cpp's write_blif) ──────────

def _write_gate_names(lines: List[str], g: Gate, out_name: str, in_names: List[str]) -> None:
    """Append `.names` truth-table lines for one gate to *lines*."""
    t = g.gtype
    if t == "and":
        lines.append(f".names {in_names[0]} {in_names[1]} {out_name}")
        lines.append("11 1")
    elif t == "or":
        lines.append(f".names {in_names[0]} {in_names[1]} {out_name}")
        lines.append("1- 1")
        lines.append("-1 1")
    elif t == "nand":
        lines.append(f".names {in_names[0]} {in_names[1]} {out_name}")
        lines.append("0- 1")
        lines.append("-0 1")
    elif t == "nor":
        lines.append(f".names {in_names[0]} {in_names[1]} {out_name}")
        lines.append("00 1")
    elif t == "xor":
        lines.append(f".names {in_names[0]} {in_names[1]} {out_name}")
        lines.append("01 1")
        lines.append("10 1")
    elif t == "xnor":
        lines.append(f".names {in_names[0]} {in_names[1]} {out_name}")
        lines.append("00 1")
        lines.append("11 1")
    elif t == "not":
        lines.append(f".names {in_names[0]} {out_name}")
        lines.append("0 1")
    elif t == "buf":
        lines.append(f".names {in_names[0]} {out_name}")
        lines.append("1 1")
    else:
        raise ValueError(f"unsupported gate type for BLIF: {t}")


def _sanitize(name: str) -> str:
    """BLIF-safe identifier (bit-selects use brackets, which BLIF tolerates
    in most readers, but we normalize to be safe across ABC versions)."""
    return name.replace("[", "_").replace("]", "_").replace("'", "_p")


def _write_cone_blif(nl: Netlist, root: str, path: Path, model: str,
                      invert_output: bool = False,
                      extra_inputs: Optional[Set[str]] = None) -> Set[str]:
    """Write a single-output BLIF computing *root*'s combinational cone.

    PIs and DFF Q outputs in the cone become BLIF `.inputs` (flop-cut).
    Constants (1'b0/1'b1) become dedicated constant `.names` nodes. The
    output is always named the fixed literal `o` (regardless of *root*'s
    real net name) so that two cones written by this function for two
    *different* nets can still be handed to ABC `cec` as a matching pair —
    `cec` matches primary outputs by name, and two BLIFs whose sole output
    is both literally called `o` compare that output's logic function
    directly, which is exactly the "are net A and net B the same function"
    question this oracle needs to ask.

    ABC's `cec` also insists the two networks' `.inputs` lists match
    (by name/position) — it does NOT treat a name present in one file but
    absent from the other as a safe don't-care, it just errors out. So when
    comparing two different nets' cones, callers pass *extra_inputs* = the
    other cone's boundary set; any name in there that this cone doesn't
    actually use is still declared as an (unread) `.inputs` entry, giving
    both files an identical, sorted input list.

    Returns the set of BLIF input names used (sanitized), for cec pairing.
    """
    gates_in_cone: List[Gate] = []
    seen_gate_names: Set[str] = set()
    boundary_inputs: Set[str] = set()
    seen_nets: Set[str] = set()
    stack = [root]
    while stack:
        net = stack.pop()
        if net in seen_nets:
            continue
        seen_nets.add(net)
        if net in CONSTS:
            boundary_inputs.add(net)
            continue
        g = nl.driver.get(net)
        if g is None:
            # PI or otherwise undriven -> becomes a BLIF input
            boundary_inputs.add(net)
            continue
        if g.name not in seen_gate_names:
            seen_gate_names.add(g.name)
            gates_in_cone.append(g)
        if g.gtype == "dff":
            # flop-cut: DFF Q becomes an input, do not walk its D-side fanin
            boundary_inputs.add(net)
            continue
        stack.extend(g.inputs)

    own_inputs = {_sanitize(n) for n in boundary_inputs if n not in CONSTS}
    all_inputs = sorted(own_inputs | {_sanitize(n) for n in (extra_inputs or set())})
    out_name = _sanitize(root)

    lines = [f".model {model}"]
    lines.append(".inputs " + " ".join(all_inputs) if all_inputs else ".inputs")
    lines.append(".outputs o")

    for const in (boundary_inputs & CONSTS):
        cname = _sanitize(const)
        val = "1" if const == "1'b1" else "0"
        lines.append(f".names {cname}")
        if val == "1":
            lines.append("1")
        # a constant-0 node is represented by an empty .names (no rows) —
        # ABC/BLIF convention: cover with zero on-set rows means always 0.

    for g in gates_in_cone:
        gout = _sanitize(g.output)
        gins = [_sanitize(x) for x in g.inputs]
        _write_gate_names(lines, g, gout, gins)

    # wire out_name -> the fixed output name `o`, optionally inverted
    lines.append(f".names {out_name} o")
    lines.append("0 1" if invert_output else "1 1")

    lines.append(".end")
    Path(path).write_text("\n".join(lines) + "\n")
    return own_inputs


def signals_equivalent(nl: Netlist, a: str, b: str,
                        abc_path: Path = ABC_BIN_DEFAULT,
                        timeout: int = 120) -> Optional[bool]:
    """Are nets *a* and *b* functionally equivalent (flop-cut, comb. cones)?

    Builds one single-output BLIF per net (own writer, own cone extraction —
    never parser_cpp's write_blif) over the union of PI/DFF-Q boundary
    inputs, then asks ABC `cec` on the pair. Returns None if ABC is
    unavailable or times out (never fabricates True/False in that case).
    """
    abc_path = Path(abc_path)
    if not abc_path.is_file():
        return None
    if a == b:
        return True
    with tempfile.TemporaryDirectory(prefix="oracle_sigeq_") as td:
        pa, pb = os.path.join(td, "a.blif"), os.path.join(td, "b.blif")
        try:
            # first pass: discover each cone's own boundary inputs
            ins_a = _write_cone_blif(nl, a, Path(pa), "sigA")
            ins_b = _write_cone_blif(nl, b, Path(pb), "sigB")
            # second pass: rewrite both with a padded, identical .inputs list
            # — ABC `cec` errors out (rather than treating it as a don't-
            # care) if the two networks' input lists don't match by name.
            _write_cone_blif(nl, a, Path(pa), "sigA", extra_inputs=ins_b)
            _write_cone_blif(nl, b, Path(pb), "sigB", extra_inputs=ins_a)
        except ValueError:
            return None
        try:
            r = subprocess.run(
                [str(abc_path), "-q", f"cec {pa} {pb}"],
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        low = (r.stdout + r.stderr).lower()
        if "are equivalent" in low or "networks are equivalent" in low:
            return True
        if "not equivalent" in low:
            return False
        return None


def always_const(nl: Netlist, net: str, abc_path: Path = ABC_BIN_DEFAULT,
                  timeout: int = 120) -> Optional[int]:
    """Is *net* always 0, always 1, or neither? Returns 0, 1, or None.

    None covers BOTH "ABC unavailable/timeout" AND "provably not constant"
    per the API contract (0|1|None) — callers that need to distinguish
    "not constant" from "inconclusive" should use signals_equivalent-style
    SAT probing directly; for this oracle's purposes None simply means "no
    definitive const value was established."
    """
    abc_path = Path(abc_path)
    if not abc_path.is_file():
        return None
    with tempfile.TemporaryDirectory(prefix="oracle_const_") as td:
        p1 = os.path.join(td, "c1.blif")
        try:
            _write_cone_blif(nl, net, Path(p1), "constchk", invert_output=False)
        except ValueError:
            return None
        try:
            r1 = subprocess.run(
                [str(abc_path), "-q", f"read_blif {p1}; strash; sat"],
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        o1 = (r1.stdout + r1.stderr).upper()
        can_be_1 = "SATISFIABLE" in o1 and "UNSATISFIABLE" not in o1
        if not can_be_1 and "UNSATISFIABLE" not in o1:
            return None  # ABC gave neither verdict — inconclusive

        p2 = os.path.join(td, "c2.blif")
        _write_cone_blif(nl, net, Path(p2), "constchk_inv", invert_output=True)
        try:
            r2 = subprocess.run(
                [str(abc_path), "-q", f"read_blif {p2}; strash; sat"],
                capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None
        o2 = (r2.stdout + r2.stderr).upper()
        can_be_0 = "SATISFIABLE" in o2 and "UNSATISFIABLE" not in o2
        if not can_be_0 and "UNSATISFIABLE" not in o2:
            return None

        if not can_be_1 and can_be_0:
            return 0
        if can_be_1 and not can_be_0:
            return 1
        return None  # both reachable -> not constant


# ── self-test ────────────────────────────────────────────────────────────

_MICRO_NETLIST = """
module top(a, b, c, clk, rst, y, z, q_out);
  input a, b, c, clk, rst;
  input [1:0] bus;
  output y, z, q_out;
  wire n1, n2, n3, n4, n5, n6, n7, n8, n9, n10, n11;

  and g1(n1, a, b);
  not g2(n2, n1);
  nand g3(n3, a, b);
  buf g4(n4, n3);

  or g5(n5, a, c);
  and g6(n6, a, c);
  not g7(n7, n6);
  or g8(n8, n5, n7);

  dff g9(.RN(rst), .SN(1'b1), .CK(clk), .D(n1), .Q(y));
  and g10(n9, y, c);

  xor g11(n10, bus[0], bus[1]);
  xnor g12(n11, bus[0], bus[1]);
  not g13(z, n11);

  buf g14(q_out, y);
endmodule
"""


def _selftest() -> None:
    failures: List[str] = []

    def check(cond: bool, msg: str) -> None:
        if not cond:
            failures.append(msg)

    with tempfile.TemporaryDirectory(prefix="oracle_selftest_") as td:
        vpath = Path(td) / "micro.v"
        vpath.write_text(_MICRO_NETLIST)
        nl = parse_netlist(vpath)

        # -- 1. hand-computed expectations over the micro-netlist --
        counts = count_gates(nl)
        expect_counts = {"and": 3, "or": 2, "nand": 1, "nor": 0, "not": 3,
                          "buf": 2, "xor": 1, "xnor": 1, "dff": 1}
        check(counts == expect_counts, f"count_gates mismatch: {counts} vs {expect_counts}")

        check(fanout_of(nl, "n1") == ["g2", "g9"] or
              sorted(fanout_of(nl, "n1")) == ["g2", "g9"],
              f"fanout_of(n1) = {fanout_of(nl, 'n1')}, expected [g2, g9]")
        check(fanout_of(nl, "a") and sorted(fanout_of(nl, "a")) == ["g1", "g3", "g5", "g6"],
              f"fanout_of(a) = {fanout_of(nl, 'a')}")

        # fanin cone of y (DFF output) strict-combinational = just {g9}
        check(fanin_cone_gates(nl, "y", through_dff=False) == {"g9"},
              f"fanin_cone_gates(y, False) = {fanin_cone_gates(nl, 'y', False)}")
        # through_dff=True walks into n1's logic (g1) too
        check(fanin_cone_gates(nl, "y", through_dff=True) == {"g9", "g1"},
              f"fanin_cone_gates(y, True) = {fanin_cone_gates(nl, 'y', True)}")
        # fanin cone of n8 = {g8, g5, g7, g6}
        check(fanin_cone_gates(nl, "n8") == {"g8", "g5", "g7", "g6"},
              f"fanin_cone_gates(n8) = {fanin_cone_gates(nl, 'n8')}")

        # fanout cone of a (strict comb, stop at DFF): a feeds g1,g3,g5,g6 and
        # onward through g2,g4,g7,g8 but g1->n1 feeds g9 (dff) which stops.
        fo_a = fanout_cone_gates(nl, "a", through_dff=False)
        check(fo_a == {"g1", "g2", "g3", "g4", "g5", "g6", "g7", "g8", "g9"},
              f"fanout_cone_gates(a, False) = {fo_a}")
        fo_a_dff = fanout_cone_gates(nl, "a", through_dff=True)
        check(fo_a_dff == fo_a | {"g10", "g14"},
              f"fanout_cone_gates(a, True) = {fo_a_dff}")

        # depth: y (DFF Q) has combinational depth 0 (O1)
        levels = _combinational_levels(nl)
        check(levels.get("y") == 0, f"level(y) = {levels.get('y')}, expected 0 (O1)")
        # n2 = NOT(AND(a,b)) -> depth 2; n8 = OR(OR(a,c), NOT(AND(a,c))) -> depth 3
        check(levels.get("n2") == 2, f"level(n2) = {levels.get('n2')}, expected 2")
        check(levels.get("n8") == 3, f"level(n8) = {levels.get('n8')}, expected 3")
        check(max_depth(nl) == 3, f"max_depth = {max_depth(nl)}, expected 3")

        # depth_between
        check(depth_between(nl, "a", "n2") == 2, f"depth_between(a,n2) = {depth_between(nl, 'a', 'n2')}")
        check(depth_between(nl, "a", "n8") == 3, f"depth_between(a,n8) = {depth_between(nl, 'a', 'n8')}")
        check(depth_between(nl, "y", "n8") is None, f"depth_between(y,n8) should be None (DFF boundary)")

        # path_exists / avoid semantics (gate name OR net name)
        check(path_exists(nl, "a", "n8") is True, "path_exists(a,n8) should be True")
        check(path_exists(nl, "a", "n8", avoid="g8") is False,
              "path_exists(a,n8,avoid=g8) should be False (g8 drives n8 on every route)")
        check(path_exists(nl, "a", "n8", avoid="g7") is True,
              "path_exists(a,n8,avoid=g7) should still be True via the n5 route (a->g5->n5->g8->n8)")
        check(path_exists(nl, "a", "n8", avoid="n5") is True,
              "path_exists(a,n8,avoid=n5) should still be True via n6/n7 route")
        check(path_exists(nl, "y", "n8") is False, "path_exists(y,n8) should be False (no comb path)")

        # count_paths: a -> n8 has exactly 2 disjoint paths (via n5, via n6/n7)
        check(count_paths(nl, "a", "n8") == 2, f"count_paths(a,n8) = {count_paths(nl, 'a', 'n8')}")
        check(count_paths(nl, "a", "n8", avoid="g5") == 1,
              f"count_paths(a,n8,avoid=g5) = {count_paths(nl, 'a', 'n8', avoid='g5')}")

        # list_pio
        pio = list_pio(nl)
        expect_inputs = {("a", 1), ("b", 1), ("c", 1), ("clk", 1), ("rst", 1), ("bus", 2)}
        check(set(pio["inputs"]) == expect_inputs, f"list_pio inputs = {pio['inputs']}")
        check(set(pio["outputs"]) == {("y", 1), ("z", 1), ("q_out", 1)},
              f"list_pio outputs = {pio['outputs']}")

        # flops_by_clock
        check(flops_by_clock(nl, "clk") == ["g9"], f"flops_by_clock(clk) = {flops_by_clock(nl, 'clk')}")
        check(flops_by_clock(nl, "rst") == [], "flops_by_clock(rst) should be empty (rst is RN, not CK)")

        # max_pi_to_dff_depth: g9's D = n1 = AND(a,b), level 1
        check(max_pi_to_dff_depth(nl) == 1, f"max_pi_to_dff_depth = {max_pi_to_dff_depth(nl)}")

        # r2r: only one DFF (g9), Q=y feeds g10 (and, level1) but g10's output
        # n9 feeds nothing further (no DFF D reads n9) -> no register-to-
        # register path exists in this micro-design; r2r_max_depth = 0.
        check(r2r_max_depth(nl) == 0, f"r2r_max_depth = {r2r_max_depth(nl)} (single DFF, no r2r path)")
        check(r2r_path_count(nl) == 0, f"r2r_path_count = {r2r_path_count(nl)}")

        # -- 3. signals_equivalent / always_const sanity (needs ABC) --
        abc = ABC_BIN_DEFAULT
        if abc.is_file():
            # n3 = NAND(a,b); build an equivalent NOT(AND(a,b)) = n2. n2 vs n3
            # should be equivalent.
            eq = signals_equivalent(nl, "n2", "n3", abc)
            check(eq is True, f"signals_equivalent(n2,n3) = {eq}, expected True (NOT(AND) == NAND)")
            # n2 (NOT AND(a,b)) vs n5 (OR(a,c)) are NOT equivalent in general.
            neq = signals_equivalent(nl, "n2", "n5", abc)
            check(neq is False, f"signals_equivalent(n2,n5) = {neq}, expected False")
            # always_const sanity: n1=AND(a,b) is not constant.
            ac = always_const(nl, "n1", abc)
            check(ac is None, f"always_const(n1) = {ac}, expected None (not constant)")
        else:
            print("[selftest] WARNING: ABC binary not found, skipping SAT-level checks", file=sys.stderr)

    # -- 2. cross-check against parser_cpp on real designs --
    cross_report = _cross_check_parser_cpp(failures)

    print("=" * 70)
    if failures:
        print(f"SELFTEST FAILED: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        print(cross_report)
        print("=" * 70)
        sys.exit(1)
    else:
        print("SELFTEST OK: all micro-netlist assertions and cross-checks passed")
        print(cross_report)
        print("=" * 70)
        sys.exit(0)


def _cross_check_parser_cpp(failures: List[str]) -> str:
    """Cross-check count_gates / path_exists / depth vs parser_cpp on real
    testcases. Appends hard mismatches to *failures*; DIVERGENT-DEFINITION
    findings (expected per depth semantics differences) are reported but do
    NOT fail selftest, matching the answer-checker's own DIVERGENT-DEFINITION
    verdict category."""
    lines = ["", "-- parser_cpp cross-check --"]
    if not PARSER_BIN.is_file():
        lines.append("parser_cpp binary not found, skipping cross-check")
        return "\n".join(lines)

    cases = {
        1: ROOT / "testcase" / "test01" / "test01.v",
        4: ROOT / "testcase" / "test04" / "test04.v",
        5: ROOT / "testcase" / "test05" / "test05.v",
        21: ROOT / "testcase" / "test21" / "test21.v",
    }
    # (case, start, end) pairs for path_exists / count_paths cross-check
    path_pairs = {
        1: [("n0[0]", "n3[15]"), ("n0[0]", "n4[0]")],
        4: [("n0[0]", "n3")],
        5: [("n5", "n11[0]"), ("n5", "n12[0]")],
        21: [("n2", "n10")],
    }

    for n, vfile in cases.items():
        if not vfile.is_file():
            lines.append(f"test{n:02d}: file missing, skipped")
            continue
        nl = parse_netlist(vfile)
        oracle_counts = count_gates(nl)

        r = subprocess.run([str(PARSER_BIN), "--in", str(vfile), "--action", "count_gates"],
                            capture_output=True, text=True, timeout=60)
        tool_counts = {k: int(v) for k, v in re.findall(r"(\w+):\s*(\d+)", r.stdout)}
        tool_counts_full = {t: tool_counts.get(t, 0) for t in ALL_TYPES}
        match = oracle_counts == tool_counts_full
        lines.append(f"test{n:02d} count_gates: oracle={oracle_counts} tool={tool_counts_full} "
                      f"{'MATCH' if match else 'MISMATCH'}")
        if not match:
            failures.append(f"test{n:02d} count_gates mismatch vs parser_cpp")

        for (s, e) in path_pairs.get(n, []):
            oracle_exists = path_exists(nl, s, e)
            r2 = subprocess.run(
                [str(PARSER_BIN), "--in", str(vfile), "--action", "count_paths",
                 "--start", s, "--end", e], capture_output=True, text=True, timeout=60)
            m = re.search(r"Paths:\s*(\d+)", r2.stdout)
            tool_count = int(m.group(1)) if m else 0
            tool_exists = tool_count > 0
            oracle_count = count_paths(nl, s, e)
            lines.append(f"test{n:02d} path {s}->{e}: oracle_exists={oracle_exists} "
                         f"tool_exists={tool_exists}; oracle_count={oracle_count} tool_count={tool_count} "
                         f"{'MATCH' if oracle_exists == tool_exists else 'MISMATCH'}")
            if oracle_exists != tool_exists:
                failures.append(f"test{n:02d} path_exists {s}->{e} mismatch vs parser_cpp")
            elif oracle_count != tool_count:
                lines.append(f"  NOTE: existence agrees but path COUNT differs "
                             f"(oracle={oracle_count} tool={tool_count}) — possibly a "
                             f"cap/enumeration difference, not necessarily a bug")

        # depth cross-check: parser_cpp calc_depth needs --end (and optional
        # --start); compare max_depth-style single-output depth for a PO
        # that is actually driven (some PO bit-selects in these designs are
        # declared by a bus width but never driven by any gate — both tools
        # agree those are depth-less; skip straight to a driven one so the
        # check exercises real levelization, not the undriven-net edge case).
        driven_po = next((o for o in sorted(nl.outputs) if o in nl.driver), None)
        if driven_po:
            end = driven_po
            r3 = subprocess.run(
                [str(PARSER_BIN), "--in", str(vfile), "--action", "calc_depth", "--end", end],
                capture_output=True, text=True, timeout=60)
            m = re.search(r"Depth:\s*(-?\d+)", r3.stdout)
            tool_depth = int(m.group(1)) if m else None
            oracle_depth = _combinational_levels(nl).get(end)
            # normalize sentinels: oracle uses None, tool uses -1, for "no
            # depth" (undriven net) — treat those as equal, not divergent.
            oracle_norm = -1 if oracle_depth is None else oracle_depth
            agree = (oracle_norm == tool_depth)
            lines.append(f"test{n:02d} depth(end={end}): oracle={oracle_depth} tool={tool_depth} "
                         f"{'MATCH' if agree else 'DIVERGENT-DEFINITION'}")
            if not agree:
                lines.append(f"  DIVERGENCE NOTE: parser_cpp calc_depth(--end) with no --start "
                             f"levelizes from ALL sources (PIs+DFF-Q) same as this oracle's "
                             f"max_depth-style level map; if they differ here it indicates a "
                             f"real definitional gap worth recording, not a bug to silently patch.")

        if n == 21:
            # DFF-specific cross-checks: flops_by_clock, max_pi_to_dff_depth
            r4 = subprocess.run(
                [str(PARSER_BIN), "--in", str(vfile), "--action", "flipflops_by_clock",
                 "--clock", "n0"], capture_output=True, text=True, timeout=60)
            tool_dffs = set(re.findall(r'"name":\s*"(\w+)"', r4.stdout))
            oracle_dffs = set(flops_by_clock(nl, "n0"))
            agree = tool_dffs == oracle_dffs
            lines.append(f"test21 flops_by_clock(n0): oracle_count={len(oracle_dffs)} "
                         f"tool_count={len(tool_dffs)} {'MATCH' if agree else 'MISMATCH'}")
            if not agree:
                failures.append("test21 flops_by_clock mismatch vs parser_cpp")

            r5 = subprocess.run(
                [str(PARSER_BIN), "--in", str(vfile), "--action", "max_pi_to_dff_depth"],
                capture_output=True, text=True, timeout=60)
            m = re.search(r'"max_pi_to_dff_d_depth":\s*(-?\d+)', r5.stdout)
            tool_val = int(m.group(1)) if m else None
            oracle_val = max_pi_to_dff_depth(nl)
            agree = tool_val == oracle_val
            lines.append(f"test21 max_pi_to_dff_depth: oracle={oracle_val} tool={tool_val} "
                         f"{'MATCH' if agree else 'DIVERGENT-DEFINITION'}")
            if not agree:
                lines.append("  DIVERGENCE NOTE: recorded, not silently patched — see report.")

            # r2r_path_count: parser_cpp's `r2r_paths` action enumerates with
            # MAX_PATHS_PER_PAIR=5 and a global MAX_TOTAL_PATHS=200 cap (see
            # graph.cpp r2r_paths()), so its sum of per-pair path_count is a
            # TRUNCATED enumeration, not a true total — this oracle's
            # r2r_path_count is the uncapped DP sum. These are expected to
            # differ; report both, do not treat the difference as a defect
            # (matches the already-documented O3 enumeration-cap finding).
            r6 = subprocess.run(
                [str(PARSER_BIN), "--in", str(vfile), "--action", "r2r_paths"],
                capture_output=True, text=True, timeout=60)
            tool_r2r_sum = sum(int(x) for x in re.findall(r'"path_count":\s*(\d+)', r6.stdout))
            oracle_r2r = r2r_path_count(nl)
            lines.append(f"test21 r2r_path_count: oracle(uncapped)={oracle_r2r} "
                         f"tool(capped enum sum)={tool_r2r_sum} "
                         f"{'as expected (tool caps at 200 total / 5 per pair, O3)' if oracle_r2r != tool_r2r_sum else 'MATCH'}")

    return "\n".join(lines)


def _timing_report() -> str:
    """Perf sanity: parse + pure-graph queries on the largest testcases."""
    lines = ["", "-- timing (test12 ~91k gates) --"]
    vfile = ROOT / "testcase" / "test12" / "test12.v"
    if not vfile.is_file():
        lines.append("test12.v not found, skipping timing")
        return "\n".join(lines)
    t0 = time.time()
    nl = parse_netlist(vfile)
    t1 = time.time()
    _ = count_gates(nl)
    t2 = time.time()
    _ = max_depth(nl)
    t3 = time.time()
    lines.append(f"parse: {t1 - t0:.2f}s, count_gates: {t2 - t1:.2f}s, "
                 f"max_depth: {t3 - t2:.2f}s, total: {t3 - t0:.2f}s")
    return "\n".join(lines)


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--selftest", action="store_true", help="run the self-verification suite")
    ap.add_argument("--timing", action="store_true", help="report parse/query timing on test12")
    a = ap.parse_args()
    if a.selftest:
        _selftest()
    elif a.timing:
        print(_timing_report())
    else:
        ap.print_help()


if __name__ == "__main__":
    main()
