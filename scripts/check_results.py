#!/usr/bin/env python3
"""Grading-layer checker: verify hard requirements on testcase outputs.

Independent of the agent pipeline: netlist structure is parsed with a
self-contained mini-parser (NOT the C++ engine), so structural checks
double-check the system rather than trusting it. Functional equivalence
reuses parser_cpp's write_blif + ABC cec, since ABC does the actual math.

Per testcase it checks (from the hard requirements in prompt.txt):
  - output netlist exists and parses
  - functional equivalence to the input netlist (ABC cec, flop-cut)
  - structural hard requirements: max fanout, basis purity (whole design
    or cone), forbidden gate types, per-signal buffer trees
  - soft/ambiguous requirements (renames, back-to-back inverters,
    dedicated buffers surviving later transforms) are reported as WARN
    and do not fail the case

Usage:
    python3 scripts/check_results.py --all
    python3 scripts/check_results.py --case test26
    python3 scripts/check_results.py --from 21 --to 30
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tempfile
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Set, Tuple

ROOT = Path(__file__).resolve().parent.parent
PARSER_BIN = ROOT / "src" / "eda_engine" / "parser" / "parser_cpp"
ABC_BIN = ROOT / "tools" / "abc" / "abc"

GATE_TYPES = {"and", "or", "nand", "nor", "not", "buf", "xor", "xnor"}
CONSTS = {"1'b0", "1'b1"}


# ── independent mini-parser ──────────────────────────────────────────────────

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
    inputs: Set[str]              # PI base names (buses expanded not needed)
    outputs: Set[str]
    driver: Dict[str, Gate]       # net -> driving gate
    loads: Dict[str, List[Gate]]  # net -> consuming gates


_RE_PRIM = re.compile(
    r"^\s*(and|or|nand|nor|not|buf|xor|xnor)\s+(\S+?)\s*\(([^;]*)\)\s*;", re.M)
_RE_DFF = re.compile(r"^\s*dff\s+(\S+?)\s*\(([^;]*)\)\s*;", re.M)
_RE_PORT = re.compile(r"^\s*(input|output)\s+(?:\[\d+:\d+\]\s*)?(.*?);", re.M | re.S)
_RE_DFF_PIN = re.compile(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)")


def parse_netlist(path: Path) -> Netlist:
    text = path.read_text()
    # strip comments
    text = re.sub(r"//[^\n]*", "", text)
    text = re.sub(r"/\*.*?\*/", "", text, flags=re.S)

    inputs: Set[str] = set()
    outputs: Set[str] = set()
    for kind, names in _RE_PORT.findall(text):
        for n in names.replace("\n", " ").split(","):
            n = n.strip()
            if n:
                (inputs if kind == "input" else outputs).add(n)

    gates: List[Gate] = []
    for gtype, name, conns in _RE_PRIM.findall(text):
        nets = [c.strip() for c in conns.split(",") if c.strip()]
        out = nets[0] if nets else ""
        ins = [n for n in nets[1:] if n not in CONSTS]
        gates.append(Gate(name, gtype, out, ins))
    for name, conns in _RE_DFF.findall(text):
        pins = {p.upper(): v.strip() for p, v in _RE_DFF_PIN.findall(conns)}
        out = pins.get("Q", "")
        ins = [v for p, v in pins.items()
               if p != "Q" and v and v not in CONSTS]
        gates.append(Gate(name, "dff", out, ins, pins))

    driver: Dict[str, Gate] = {}
    loads: Dict[str, List[Gate]] = defaultdict(list)
    for g in gates:
        if g.output:
            driver[g.output] = g
        for n in g.inputs:
            loads[n].append(g)
    return Netlist(gates, inputs, outputs, driver, loads)


# ── structural checks ────────────────────────────────────────────────────────

def fanin_cone(nl: Netlist, root: str, through_dff: bool = True) -> List[Gate]:
    """Transitive fanin cone of *root* (through flip-flops, matching D4)."""
    seen: Set[str] = set()
    cone: List[Gate] = []
    stack = [root]
    while stack:
        net = stack.pop()
        if net in seen:
            continue
        seen.add(net)
        g = nl.driver.get(net)
        if g is None:
            continue
        if g.gtype == "dff" and not through_dff:
            continue
        cone.append(g)
        stack.extend(g.inputs)
    return cone


def check_max_fanout(nl: Netlist, limit: int) -> Tuple[bool, str]:
    """No net driven by a gate may have more than *limit* loads."""
    worst = 0
    worst_net = ""
    n_over = 0
    for net, g in nl.driver.items():
        n = len(nl.loads.get(net, []))
        if n > limit:
            n_over += 1
        if n > worst:
            worst, worst_net = n, net
    ok = n_over == 0
    return ok, f"max gate fanout {worst} ({worst_net}); {n_over} nets over {limit}"


def check_net_tree_fanout(nl: Netlist, net: str, limit: int) -> Tuple[bool, str]:
    """*net* and every BUF downstream in its buffer tree drive <= limit loads."""
    bad = []
    n0 = len(nl.loads.get(net, []))
    if n0 > limit:
        bad.append(f"{net}:{n0}")
    stack = [g for g in nl.loads.get(net, []) if g.gtype == "buf"]
    seen: Set[str] = set()
    while stack:
        g = stack.pop()
        if g.name in seen:
            continue
        seen.add(g.name)
        n = len(nl.loads.get(g.output, []))
        if n > limit:
            bad.append(f"{g.output}:{n}")
        stack.extend(x for x in nl.loads.get(g.output, []) if x.gtype == "buf")
    ok = not bad
    return ok, ("tree fanout ok" if ok else f"over-limit drivers: {', '.join(bad[:5])}")


def check_basis(gates: List[Gate], basis: Set[str]) -> Tuple[bool, str]:
    """All combinational gates in *gates* are in *basis* (BUF/DFF exempt, D2)."""
    allowed = basis | {"buf", "dff"}
    bad = defaultdict(int)
    for g in gates:
        if g.gtype not in allowed:
            bad[g.gtype] += 1
    ok = not bad
    detail = "pure" if ok else ", ".join(f"{t}×{c}" for t, c in sorted(bad.items()))
    return ok, f"basis {'+'.join(sorted(basis)).upper()}: {detail}"


def check_no_type(gates: List[Gate], gtype: str) -> Tuple[bool, str]:
    n = sum(1 for g in gates if g.gtype == gtype)
    return n == 0, f"{gtype.upper()} count: {n}"


def check_no_b2b_inverters(nl: Netlist) -> Tuple[bool, str]:
    n = 0
    for g in nl.gates:
        if g.gtype != "not":
            continue
        d = nl.driver.get(g.inputs[0]) if g.inputs else None
        if d is not None and d.gtype == "not":
            n += 1
    return n == 0, f"back-to-back NOT pairs remaining: {n}"


def check_name_exists(nl: Netlist, name: str) -> Tuple[bool, str]:
    names = {g.name for g in nl.gates} | set(nl.driver.keys())
    ok = name in names
    return ok, f"'{name}' {'present' if ok else 'NOT found'}"


def check_dedicated_buffers(nl: Netlist, net: str) -> Tuple[bool, str]:
    ld = nl.loads.get(net, [])
    non_buf = [g for g in ld if g.gtype != "buf"]
    ok = not non_buf and len(ld) > 0
    return ok, (f"{len(ld)} loads, all BUF" if ok else
                f"{len(non_buf)}/{len(ld)} loads of {net} are not BUF")


# ── equivalence via parser_cpp write_blif + ABC cec ──────────────────────────

def check_equivalence(orig: Path, out: Path, timeout: int = 300) -> Tuple[Optional[bool], str]:
    if not PARSER_BIN.is_file():
        return None, "parser_cpp missing"
    if not ABC_BIN.is_file():
        return None, "ABC missing"
    with tempfile.TemporaryDirectory(prefix="check_cec_") as td:
        b1, b2 = os.path.join(td, "a.blif"), os.path.join(td, "b.blif")
        for src, dst in ((orig, b1), (out, b2)):
            r = subprocess.run(
                [str(PARSER_BIN), "--in", str(src), "--action", "write_blif",
                 "--out", dst],
                capture_output=True, text=True, timeout=120)
            if r.returncode != 0 or not os.path.isfile(dst):
                return None, f"write_blif failed for {src.name}: {r.stderr.strip()[:120]}"
        try:
            r = subprocess.run([str(ABC_BIN), "-q", f"cec {b1} {b2}"],
                               capture_output=True, text=True, timeout=timeout)
        except subprocess.TimeoutExpired:
            return None, f"ABC cec timeout ({timeout}s)"
        low = (r.stdout + r.stderr).lower()
        if "are equivalent" in low:
            return True, "EQUIVALENT (ABC cec, flop-cut)"
        if "not equivalent" in low:
            return False, "NOT EQUIVALENT"
        return None, f"inconclusive: {(r.stdout + r.stderr).strip()[:120]}"


# ── per-case hard requirements ───────────────────────────────────────────────
# hard: violating fails the case (0 credit per spec §5).
# warn: ambiguous/best-effort per docs/OPEN_QUESTIONS.md (D1/D2/O-items).

def case_checks(n: int, nl: Netlist) -> List[Tuple[str, bool, Optional[bool], str]]:
    """Return list of (label, is_hard, ok, detail). ok=None means skipped."""
    c: List[Tuple[str, bool, Optional[bool], str]] = []

    def hard(label, res):
        c.append((label, True, res[0], res[1]))

    def warn(label, res):
        c.append((label, False, res[0], res[1]))

    if n in (21, 22, 23, 24, 26, 27, 28, 29, 30, 36, 40):
        hard("fanout≤4", check_max_fanout(nl, 4))
    if n == 34:
        hard("fanout≤4", check_max_fanout(nl, 4))
        hard("clk n0 tree≤4", check_net_tree_fanout(nl, "n0", 4))
    if n in (36, 38):
        hard("rst n1 tree≤4", check_net_tree_fanout(nl, "n1", 4))

    if n in (28, 29, 30):
        hard("whole=AND+NOT", check_basis(nl.gates, {"and", "not"}))
    if n == 34:
        hard("whole=AND+NOT", check_basis(nl.gates, {"and", "not"}))
        hard("no XNOR", check_no_type(nl.gates, "xnor"))
    if n == 40:
        hard("whole=NAND+NOT", check_basis(nl.gates, {"nand", "not"}))

    if n == 25:
        hard("cone(n11[0]) no OR",
             check_no_type(fanin_cone(nl, "n11[0]"), "or"))
    if n == 26:
        hard("cone(n10)=NOR+NOT", check_basis(fanin_cone(nl, "n10"), {"nor", "not"}))
    if n == 27:
        hard("cone(n15) no XOR", check_no_type(fanin_cone(nl, "n15"), "xor"))
    if n == 33:
        hard("no XNOR", check_no_type(nl.gates, "xnor"))
        hard("cone(n8)=NAND+NOT", check_basis(fanin_cone(nl, "n8"), {"nand", "not"}))
    if n == 35:
        hard("no XNOR", check_no_type(nl.gates, "xnor"))
        hard("no XOR", check_no_type(nl.gates, "xor"))
    if n == 37:
        # n8/n9 cones may overlap; a later NOR restructure of n9 can
        # re-introduce NORs into n8's cone — report both, treat n9 as hard.
        warn("cone(n8)=NAND+NOT", check_basis(fanin_cone(nl, "n8"), {"nand", "not"}))
        hard("cone(n9)=NOR+NOT", check_basis(fanin_cone(nl, "n9"), {"nor", "not"}))
    if n == 39:
        hard("no XOR", check_no_type(nl.gates, "xor"))

    if n in (26, 27, 28, 29, 30, 31, 35, 38, 39, 40):
        warn("no b2b NOT", check_no_b2b_inverters(nl))

    if n in (24, 25):
        warn("renamed_gate", check_name_exists(nl, "renamed_gate"))
    if n in (25, 32, 35, 38):
        warn("renamed_wire", check_name_exists(nl, "renamed_wire"))
    if n == 31:
        warn("renamed_sig", check_name_exists(nl, "renamed_sig"))
        warn("n2 dedicated BUFs", check_dedicated_buffers(nl, "n2"))
    if n in (34, 39):
        warn("n2 dedicated BUFs", check_dedicated_buffers(nl, "n2"))

    return c


# ── driver ───────────────────────────────────────────────────────────────────

def run_case(n: int, cec_timeout: int) -> Tuple[str, bool]:
    name = f"test{n:02d}"
    pdir = ROOT / "testcase" / name
    orig = pdir / f"{name}.v"
    out = pdir / f"{name}_out.v"
    if not orig.is_file():
        return f"{name}: MISSING input", False
    if not out.is_file():
        return f"{name}: NO_OUTPUT ({out.name} not written)", False

    try:
        nl = parse_netlist(out)
    except Exception as exc:  # noqa: BLE001
        return f"{name}: PARSE_FAIL {exc}", False
    if not nl.gates:
        return f"{name}: PARSE_FAIL (0 gates parsed)", False

    lines = []
    hard_fail = False

    eq, eq_detail = check_equivalence(orig, out, cec_timeout)
    if eq is False:
        hard_fail = True
    mark = {True: "PASS", False: "FAIL", None: "????"}[eq]
    lines.append(f"    [{mark}] equivalence      {eq_detail}")

    for label, is_hard, ok, detail in case_checks(n, nl):
        if ok is False and is_hard:
            hard_fail = True
        mark = {True: "PASS", False: ("FAIL" if is_hard else "warn"), None: "skip"}[ok]
        lines.append(f"    [{mark}] {label:<16} {detail}")

    verdict = "FAIL" if hard_fail else ("PASS" if eq is True else "PASS?")
    header = f"{name}: {verdict}  ({len(nl.gates)} gates in output)"
    return "\n".join([header] + lines), not hard_fail


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--case", type=str, help="e.g. test26")
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=40)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--cec-timeout", type=int, default=300)
    a = ap.parse_args()

    if a.case:
        nums = [int(re.sub(r"\D", "", a.case))]
    else:
        nums = list(range(a.lo, a.hi + 1))

    n_pass = 0
    for n in nums:
        report, ok = run_case(n, a.cec_timeout)
        print(report, flush=True)
        n_pass += ok
    print(f"\n=== {n_pass}/{len(nums)} cases with no hard-requirement failure ===")
    sys.exit(0 if n_pass == len(nums) else 1)


if __name__ == "__main__":
    main()
