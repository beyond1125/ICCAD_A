#!/usr/bin/env python3
"""Transform-goal checker (companion to eval_harness.py).

`eval_harness.py` proves each output netlist is *equivalent* to its input — necessary,
but NOT sufficient: a no-op transform passes ABC `cec` perfectly while achieving nothing.
This script closes that gap. For each imperative instruction in a testcase `prompt.txt`,
it asserts the *structural goal* the instruction implies on `<case>_out.v`, using the same
independent Python oracle (`Netlist`) that eval_harness uses — never the C++ tools under test.

Per-instruction verdict is two independent axes:
    goal-achieved  (this script)   AND   equiv-preserved  (ABC cec, optional here)
so you can tell "broke it" (equiv X) from "didn't do it" (goal X).

Predicates (all classified from `prompt.txt` by `classify_line`):
  - fanout limit (global) and single-signal / dedicated per-load buffering
  - basis remap (cone + whole netlist) and type-specific decompose-in-cone
  - type replacement with exact-count delta (e.g. XOR -> 4-NAND, asserts count = N x src)
  - depth: node/cone <= K, all-outputs <= K, and whole-design reduction (advisory)
  - inverter collapse, dangling/floating removal, redundant (duplicate) removal
  - constant propagation (no gate of a type keeps its constant input)
  - rename (old identifier gone, new present)

Analysis questions ("how many ... / list ... / what is ...") are neither goals nor counted
as unclassified. A line with a transform verb that no predicate matches is reported as
`[unclassified]` so coverage gaps stay visible rather than silently passing.

Oracle note: the eval_harness Netlist drops DFF control-pin connections (.CK/.RN/.SN);
`augment_control_nets` re-parses them so clock/reset fanout and dangling-detection are not
blind to logic feeding flop control pins.

Known limitation — FINAL-STATE checking: every goal is asserted on the final `<case>_out.v`.
When a prompt issues several transforms touching the same property, a goal for an *earlier*
instruction can be legitimately undone by a *later* one (e.g. test34: "fanout <=4" at line 13,
then a netlist-wide "reconstruct to AND+NOT" at line 18 that does not re-enforce fanout). Such
a case reports UNMET even though the earlier step ran. Per-step checking would need to re-drive
the agent's transform sequence; for now, read UNMET as "the property does not hold in the final
netlist" and check instruction order before calling it a transform bug.

Usage:
    python3 scripts/goal_check.py                 # every testcase found
    python3 scripts/goal_check.py --from 21 --to 30
    python3 scripts/goal_check.py --case 26
    python3 scripts/goal_check.py --skip-equiv     # goal axis only (no ABC)
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import Counter
from pathlib import Path

# Reuse the independent oracle + equivalence check from the eval harness.
sys.path.insert(0, str(Path(__file__).resolve().parent))
from eval_harness import ROOT, Netlist, cec, find_abc  # noqa: E402

# Gate-type tokens as they appear (uppercase) in the prompts. Matching the ORIGINAL-case
# line avoids mistaking the lowercase conjunction "and" for the AND gate type.
BASIS_TOKENS = ("NAND", "NOR", "XNOR", "XOR", "AND", "OR", "NOT", "BUF")
# Verbs that mark a line as a transform instruction (for unclassified-coverage reporting).
TRANSFORM_VERBS = (
    "insert", "convert", "reconstruct", "reduce", "optimize", "remove", "sweep",
    "collapse", "replace", "rewrite", "simplify", "propagate", "rename", "decompose",
    "buffer", "restructure", "perform fanout",
)


# ── oracle helpers (structural predicates operate on Netlist) ─────────────────
def driver_map(net: Netlist) -> dict:
    """net-name -> the combinational gate tuple that drives it."""
    return {g[3]: g for g in net.gates}


def fanin_cone_gates(net: Netlist, node: str) -> list:
    """Combinational gates in the fanin cone of `node`, stopping at PIs and flop Qs.

    If `node` is itself a flip-flop output (a registered signal, e.g. a PO driven by
    `.Q(node)`), the meaningful combinational cone is the logic feeding that flop's D pin,
    so the walk starts from D instead of dead-ending at the Q boundary.
    """
    dm = driver_map(net)
    flop_d = {q: d for _, q, d in net.dffs}
    flop_q = set(flop_d)
    start = flop_d.get(node, node)           # resolve a registered signal to its D-cone
    cone, seen, stack = [], set(), [start]
    while stack:
        nn = stack.pop()
        if nn in seen:
            continue
        seen.add(nn)
        g = dm.get(nn)
        if not g or nn in flop_q:            # PI, flop boundary, or undriven
            continue
        cone.append(g)
        for inp in g[2]:
            if "'" not in inp and inp not in flop_q:
                stack.append(inp)
    return cone


def extract_basis(line: str) -> set:
    """Gate types the instruction restricts the result to (uppercase tokens only)."""
    seg = line.split("only", 1)[1] if "only" in line.lower() else line
    found = re.findall(r"\b(" + "|".join(BASIS_TOKENS) + r")\b", seg)
    return {t.lower() for t in found}


def depth_map(net: Netlist) -> dict:
    """net-name -> combinational logic depth (gates on the longest path from a PI/flop-Q).

    Definition (independent of the C++ tool, documented for reconciliation): PIs, constants
    and flip-flop Qs are level 0; each multi-input logic gate adds one level; BUF and NOT are
    transparent (0 levels). This "logic depth" mirrors the AIG-level notion the depth passes
    actually optimize (ABC resyn2, where inverters/buffers are free) — counting BUF/NOT would
    make basis-remapped, buffered outputs look deeper than the logic they implement.
    Iterative longest-path over the flop-cut DAG; memoized on the Netlist.
    """
    if hasattr(net, "_depthmap"):
        return net._depthmap
    dm = driver_map(net)
    flop_q = {q for _, q, _ in net.dffs}
    depth: dict = {}
    for g in net.gates:
        if g[3] in depth:
            continue
        stack = [(g[3], False)]
        while stack:
            node, processed = stack.pop()
            if node in depth:
                continue
            gg = dm.get(node)
            if gg is None or node in flop_q:        # PI / const / flop boundary
                depth[node] = 0
                continue
            if not processed:
                stack.append((node, True))
                for inp in gg[2]:
                    if "'" not in inp and inp not in depth:
                        stack.append((inp, False))
            else:
                inc = 0 if gg[0] in ("buf", "not") else 1        # BUF/NOT transparent
                depth[node] = inc + max((depth.get(i, 0) for i in gg[2] if "'" not in i),
                                        default=0)
    net._depthmap = depth
    return depth


def node_depth(net: Netlist, node: str) -> int:
    """Depth of `node`; a registered signal resolves to the depth of its flop's D-cone."""
    dm = depth_map(net)
    flop_d = {q: d for _, q, d in net.dffs}
    return dm.get(flop_d.get(node, node), 0)


def max_depth(net: Netlist) -> int:
    dm = depth_map(net)
    return max((dm.get(g[3], 0) for g in net.gates), default=0)


def po_depths(net: Netlist) -> dict:
    """Primary-output name -> combinational depth (registered POs via their D-cone)."""
    return {p: node_depth(net, p) for p in net.pos}


# The eval_harness oracle keeps only DFF Q/D; it drops control-pin connections (.CK/.RN/.SN).
# Re-parse them so clock/reset fanout and dangling-detection see loads feeding flop controls.
_CTRL_PINS = ("CK", "CLK", "RN", "SN", "R", "S", "CLR", "PRE", "SET", "RESET")


def augment_control_nets(net: Netlist, path: Path) -> Netlist:
    """Attach `net._ctrl` = list of driver nets feeding DFF control pins (memoized)."""
    if hasattr(net, "_ctrl"):
        return net
    txt = re.sub(r"//.*", "", path.read_text())
    ctrl = []
    for m in re.finditer(r"\bdff\s+\w+\s*\(([^;]*)\)\s*;", txt, re.I):
        for pin, val in re.findall(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)", m.group(1)):
            if pin.upper() in _CTRL_PINS and val and "'" not in val:
                ctrl.append(val)
    net._ctrl = ctrl
    return net


def loads_of(net: Netlist, sig: str) -> int:
    """Fanout of `sig`: consumer pins across gate inputs, DFF D, and DFF control pins."""
    c = sum(g[2].count(sig) for g in net.gates)
    c += sum(1 for _, _, d in net.dffs if d == sig)
    c += getattr(net, "_ctrl", []).count(sig)
    return c


def reachable_outputs(net: Netlist) -> set:
    """Gate outputs in the transitive fanin of any PO, DFF D, or DFF control net."""
    dm = driver_map(net)
    flop_q = {q for _, q, _ in net.dffs}
    seen, live = set(), set()
    stack = list(net.pos) + [d for _, _, d in net.dffs if d] + list(getattr(net, "_ctrl", []))
    while stack:
        n = stack.pop()
        if n in seen:
            continue
        seen.add(n)
        g = dm.get(n)
        if not g or n in flop_q:
            continue
        live.add(g[3])
        for i in g[2]:
            if "'" not in i:
                stack.append(i)
    return live


def gate_has_const_input(gate, value: str | None) -> bool:
    """True if the gate has a constant input; `value` in {'0','1',None(any)}."""
    for s in gate[2]:
        if "'" in s:
            if value is None or s.strip().endswith(f"'b{value}") or s.strip().endswith(value):
                return True
    return False


def all_names(net: Netlist) -> set:
    """Every identifier the netlist mentions: gate/DFF instance names and all net names."""
    names = set()
    for gt, name, ins, out in net.gates:
        names.add(name)
        names.add(out)
        names.update(s for s in ins if "'" not in s)
    for name, q, d in net.dffs:
        names.update({name, q, d})
    names |= net.pis | net.pos | set(getattr(net, "_ctrl", []))
    names.discard("")
    return names


# ── goal predicates ───────────────────────────────────────────────────────────
# Each returns (met: bool | None, detail: str). None => not applicable / could not check.
def check_fanout(out: Netlist, n: int):
    mfo = out.max_gate_fanout()
    return (mfo <= n, f"max fanout {mfo} (limit {n})")


def check_basis(out: Netlist, basis: set, node: str | None):
    gates = fanin_cone_gates(out, node) if node else out.gates
    allowed = basis | {"buf"}
    bad = Counter(g[0] for g in gates if g[0] not in allowed)
    scope = f"cone({node})" if node else "netlist"
    if not gates:
        return (None, f"{scope}: no gates found (node missing?)")
    if bad:
        return (False, f"{scope}: {sum(bad.values())} gate(s) outside {sorted(basis)}: {dict(bad)}")
    return (True, f"{scope}: all {len(gates)} gates in {sorted(basis)}")


def check_inverter_collapse(out: Netlist, _p=None):
    not_out = {g[3] for g in out.gates if g[0] == "not"}
    pairs = [g[1] for g in out.gates if g[0] == "not" and g[2] and g[2][0] in not_out]
    if pairs:
        return (False, f"{len(pairs)} back-to-back NOT->NOT pair(s) remain")
    return (True, "no NOT->NOT adjacency")


def check_node_depth(out: Netlist, node: str, k: int):
    d = node_depth(out, node)
    if d == 0 and node not in out.pos and node not in {q for _, q, _ in out.dffs}:
        return (None, f"node {node} not found in output")
    return (d <= k, f"depth({node}) = {d} (target <= {k}, logic-level def)")


def check_max_depth_reduced(base: Netlist, out: Netlist):
    # Advisory only: whole-design depth on the FINAL netlist is confounded by later basis
    # remapping / gate decomposition (which add logic levels) and by the depth definition,
    # so this reports the before/after logic depth without scoring pass/fail.
    b, o = max_depth(base), max_depth(out)
    arrow = "->" if o != b else "=="
    return (None, f"max logic depth {b} {arrow} {o} (advisory: not scored)")


def check_all_outputs_depth(out: Netlist, k: int):
    bad = {p: d for p, d in po_depths(out).items() if d > k}
    if bad:
        worst = max(bad.values())
        return (False, f"{len(bad)} output(s) exceed depth {k} (worst {worst})")
    return (True, f"all {len(out.pos)} outputs within depth {k}")


def check_dangling(out: Netlist):
    live = reachable_outputs(out)
    dead = [g for g in out.gates if g[3] not in live]
    if dead:
        kinds = Counter(g[0] for g in dead)
        return (False, f"{len(dead)} gate(s) not reachable from any PO/flop: {dict(kinds)}")
    return (True, "no dangling gates (all reach a PO/flop)")


def check_redundant(out: Netlist):
    sig = Counter((g[0], tuple(sorted(g[2]))) for g in out.gates)
    dups = {k: c for k, c in sig.items() if c > 1}
    if dups:
        extra = sum(c - 1 for c in dups.values())
        return (False, f"{extra} redundant gate(s) share (type,inputs) with another")
    return (True, "no duplicate (type,inputs) gates remain")


def check_const_prop(out: Netlist, gtype: str, value: str | None):
    bad = [g for g in out.gates if g[0] == gtype and gate_has_const_input(g, value)]
    vtxt = f"constant-{value}" if value else "constant"
    if bad:
        return (False, f"{len(bad)} {gtype.upper()} gate(s) still have a {vtxt} input")
    return (True, f"no {gtype.upper()} gate retains a {vtxt} input")


def check_dedicated_buffer(base: Netlist, out: Netlist, sig: str):
    want = loads_of(base, sig)
    bufs = [g for g in out.gates if g[0] == "buf" and g[2] and g[2][0] == sig]
    direct_nonbuf = [g for g in out.gates
                     if g[0] != "buf" and sig in g[2]] + [1 for _, _, d in out.dffs if d == sig]
    ok = (len(bufs) == want) and not direct_nonbuf
    detail = f"{len(bufs)} dedicated BUF(s) on {sig} (expect {want} = its loads)"
    if direct_nonbuf:
        detail += f"; {len(direct_nonbuf)} load(s) still driven directly"
    return (ok, detail)


def check_signal_fanout(out: Netlist, sig: str, n: int):
    fo = loads_of(out, sig)
    return (fo <= n, f"fanout({sig}) = {fo} (limit {n}, incl. flop control pins)")


def check_rename(out: Netlist, old: str, new: str):
    names = all_names(out)
    old_gone, new_here = old not in names, new in names
    if old_gone and new_here:
        return (True, f"{old} -> {new} (old absent, new present)")
    return (False, f"rename incomplete: {old} {'absent' if old_gone else 'STILL PRESENT'}, "
                   f"{new} {'present' if new_here else 'MISSING'}")


def check_decompose_in_cone(out: Netlist, node: str, src: str):
    cone = fanin_cone_gates(out, node)
    remain = [g for g in cone if g[0] == src]
    if not cone:
        return (None, f"cone({node}) empty (node missing?)")
    if remain:
        return (False, f"{len(remain)} {src.upper()} gate(s) remain in cone({node})")
    return (True, f"no {src.upper()} gates in cone({node}) ({len(cone)} gates)")


def check_type_replaced(base: Netlist, out: Netlist, src: str, mult: int | None, tgt: str | None):
    bc, oc = base.gate_counts(), out.gate_counts()
    remain = oc.get(src, 0)
    detail = f"{src.upper()} remaining {remain}"
    ok = remain == 0
    if mult and tgt:
        added = oc.get(tgt, 0) - bc.get(tgt, 0)
        expected = mult * bc.get(src, 0)
        detail += f"; {tgt.upper()} added {added} (expect {mult}x{bc.get(src,0)}={expected})"
        ok = ok and (added == expected)
    return (ok, detail)


# ── instruction classifier ────────────────────────────────────────────────────
class Goal:
    def __init__(self, kind: str, text: str, check):
        self.kind, self.text, self.check = kind, text, check


_NODE = r"(\w+(?:\[\d+\])?)"


def _depth_node(lo: str) -> str | None:
    """The node a depth goal targets, or None for a whole-design depth goal."""
    for pat in (
        rf"optimize\s+{_NODE}\s+to at most",           # "optimize n9 to at most 4 levels"
        rf"restructure\s+{_NODE}\s+with a target depth",  # "restructure n10 with a target depth of 4"
        rf"cone of\s+(?:output\s+|input\s+)?{_NODE}",  # "...cone of output n14...", "...cone of n8..."
    ):
        m = re.search(pat, lo)
        if m:
            return m.group(1)
    return None


def _depth_target(lo: str) -> int | None:
    """The depth bound K in a node depth goal (`<= K` / `at most K` / `depth K`)."""
    m = (re.search(r"at most\s+(\d+)\s+level", lo)
         or re.search(r"target depth(?:\s+of)?\s+(\d+)", lo)
         or re.search(r"depth\s+(\d+)\s+or less", lo)
         or re.search(r"depth of the cone of\s+\w+(?:\[\d+\])?\s+to\s+(\d+)", lo)
         or re.search(r"targeting depth\s+(\d+)", lo)
         or re.search(r"\bto\s+(?:at most\s+)?(\d+)\s+levels?", lo))
    return int(m.group(1)) if m else None


def classify_line(line: str) -> Goal | None:
    lo = line.lower()
    # Analysis questions ("How many X were removed?") are never transform goals. Transform
    # instructions are imperative and end with '.', so a trailing '?' is a reliable reject —
    # without this, a report/count query gets mis-scored as a goal (e.g. a "redundant" or
    # "const-prop" predicate off "How many ... were eliminated?").
    if line.rstrip().endswith("?"):
        return None
    is_question = False

    # GLOBAL fanout limit only: "no gate drives more than N loads" or netlist-wide
    # "fanout optimization ... maximum fanout N". Signal-scoped buffering ("on the clock
    # signal n0", "each load of n2") is a distinct goal deferred to a later phase, and
    # analysis questions ("what is the fanout of n0") are skipped.
    if not is_question and "signal" not in lo:            # signal-scoped buffering is Phase 3
        m = re.search(r"no gate\b.{0,20}?drives more than\s+(\d+)\s+load", lo)
        if not m and "fanout optimization" in lo:
            m = re.search(r"maximum fanout\s+(\d+)", lo)
        if m:
            n = int(m.group(1))
            return Goal("fanout", line, lambda b, o, n=n: check_fanout(o, n))

    # basis remap — cone: "convert the logic cone of [output] X to use only <BASIS> gates".
    # Excludes type-specific "replace all <TYPE> gates in the cone" (a decompose goal that
    # leaves other gate types in place — deferred to a later phase).
    mc = re.search(r"cone of\s+(?:output\s+|input\s+)?(\w+(?:\[\d+\])?)", lo)
    decompose_in_cone = "replace all" in lo or bool(re.search(r"\ball\b.*\bgates?\b.*\bcone", lo))
    if mc and "only" in lo and not decompose_in_cone:
        node, basis = mc.group(1), extract_basis(line)
        if basis:
            return Goal("basis-cone", line, lambda b, o, n=node, s=basis: check_basis(o, s, n))

    # basis remap — whole netlist: "reconstruct the entire netlist using only <BASIS> gates"
    if ("reconstruct" in lo or "entire netlist" in lo or "whole netlist" in lo) and "only" in lo:
        basis = extract_basis(line)
        if basis:
            return Goal("basis-netlist", line, lambda b, o, s=basis: check_basis(o, s, None))

    # inverter collapse: "collapse back-to-back inverters" / "NOT followed by NOT"
    if ("back-to-back" in lo or "not followed by not" in lo) or ("collapse" in lo and "invert" in lo):
        return Goal("inverter-collapse", line, lambda b, o: check_inverter_collapse(o))

    # ── Phase 2: depth goals ──────────────────────────────────────────────────
    # Require a transform verb so analysis queries ("compute/determine the depth ...", which
    # need no '?') are not mistaken for depth-reduction goals.
    depth_verb = any(v in lo for v in ("reduce", "optimize", "minimize", "restructure",
                                       "flatten", "shorten"))
    if not is_question and ("depth" in lo or re.search(r"\blevels?\b", lo)) and depth_verb:
        node = _depth_node(lo)
        k = _depth_target(lo)
        if node and k is not None:                              # node/cone depth <= K
            return Goal("depth-node", line, lambda b, o, n=node, kk=k: check_node_depth(o, n, kk))
        me = re.search(r"each output with depth greater than\s+(\d+)", lo)
        if me:                                                  # all POs <= K
            kk = int(me.group(1))
            return Goal("depth-outputs", line, lambda b, o, kk=kk: check_all_outputs_depth(o, kk))
        if node is None and ("critical path" in lo or "logic depth" in lo
                             or "maximum path depth" in lo or "path depth" in lo):
            return Goal("depth-global", line, check_max_depth_reduced)  # depth not worse than input

    # ── Phase 2: whole-design type replacement with exact-count delta ─────────
    # "convert/replace/rewrite all|every <SRC> gates ... [to N-<TGT> / with <TGT>-only]".
    # Excludes cone-scoped ("in the cone") and constant-input ("tied to constant") variants,
    # which are decompose / const-prop goals handled in a later phase.
    mt = re.search(r"(?:replace|convert|rewrite)\s+(?:all|every)\s+(?:2-input\s+)?"
                   r"(xor|xnor|and|or|nand|nor)\b", lo)
    if mt and "cone" not in lo and "constant" not in lo and "tied to" not in lo:
        src = mt.group(1)
        mc = re.search(r"(\d+)\s*-?\s*(nand|nor|and|or)\b", lo)   # explicit "4-NAND" / "4 NOR"
        mult = int(mc.group(1)) if mc else None
        tgt = mc.group(2) if mc else None
        return Goal("type-replace", line,
                    lambda b, o, s=src, m=mult, t=tgt: check_type_replaced(b, o, s, m, t))

    # ── Phase 3 ───────────────────────────────────────────────────────────────
    # decompose / replace a specific gate type WITHIN a cone (rest of cone left as-is)
    mdc = re.search(r"(?:decompose|replace)\s+all\s+(?:2-input\s+)?"
                    r"(xor|xnor|and|or|nand|nor)\s+gates?\b.*\bcone of\s+"
                    r"(?:output\s+|input\s+)?(\w+(?:\[\d+\])?)", lo)
    if mdc and "constant" not in lo and "tied to" not in lo:
        src, node = mdc.group(1), mdc.group(2)
        return Goal("decompose-cone", line,
                    lambda b, o, s=src, n=node: check_decompose_in_cone(o, n, s))

    # constant propagation on a gate type: no such gate keeps the constant input
    if "propagat" in lo or "tied to" in lo or ("simplify" in lo and "constant" in lo):
        mtype = re.search(r"\b(and|or|nand|nor|xor|xnor)\s+gates?\b", lo)
        mval = re.search(r"constant[- ]?([01])", lo) or re.search(r"'b([01])", lo)
        if mtype:
            gt = mtype.group(1)
            val = mval.group(1) if mval else None
            return Goal("const-prop", line, lambda b, o, g=gt, v=val: check_const_prop(o, g, v))

    # dangling / floating removal, and redundant (duplicate) removal
    if ("dangling" in lo or "floating" in lo) and ("remove" in lo or "sweep" in lo):
        return Goal("dangling", line, lambda b, o: check_dangling(o))
    if "redundant" in lo and "remove" in lo:
        return Goal("redundant", line, lambda b, o: check_redundant(o))

    # dedicated per-load buffering of a named signal (with BUF-added == its load count)
    md = re.search(r"insert a buf gate on signal\s+(\w+(?:\[\d+\])?)", lo)
    if md and ("dedicated" in lo or "each load" in lo):
        sig = md.group(1)
        return Goal("dedicated-buf", line, lambda b, o, s=sig: check_dedicated_buffer(b, o, s))

    # single-signal (clock/reset) fanout buffering: the signal's own fanout <= N
    ms = re.search(r"insert buffers on the (?:clock|reset|set)?\s*signal\s+(\w+(?:\[\d+\])?)", lo)
    if ms and ("fanout" in lo or "load" in lo):
        sig = ms.group(1)
        mn = (re.search(r"more than\s+(\d+)\s+load", lo)
              or re.search(r"at most\s+(\d+)\s+load", lo)
              or re.search(r"fanout[^\d]*(\d+)", lo))
        if mn:
            n = int(mn.group(1))
            return Goal("signal-fanout", line,
                        lambda b, o, s=sig, nn=n: check_signal_fanout(o, s, nn))

    # rename a gate / wire / signal: old identifier gone, new present
    mr = (re.search(r"rename\s+(?:internal\s+)?(?:gate|wire|signal|node)?\s*"
                    r"(\w+(?:\[\d+\])?)\s+to\s+(\w+)", lo)
          or re.search(r"change the identifier of\s+(?:gate|wire|signal)?\s*"
                       r"(\w+(?:\[\d+\])?)\s+to\s+(\w+)", lo)
          or re.search(r"update the name of\s+(?:signal|wire|gate)?\s*"
                       r"(\w+(?:\[\d+\])?)\s+to\s+(\w+)", lo))
    if mr:
        old, new = mr.group(1), mr.group(2)
        return Goal("rename", line, lambda b, o, a=old, c=new: check_rename(o, a, c))

    return None


_QUERY_PREFIX = ("how ", "what ", "which ", "does ", "do ", "list ", "report ", "derive ",
                 "count ", "compute ", "calculate ", "determine ", "express ", "prove ",
                 "check ", "are there", "is there", "write the")


def _is_query(line: str) -> bool:
    """A reporting/analysis instruction (asks for an answer, not a netlist transform)."""
    lo = line.lower()
    return lo.rstrip().endswith("?") or lo.startswith(_QUERY_PREFIX)


def classify_prompt(prompt: Path):
    """Return (goals, unclassified_transform_lines). Analysis questions are neither."""
    goals, unclassified = [], []
    for raw in prompt.read_text().splitlines():
        line = raw.strip()
        if not line:
            continue
        g = classify_line(line)
        if g:
            goals.append(g)
        elif any(v in line.lower() for v in TRANSFORM_VERBS) and not _is_query(line):
            unclassified.append(line)
    return goals, unclassified


# ── per-testcase evaluation ────────────────────────────────────────────────────
def eval_case(n: int, do_equiv: bool) -> dict | None:
    name = f"test{n:02d}"
    d = ROOT / "testcase" / name
    orig, out = d / f"{name}.v", d / f"{name}_out.v"
    prompt = d / "prompt.txt"
    if not orig.is_file() or not prompt.is_file():
        return None

    res = {"name": name, "goals": [], "unclassified": [], "equiv": None}
    base = augment_control_nets(Netlist(orig), orig)
    goals, unclassified = classify_prompt(prompt)
    res["unclassified"] = unclassified

    if not out.is_file():
        res["status"] = "NO-OUTPUT"
        res["goals"] = [(g.kind, None, "no output netlist", g.text) for g in goals]
        res["met"], res["total"], res["advisory"] = 0, len(goals), []
        return res

    outnet = augment_control_nets(Netlist(out), out)
    for g in goals:
        try:
            met, detail = g.check(base, outnet)
        except Exception as e:                       # a predicate bug must not abort the sweep
            met, detail = None, f"check error: {e}"
        res["goals"].append((g.kind, met, detail, g.text))

    if do_equiv and find_abc():
        res["equiv"] = cec(out, orig)

    # Advisory results (met is None) are informational — not scored for pass/fail.
    scored = [(k, m, d, t) for k, m, d, t in res["goals"] if m is not None]
    met = sum(1 for _, m, _, _ in scored if m is True)
    total = len(scored)
    res["met"], res["total"] = met, total
    res["advisory"] = [(k, d) for k, m, d, t in res["goals"] if m is None]
    if total == 0:
        res["status"] = "ADVISORY" if res["advisory"] else "NO-GOALS"
    elif met == total:
        res["status"] = "PASS"
    else:
        res["status"] = "UNMET"
    return res


def _goal_status(met) -> str:
    return {True: "pass", False: "fail", None: "advisory"}[met]


def _emit_json(rows: list) -> None:
    out = []
    for r in rows:
        out.append({
            "name": r["name"],
            "status": r["status"],
            "equiv": r["equiv"],
            "met": r.get("met", 0),
            "total": r.get("total", 0),
            "goals": [{"kind": k, "status": _goal_status(m), "detail": d, "instruction": t}
                      for k, m, d, t in r["goals"]],
            "unclassified": r.get("unclassified", []),
        })
    print(json.dumps(out, indent=2))


def _emit_detail(rows: list) -> None:
    sym = {"pass": "PASS", "fail": "FAIL", "advisory": "~adv"}
    for r in rows:
        head = f"{r['name']}  [{r['status']}]  goal {r.get('met',0)}/{r.get('total',0)}"
        if r["equiv"]:
            head += f"  equiv={r['equiv']}"
        print(f"\n{head}\n" + "-" * len(head))
        for k, m, d, t in r["goals"]:
            print(f"  {sym[_goal_status(m)]:5} {k:18} {d}")
            print(f"        instr: {t}")
        for line in r.get("unclassified", []):
            print(f"  {'?':5} {'unclassified':18} {line}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=40)
    ap.add_argument("--case", type=int)
    ap.add_argument("--skip-equiv", action="store_true", help="goal axis only, no ABC cec")
    ap.add_argument("--detail", action="store_true", help="per-instruction pass/fail breakdown")
    ap.add_argument("--json", action="store_true", help="emit machine-readable per-goal results")
    a = ap.parse_args()

    nums = [a.case] if a.case else range(a.lo, a.hi + 1)
    rows = [r for r in (eval_case(n, not a.skip_equiv) for n in nums) if r is not None]

    if a.json:
        _emit_json(rows)
        return
    if a.detail:
        _emit_detail(rows)
        return

    print(f"{'case':7} {'status':9} {'goal':6} {'equiv':10} notes")
    print("-" * 84)
    for r in rows:
        unmet = [f"{k}: {d}" for k, m, d, t in r["goals"] if m is False]
        note = "; ".join(unmet)
        for k, d in r.get("advisory", []):
            note += f"  ~{k}: {d}"
        if r["unclassified"]:
            note += f"  [unclassified x{len(r['unclassified'])}]"
        goalcol = f"{r.get('met', 0)}/{r.get('total', 0)}"
        print(f"{r['name']:7} {r['status']:9} {goalcol:6} {str(r['equiv'] or '-'):10} {note[:60]}",
              flush=True)

    print("-" * 84)
    with_goals = [r for r in rows if r["total"] > 0 and r["status"] != "NO-OUTPUT"]
    goals_total = sum(r["total"] for r in with_goals)
    goals_met = sum(r["met"] for r in with_goals)
    unclassified = sum(len(r["unclassified"]) for r in rows)
    print(f"status: {dict(Counter(r['status'] for r in rows))}")
    if goals_total:
        print(f"GOAL: {goals_met}/{goals_total} transform instructions verified achieved "
              f"across {len(with_goals)} cases")
    if unclassified:
        print(f"UNCLASSIFIED: {unclassified} transform-looking lines not yet checked "
              f"(later phases)")
    # exit non-zero only on a definite failure (a checked goal that is UNMET)
    bad = any(m is False for r in rows for _, m, _ in r["goals"])
    sys.exit(1 if bad else 0)


if __name__ == "__main__":
    main()
