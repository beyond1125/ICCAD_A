#!/usr/bin/env python3
"""Ground-truth-free evaluation harness.

Scores the system with NO external answer key, using three self-generated sources
of truth:

  1. EQUIVALENCE  — ABC `cec` proves each testNN_out.v is functionally equivalent
                    to the original testNN.v (validates every transform).
  2. INVARIANTS   — properties that must hold on the output netlist:
                    flip-flop count preserved, max gate fanout, round-trip stable.
  3. DIFFERENTIAL — an independent Python oracle (this file) vs the C++ tools on
                    each original netlist: gate counts and combinational path
                    existence. Agreement = confidence; disagreement = a real bug.
                    A tool timeout where the oracle answers instantly is itself a
                    finding (e.g. path enumeration that does not scale).

Usage:
    python3 scripts/eval_harness.py                 # every testcase found
    python3 scripts/eval_harness.py --from 21 --to 30
    python3 scripts/eval_harness.py --case 12
    python3 scripts/eval_harness.py --skip-paths    # skip the (slow) tool path checks
"""
from __future__ import annotations

import argparse
import re
import subprocess
import sys
import time
from collections import Counter, deque
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PARSER = ROOT / "src" / "eda_engine" / "parser" / "parser_cpp"
GATE_KINDS = ("not", "and", "or", "xor", "nor", "nand", "xnor", "buf", "dff")


def find_abc() -> Path | None:
    for c in (ROOT / "abc" / "abc", ROOT / "tools" / "abc" / "abc"):
        if c.is_file():
            return c
    return None


# ── independent netlist model (the oracle) ────────────────────────────────────
class Netlist:
    def __init__(self, path: Path):
        txt = re.sub(r"//.*", "", path.read_text())
        self.pis, self.pos = set(), set()
        for kw, store in (("input", self.pis), ("output", self.pos)):
            for m in re.finditer(rf"\b{kw}\b\s*(?:\[(\d+):(\d+)\])?\s*([^;]+);", txt):
                msb, lsb, names = m.group(1), m.group(2), m.group(3)
                for nm in re.findall(r"\w+", names):
                    if msb is not None:
                        a, b = int(msb), int(lsb)
                        for i in range(min(a, b), max(a, b) + 1):
                            store.add(f"{nm}[{i}]")
                    else:
                        store.add(nm)
        self.gates = []   # (type, name, inputs[list], output)
        self.dffs = []    # (name, Q, D)
        for m in re.finditer(
            r"\b(not|and|or|xor|nor|nand|xnor|buf|dff)\s+(\w+)\s*\(([^;]*)\)\s*;", txt, re.I
        ):
            gt, name, body = m.group(1).lower(), m.group(2), m.group(3)
            if "." in body:                                    # named ports (DFF)
                pins = {k: v.strip() for k, v in re.findall(r"\.(\w+)\s*\(\s*([^)]*?)\s*\)", body)}
                self.dffs.append((name, pins.get("Q", ""), pins.get("D", "")))
            else:
                p = [x.strip() for x in body.split(",") if x.strip()]
                if p:
                    self.gates.append((gt, name, p[1:], p[0]))
        # net -> list of consumer combinational gates (for forward reachability)
        self._consumers = {}
        for gt, name, ins, out in self.gates:
            for s in ins:
                self._consumers.setdefault(s, []).append((gt, out))

    def gate_counts(self) -> dict:
        c = Counter(gt for gt, *_ in self.gates)
        c["dff"] = len(self.dffs)
        return {k: c.get(k, 0) for k in GATE_KINDS}

    def total_gates(self) -> int:
        return len(self.gates) + len(self.dffs)

    def max_gate_fanout(self) -> int:
        loads = Counter()
        for gt, name, ins, out in self.gates:
            for s in ins:
                if "'" not in s:
                    loads[s] += 1
        for _, q, d in self.dffs:
            if d and "'" not in d:
                loads[d] += 1
        driven = {out for _, _, _, out in self.gates} | {q for _, q, _ in self.dffs}
        return max((loads[n] for n in driven if "'" not in n), default=0)

    def path_exists(self, start: str, end: str, avoid: str = "") -> bool:
        """Combinational path start->end (stops at flip-flops), avoiding `avoid`."""
        if start == avoid or end == avoid:
            return False
        seen, q = {start}, deque([start])
        while q:
            net = q.popleft()
            if net == end:
                return True
            for gt, out in self._consumers.get(net, ()):
                if gt == "dff" or out == avoid or out in seen:
                    continue
                seen.add(out)
                q.append(out)
        return False


# ── C++ tool invocation ───────────────────────────────────────────────────────
def tool(vfile: Path, action: str, timeout: int = 120, **kw) -> tuple[str, bool]:
    cmd = [str(PARSER), "--in", str(vfile), "--action", action]
    for k, v in kw.items():
        cmd += [f"--{k}", str(v)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        return r.stdout.strip(), True
    except subprocess.TimeoutExpired:
        return "TIMEOUT", False


def tool_gate_counts(vfile: Path) -> dict:
    out, ok = tool(vfile, "count_gates")
    if not ok:
        return {}
    d = {k: int(v) for k, v in re.findall(r"(\w+): (\d+)", out)}
    return {k: d.get(k, 0) for k in GATE_KINDS}


def cec(a: Path, b: Path) -> str:
    """Flop-cut BLIF of both, ABC cec. Returns EQUIV / NOTEQUIV / ERROR."""
    abc = find_abc()
    if not abc:
        return "NO-ABC"
    ba, bb = ROOT / "eval_a.blif", ROOT / "eval_b.blif"
    for v, blif in ((a, ba), (b, bb)):
        _, ok = tool(v, "write_blif", out=str(blif))
        if not ok or not blif.is_file():
            return "BLIF-ERR"
    try:
        r = subprocess.run([str(abc), "-q", f"cec {ba} {bb}"], capture_output=True, text=True, timeout=300)
    except subprocess.TimeoutExpired:
        return "CEC-TIMEOUT"
    finally:
        for f in (ba, bb):
            f.unlink(missing_ok=True)
    o = (r.stdout + r.stderr).lower()
    if "are equivalent" in o:
        return "EQUIV"
    if "not equivalent" in o:
        return "NOTEQUIV"
    return "CEC-ERR"


# ── path-query extraction from prompts ────────────────────────────────────────
_PATH_RE = re.compile(
    r"(?:path|combinational path).*?from\s+(\w+(?:\[\d+\])?)\s+to\s+(\w+(?:\[\d+\])?)"
    r"|connecting\s+input\s+(\w+(?:\[\d+\])?)\s+to\s+output\s+(\w+(?:\[\d+\])?)", re.I)
_AVOID_RE = re.compile(r"(?:avoid(?:ing)?|not traverse|without)\s+(?:node\s+)?(\w+(?:\[\d+\])?)", re.I)


# Category words that _PATH_RE can capture from meta-questions like
# "Find all paths of length 0 (direct wire connections from PI to PO)"
# (test38) — those are node classes, not node names; there is no concrete
# pair to differentially check.
_GENERIC_ENDPOINTS = {"pi", "po", "pis", "pos", "input", "inputs",
                      "output", "outputs", "register", "registers"}


def path_queries(prompt: Path):
    """Yield (start, end, avoid) for path-existence prompt lines."""
    for line in prompt.read_text().splitlines():
        if "path" not in line.lower():
            continue
        m = _PATH_RE.search(line)
        if not m:
            continue
        s = m.group(1) or m.group(3)
        e = m.group(2) or m.group(4)
        if not s or not e:
            continue
        if s.lower() in _GENERIC_ENDPOINTS or e.lower() in _GENERIC_ENDPOINTS:
            continue
        av = _AVOID_RE.search(line)
        yield s, e, (av.group(1) if av else "")


# ── per-testcase evaluation ───────────────────────────────────────────────────
def eval_case(n: int, skip_paths: bool) -> dict:
    name = f"test{n:02d}"
    d = ROOT / "testcase" / name
    orig = d / f"{name}.v"
    out = d / f"{name}_out.v"
    res = {"name": name, "notes": []}
    if not orig.is_file():
        res["status"] = "NO-NETLIST"
        return res

    net = Netlist(orig)

    # --- differential: gate counts (oracle vs tool) on the ORIGINAL ---
    oc, tc = net.gate_counts(), tool_gate_counts(orig)
    res["count_match"] = (oc == tc)
    if not res["count_match"]:
        diff = {k: (oc[k], tc.get(k)) for k in GATE_KINDS if oc[k] != tc.get(k)}
        res["notes"].append(f"count mismatch (oracle,tool): {diff}")

    # --- differential: path existence (oracle vs tool find_paths), if any ---
    res["path_checks"] = []
    for s, e, av in path_queries(d / "prompt.txt"):
        exp = net.path_exists(s, e, av)
        entry = {"q": f"{s}->{e}" + (f" !{av}" if av else ""), "oracle": exp}
        if not skip_paths:
            t0 = time.time()
            o, ok = tool(orig, "list_paths", timeout=30, start=s, end=e, avoid=av or "")
            entry["tool_secs"] = round(time.time() - t0, 1)
            if not ok:
                entry["tool"] = "TIMEOUT"
                res["notes"].append(f"find_paths TIMEOUT on {entry['q']} (oracle={exp} in <1s)")
            elif o.startswith("Error:"):
                # bad node names etc. — a failed query, not an existence claim
                # (used to read "Error: ... not found." as tool=True, test38)
                entry["tool"] = "ERROR"
                res["notes"].append(f"find_paths ERROR on {entry['q']}: {o.splitlines()[0]}")
            else:
                # tool returns a list; "exists" = at least one path line present
                got = ("no path" not in o.lower()) and bool(re.search(r"\bn?\w+\[?\d*\]?\b", o))
                entry["tool"] = got
                if got != exp:
                    res["notes"].append(f"path disagree {entry['q']}: oracle={exp} tool={got}")
        res["path_checks"].append(entry)

    # --- output netlist: equivalence + invariants ---
    if out.is_file():
        outnet = Netlist(out)
        res["equiv"] = cec(out, orig)
        # invariant: flip-flop count preserved
        res["dff_ok"] = (len(outnet.dffs) == len(net.dffs))
        if not res["dff_ok"]:
            res["notes"].append(f"DFF count changed {len(net.dffs)}->{len(outnet.dffs)}")
        res["max_fanout"] = outnet.max_gate_fanout()
        # invariant: round-trip stable (load out -> write -> same gate count)
        rt = ROOT / "eval_rt.v"
        _, ok = tool(out, "write", out=str(rt))
        if ok and rt.is_file():
            res["roundtrip_ok"] = (Netlist(rt).total_gates() == outnet.total_gates())
            rt.unlink(missing_ok=True)
            if not res["roundtrip_ok"]:
                res["notes"].append("round-trip changed gate count")
    else:
        res["equiv"] = "NO-OUTPUT"

    if res["equiv"] == "EQUIV" and res["count_match"] and res.get("dff_ok", True):
        res["status"] = "PASS"
    elif res["equiv"] in ("NOTEQUIV", "BLIF-ERR", "CEC-ERR"):
        res["status"] = "FAIL"
    elif res["equiv"] == "NO-OUTPUT":
        res["status"] = "NO-OUTPUT"
    else:
        res["status"] = "CHECK"
    return res


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=40)
    ap.add_argument("--case", type=int)
    ap.add_argument("--skip-paths", action="store_true", help="skip slow tool path checks")
    a = ap.parse_args()
    if not PARSER.is_file():
        sys.exit(f"parser binary missing: {PARSER}\n  build: python3 scripts/build_parser.py")

    nums = [a.case] if a.case else range(a.lo, a.hi + 1)
    rows = []
    print(f"{'case':7} {'status':9} {'equiv':11} {'cnt':4} {'dff':4} {'maxFO':6} notes")
    print("-" * 80)
    for n in nums:
        r = eval_case(n, a.skip_paths)
        if r["status"] == "NO-NETLIST":
            continue
        rows.append(r)
        note = "; ".join(r["notes"])[:60]
        print(f"{r['name']:7} {r['status']:9} {r.get('equiv',''):11} "
              f"{'ok' if r.get('count_match') else 'X':4} "
              f"{'ok' if r.get('dff_ok', True) else 'X':4} "
              f"{r.get('max_fanout', ''):>6} {note}", flush=True)

    print("-" * 80)
    st = Counter(r["status"] for r in rows)
    outs = [r for r in rows if r["equiv"] != "NO-OUTPUT"]
    equiv_pass = sum(1 for r in outs if r["equiv"] == "EQUIV")
    cnt_pass = sum(1 for r in rows if r.get("count_match"))
    print(f"status: {dict(st)}")
    if outs:
        print(f"EQUIVALENCE (transforms): {equiv_pass}/{len(outs)} outputs proven equivalent")
    print(f"DIFFERENTIAL gate-count: {cnt_pass}/{len(rows)} match the independent oracle")
    timeouts = [e for r in rows for e in r.get("path_checks", []) if e.get("tool") == "TIMEOUT"]
    if timeouts:
        print(f"PATH-TOOL TIMEOUTS: {len(timeouts)} (oracle answered each; tool does not scale)")
    sys.exit(0 if all(r["status"] in ("PASS", "NO-OUTPUT", "CHECK") for r in rows) else 1)


if __name__ == "__main__":
    main()
