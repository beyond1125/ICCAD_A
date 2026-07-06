#!/usr/bin/env python3
"""Grade the LLM agent's ANALYSIS answers against oracle ground truth.

Reads each testcase's `prompt.txt` (one request per line) and its recorded
`<case>.log` (`#RESPONSE <n>` ... `#END <n>` blocks — line N of prompt.txt is
response id N; line 1 is the testcase-init) and, for every request that asks
an analysis QUESTION about the *original, untransformed* netlist, extracts the
agent's claimed answer and compares it against `scripts/netlist_oracle.py`
(imported directly — this file does NOT re-implement graph algorithms).

Independent of the pipeline in the same spirit as `check_results.py` and
`eval_harness.py`: it never trusts the agent's own tool output, only the
prose it actually wrote back to the user, and it grades against the oracle's
independent re-implementation plus (for numeric adjudication of definitional
gaps) a cross-check against `parser_cpp` itself.

STATE GATING: an analysis answer is only meaningful while the design still
equals the ORIGINAL netlist. The first "transform" (or unsupported-mutation)
line in prompt.txt moves the design state forward; every analysis line at or
after that point is graded SKIPPED-STATE, not compared to the oracle (which
only ever answers questions about the untouched input `.v`). test01-test20
contain no transform lines, so they are graded end-to-end; test21+ typically
only have their gate_count_breakdown line (before the first transform) graded.

Usage:
    python3 scripts/check_answers.py --case test02
    python3 scripts/check_answers.py --all
    python3 scripts/check_answers.py --from 1 --to 20
    python3 scripts/check_answers.py --case test02 --log-dir /tmp/myfixtures
    python3 scripts/check_answers.py --selftest
"""
from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, List, Optional, Tuple

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(Path(__file__).resolve().parent))

import netlist_oracle as oracle  # noqa: E402

PARSER_BIN = ROOT / "src" / "eda_engine" / "parser" / "parser_cpp"
ABC_BIN = ROOT / "tools" / "abc" / "abc"

GATE_TYPE_NAMES = ("NOT", "AND", "OR", "NAND", "NOR", "XOR", "XNOR", "BUF", "DFF")


# ── request classification ───────────────────────────────────────────────

# A net/gate token: n123, n123[4], g0, renamed_sig, bare identifiers... kept
# permissive (word chars + optional bit-select) since oracle lookups simply
# fail closed (KeyError-free: driver.get/loads.get return sensible defaults)
# if a name doesn't exist in the parsed netlist.
_TOK = r"[A-Za-z_][A-Za-z0-9_]*(?:\[\d+\])?"

_RE_INIT = re.compile(r"^this is the beginning of a new testcase", re.I)
_RE_LOAD = re.compile(r"please load the design from", re.I)
_RE_WRITE = re.compile(r"please write the current design to", re.I)

_RE_GATE_COUNT_BREAKDOWN = re.compile(
    r"count all the gates.*broken down by gate type", re.I)
_RE_TOTAL_GATE_COUNT = re.compile(
    r"(compute|what is) the total gate count", re.I)

_RE_PATH_EXISTS_AVOID = re.compile(
    r"(?:determine whether|verify whether).{0,40}path\b.*\bfrom\s+(?P<src>" + _TOK +
    r")\s+to\s+(?P<dst>" + _TOK + r").*(?:avoid|not travers\w*)\w*\s+(?:node\s+)?(?P<avoid>" + _TOK + r")",
    re.I)
_RE_PATH_EXISTS_AVOID2 = re.compile(
    r"path connecting input\s+(?P<src>" + _TOK + r")\s+to output\s+(?P<dst>" + _TOK +
    r")\s+exists while avoiding\s+(?P<avoid>" + _TOK + r")", re.I)
_RE_PATH_EXISTS_PLAIN = re.compile(
    r"does a combinational path (?:exist|from)\b.*from\s+(?:primary input\s+)?(?P<src>" + _TOK +
    r")\s+to\s+(?:primary output\s+|output\s+)?(?P<dst>" + _TOK + r")", re.I)
_RE_PATH_EXISTS_AVOID3 = re.compile(
    r"does a combinational path from\s+(?P<src>" + _TOK + r")\s+to\s+(?P<dst>" + _TOK +
    r")\s+exist that avoids\s+(?P<avoid>" + _TOK + r")", re.I)

_RE_LIST_PATHS = re.compile(
    r"list every path originating at (?:primary input\s+)?(?P<src>" + _TOK +
    r")\s+and terminating at (?:primary output\s+)?(?P<dst>" + _TOK + r")", re.I)
_RE_LIST_PATHS2 = re.compile(
    r"(?:provide a complete enumeration of paths|find all combinational paths)"
    r".*?between\s+(?P<src>" + _TOK + r")\s+and\s+(?P<dst>" + _TOK + r")", re.I)
_RE_LIST_PATHS3 = re.compile(
    r"find all combinational paths from (?:primary input\s+)?(?P<src>" + _TOK +
    r")\s+to (?:primary output\s+)?(?P<dst>" + _TOK + r")", re.I)

_RE_MAX_DEPTH_BETWEEN = re.compile(
    r"(?:compute the maximum logic depth from|determine the longest combinational path depth from|"
    r"calculate the critical path depth between)\s+(?:input\s+)?(?P<src>" + _TOK +
    r")\s+(?:to|and)\s+(?:output\s+)?(?P<dst>" + _TOK + r")", re.I)

_RE_FANOUT_COUNT = re.compile(
    r"(?:determine the number of gates driven by\s+|what is the fanout of (?:primary input\s+)?)"
    r"(?P<node>" + _TOK + r")", re.I)

_RE_SUCCESSORS = re.compile(
    r"(?:enumerate the immediate successors of gate|report every gate connected to the output of)\s+"
    r"(?P<node>" + _TOK + r")", re.I)

_RE_FANIN_CONE_SIZE = re.compile(
    r"how many gates are in the (?:fanin cone of|logic cone of)\s+(?:primary output\s+)?(?P<node>" + _TOK + r")",
    re.I)
_RE_FANIN_CONE_SIZE2 = re.compile(
    r"compute the transitive fanin cone of\s+(?:output\s+|primary output\s+)?(?P<node>" + _TOK + r")",
    re.I)

_RE_FANOUT_CONE_SIZE = re.compile(
    r"(?:compute the transitive fanout cone of|what is the transitive fanout of)\s+"
    r"(?:input\s+|primary input\s+)?(?P<node>" + _TOK + r")", re.I)

_RE_CONE_DEPTH = re.compile(
    r"compute the maximum logic depth of the fanin cone of\s+(?:output\s+|primary output\s+)?(?P<node>" + _TOK + r")",
    re.I)

_RE_SIGNAL_EQUIV = re.compile(
    r"(?:determine whether signals|check functional equivalence between (?:internal )?signals)\s+"
    r"(?P<a>" + _TOK + r")\s+and\s+(?P<b>" + _TOK + r")", re.I)
_RE_SIGNAL_EQUIV2 = re.compile(
    r"verify that\s+(?P<a>" + _TOK + r")\s+and\s+(?P<b>" + _TOK + r")\s+produce identical logic values",
    re.I)
_RE_SIGNAL_EQUIV3 = re.compile(
    r"check whether internal signals\s+(?P<a>" + _TOK + r")\s+and\s+(?P<b>" + _TOK +
    r")\s+are functionally equivalent", re.I)

_RE_ALWAYS_CONST = re.compile(
    r"is (?:output\s+)?(?P<node>" + _TOK + r")\s+always\s+(?P<val>0|1)\b", re.I)

_RE_PIO_COUNT = re.compile(
    r"determine the number of primary inputs and outputs|how many primary inputs and primary outputs",
    re.I)
_RE_PIO_LIST_IN = re.compile(r"list all the primary inputs.*bit widths", re.I)
_RE_PIO_LIST_OUT = re.compile(r"list all primary outputs.*bit widths", re.I)

_RE_FLOPS_BY_CLOCK = re.compile(
    r"list all flip-flops driven by clock\s+(?P<clk>" + _TOK + r")", re.I)

_RE_PI_TO_DFF_DEPTH = re.compile(
    r"maximum logic depth from any primary input to any dff d-pin", re.I)

_RE_GLOBAL_MAX_DEPTH = re.compile(
    r"maximum combinational (?:depth|logic depth) from any primary input to any primary output"
    r"|what is the maximum combinational logic depth in the design now"
    r"|what is the maximum combinational depth from any primary input to any primary output",
    re.I)

_RE_R2R_PATHS = re.compile(r"list all register-to-register paths", re.I)
_RE_R2R_DEPTH = re.compile(
    r"maximum combinational depth on any register-to-register path", re.I)

# transform / mutation intent verbs — a line matching this AND not ending in
# "?" is a transform request (also marks the state boundary).
_RE_TRANSFORM_INTENT = re.compile(
    r"\b(insert|reconstruct|convert|replace|decompose|collapse|merge|remove|delete|"
    r"rename|change the identifier|update the name|simplify|restructure|reduce|"
    r"eliminate|optimize|perform .*optimization|prune|sweep|trim|remap|rewrite|"
    r"try to (?:replace|restructure|optimize|insert|merge|reduce|rename|reconnect)|"
    r"reconnect)\b", re.I)

# unsupported analysis families: no oracle, or intrinsically requires the
# post-transform state to answer ("how many X were eliminated/added/removed",
# "how many X are now/currently in the design", equivalence-to-transformed-
# state checks, free-form gate listings/reports with no comparable oracle
# family, and other one-off phrasings the family list doesn't cover).
_RE_UNSUPPORTED = re.compile(
    r"boolean equation|boolean function|symmetric with respect to|articulation point"
    r"|deepest (?:fanin )?(?:logic )?cone|largest fanin cone"
    r"|how many .*(?:were|was) (?:eliminated|added|removed|merged|found)"
    r"|how many .*\b(?:now|currently)\b"
    r"|cut between any primary input"
    r"|enable or hold structures"
    r"|highest fanout"
    r"|does every path from.*pass through"
    r"|lies on any maximum-depth path"
    r"|reachable from\s+" + _TOK +
    r"|shared between the fanin cones"
    r"|depend on input"
    r"|find all paths of length 0"
    r"|logic expression for"
    r"|d input logic of the flip-flops"
    r"|(?:prove|verify|check whether|confirm) that the (?:transformed )?design"
    r"|verify functional equivalence between the current design"
    r"|functionally equivalent to the (?:netlist as last loaded|original)"
    r"|equivalent to the pre-transformation netlist"
    r"|what type of gate is\s+" + _TOK +
    r"|what is the maximum fanout of\s+" + _TOK + r"\s+now"
    r"|report (?:any|the number of each gate type)\b"
    r"|list all (?:nand|nor|xor|xnor|and|or|not|buf) gates in this design"
    r"|list all gates (?:that now connect|currently driven)"
    r"|does there exist any pair of internal signals"
    r"|floating inputs or unconnected output ports"
    r"|compute the fanin logic cone of.*and list all gates"
    r"|how many outputs have a logic depth greater than"
    r"|what is the depth of the cone of\s+" + _TOK + r"\s+now"
    r"|report the total\s+\w+\s+gate count after"
    r"|gates with one or more inputs tied to",
    re.I)


@dataclass
class Classified:
    qtype: str
    params: Dict[str, str] = field(default_factory=dict)


def classify_request(line: str) -> Classified:
    """Classify one prompt.txt line -> (qtype, params).

    qtype in {"protocol", "transform", "unsupported"} or one of the analysis
    family names listed in the module docstring / task spec.
    """
    s = line.strip()
    if not s:
        return Classified("protocol")
    if _RE_INIT.search(s) or _RE_LOAD.search(s) or _RE_WRITE.search(s):
        return Classified("protocol")

    is_question = s.rstrip().endswith("?")

    # unsupported families take priority over transform-intent verbs matching
    # inside a question (e.g. "How many X were eliminated?" contains no
    # transform verb itself, but guard order matters for e.g. "Simplify the
    # reported NAND gates..." which IS a transform, vs "How many NAND gates
    # were eliminated by constant propagation?" which is unsupported).
    if _RE_UNSUPPORTED.search(s):
        return Classified("unsupported")

    if not is_question and _RE_TRANSFORM_INTENT.search(s):
        return Classified("transform")

    if _RE_GATE_COUNT_BREAKDOWN.search(s):
        return Classified("gate_count_breakdown")
    if _RE_TOTAL_GATE_COUNT.search(s):
        return Classified("gate_count_breakdown")

    m = _RE_PATH_EXISTS_AVOID.search(s) or _RE_PATH_EXISTS_AVOID2.search(s) or \
        _RE_PATH_EXISTS_AVOID3.search(s)
    if m:
        return Classified("path_exists_avoiding", m.groupdict())
    m = _RE_PATH_EXISTS_PLAIN.search(s)
    if m:
        d = m.groupdict()
        d.setdefault("avoid", None)
        return Classified("path_exists_avoiding", d)

    m = _RE_LIST_PATHS.search(s) or _RE_LIST_PATHS2.search(s) or _RE_LIST_PATHS3.search(s)
    if m:
        return Classified("list_paths", m.groupdict())

    m = _RE_MAX_DEPTH_BETWEEN.search(s)
    if m:
        return Classified("max_depth_between", m.groupdict())

    if _RE_PI_TO_DFF_DEPTH.search(s):
        return Classified("pi_to_dff_depth")

    if _RE_GLOBAL_MAX_DEPTH.search(s):
        return Classified("global_max_depth")

    if _RE_R2R_DEPTH.search(s):
        return Classified("r2r_max_depth")

    if _RE_R2R_PATHS.search(s):
        return Classified("r2r_paths")

    m = _RE_CONE_DEPTH.search(s)
    if m:
        return Classified("cone_depth", m.groupdict())

    m = _RE_FANOUT_COUNT.search(s)
    if m:
        return Classified("fanout_count", m.groupdict())

    m = _RE_SUCCESSORS.search(s)
    if m:
        return Classified("successors", m.groupdict())

    m = _RE_FANIN_CONE_SIZE.search(s) or _RE_FANIN_CONE_SIZE2.search(s)
    if m:
        return Classified("fanin_cone_size", m.groupdict())

    m = _RE_FANOUT_CONE_SIZE.search(s)
    if m:
        return Classified("fanout_cone_size", m.groupdict())

    m = _RE_SIGNAL_EQUIV.search(s) or _RE_SIGNAL_EQUIV2.search(s) or _RE_SIGNAL_EQUIV3.search(s)
    if m:
        return Classified("signal_equiv", m.groupdict())

    m = _RE_ALWAYS_CONST.search(s)
    if m:
        return Classified("always_const", m.groupdict())

    if _RE_PIO_COUNT.search(s):
        return Classified("pio_count")
    if _RE_PIO_LIST_IN.search(s):
        return Classified("pio_list", {"which": "inputs"})
    if _RE_PIO_LIST_OUT.search(s):
        return Classified("pio_list", {"which": "outputs"})

    m = _RE_FLOPS_BY_CLOCK.search(s)
    if m:
        return Classified("flops_by_clock", m.groupdict())

    # fallthrough: any remaining transform-intent line even if phrased as a
    # question ("Try to ... ?") still mutates state.
    if _RE_TRANSFORM_INTENT.search(s):
        return Classified("transform")

    return Classified("unclassified")


# ── log parsing ──────────────────────────────────────────────────────────

_RE_RESPONSE_BLOCK = re.compile(
    r"#RESPONSE\s+(\d+)\s*\n(.*?)\n#END\s+\1\b", re.S)


def parse_log(log_path: Path) -> Dict[int, str]:
    """{response_id: response_text} for every #RESPONSE n ... #END n block."""
    text = log_path.read_text(errors="replace")
    out: Dict[int, str] = {}
    for m in _RE_RESPONSE_BLOCK.finditer(text):
        out[int(m.group(1))] = m.group(2)
    return out


_RE_LLM_ERROR = re.compile(r"error communicating with the llm service", re.I)


# ── claim extraction ─────────────────────────────────────────────────────

_NUM = r"[\d,]+"
# A number that is NOT part of an identifier or bit-select: rejects the "1"
# in `n0[1]` (preceded by "[" / followed by "]") and the "13" in "n13"
# (preceded by a word char). Bug found on test18 turn 9: claim=1 was scraped
# from `n0[1]` while the agent's actual answer was the (correct) 55.
_NUM_STANDALONE = rf"(?<![\w\[])({_NUM})(?![\w\]])"


def _clean_int(s: str) -> Optional[int]:
    s = s.strip().replace(",", "")
    if not re.fullmatch(r"-?\d+", s):
        return None
    return int(s)


def extract_gate_count_breakdown(text: str) -> Tuple[Optional[Dict[str, int]], Optional[int]]:
    """Parse a markdown table `| NOT | 2,412 |` -> {type: count}, plus total."""
    counts: Dict[str, int] = {}
    total: Optional[int] = None
    row_re = re.compile(
        r"\|?\s*\**\s*(" + "|".join(GATE_TYPE_NAMES) + r"|TOTAL)\s*\**\s*\|\s*\**\s*(" +
        _NUM + r")\s*\**\s*\|?", re.I)
    for m in row_re.finditer(text):
        name = m.group(1).upper()
        val = _clean_int(m.group(2))
        if val is None:
            continue
        if name == "TOTAL":
            total = val
        else:
            counts[name] = val
    if not counts:
        # fall back to inline "NOT: 2412" / "NOT - 2412" style
        for name in GATE_TYPE_NAMES:
            m = re.search(rf"\b{name}\b\s*[:\-]\s*({_NUM})", text, re.I)
            if m:
                v = _clean_int(m.group(1))
                if v is not None:
                    counts[name] = v
    m = re.search(r"total\s*(?:gates?|count)?\s*[:\-]?\s*\**\s*(" + _NUM + r")", text, re.I)
    if m and total is None:
        total = _clean_int(m.group(1))
    return (counts or None), total


_RE_YES = re.compile(
    r"\*\*yes\b|(?<![a-z])yes[,.\b]|does exist\b"
    r"|(?<!not )(?<!not equivalent)are functionally equivalent"
    r"|(?<!not )are equivalent|always\s+(?:0|1)\s*:?\s*yes|\bis a cut\b", re.I)
_RE_NO = re.compile(
    r"\*\*no\b|(?<![a-z])no[,.\b]|are not functionally equivalent|are not equivalent"
    r"|\bare not\b|does not exist\b|not a cut\b", re.I)


def extract_yes_no(text: str) -> Optional[bool]:
    """Conservative yes/no extraction: UNVERIFIED (None) unless one polarity
    clearly dominates (both present or neither present -> None)."""
    yes = bool(_RE_YES.search(text))
    no = bool(_RE_NO.search(text))
    if yes and not no:
        return True
    if no and not yes:
        return False
    return None


def extract_number_near(text: str, node: Optional[str]) -> Optional[int]:
    """Prefer a bolded/table number adjacent to *node*; else the first
    unambiguous standalone number claim. Never guesses among conflicts."""
    candidates: List[int] = []
    if node:
        node_re = re.escape(node)
        for pat in (
            rf"\*\*{node_re}\*\*[^\d]{{0,40}}{_NUM_STANDALONE}",
            rf"{node_re}[^\d\n]{{0,40}}?\b(?:is|=|:|has)\b[^\d\n]{{0,25}}{_NUM_STANDALONE}",
            rf"{_NUM_STANDALONE}[^\d\n]{{0,40}}?{node_re}",
        ):
            for m in re.finditer(pat, text, re.I):
                v = _clean_int(m.group(1))
                if v is not None:
                    candidates.append(v)
        if candidates and len(set(candidates)) == 1:
            return candidates[0]
        if candidates:
            return None  # conflicting candidates near the node -> UNVERIFIED

    # generic bold-number / "the answer is N" style fallback
    generic: List[int] = []
    for pat in (r"\*\*(" + _NUM + r")\*\*",
                # bold number with a unit suffix, e.g. "**55 gate levels**"
                r"\*\*(" + _NUM + r")\b[^*\n]{0,30}\*\*"):
        for m in re.finditer(pat, text):
            v = _clean_int(m.group(1))
            if v is not None:
                generic.append(v)
    if len(set(generic)) == 1:
        return generic[0]
    if not generic:
        m = re.search(r"\b(?:is|are|total(?: of)?|found)\s*:?\s*(" + _NUM + r")\b", text, re.I)
        if m:
            return _clean_int(m.group(1))
    return None


def extract_list_paths_count(text: str) -> Optional[int]:
    m = re.search(r"total (?:number of )?paths?(?: found)?\s*:?\s*\**\s*(" + _NUM + r")", text, re.I)
    if m:
        return _clean_int(m.group(1))
    m = re.search(r"(" + _NUM + r")\s+(?:distinct|total|unique)?\s*paths?\b", text, re.I)
    if m:
        return _clean_int(m.group(1))
    m = re.search(r"found\s+(" + _NUM + r")\s+paths?\b", text, re.I)
    if m:
        return _clean_int(m.group(1))
    # "No (combinational/such) paths exist/found/connect ..." is a zero claim.
    # Any explicit number elsewhere would have matched the patterns above, so
    # reaching here with a clear negative statement is unambiguous.
    if re.search(r"\bno\s+(?:combinational\s+|such\s+)?paths?\s+"
                 r"(?:exist|were\s+found|found|connect)", text, re.I):
        return 0
    return None


def extract_node_list(text: str) -> Optional[List[str]]:
    """Best-effort list of gate/net tokens mentioned (bullets, commas, table
    rows). Used for successors/fanout_count list comparison (set-compare)."""
    toks = re.findall(r"\b(g\d+|n\d+(?:\[\d+\])?)\b", text)
    return sorted(set(toks)) if toks else None


# ── verdicts ─────────────────────────────────────────────────────────────

VERDICTS = ("CORRECT", "WRONG", "DIVERGENT", "UNVERIFIED", "UNVERIFIED-TYPE",
            "SKIPPED-STATE", "LLM_ERROR")


@dataclass
class TurnResult:
    turn: int
    qtype: str
    params: Dict[str, str]
    verdict: str
    detail: str = ""


def _resolve_net(nl: "oracle.Netlist", token: str) -> str:
    """A family's [node] param may name either a NET (n5, n0[0]) or a GATE
    INSTANCE (g0) — "fanout of g0" / "successors of g0" mean the fanout/cone
    of that gate's OUTPUT net, not a (meaningless) lookup of "g0" as a net
    name. If *token* is a known gate instance name, resolve to its output
    net; otherwise return it unchanged (assume it already names a net)."""
    for g in nl.gates:
        if g.name == token:
            return g.output or token
    return token


def _parser_cpp_available() -> bool:
    return PARSER_BIN.is_file()


def _run_parser_cpp(vfile: Path, action: str, **kw) -> str:
    import subprocess
    args = [str(PARSER_BIN), "--in", str(vfile), "--action", action]
    for k, v in kw.items():
        if v is None:
            continue
        args += [f"--{k}", str(v)]
    r = subprocess.run(args, capture_output=True, text=True, timeout=150)
    return r.stdout


def adjudicate_numeric(vfile: Path, qtype: str, params: Dict[str, str],
                        claim: int, oracle_val: int) -> str:
    """claim != oracle_val: consult parser_cpp before declaring WRONG.

    Returns "WRONG" or "DIVERGENT" (claim matches parser_cpp -> a definition
    difference, not a real error).
    """
    if not _parser_cpp_available():
        return "WRONG"
    try:
        if qtype == "max_depth_between":
            out = _run_parser_cpp(vfile, "calc_depth", start=params.get("src"),
                                   end=params.get("dst"))
            m = re.search(r"Depth:\s*(-?\d+)", out)
        elif qtype == "cone_depth":
            out = _run_parser_cpp(vfile, "calc_depth", end=params.get("node"))
            m = re.search(r"Depth:\s*(-?\d+)", out)
        elif qtype == "global_max_depth":
            out = _run_parser_cpp(vfile, "calc_depth", end="")
            m = None  # global depth needs a PO scan; skip parser_cpp adjudication
        elif qtype == "fanin_cone_size":
            out = _run_parser_cpp(vfile, "count_fanin", node=params.get("node"))
            m = re.search(r"Fanin Gates:\s*(-?\d+)", out)
        elif qtype == "fanout_cone_size":
            out = _run_parser_cpp(vfile, "count_fanout", node=params.get("node"))
            m = re.search(r"Fanout Gates:\s*(-?\d+)", out)
        elif qtype == "fanout_count":
            # "gates driven by X" is ambiguous: direct loads (oracle) vs the
            # transitive fanout cone. If the claim matches the transitive
            # count, grade it DIVERGENT (definition choice), not WRONG.
            out = _run_parser_cpp(vfile, "count_fanout", node=params.get("node"))
            m = re.search(r"Fanout Gates:\s*(-?\d+)", out)
        elif qtype in ("pi_to_dff_depth",):
            out = _run_parser_cpp(vfile, "max_pi_to_dff_depth")
            m = re.search(r"(-?\d+)", out)
        elif qtype in ("gate_count_breakdown",):
            out = _run_parser_cpp(vfile, "count_gates")
            m = None
        else:
            return "WRONG"
        if m:
            tool_val = _clean_int(m.group(1))
            if tool_val == claim:
                return "DIVERGENT"
        return "WRONG"
    except Exception:
        return "WRONG"


# ── grading a single response for a given classified request ────────────

def grade_turn(turn: int, qtype: str, params: Dict[str, str], answer: str,
               nl: "oracle.Netlist", vfile: Path,
               abc_path: Path) -> TurnResult:
    if _RE_LLM_ERROR.search(answer):
        return TurnResult(turn, qtype, params, "LLM_ERROR", "LLM service error in response")

    try:
        if qtype == "gate_count_breakdown":
            counts, claimed_total = extract_gate_count_breakdown(answer)
            if counts is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", "could not parse gate table")
            oc = oracle.count_gates(nl)
            oracle_map = {t.upper(): oc.get(t.lower(), 0) for t in GATE_TYPE_NAMES}
            mism = {t: (counts.get(t), oracle_map[t]) for t in GATE_TYPE_NAMES
                    if t in counts and counts[t] != oracle_map[t]}
            missing = [t for t in GATE_TYPE_NAMES if t not in counts]
            if mism:
                return TurnResult(turn, qtype, params, "WRONG",
                                   f"mismatches={mism} oracle={oracle_map}")
            if missing:
                return TurnResult(turn, qtype, params, "UNVERIFIED",
                                   f"table missing types {missing}; present ones matched oracle")
            return TurnResult(turn, qtype, params, "CORRECT", f"claim={counts} oracle={oracle_map}")

        if qtype == "path_exists_avoiding":
            claim = extract_yes_no(answer)
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", "no clear yes/no in answer")
            src, dst, avoid = params.get("src"), params.get("dst"), params.get("avoid")
            ov = oracle.path_exists(nl, src, dst, avoid)
            verdict = "CORRECT" if claim == ov else "WRONG"
            return TurnResult(turn, qtype, params, verdict,
                               f"claim={'yes' if claim else 'no'} oracle={'yes' if ov else 'no'}")

        if qtype == "list_paths":
            claim = extract_list_paths_count(answer)
            src, dst = params.get("src"), params.get("dst")
            ov = oracle.count_paths(nl, src, dst)
            if claim is None:
                if re.search(r"saved to", answer, re.I):
                    return TurnResult(turn, qtype, params, "UNVERIFIED",
                                       f"only pointed to a saved file; oracle count={ov}")
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"no count found; oracle={ov}")
            if claim == ov:
                return TurnResult(turn, qtype, params, "CORRECT", f"claim={claim} oracle={ov}")
            if _parser_cpp_available():
                try:
                    out = _run_parser_cpp(vfile, "count_paths", start=src, end=dst)
                    m = re.search(r"Paths:\s*(\d+)", out)
                    tool_val = _clean_int(m.group(1)) if m else None
                    if tool_val == claim:
                        return TurnResult(turn, qtype, params, "DIVERGENT",
                                           f"claim={claim} matches parser_cpp capped count "
                                           f"(oracle uncapped={ov}, tool={tool_val})")
                except Exception:
                    pass
            return TurnResult(turn, qtype, params, "WRONG", f"claim={claim} oracle={ov}")

        if qtype == "max_depth_between":
            claim = extract_number_near(answer, params.get("dst")) or extract_number_near(answer, None)
            src, dst = params.get("src"), params.get("dst")
            ov = oracle.depth_between(nl, src, dst)
            if claim is None or ov is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED",
                                   f"claim={claim} oracle={ov}")
            if claim == ov:
                return TurnResult(turn, qtype, params, "CORRECT", f"claim={claim} oracle={ov}")
            v = adjudicate_numeric(vfile, qtype, params, claim, ov)
            return TurnResult(turn, qtype, params, v, f"claim={claim} oracle={ov}")

        if qtype == "fanout_count":
            node = params.get("node")
            net = _resolve_net(nl, node)
            claim = extract_number_near(answer, node)
            ov = len(oracle.fanout_of(nl, net))
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}, no clean claim")
            verdict = ("CORRECT" if claim == ov
                       else adjudicate_numeric(vfile, qtype, params, claim, ov))
            return TurnResult(turn, qtype, params, verdict, f"claim={claim} oracle={ov}")

        if qtype == "successors":
            node = params.get("node")
            net = _resolve_net(nl, node)
            claimed_list = extract_node_list(answer)
            ov = sorted(oracle.fanout_of(nl, net))
            if not claimed_list:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            claimed_set = {t for t in claimed_list if t != node}
            verdict = "CORRECT" if claimed_set == set(ov) else "WRONG"
            return TurnResult(turn, qtype, params, verdict, f"claim={sorted(claimed_set)} oracle={ov}")

        if qtype == "fanin_cone_size":
            node = params.get("node")
            net = _resolve_net(nl, node)
            claim = extract_number_near(answer, node)
            ov = len(oracle.fanin_cone_gates(nl, net))
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            if claim == ov:
                return TurnResult(turn, qtype, params, "CORRECT", f"claim={claim} oracle={ov}")
            v = adjudicate_numeric(vfile, qtype, params, claim, ov)
            return TurnResult(turn, qtype, params, v, f"claim={claim} oracle={ov}")

        if qtype == "fanout_cone_size":
            node = params.get("node")
            net = _resolve_net(nl, node)
            claim = extract_number_near(answer, node)
            ov = len(oracle.fanout_cone_gates(nl, net))
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            if claim == ov:
                return TurnResult(turn, qtype, params, "CORRECT", f"claim={claim} oracle={ov}")
            v = adjudicate_numeric(vfile, qtype, params, claim, ov)
            return TurnResult(turn, qtype, params, v, f"claim={claim} oracle={ov}")

        if qtype == "cone_depth":
            node = params.get("node")
            net = _resolve_net(nl, node)
            claim = extract_number_near(answer, node)
            levels = oracle._combinational_levels(nl)
            ov = levels.get(net)
            if claim is None or ov is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"claim={claim} oracle={ov}")
            if claim == ov:
                return TurnResult(turn, qtype, params, "CORRECT", f"claim={claim} oracle={ov}")
            v = adjudicate_numeric(vfile, qtype, params, claim, ov)
            return TurnResult(turn, qtype, params, v, f"claim={claim} oracle={ov}")

        if qtype == "signal_equiv":
            claim = extract_yes_no(answer)
            a, b = params.get("a"), params.get("b")
            ov = oracle.signals_equivalent(nl, a, b, abc_path=abc_path)
            if claim is None or ov is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"claim={claim} oracle={ov}")
            verdict = "CORRECT" if claim == ov else "WRONG"
            return TurnResult(turn, qtype, params, verdict, f"claim={claim} oracle={ov}")

        if qtype == "always_const":
            node, val = params.get("node"), params.get("val")
            claim = extract_yes_no(answer)
            ac = oracle.always_const(nl, node, abc_path=abc_path)
            if claim is None or ac is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"claim={claim} oracle_const={ac}")
            ov = (ac == int(val))
            verdict = "CORRECT" if claim == ov else "WRONG"
            return TurnResult(turn, qtype, params, verdict, f"claim={claim} oracle={ov} (const={ac})")

        if qtype == "pio_count":
            pio = oracle.list_pio(nl)
            n_in, n_out = len(pio["inputs"]), len(pio["outputs"])
            m = re.search(r"(" + _NUM + r")\s+primary input", answer, re.I)
            m2 = re.search(r"(" + _NUM + r")\s+primary output", answer, re.I)
            claim_in = _clean_int(m.group(1)) if m else None
            claim_out = _clean_int(m2.group(1)) if m2 else None
            if claim_in is None or claim_out is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED",
                                   f"oracle inputs={n_in} outputs={n_out}")
            verdict = "CORRECT" if (claim_in, claim_out) == (n_in, n_out) else "WRONG"
            return TurnResult(turn, qtype, params, verdict,
                               f"claim=({claim_in},{claim_out}) oracle=({n_in},{n_out})")

        if qtype == "pio_list":
            return TurnResult(turn, qtype, params, "UNVERIFIED-TYPE",
                               "pio_list: full name+width set comparison not implemented")

        if qtype == "flops_by_clock":
            clk = params.get("clk")
            claimed_list = extract_node_list(answer)
            ov = sorted(oracle.flops_by_clock(nl, clk))
            if not claimed_list:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            claimed_set = {t for t in claimed_list if t != clk}
            verdict = "CORRECT" if claimed_set == set(ov) else "WRONG"
            return TurnResult(turn, qtype, params, verdict, f"claim={sorted(claimed_set)} oracle={ov}")

        if qtype == "pi_to_dff_depth":
            claim = extract_number_near(answer, None)
            ov = oracle.max_pi_to_dff_depth(nl)
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            if claim == ov:
                return TurnResult(turn, qtype, params, "CORRECT", f"claim={claim} oracle={ov}")
            v = adjudicate_numeric(vfile, qtype, params, claim, ov)
            return TurnResult(turn, qtype, params, v, f"claim={claim} oracle={ov}")

        if qtype == "global_max_depth":
            claim = extract_number_near(answer, None)
            ov = oracle.max_depth(nl)
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            verdict = "CORRECT" if claim == ov else "WRONG"
            return TurnResult(turn, qtype, params, verdict, f"claim={claim} oracle={ov}")

        if qtype == "r2r_paths":
            return TurnResult(turn, qtype, params, "UNVERIFIED-TYPE",
                               "r2r_paths: free-form per-pair enumeration not compared")

        if qtype == "r2r_max_depth":
            claim = extract_number_near(answer, None)
            ov = oracle.r2r_max_depth(nl)
            if claim is None:
                return TurnResult(turn, qtype, params, "UNVERIFIED", f"oracle={ov}")
            verdict = "CORRECT" if claim == ov else "WRONG"
            return TurnResult(turn, qtype, params, verdict, f"claim={claim} oracle={ov}")

    except Exception as exc:  # noqa: BLE001 — never crash the grading loop
        return TurnResult(turn, qtype, params, "UNVERIFIED", f"grading exception: {exc}")

    return TurnResult(turn, qtype, params, "UNVERIFIED-TYPE", f"no grader wired for {qtype}")


# ── per-case driver ──────────────────────────────────────────────────────

@dataclass
class CaseReport:
    name: str
    turns: List[TurnResult] = field(default_factory=list)
    invalid: bool = False
    invalid_reason: str = ""


def grade_case(case_dir: Path, case_name: str, log_dir: Optional[Path] = None,
               abc_path: Path = ABC_BIN) -> CaseReport:
    prompt_path = case_dir / "prompt.txt"
    log_path = (log_dir or case_dir) / f"{case_name}.log"
    vfile = case_dir / f"{case_name}.v"

    report = CaseReport(case_name)
    if not prompt_path.is_file():
        report.invalid = True
        report.invalid_reason = "prompt.txt missing"
        return report
    if not log_path.is_file():
        report.invalid = True
        report.invalid_reason = f"log missing ({log_path})"
        return report
    if not vfile.is_file():
        report.invalid = True
        report.invalid_reason = "original .v missing"
        return report

    lines = prompt_path.read_text().splitlines()
    responses = parse_log(log_path)

    n_llm_error = sum(1 for txt in responses.values() if _RE_LLM_ERROR.search(txt))
    if responses and n_llm_error * 2 > len(responses):
        report.invalid = True
        report.invalid_reason = f"LOG_INVALID: {n_llm_error}/{len(responses)} turns are LLM_ERROR"
        return report

    nl = oracle.parse_netlist(vfile)

    state_broken = False
    for i, line in enumerate(lines, start=1):
        cls = classify_request(line)
        qtype, params = cls.qtype, cls.params

        if qtype in ("protocol", "unclassified"):
            continue

        if qtype == "transform":
            state_broken = True
            continue

        if qtype == "unsupported":
            answer = responses.get(i, "")
            if _RE_LLM_ERROR.search(answer):
                report.turns.append(TurnResult(i, qtype, params, "LLM_ERROR", "LLM service error"))
            else:
                report.turns.append(TurnResult(i, qtype, params, "UNVERIFIED-TYPE",
                                                "no oracle for this family"))
            # unsupported lines that are themselves mutations (e.g. "how many
            # X were eliminated" only follows a real transform, which already
            # set state_broken via its own line) do not themselves move state.
            continue

        # analysis family
        answer = responses.get(i)
        if answer is None:
            report.turns.append(TurnResult(i, qtype, params, "UNVERIFIED", "no response recorded"))
            continue

        if state_broken:
            report.turns.append(TurnResult(i, qtype, params, "SKIPPED-STATE",
                                            "design mutated by an earlier transform line"))
            continue

        result = grade_turn(i, qtype, params, answer, nl, vfile, abc_path)
        report.turns.append(result)

    return report


def format_turn(t: TurnResult) -> str:
    pstr = ""
    if t.params:
        pieces = [f"{k}={v}" for k, v in t.params.items() if v is not None]
        pstr = "(" + ", ".join(pieces) + ")" if pieces else ""
    return f"  turn {t.turn:<3} {t.qtype}{pstr} {t.verdict} ({t.detail})"


def print_case_report(report: CaseReport) -> None:
    print(f"=== {report.name} ===")
    if report.invalid:
        print(f"  {report.invalid_reason}")
        return
    if not report.turns:
        print("  (no analysis turns to grade)")
        return
    for t in report.turns:
        print(format_turn(t))
    counts: Dict[str, int] = {}
    for t in report.turns:
        counts[t.verdict] = counts.get(t.verdict, 0) + 1
    print(f"  -- {report.name} verdict counts: " +
          ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))


# ── selftest with synthetic fixtures ─────────────────────────────────────

_FIXTURE_V = """
module top(a, b, c, y, z);
  input a, b, c;
  output y, z;
  wire n1, n2;
  and g1(n1, a, b);
  or g2(n2, a, c);
  not g3(y, n1);
  buf g4(z, n2);
endmodule
"""

_FIXTURE_PROMPT = """This is the beginning of a new testcase. The case name is fixtest.
Please load the design from the file fixtest.v located in the directory testcase/fixtest/.
Please count all the gates in this design and report the total count broken down by gate type (AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF).
Determine whether signals n1 and n2 are functionally equivalent.
Please write the current design to the output file fixtest_out.v.
"""


def _selftest() -> int:
    import tempfile
    failures: List[str] = []

    with tempfile.TemporaryDirectory(prefix="check_answers_selftest_") as td:
        tdp = Path(td)
        case_dir = tdp / "fixtest"
        case_dir.mkdir()
        (case_dir / "fixtest.v").write_text(_FIXTURE_V)
        (case_dir / "prompt.txt").write_text(_FIXTURE_PROMPT)

        # -- fixture 1: WRONG numeric claim (gate_count_breakdown) --
        log_wrong = (
            "#RESPONSE 1\nAcknowledged.\n#END 1\n"
            "#RESPONSE 2\nLoaded.\n#END 2\n"
            "#RESPONSE 3\n"
            "| Gate Type | Count |\n|---|---|\n"
            "| AND | 1 |\n| OR | 1 |\n| NOT | 1 |\n| NAND | 0 |\n| NOR | 0 |\n"
            "| XOR | 0 |\n| XNOR | 0 |\n| BUF | 99 |\n| DFF | 0 |\n"
            "#END 3\n"
            "#RESPONSE 4\nWritten.\n#END 4\n"
        )
        (case_dir / "fixtest.log").write_text(log_wrong)
        rep = grade_case(case_dir, "fixtest", abc_path=ABC_BIN)
        turn3 = next((t for t in rep.turns if t.turn == 3), None)
        if turn3 is None or turn3.verdict != "WRONG":
            failures.append(f"fixture1 (WRONG numeric): got {turn3}")

        # -- fixture 2: yes/no question with both polarities present --
        log_ambiguous = (
            "#RESPONSE 1\nAcknowledged.\n#END 1\n"
            "#RESPONSE 2\nLoaded.\n#END 2\n"
            "#RESPONSE 3\n"
            "| Gate Type | Count |\n|---|---|\n"
            "| AND | 1 |\n| OR | 1 |\n| NOT | 1 |\n| NAND | 0 |\n| NOR | 0 |\n"
            "| XOR | 0 |\n| XNOR | 0 |\n| BUF | 1 |\n| DFF | 0 |\n"
            "#END 3\n"
            "#RESPONSE 4\n**Yes**, they seem related, but actually **No**, not equivalent.\n#END 4\n"
            "#RESPONSE 5\nWritten.\n#END 5\n"
        )
        (case_dir / "fixtest.log").write_text(log_ambiguous)
        rep2 = grade_case(case_dir, "fixtest", abc_path=ABC_BIN)
        turn4 = next((t for t in rep2.turns if t.turn == 4), None)
        if turn4 is None or turn4.verdict != "UNVERIFIED":
            failures.append(f"fixture2 (ambiguous yes/no): got {turn4}")

        # -- fixture 3: LLM_ERROR majority -> LOG_INVALID --
        log_err = (
            "#RESPONSE 1\nError communicating with the LLM service.\n#END 1\n"
            "#RESPONSE 2\nError communicating with the LLM service.\n#END 2\n"
            "#RESPONSE 3\nError communicating with the LLM service.\n#END 3\n"
        )
        (case_dir / "fixtest.log").write_text(log_err)
        rep3 = grade_case(case_dir, "fixtest", abc_path=ABC_BIN)
        if not rep3.invalid or "LOG_INVALID" not in rep3.invalid_reason:
            failures.append(f"fixture3 (LLM_ERROR majority): got invalid={rep3.invalid} "
                             f"reason={rep3.invalid_reason!r}")

    print("=" * 70)
    if failures:
        print(f"SELFTEST FAILED: {len(failures)} assertion(s) failed")
        for f in failures:
            print(f"  - {f}")
        print("=" * 70)
        return 1
    print("SELFTEST OK: all synthetic fixture checks passed")
    print("=" * 70)
    return 0


def _classification_dry_run() -> bool:
    """Parse all 40 prompt.txt files, print qtype histogram, flag any
    'unclassified' lines. Returns True iff there are zero unclassified lines."""
    hist: Dict[str, int] = {}
    unclassified: List[str] = []
    for i in range(1, 41):
        p = ROOT / "testcase" / f"test{i:02d}" / "prompt.txt"
        if not p.is_file():
            continue
        for line in p.read_text().splitlines():
            if not line.strip():
                continue
            cls = classify_request(line)
            hist[cls.qtype] = hist.get(cls.qtype, 0) + 1
            if cls.qtype == "unclassified":
                unclassified.append(f"test{i:02d}: {line.strip()}")
    print("-- qtype histogram over 40 prompt.txt files --")
    for k, v in sorted(hist.items(), key=lambda kv: -kv[1]):
        print(f"  {k:<24} {v}")
    if unclassified:
        print(f"-- {len(unclassified)} UNCLASSIFIED line(s) --")
        for u in unclassified:
            print(f"  {u}")
    else:
        print("-- 0 unclassified lines --")
    return not unclassified


# ── CLI ──────────────────────────────────────────────────────────────────

def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__,
                                 formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--case", type=str, help="e.g. test02")
    ap.add_argument("--from", dest="lo", type=int, default=1)
    ap.add_argument("--to", dest="hi", type=int, default=40)
    ap.add_argument("--all", action="store_true")
    ap.add_argument("--log-dir", type=str, default=None,
                     help="override directory to read <case>.log from (testing fixtures)")
    ap.add_argument("--abc-path", type=str, default=str(ABC_BIN))
    ap.add_argument("--selftest", action="store_true", help="run synthetic-fixture selftest")
    ap.add_argument("--dry-run-classify", action="store_true",
                     help="print qtype histogram over all 40 prompt.txt files and exit")
    a = ap.parse_args()

    if a.selftest:
        sys.exit(_selftest())

    if a.dry_run_classify:
        ok = _classification_dry_run()
        sys.exit(0 if ok else 1)

    if a.case:
        # accept either a canonical "testNN" name or an arbitrary fixture
        # case name (only meaningful together with --log-dir, e.g. selftest
        # fixtures that don't live under testcase/).
        case_names = [a.case]
    elif a.all:
        case_names = [f"test{n:02d}" for n in range(1, 41)]
    else:
        case_names = [f"test{n:02d}" for n in range(a.lo, a.hi + 1)]

    log_dir = Path(a.log_dir) if a.log_dir else None
    abc_path = Path(a.abc_path)

    any_wrong = False
    grand: Dict[str, int] = {}
    per_case_summary: List[str] = []

    for case_name in case_names:
        case_dir = ROOT / "testcase" / case_name
        if not case_dir.is_dir() and log_dir is not None and log_dir.is_dir():
            # fixture/testing mode: prompt.txt/<case>.v also live under
            # --log-dir rather than the real testcase/<case> tree.
            case_dir = log_dir
        report = grade_case(case_dir, case_name, log_dir=log_dir, abc_path=abc_path)
        print_case_report(report)
        if report.invalid:
            per_case_summary.append(f"{case_name}: INVALID ({report.invalid_reason})")
            continue
        counts: Dict[str, int] = {}
        for t in report.turns:
            counts[t.verdict] = counts.get(t.verdict, 0) + 1
            grand[t.verdict] = grand.get(t.verdict, 0) + 1
            if t.verdict == "WRONG":
                any_wrong = True
        per_case_summary.append(
            f"{case_name}: " + ", ".join(f"{k}={v}" for k, v in sorted(counts.items())))

    print("\n" + "=" * 70)
    print("GLOBAL SUMMARY")
    print("=" * 70)
    for line in per_case_summary:
        print(f"  {line}")
    print("-" * 70)
    total = sum(grand.values())
    print(f"TOTAL graded turns: {total}")
    for v in VERDICTS:
        print(f"  {v:<16} {grand.get(v, 0)}")

    sys.exit(1 if any_wrong else 0)


if __name__ == "__main__":
    main()
