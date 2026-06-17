"""Shared library for testcase verification (used by verify_testcases.py).

This module is NOT meant to be run directly.  It provides:

- **Prompt dispatch** — map each prompt.txt line to an EDAEngine tool call
  without calling a real LLM (rule-based, deterministic).
- **ABC equivalence** — export BLIF via parser ``write_blif`` and run ``abc cec``.
- **Structured results** — StepResult (per prompt) and CaseResult (per testcase).
- **RunLogger** — write human-readable report.md + SUMMARY under verification_runs/.
- **Tier presets** — smoke / basic / … so you do not have to run all 40 cases every time.
"""

from __future__ import annotations

import inspect
import os
import re
import subprocess
import sys
import textwrap
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional, Tuple


ROOT = Path(__file__).resolve().parent.parent
TESTCASE_DIR = ROOT / "testcase"

TRANSFORM_KEYWORDS = re.compile(
    r"insert buffer|remap|replace all|optimize|collapse|remove|propagat|"
    r"rename|reconnect|ensure.*equival|make sure nothing changes|"
    r"functionality does not change|functionally equivalent",
    re.I,
)


@dataclass
class ToolCallSpec:
    name: str
    arguments: Dict[str, Any]


@dataclass
class StepResult:
    line_no: int
    prompt: str
    status: str  # PASS | FAIL | SKIP | UNSUPPORTED
    tool: Optional[str] = None
    tool_args: Optional[Dict[str, Any]] = None
    engine_result: str = ""
    notes: str = ""


@dataclass
class CaseResult:
    case_id: str
    status: str  # PASS | PARTIAL | FAIL | SKIP
    steps: List[StepResult] = field(default_factory=list)
    output_file: Optional[str] = None
    abc_status: Optional[str] = None  # EQUIVALENT | NOT_EQUIVALENT | SKIPPED | ERROR
    abc_detail: str = ""

    @property
    def step_counts(self) -> Dict[str, int]:
        counts = {"PASS": 0, "FAIL": 0, "UNSUPPORTED": 0, "SKIP": 0}
        for s in self.steps:
            counts[s.status] = counts.get(s.status, 0) + 1
        return counts

    @property
    def actionable_steps(self) -> List[StepResult]:
        """Steps that actually invoke a tool (exclude init SKIP)."""
        return [s for s in self.steps if s.status != "SKIP"]

    @property
    def first_failure(self) -> Optional[StepResult]:
        for s in self.steps:
            if s.status == "FAIL":
                return s
        return None


# Tier presets — default scope for merge verification.
# Expand tiers as more testcases become passable.
VERIFY_TIERS: Dict[str, List[str]] = {
    "smoke": [f"test{n:02d}" for n in range(1, 3)],       # load / write / count
    "basic": [f"test{n:02d}" for n in range(1, 9)],       # + path / depth queries
    "analysis": [f"test{n:02d}" for n in range(1, 15)],   # through test14
    "transform": [f"test{n:02d}" for n in (21, 22, 23, 40)],  # buffer / opt / remap
    "all": [f"test{n:02d}" for n in range(1, 41)],
}
DEFAULT_TIER = "smoke"


def find_abc_binary() -> Optional[Path]:
    env = os.environ.get("ABC_BIN")
    if env and Path(env).is_file():
        return Path(env).resolve()
    for cand in (ROOT / "tools" / "abc" / "abc", ROOT / "abc" / "abc"):
        if cand.is_file():
            return cand.resolve()
    return None


def find_parser_binary() -> Optional[Path]:
    env = os.environ.get("PARSER_BIN")
    if env and Path(env).is_file():
        return Path(env).resolve()
    parser_dir = ROOT / "src" / "eda_engine" / "parser"
    for name in ("parser_cpp", "parser_cpp.exe"):
        path = parser_dir / name
        if path.is_file():
            return path.resolve()
    return None


def parser_supports_action(parser_bin: Path, action: str) -> bool:
    """Probe whether the compiled parser recognises *action*."""
    dummy = ROOT / "testcase" / "test01" / "test01.v"
    if not dummy.is_file():
        return False
    proc = subprocess.run(
        [str(parser_bin), "--in", str(dummy), "--action", action, "--out", os.devnull],
        capture_output=True,
        text=True,
    )
    combined = (proc.stdout + proc.stderr).lower()
    return "unknown action" not in combined


def run_parser_action(
    parser_bin: Path,
    in_file: str,
    action: str,
    **kwargs: Any,
) -> Tuple[bool, str]:
    cmd = [str(parser_bin), "--in", os.path.normpath(in_file), "--action", action]
    for key, val in kwargs.items():
        cmd.extend([f"--{key}", str(val)])
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    except FileNotFoundError:
        return False, f"Parser binary not found: {parser_bin}"
    out = (proc.stdout + proc.stderr).strip()
    ok = proc.returncode == 0 and "error" not in out.lower()[:80]
    return ok, out


def abc_cec_on_verilog(
    parser_bin: Path,
    abc_bin: Path,
    reference_v: str,
    current_v: str,
    work_dir: Path,
) -> Tuple[str, str]:
    """Export flop-cut BLIF from both netlists and run `abc cec`."""
    work_dir.mkdir(parents=True, exist_ok=True)
    ref_blif = work_dir / "ref.blif"
    cur_blif = work_dir / "cur.blif"

    if not parser_supports_action(parser_bin, "write_blif"):
        return "SKIPPED", "Parser lacks write_blif action — merge buffer-insertion parser first."

    ok1, e1 = run_parser_action(parser_bin, reference_v, "write_blif", out=str(ref_blif))
    ok2, e2 = run_parser_action(parser_bin, current_v, "write_blif", out=str(cur_blif))
    if not ok1 or not ok2 or not ref_blif.is_file() or not cur_blif.is_file():
        return "ERROR", f"BLIF export failed.\nref: {e1}\ncur: {e2}"

    cmd = [str(abc_bin), "-q", f"cec {ref_blif} {cur_blif}"]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=300, check=False)
    except Exception as exc:  # noqa: BLE001
        return "ERROR", f"ABC subprocess failed: {exc}"

    combined = (proc.stdout + proc.stderr).strip()
    low = combined.lower()
    log_body = textwrap.dedent(
        f"""\
        ABC command : {' '.join(cmd)}
        exit code   : {proc.returncode}
        --- stdout/stderr ---
        {combined}
        """
    )
    if "are equivalent" in low:
        return "EQUIVALENT", log_body
    if "not equivalent" in low:
        return "NOT_EQUIVALENT", log_body
    return "ERROR", log_body


def engine_has(engine: Any, method: str) -> bool:
    return callable(getattr(engine, method, None))


def available_engine_tools(engine: Any) -> List[str]:
    names = [
        "load_design",
        "write_design",
        "analyze_depth",
        "analyze_critical_path",
        "find_paths",
        "check_path_exists",
        "get_node_info",
        "list_nodes",
        "replace_gate",
        "count_gates",
        "count_fanin_gates",
        "count_fanout_gates",
        "get_fanin_cone",
        "get_fanout_cone",
        "get_fanin_depth",
        "insert_buffers",
        "check_equivalence",
    ]
    return [n for n in names if engine_has(engine, n)]


def _extract_load_path(text: str, case_id: str) -> Dict[str, str]:
    m = re.search(r"testcase/([\w]+)/([\w]+\.v)", text, re.I)
    if m:
        return {"filepath": f"testcase/{m.group(1)}/{m.group(2)}"}
    return {"filepath": f"testcase/{case_id}/{case_id}.v"}


def _extract_write_path(text: str, case_id: str) -> Dict[str, str]:
    m = re.search(r"([\w]+_out\.v)", text, re.I)
    fname = m.group(1) if m else f"{case_id}_out.v"
    return {"filepath": f"testcase/{case_id}/{fname}"}


def _extract_node(text: str) -> Optional[str]:
    for pat in (
        r"output\s+(\w+)",
        r"node\s+(\w+)",
        r"signal\s+(\w+)",
        r"gate\s+(\w+)",
        r"\b(g\d+)\b",
        r"\b(n\d+)\b",
    ):
        m = re.search(pat, text, re.I)
        if m:
            return m.group(1)
    return None


def _extract_depth_args(text: str) -> Dict[str, str]:
    m = re.search(
        r"from\s+(?:input\s+)?(\S+)\s+to\s+(?:output\s+)?(\S+)",
        text,
        re.I,
    )
    if m:
        return {"start_node": m.group(1), "end_node": m.group(2)}
    m2 = re.search(r"to\s+(?:output\s+)?(\S+)", text, re.I)
    if m2:
        return {"end_node": m2.group(1)}
    return {}

def _extract_path_avoid(text: str) -> Dict[str, str]:
    m1 = re.search(r"from\s+(?:input\s+)?([\w\[\]]+)\s+to\s+(?:output\s+)?([\w\[\]]+)", text, re.I)
    m2 = re.search(r"between\s+(?:input\s+)?([\w\[\]]+)\s+and\s+(?:output\s+)?([\w\[\]]+)", text, re.I)
    m3 = re.search(r"connecting\s+(?:input\s+)?([\w\[\]]+)\s+to\s+(?:output\s+)?([\w\[\]]+)", text, re.I)
    m4 = re.search(r"originating at\s+(?:primary input\s+)?([\w\[\]]+)\s+and terminating at\s+(?:primary output\s+)?([\w\[\]]+)", text, re.I)

    res = {}
    if m1:
        res["start_node"] = m1.group(1)
        res["end_node"] = m1.group(2)
    elif m2:
        res["start_node"] = m2.group(1)
        res["end_node"] = m2.group(2)
    elif m3:
        res["start_node"] = m3.group(1)
        res["end_node"] = m3.group(2)
    elif m4:
        res["start_node"] = m4.group(1)
        res["end_node"] = m4.group(2)

    av = re.search(r"(?:avoiding|not traverse node)\s+([\w\[\]]+)", text, re.I)
    if av:
        res["avoid_node"] = av.group(1)
    return res
    m2 = re.search(r"from\s+(\S+)\s+to\s+(\S+)", text, re.I)
    if m2:
        return {"start_node": m2.group(1), "end_node": m2.group(2)}
    return {}


def _extract_replace_gate(text: str) -> Optional[Dict[str, str]]:
    m = re.search(r"replace.*?(\w+).*?(AND|OR|NOT|NAND|NOR|XOR|XNOR|BUF|DFF)", text, re.I)
    if m:
        return {"target": m.group(1), "new_type": m.group(2).upper()}
    return None


def dispatch_prompt(
    prompt: str,
    case_id: str,
    engine: Any,
) -> Tuple[Optional[ToolCallSpec], str]:
    """Map a natural-language prompt line to an engine tool call."""
    text = prompt.strip()
    tools = set(available_engine_tools(engine))

    if re.search(r"\bload\b.*\.v", text, re.I):
        if "load_design" in tools:
            return ToolCallSpec("load_design", _extract_load_path(text, case_id)), ""
        return None, "load_design not available on engine"

    if re.search(r"\bwrite\b.*\.v|\boutput file\b", text, re.I):
        if "write_design" in tools:
            return ToolCallSpec("write_design", _extract_write_path(text, case_id)), ""
        return None, "write_design not available on engine"

    if re.search(r"count all the gates|broken down by gate type", text, re.I):
        if "count_gates" in tools:
            return ToolCallSpec("count_gates", {}), ""
        return None, "count_gates not available on engine"

    if re.search(r"insert buffer|no gate.*drives more than\s+(\d+)", text, re.I):
        if "insert_buffers" in tools:
            m = re.search(r"more than\s+(\d+)", text, re.I)
            max_fanout = int(m.group(1)) if m else 4
            return ToolCallSpec("insert_buffers", {"max_fanout": max_fanout}), ""
        return None, "insert_buffers not available — need buffer-insertion branch parser/engine"

    if re.search(r"verify.*equival|prove.*equivalent|functional equivalence", text, re.I):
        if "check_equivalence" in tools:
            return ToolCallSpec("check_equivalence", {}), ""
        return None, "check_equivalence not on engine (will try standalone ABC after write)"

    if re.search(r"fanin cone.*how many gates|gates are in the fanin cone", text, re.I):
        node = _extract_node(text)
        if node and "count_fanin_gates" in tools:
            return ToolCallSpec("count_fanin_gates", {"node_name": node}), ""
        return None, "count_fanin_gates not available or node not parsed"

    if re.search(r"fanout cone|fanout of primary input", text, re.I):
        node = _extract_node(text)
        if node and "count_fanout_gates" in tools:
            return ToolCallSpec("count_fanout_gates", {"node_name": node}), ""
        return None, "count_fanout_gates not available or node not parsed"

    if re.search(r"fanin cone", text, re.I) and not re.search(r"how many", text, re.I):
        node = _extract_node(text)
        if node and "get_fanin_cone" in tools:
            return ToolCallSpec("get_fanin_cone", {"node_name": node}), ""
        return None, "get_fanin_cone not available"

    if re.search(r"fanout cone", text, re.I) and not re.search(r"how many", text, re.I):
        node = _extract_node(text)
        if node and "get_fanout_cone" in tools:
            return ToolCallSpec("get_fanout_cone", {"node_name": node}), ""
        return None, "get_fanout_cone not available"

    if re.search(r"list every path|every path originating|enumeration of paths between", text, re.I):
        args = _extract_path_avoid(text)
        if args.get("start_node") and args.get("end_node") and "find_paths" in tools:
            return ToolCallSpec("find_paths", args), ""
        return None, "find_paths not available or path endpoints not parsed"

    if re.search(r"path.*exist|whether a combinational path|verify whether a path", text, re.I):
        args = _extract_path_avoid(text)
        if args.get("start_node") and args.get("end_node") and "check_path_exists" in tools:
            return ToolCallSpec("check_path_exists", args), ""
        return None, "check_path_exists not available or path endpoints not parsed"

    if re.search(r"\bdepth\b|\blogic depth\b|\bcritical path\b", text, re.I):
        args = _extract_depth_args(text)
        if re.search(r"critical path", text, re.I) and "analyze_critical_path" in tools:
            if args.get("start_node") and args.get("end_node"):
                return ToolCallSpec("analyze_critical_path", args), ""
        if "analyze_depth" in tools and args.get("end_node"):
            if args.get("start_node"):
                return ToolCallSpec("analyze_depth", args), ""
            return ToolCallSpec("analyze_depth", {"start_node": "", "end_node": args["end_node"]}), ""
        return None, "depth tools not available or endpoints not parsed"

    if re.search(r"what type of gate is", text, re.I):
        node = _extract_node(text)
        if node and "get_node_info" in tools:
            return ToolCallSpec("get_node_info", {"node_name": node}), ""
        return None, "get_node_info not available"

    if re.search(r"replace.*gate|remap", text, re.I):
        args = _extract_replace_gate(text)
        if args and "replace_gate" in tools:
            return ToolCallSpec("replace_gate", args), ""
        return None, "replace_gate not available or pattern not parsed"

    if re.search(r"list all|list every|list nodes", text, re.I):
        if "list_nodes" in tools:
            return ToolCallSpec("list_nodes", {}), ""
        return None, "list_nodes not available"

    return None, "No rule matched — operation likely not implemented yet"


def execute_tool(engine: Any, spec: ToolCallSpec) -> str:
    fn = getattr(engine, spec.name)
    sig = inspect.signature(fn)
    filtered = {k: v for k, v in spec.arguments.items() if k in sig.parameters}
    return str(fn(**filtered))


def is_error_result(text: str) -> bool:
    low = text.lower()
    return low.startswith("error") or "error executing" in low or "not found at" in low


def discover_all_cases() -> List[str]:
    cases: List[str] = []
    for entry in sorted(TESTCASE_DIR.iterdir()):
        if not entry.is_dir():
            continue
        if not re.fullmatch(r"test\d{2}", entry.name):
            continue
        case_id = entry.name
        if (entry / f"{case_id}.v").is_file() and (entry / "prompt.txt").is_file():
            cases.append(case_id)
    return cases


def resolve_case_list(
    *,
    tier: Optional[str] = None,
    cases: Optional[List[str]] = None,
    case_from: Optional[str] = None,
    case_to: Optional[str] = None,
) -> List[str]:
    """Resolve which testcases to run from tier / explicit list / numeric range."""
    available = set(discover_all_cases())

    if cases:
        selected = cases
    elif tier:
        if tier not in VERIFY_TIERS:
            known = ", ".join(sorted(VERIFY_TIERS))
            raise ValueError(f"Unknown tier '{tier}'. Choose from: {known}")
        selected = VERIFY_TIERS[tier]
    elif case_from or case_to:
        start = case_from or "test01"
        end = case_to or "test40"
        m1 = re.fullmatch(r"test(\d{2})", start)
        m2 = re.fullmatch(r"test(\d{2})", end)
        if not m1 or not m2:
            raise ValueError("Range endpoints must look like test01 … test40")
        lo, hi = int(m1.group(1)), int(m2.group(1))
        if lo > hi:
            lo, hi = hi, lo
        selected = [f"test{n:02d}" for n in range(lo, hi + 1)]
    else:
        selected = VERIFY_TIERS[DEFAULT_TIER]

    missing = [c for c in selected if c not in available]
    if missing:
        raise ValueError(f"Testcase(s) not found on disk: {', '.join(missing)}")

    # Preserve tier/range order, only keep those that exist.
    return [c for c in selected if c in available]


def load_prompt_lines(case_id: str) -> List[Tuple[int, str]]:
    """Return (1-based line number, stripped text) for non-empty prompt lines."""
    path = TESTCASE_DIR / case_id / "prompt.txt"
    lines: List[Tuple[int, str]] = []
    for i, raw in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        text = raw.strip()
        if text:
            lines.append((i, text))
    return lines


def finalize_case_status(result: CaseResult, *, write_requested: bool, expected_out: str) -> None:
    """Set CaseResult.status from step outcomes and post-checks."""
    counts = result.step_counts

    if counts.get("FAIL", 0) > 0:
        result.status = "FAIL"
        return
    if result.abc_status == "NOT_EQUIVALENT":
        result.status = "FAIL"
        return
    if write_requested and not result.output_file:
        result.status = "FAIL"
        result.steps.append(
            StepResult(0, "(post-run)", "FAIL", notes=f"Expected output missing: {expected_out}")
        )
        return
    if counts.get("UNSUPPORTED", 0) > 0:
        result.status = "PARTIAL"
        return
    result.status = "PASS"


def run_case(
    case_id: str,
    engine: Any,
    parser_bin: Optional[Path],
    abc_bin: Optional[Path],
    run_logger: "RunLogger",
    *,
    step_filter: Optional[set[int]] = None,
    stop_on_fail: bool = False,
    verbose: bool = False,
) -> CaseResult:
    """Execute one testcase prompt-by-prompt; each step gets its own StepResult."""
    case_dir = TESTCASE_DIR / case_id
    result = CaseResult(case_id=case_id, status="PASS")

    engine.reset()
    original_v = str(case_dir / f"{case_id}.v")
    expected_out = str(case_dir / f"{case_id}_out.v")
    had_transform = False
    write_requested = False
    abc_work = run_logger.case_dir(case_id) / "abc"

    prompt_lines = load_prompt_lines(case_id)
    total = len(prompt_lines)

    for seq, (line_no, line) in enumerate(prompt_lines, 1):
        if step_filter is not None and line_no not in step_filter:
            continue

        prefix = f"  {case_id} step {seq}/{total} (L{line_no})"

        if re.search(r"beginning of a new testcase", line, re.I):
            result.steps.append(
                StepResult(line_no, line, "SKIP", notes="testcase init — no tool call")
            )
            if verbose:
                print(f"{prefix} SKIP  init")
            continue

        spec, note = dispatch_prompt(line, case_id, engine)
        if spec is None:
            if TRANSFORM_KEYWORDS.search(line):
                had_transform = True
            result.steps.append(StepResult(line_no, line, "UNSUPPORTED", notes=note))
            if verbose:
                print(f"{prefix} UNSUPPORTED  {note[:60]}")
            continue

        if spec.name == "write_design":
            write_requested = True
        if spec.name in ("insert_buffers", "replace_gate"):
            had_transform = True

        try:
            engine_out = execute_tool(engine, spec)
        except Exception as exc:  # noqa: BLE001
            engine_out = f"Error executing {spec.name}: {exc}"

        step_status = "FAIL" if is_error_result(engine_out) else "PASS"
        result.steps.append(
            StepResult(
                line_no=line_no,
                prompt=line,
                status=step_status,
                tool=spec.name,
                tool_args=spec.arguments,
                engine_result=engine_out,
                notes=note,
            )
        )
        if verbose:
            print(f"{prefix} {step_status}  {spec.name}")

        if stop_on_fail and step_status == "FAIL":
            if verbose:
                print(f"  {case_id} — stopped at first FAIL (step L{line_no})")
            break

    out_path = expected_out if Path(expected_out).is_file() else None
    result.output_file = out_path

    if had_transform and out_path and parser_bin and abc_bin:
        abc_status, abc_detail = abc_cec_on_verilog(
            parser_bin, abc_bin, original_v, out_path, abc_work
        )
        result.abc_status = abc_status
        result.abc_detail = abc_detail
        (abc_work / "equivalence.log").write_text(abc_detail, encoding="utf-8")
        if abc_status == "ERROR":
            result.steps.append(
                StepResult(0, "(post-run ABC cec)", "FAIL", notes=abc_detail[:300])
            )
    elif had_transform and write_requested:
        result.abc_status = "SKIPPED"
        result.abc_detail = "ABC skipped — missing write_blif, output file, or ABC binary."
    else:
        result.abc_status = "N/A"

    finalize_case_status(result, write_requested=write_requested, expected_out=expected_out)
    run_logger.write_case_log(result)
    return result


def aggregate_step_stats(results: List[CaseResult]) -> Dict[str, int]:
    totals = {"PASS": 0, "FAIL": 0, "UNSUPPORTED": 0, "SKIP": 0}
    for r in results:
        for k, v in r.step_counts.items():
            totals[k] = totals.get(k, 0) + v
    return totals


class RunLogger:
    """Write human-readable per-step logs under verification_runs/."""

    def __init__(self, run_dir: Path, *, tier: str, case_list: List[str]) -> None:
        self.run_dir = run_dir
        self.tier = tier
        self.case_list = case_list
        self.run_dir.mkdir(parents=True, exist_ok=True)
        self.summary_path = run_dir / "SUMMARY.md"
        self.issues_path = run_dir / "ISSUES.md"
        self.steps_csv_path = run_dir / "steps.csv"
        self._summary_lines: List[str] = [
            f"# Verification run — {run_dir.name}",
            "",
            f"Started: {datetime.now(timezone.utc).isoformat()}",
            f"Tier   : `{tier}`",
            f"Cases  : {', '.join(case_list)}",
            "",
            "## Per testcase",
            "",
            "| Case | Case status | Steps P/F/U/S | First fail | ABC | Output |",
            "|------|-------------|---------------|------------|-----|--------|",
        ]
        self._csv_rows: List[str] = ["case_id,line_no,status,tool,prompt"]

    def case_dir(self, case_id: str) -> Path:
        d = self.run_dir / case_id
        d.mkdir(parents=True, exist_ok=True)
        return d

    def write_case_log(self, result: CaseResult) -> None:
        cdir = self.case_dir(result.case_id)
        counts = result.step_counts
        step_summary = f"{counts.get('PASS',0)}/{counts.get('FAIL',0)}/{counts.get('UNSUPPORTED',0)}/{counts.get('SKIP',0)}"
        first_fail = result.first_failure
        first_fail_txt = (
            f"L{first_fail.line_no}: {first_fail.prompt[:50]}…"
            if first_fail and len(first_fail.prompt) > 50
            else (f"L{first_fail.line_no}: {first_fail.prompt}" if first_fail else "—")
        )

        lines = [
            f"# {result.case_id} — {result.status}",
            "",
            f"Step breakdown (PASS / FAIL / UNSUPPORTED / SKIP): **{step_summary}**",
            f"Output file: {result.output_file or '(none)'}",
            f"ABC status : {result.abc_status or 'n/a'}",
            "",
        ]
        if first_fail:
            lines.extend([
                "## First failure",
                "",
                f"- Line {first_fail.line_no}: {first_fail.prompt}",
                f"- Tool: `{first_fail.tool or 'n/a'}`",
                f"- Result: {first_fail.engine_result[:200] if first_fail.engine_result else first_fail.notes}",
                "",
            ])
        if result.abc_detail:
            lines.extend(["## ABC detail", "", "```", result.abc_detail.rstrip(), "```", ""])

        lines.append("## Steps")
        lines.append("")
        for step in result.steps:
            icon = {"PASS": "✓", "FAIL": "✗", "UNSUPPORTED": "?", "SKIP": "·"}.get(step.status, "?")
            lines.append(f"### [{icon}] Line {step.line_no} — {step.status}")
            lines.append("")
            lines.append(f"**Prompt:** {step.prompt}")
            lines.append("")
            if step.tool:
                lines.append(f"**Tool:** `{step.tool}`({step.tool_args})")
                lines.append("")
            if step.engine_result:
                lines.extend(["**Engine result:**", "```", step.engine_result.rstrip(), "```", ""])
            if step.notes:
                lines.append(f"**Notes:** {step.notes}")
            lines.append("")

            prompt_csv = step.prompt.replace('"', '""')
            self._csv_rows.append(
                f'{result.case_id},{step.line_no},{step.status},{step.tool or ""},"{prompt_csv}"'
            )

        (cdir / "report.md").write_text("\n".join(lines), encoding="utf-8")

        self._summary_lines.append(
            f"| {result.case_id} | {result.status} | {step_summary} | {first_fail_txt} | "
            f"{result.abc_status or '-'} | {result.output_file or '-'} |"
        )

    def finalize(self, results: List[CaseResult], engine_tools: List[str]) -> None:
        passed = sum(1 for r in results if r.status == "PASS")
        partial = sum(1 for r in results if r.status == "PARTIAL")
        failed = sum(1 for r in results if r.status == "FAIL")
        step_totals = aggregate_step_stats(results)

        self._summary_lines.extend([
            "",
            "## Totals (testcase level)",
            "",
            f"- **PASS** (all steps OK): {passed}",
            f"- **PARTIAL** (no FAIL, some UNSUPPORTED): {partial}",
            f"- **FAIL** (≥1 step FAIL or ABC fail): {failed}",
            f"- **Cases run**: {len(results)}",
            "",
            "## Totals (step level)",
            "",
            f"- **PASS**: {step_totals.get('PASS', 0)}",
            f"- **FAIL**: {step_totals.get('FAIL', 0)}",
            f"- **UNSUPPORTED**: {step_totals.get('UNSUPPORTED', 0)}",
            f"- **SKIP** (init): {step_totals.get('SKIP', 0)}",
            "",
            "Step-level CSV: `steps.csv`",
            "Problem steps: `ISSUES.md`",
            "",
            "## Engine tools available",
            "",
            ", ".join(f"`{t}`" for t in engine_tools) or "(none)",
            "",
        ])
        self.steps_csv_path.write_text("\n".join(self._csv_rows), encoding="utf-8")
        self._write_issues(results)

    def _write_issues(self, results: List[CaseResult]) -> None:
        """One-page list of every FAIL / UNSUPPORTED step for fast human triage."""
        problem_cases = []
        for r in results:
            bad_steps = [s for s in r.steps if s.status in ("FAIL", "UNSUPPORTED")]
            if bad_steps or r.abc_status in ("NOT_EQUIVALENT", "ERROR"):
                problem_cases.append((r, bad_steps))

        lines = [
            f"# Issues — {self.run_dir.name}",
            "",
            f"Tier: `{self.tier}`",
            "",
        ]

        if not problem_cases:
            lines.extend([
                "No problems — all steps PASS (or SKIP init only).",
                "",
                f"Full details: `{self.summary_path.name}`",
            ])
            self.issues_path.write_text("\n".join(lines), encoding="utf-8")
            return

        total_bad = sum(len(bs) for _, bs in problem_cases)
        abc_bad = sum(
            1 for r, _ in problem_cases if r.abc_status in ("NOT_EQUIVALENT", "ERROR")
        )
        lines.append(
            f"**{total_bad} problem step(s)** in **{len(problem_cases)} case(s)**"
            + (f", **{abc_bad} ABC failure(s)**" if abc_bad else "")
            + ".",
        )
        lines.extend([
            "",
            "> Read this file first. Drill down: `<case>/report.md`",
            "",
        ])

        for result, bad_steps in problem_cases:
            lines.extend([
                f"## {result.case_id} — {result.status}",
                "",
            ])
            if result.abc_status in ("NOT_EQUIVALENT", "ERROR"):
                lines.extend([
                    f"- **ABC {result.abc_status}** — see `{result.case_id}/abc/equivalence.log`",
                    "",
                ])

            if bad_steps:
                lines.extend([
                    "| Line | Status | Tool | Prompt (truncated) | Why |",
                    "|------|--------|------|--------------------|-----|",
                ])
                for s in bad_steps:
                    prompt = s.prompt if len(s.prompt) <= 72 else s.prompt[:69] + "…"
                    why = (
                        (s.engine_result[:80] + "…")
                        if s.status == "FAIL" and s.engine_result
                        else s.notes
                    )
                    why = why.replace("|", "\\|").replace("\n", " ")
                    prompt = prompt.replace("|", "\\|")
                    lines.append(
                        f"| L{s.line_no} | {s.status} | {s.tool or '—'} | {prompt} | {why} |"
                    )
                lines.append("")

            lines.append(f"Full report: `{result.case_id}/report.md`")
            lines.append("")

        self.issues_path.write_text("\n".join(lines), encoding="utf-8")
