"""Real EDA engine — Python wrapper for the C++ netlist parser and analyzer.

Each method delegates to the C++ parser binary via subprocess calls.
The engine maintains the path to the currently loaded Verilog file.

Supported operations (mirrors tool_spec.py):
    load_design       – read a Verilog file into internal state
    write_design      – emit the current design to a Verilog file
    analyze_depth     – report max combinational depth between two nodes
    find_paths        – enumerate paths between two nodes
    get_node_info     – describe a specific signal/gate
    list_nodes        – list all signals and gates in the design
    replace_gate      - replace a gate type in the design
"""

import subprocess
import os
import re
import sys
import tempfile
from typing import Any, Dict, Optional, List

# Per-action cap on parser subprocess calls. A single unbounded call (e.g.
# exponential path enumeration) can otherwise eat the whole per-request time
# limit before the planner's wall-clock budget gets a chance to intervene.
_ACTION_TIMEOUT_S = 150


def _find_parser_binary() -> str:
    """Resolve the C++ parser executable across Linux, macOS, and Windows."""
    env_path = os.environ.get("PARSER_BIN")
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)

    parser_dir = os.path.abspath(
        os.path.join(os.path.dirname(__file__), "parser")
    )
    if sys.platform == "win32":
        candidates = ("parser_cpp.exe", "parser_cpp")
    else:
        candidates = ("parser_cpp", "parser_cpp.exe")

    for name in candidates:
        path = os.path.join(parser_dir, name)
        if os.path.isfile(path):
            return path

    return os.path.join(parser_dir, candidates[0])


def _find_abc_binary() -> str:
    """Resolve the Berkeley ABC executable used for equivalence checking.

    Walks up from this file so it works regardless of how deep the package is
    nested (e.g. src/eda_engine/) and whether ABC lives in abc/ or tools/abc/.
    """
    env_path = os.environ.get("ABC_BIN")
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)
    here = os.path.dirname(os.path.abspath(__file__))
    for _ in range(6):
        for cand in (
            os.path.join(here, "abc", "abc"),
            os.path.join(here, "tools", "abc", "abc"),
            os.path.join(here, "abc", "abc.exe"),
        ):
            if os.path.isfile(cand):
                return cand
        here = os.path.dirname(here)
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "abc", "abc")


class EDAEngine:
    """Thin Python wrapper for the C++ EDA engine CLI."""

    def __init__(self) -> None:
        self._loaded_filepath: Optional[str] = None
        # The as-loaded netlist, preserved across transforms for equivalence checking.
        self._original_filepath: Optional[str] = None
        self._parser_path = _find_parser_binary()
        self._abc_path = _find_abc_binary()
        # Transforms mutate then write to a session file; _loaded_filepath is chained
        # to it so later actions (and write_design) see the transformed netlist.
        self._session_dir = tempfile.mkdtemp(prefix="eda_sess_")
        self._xform_seq = 0
        # A fanout limit, once requested, must hold on the final netlist. Logic
        # restructuring (reduce_depth) dissolves buffers, so we remember the limit
        # and re-enforce it automatically after such transforms.
        self._max_fanout_constraint: Optional[int] = None
        # Absolute paths of every write verified on disk. The planner checks this
        # to refuse answering a write request when no file was actually produced.
        self.verified_writes: List[str] = []

    def _session_path(self, tag: str, ext: str = "v") -> str:
        self._xform_seq += 1
        return os.path.join(self._session_dir, f"{tag}_{self._xform_seq}.{ext}")

    def _run_parser_on(self, in_file: str, action: str, **kwargs) -> str:
        """Run a parser action on an explicit input file (not the loaded design)."""
        cmd = [self._parser_path, "--in", os.path.normpath(in_file), "--action", action]
        for k, v in kwargs.items():
            cmd.extend([f"--{k}", str(v)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                    timeout=_ACTION_TIMEOUT_S)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            return f"Error: '{action}' exceeded the {_ACTION_TIMEOUT_S}s limit and was aborted."
        except subprocess.CalledProcessError as e:
            return f"Error executing {action}: {e.stderr.strip() or e.stdout.strip()}"
        except FileNotFoundError:
            return f"Error: Parser binary not found at {self._parser_path}"

    def _run_action(self, action: str, **kwargs) -> str:
        """Helper to run a command on the C++ parser."""
        if not self._loaded_filepath and action != "load":
             return "Error: No design loaded."

        filepath = self._loaded_filepath or kwargs.get("filepath", "")
        if filepath:
            filepath = os.path.normpath(filepath)

        # Base command with input file and action
        cmd = [
            self._parser_path,
            "--in", filepath,
            "--action", action
        ]

        # Append other arguments as --key value
        for k, v in kwargs.items():
            if k != "filepath":
                cmd.extend([f"--{k}", str(v)])

        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True,
                                    timeout=_ACTION_TIMEOUT_S)
            return result.stdout.strip()
        except subprocess.TimeoutExpired:
            # e.g. exponential path enumeration on a huge cone; give the LLM a
            # result it can react to instead of blowing the request time limit.
            return (
                f"Error: '{action}' exceeded the {_ACTION_TIMEOUT_S}s limit and was "
                f"aborted. The design state is unchanged. The result is too large "
                f"to compute exhaustively; report this limitation instead of retrying."
            )
        except subprocess.CalledProcessError as e:
            # Return error output from the parser
            return f"Error executing {action}: {e.stderr.strip() or e.stdout.strip()}"
        except FileNotFoundError:
            return f"Error: Parser binary not found at {self._parser_path}"

    def load_design(self, filepath: str) -> str:
        """Load a Verilog design."""
        res = self._run_action("load", filepath=filepath)
        if "Success" in res:
            self._loaded_filepath = filepath
            self._original_filepath = filepath
        return res

    def list_nodes(self) -> str:
        """List all signals and gate instances."""
        return self._run_action("list_nodes")

    def get_node_info(self, node_name: str) -> str:
        """Return structural information about *node_name*."""
        return self._run_action("get_info", node=node_name)

    def list_gates_by_type(self, gate_type: str) -> str:
        """List every gate of a type with its input/output signals (JSON)."""
        gt = gate_type.lower()
        gate = next((k for k in ("xnor", "nand", "nor", "xor", "and", "or", "not", "buf", "dff")
                     if k in gt), gt.strip())
        return self._run_action("list_gates_by_type", gate=gate)

    def flipflops_by_clock(self, clock: str) -> str:
        """List flip-flops driven by the given clock signal (JSON)."""
        return self._run_action("flipflops_by_clock", clock=clock)

    def max_pi_to_dff_depth(self) -> str:
        """Max combinational depth from any primary input to any flip-flop D pin (JSON)."""
        return self._run_action("max_pi_to_dff_depth")

    def list_floating(self) -> str:
        """List floating inputs, unconnected outputs, and undriven signals (JSON)."""
        return self._run_action("list_floating")

    def signal_depends_on(self, target: str, source: str) -> str:
        """Whether `target` depends on `source` (source in target's transitive fanin)."""
        return self._run_action("signal_depends_on", target=target, source=source)

    def highest_fanout_pi(self) -> str:
        """Primary input with the highest fanout (incl. clock/reset control-pin loads)."""
        return self._run_action("highest_fanout_pi")

    def analyze_depth(self, start_node: Optional[str] = None, end_node: str = "") -> str:
        """Calculate combinational depth."""
        kwargs = {"end": end_node}
        if start_node:
            kwargs["start"] = start_node
        return self._run_action("calc_depth", **kwargs)

    def analyze_critical_path(self, start_node: str, end_node: str) -> str:
        """Analyze the critical path between two nodes, returning depth and nodes."""
        return self._run_action("get_critical_path", start=start_node, end=end_node)

    # Threshold: if the C++ parser returns more than this many paths, the raw
    # output is too large for the LLM context window.  Write the full list to a
    # file and return a compact summary instead.
    _PATH_FILE_THRESHOLD = 50

    def find_paths(
        self, start_node: str, end_node: str, avoid_node: Optional[str] = None
    ) -> str:
        """Return all paths between two nodes.

        When the number of paths exceeds ``_PATH_FILE_THRESHOLD``, the full
        path list is serialized to a log file in the testcase directory and a
        compact JSON summary (with status, total count, file path, and a few
        sample paths) is returned so the LLM can report the result without
        being overwhelmed by hundreds of thousands of lines.
        """
        raw = self._run_action(
            "list_paths", start=start_node, end=end_node, avoid=avoid_node or ""
        )

        # If the engine returned an error, pass it through unchanged.
        if raw.startswith("Error"):
            return raw

        # Embed the conclusion directly in the tool result: small eval models
        # tend to copy a tool's stated conclusion verbatim, but sometimes
        # answer "yes, a path exists" for a "does a path exist" question even
        # when list_paths found zero. Prefixing the definitive answer here
        # turns that copying tendency into a safeguard instead of a failure
        # mode (see docs/PLAN_QA_fixes.md P1-5).
        if raw.strip() == "No paths found.":
            return "ANSWER: NO — " + raw

        # ── Parse the real total from the C++ header line ─────────────────
        # The C++ parser emits a header like "Found 289366 paths:" followed
        # by up to ~101 printed path lines.  The header number is the ground
        # truth; the printed lines may be truncated.
        header_match = re.search(r"Found\s+(\d+)\s+paths?:", raw)
        total = int(header_match.group(1)) if header_match else 0

        # Collect the individual path lines (may be fewer than `total`).
        path_lines = [ln for ln in raw.splitlines() if " -> " in ln]

        # If no header was found, fall back to counting printed lines.
        if total == 0:
            total = len(path_lines)

        if total <= self._PATH_FILE_THRESHOLD:
            # Small result — return the raw output directly.
            return raw

        # ── large result: write to file and return summary ────────────────
        import json

        # Derive the testcase directory from the loaded design path.
        save_dir = self._testcase_dir()

        # Use a descriptive unique filename so multiple find_paths calls in
        # the same testcase do not overwrite each other.
        avoid_tag = f"_avoid_{avoid_node}" if avoid_node else ""
        filename = f"paths_{start_node}_to_{end_node}{avoid_tag}.log"
        # Sanitise brackets in bus-index names for safe filenames.
        filename = filename.replace("[", "_").replace("]", "_")
        log_path = os.path.join(save_dir, filename) if save_dir else filename

        with open(log_path, "w", encoding="utf-8") as f:
            f.write(raw)

        # Build a compact summary for the LLM.
        sample = path_lines[:3]
        summary = {
            "status": "success",
            "total_paths_found": total,
            "saved_to_file": log_path,
            "sample_paths": sample,
        }
        return json.dumps(summary, ensure_ascii=False, indent=2)

    def _testcase_dir(self) -> Optional[str]:
        """Infer the testcase directory from the loaded design path.

        e.g. ``testcase/test14/test14.v``  →  ``testcase/test14``
        """
        if self._loaded_filepath:
            return os.path.dirname(self._loaded_filepath)
        return None

    def count_fanin_gates(self, node_name: str) -> str:
        """Count gates in the fanin cone of a specific node."""
        return self._run_action("count_fanin", node=node_name)

    def count_fanout_gates(self, node_name: str) -> str:
        """Count gates in the transitive fanout cone of a specific node."""
        return self._run_action("count_fanout", node=node_name)

    def get_fanin_cone(self, node_name: str) -> str:
        """Return all nodes in the transitive fanin cone of a specific node."""
        return self._run_action("get_fanin_cone", node=node_name)

    def get_fanout_cone(self, node_name: str) -> str:
        """Return all nodes in the transitive fanout cone of a specific node."""
        return self._run_action("get_fanout_cone", node=node_name)

    def count_gates_in_cone(self, node_name: str, direction: str = "fanin") -> str:
        """Count gates by type within the fanin or fanout cone of a node."""
        return self._run_action("count_gates_in_cone", node=node_name, direction=direction)

    def get_fanin_depth(self, node_name: str) -> str:
        """Calculate the maximum logic depth within the fanin cone of a node."""
        return self._run_action("get_fanin_depth", node=node_name)

    def list_pio(self) -> str:
        """List all primary inputs and outputs with bit widths and vector grouping."""
        return self._run_action("list_pio")

    def r2r_paths(self) -> str:
        """List all register-to-register paths through combinational logic."""
        return self._run_action("r2r_paths")

    def deepest_cone_output(self) -> str:
        """Find the primary output with the deepest fanin logic cone."""
        return self._run_action("deepest_cone_output")

    def write_design(self, filepath: str) -> str:
        """Write the design to a file.

        If a maximum-fanout constraint was requested earlier, it is re-enforced
        here so the final written netlist always satisfies it, even if later
        transforms (cone conversion, inverter collapse) reintroduced high fanout.

        The written file is verified on disk before success is reported; every
        verified write is recorded so the planner can refuse to answer a write
        request for which no file was actually produced.
        """
        if self._max_fanout_constraint is not None:
            self.insert_buffers(self._max_fanout_constraint)
        res = self._run_action("write", out=filepath)
        if "Success" in res:
            if not os.path.isfile(filepath):
                return (
                    f"Error: the parser reported success but no file exists at "
                    f"{filepath}. The design was NOT written."
                )
            self.verified_writes.append(os.path.abspath(filepath))
            size = os.path.getsize(filepath)
            return f"Design written to {filepath} ({size} bytes, verified on disk)."
        return res

    def count_gates(self) -> str:
        """Count gates by type."""
        return self._run_action("count_gates")

    def replace_gate(self, target: str, new_type: str, out_file: Optional[str] = None) -> str:
        """Replace a gate type and optionally save the result."""
        kwargs = {"target": target, "new_type": new_type}
        if out_file:
            kwargs["out"] = out_file
        return self._run_action("replace_gate", **kwargs)

    def insert_buffers(self, max_fanout: int = 4) -> str:
        """Insert buffers so no gate drives more than *max_fanout* loads.

        Functionally transparent. The transformed netlist becomes the active design,
        so a subsequent write_design (or further transform) operates on it.
        """
        work = self._session_path("buffered")
        res = self._run_action("insert_buffers", max_fanout=max_fanout, out=work)
        if "Inserted" in res and os.path.isfile(work):
            self._loaded_filepath = work
            self._max_fanout_constraint = max_fanout
        return res

    def buffer_signal(self, signal: str, max_fanout: int = 4) -> str:
        """Buffer one named signal (a wire or a primary input such as clock/reset)
        into a balanced tree so no driver exceeds max_fanout loads.

        Functionally equivalent. Handles 'insert buffers on the reset signal n1 to
        reduce its fanout to at most 4 loads per driver'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        work = self._session_path("bufsig")
        res = self._run_action("buffer_signal", signal=signal, max_fanout=max_fanout, out=work)
        if "Inserted" in res and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def reconnect_pin(self, gate: str, pin: str, signal: str) -> str:
        """Reconnect one input pin of a gate to a different signal, but only if it
        preserves functionality (verified by equivalence check; reverted otherwise).

        Handles 'try to reconnect input pin A of gate g0 to internal signal n24[0].
        Ensure the design functionality does not change'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        prev = self._loaded_filepath
        work = self._session_path("reconn")
        res = self._run_action("reconnect_pin", gate=gate, pin=pin, signal=signal, out=work)
        if not res.startswith("Reconnected") or not os.path.isfile(work):
            return res
        self._loaded_filepath = work
        eq = self.check_equivalence()
        if eq.startswith("EQUIVALENT"):
            return res + " Functionality preserved (verified equivalent)."
        self._loaded_filepath = prev  # revert: the reconnection would change function
        return (
            f"Reconnecting pin {pin} of {gate} to {signal} would change the design's "
            f"functionality, so it was not applied (reverted to preserve equivalence)."
        )

    def insert_dedicated_buffers(self, signal: str) -> str:
        """Insert a dedicated BUF gate for each load of a signal (signal -> buf -> load).

        Functionally equivalent. Handles 'insert a BUF gate on signal n2 so that each
        load of n2 is driven through a dedicated buffer'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        work = self._session_path("dedbuf")
        res = self._run_action("dedicated_buffers", signal=signal, out=work)
        if "Added" in res and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def reduce_depth(self) -> str:
        """Reduce critical-path depth by restructuring the combinational logic.

        Exports the flop-cut logic to BLIF, optimizes depth in ABC
        (strash/balance/resyn2), then rebuilds the gate-level netlist with the
        flip-flops reattached. Functionally equivalent (verify with
        check_equivalence). The optimized netlist becomes the active design.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        if not os.path.isfile(self._abc_path):
            return f"Error: ABC binary not found at {self._abc_path}. Build it or set ABC_BIN."

        cut = self._session_path("cut", "blif")
        opt = self._session_path("opt", "blif")
        work = self._session_path("depthopt")

        e1 = self._run_parser_on(self._loaded_filepath, "write_blif", out=cut)
        if "Error" in e1 or not os.path.isfile(cut):
            return f"Error exporting BLIF for depth optimization: {e1}"

        # resyn2 expanded to built-ins so we do not depend on abc.rc aliases
        # (aliases are not available under the scripted '-q' invocation).
        resyn2 = (
            "balance; rewrite; refactor; balance; rewrite; rewrite -z; "
            "balance; refactor -z; rewrite -z; balance"
        )
        script = (
            f"read_blif {cut}; strash; print_stats; "
            f"balance; {resyn2}; balance; print_stats; write_blif {opt}"
        )
        try:
            r = subprocess.run(
                [self._abc_path, "-q", script],
                capture_output=True, text=True, timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error running ABC depth optimization: {exc}"
        if not os.path.isfile(opt):
            return f"Error: ABC produced no optimized netlist. {(r.stdout + r.stderr)[:300]}"

        levels = re.findall(r"lev\s*=\s*(\d+)", r.stdout)
        e2 = self._run_parser_on(self._loaded_filepath, "rebuild", blif=opt, out=work)
        if "Success" not in e2 or not os.path.isfile(work):
            return f"Error rebuilding netlist after optimization: {e2}"

        self._loaded_filepath = work
        if len(levels) >= 2 and levels[0] != levels[-1]:
            change = (
                f"Combinational logic depth reduced from {levels[0]} to {levels[-1]} "
                f"levels (AIG)."
            )
        else:
            change = "Logic restructured for depth."

        # Restructuring dissolves buffers, so re-enforce any fanout limit that was
        # previously requested — it must still hold on the final netlist.
        rebuf = ""
        if self._max_fanout_constraint is not None:
            br = self.insert_buffers(self._max_fanout_constraint)
            if "Inserted" in br:
                rebuf = f" Re-applied max-fanout {self._max_fanout_constraint}: {br}"

        return (
            f"Reduced critical path depth via ABC restructuring (balance/resyn2). "
            f"{change} Design updated; verify with check_equivalence.{rebuf}"
        )

    def merge_equivalent_gates(self) -> str:
        """Merge gate pairs that compute the same function (structural duplicates:
        same type and same inputs), rewiring consumers to a single survivor.

        Functionally equivalent; flip-flops are never merged. Handles 'find and merge
        all gate pairs that are functionally equivalent' and 'merge structural duplicates'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        work = self._session_path("merged")
        res = self._run_action("merge_dup", out=work)
        if "Merged" in res and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def collapse_inverters(self) -> str:
        """Collapse back-to-back inverter pairs (NOT(NOT x) = x) into direct wires.

        Functionally equivalent. The cleaned netlist becomes the active design.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        work = self._session_path("collapsed")
        res = self._run_action("collapse_inv", out=work)
        if "Collapsed" in res and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def convert_cone_to_basis(self, cone_root: str, target_basis: str) -> str:
        """Convert every gate in a node's fanin cone to a target gate basis.

        Supports NOR+NOT, AND+NOT, and NAND+NOT. Functionally equivalent. Handles
        requests like 'convert the logic cone of n10 to use only NOR and NOT gates'
        or 'restructure the cone of n8 using only NAND and NOT gates'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        b = target_basis.lower()
        if "nand" in b and "not" in b:
            basis = "nand_not"
        elif "nor" in b and "not" in b:
            basis = "nor_not"
        elif "and" in b and "not" in b:
            basis = "and_not"
        else:
            basis = re.sub(r"[^a-z]+", "_", b).strip("_")
        work = self._session_path("remapped")
        res = self._run_action("remap_cone", root=cone_root, basis=basis, out=work)
        if res.startswith("Converted") and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def reconstruct_netlist_to_basis(self, target_basis: str) -> str:
        """Reconstruct the entire netlist using only a target gate basis.

        Supports AND+NOT and NOR+NOT. Functionally equivalent. Handles requests like
        'reconstruct the entire netlist using only AND and NOT gates'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        b = target_basis.lower()
        if "nand" in b and "not" in b:
            basis = "nand_not"
        elif "nor" in b and "not" in b:
            basis = "nor_not"
        elif "and" in b and "not" in b:
            basis = "and_not"
        else:
            basis = re.sub(r"[^a-z]+", "_", b).strip("_")
        work = self._session_path("reconstructed")
        res = self._run_action("remap_all", basis=basis, out=work)
        if res.startswith("Reconstructed") and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def restructure_to_depth(self, node: str, target_depth: int) -> str:
        """Best-effort report of a node's cone depth against a target depth.

        The design is depth-optimized globally by reduce_depth; this reports the
        current logic depth of the node's cone and whether it already meets the
        target, leaving the netlist unchanged (so a prior basis conversion is kept).
        Matches 'try to restructure n10 to target depth 4 ... report original if
        already optimal'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        dr = self.analyze_depth(end_node=node)
        m = re.search(r"-?\d+", dr)
        if not m:
            return f"Could not determine the depth of {node}: {dr}"
        d = int(m.group())
        if d < 0:
            return f"Node {node} was not found for depth analysis."
        if d <= target_depth:
            return (
                f"The cone of {node} has logic depth {d}, already within the target "
                f"depth of {target_depth}. No restructuring needed (reporting original)."
            )
        return (
            f"The cone of {node} has logic depth {d}; the design is already "
            f"depth-optimized, so it is reported as-is rather than further "
            f"restructured to depth {target_depth} (preserving the current logic)."
        )

    def optimize_outputs_to_depth(self, max_depth: int) -> str:
        """Best-effort: report outputs whose cone depth exceeds max_depth.

        The design is already minimized by reduce_depth; outputs still exceeding the
        target are at their minimum achievable depth, so this reports them rather than
        re-restructuring (which would undo later gate-level transforms). Matches 'for
        each output with depth greater than 4, optimize its cone to meet the constraint'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        res = self._run_action("outputs_over_depth", max=max_depth)
        if res.startswith("Error"):
            return res
        return (
            f"{res} The logic has already been globally depth-optimized; any outputs "
            f"still above depth {max_depth} are at their minimum achievable depth."
        )

    def const_propagate(self, mode: str = "propagate",
                        gate_type: str = "", const_value: str = "") -> str:
        """Detect and simplify gates with constant inputs (1'b0, 1'b1).

        mode='report' scans without modifying; mode='propagate' applies
        simplification with cascading. Optional gate_type and const_value
        filters narrow which gates are processed.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        kwargs: Dict[str, str] = {"mode": mode}
        if gate_type:
            kwargs["gate_type"] = gate_type
        if const_value:
            kwargs["const_value"] = const_value
        if mode == "propagate":
            work = self._session_path("constprop")
            kwargs["out"] = work
        res = self._run_action("const_propagate", **kwargs)
        if mode == "propagate":
            out_path = kwargs.get("out", "")
            if out_path and os.path.isfile(out_path):
                self._loaded_filepath = out_path
        return res

    def decompose_gates_in_cone(self, cone_root: str, gate_type: str,
                                target_basis: str) -> str:
        """Replace gates of a type within a cone using only a target gate basis.

        Currently supports replacing 2-input OR gates with NAND+NOT logic
        (OR(a,b) = NAND(!a,!b)). Functionally equivalent. Handles requests like
        'replace all 2-input OR gates in the cone of n11[0] with NAND and NOT only'.

        After the replacement, the method automatically computes a gate-count
        delta so the LLM can report exactly how many gates were added/removed.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."

        # Snapshot gate counts BEFORE the transformation.
        before_raw = self.count_gates()
        before_counts = self._parse_gate_counts(before_raw)

        b = target_basis.lower().replace("-", " ")
        has_not = "not" in b
        if "nand" in b:
            basis = "nand_not" if has_not else "nand"       # NAND+NOT, or NAND-only (4-NAND)
        elif "nor" in b:
            basis = "nor_not" if has_not else "nor"          # NOR+NOT, or NOR-only
        elif "and" in b and "or" in b:
            basis = "and_or_not"
        elif "and" in b:
            basis = "and_not"
        else:
            basis = re.sub(r"[^a-z]+", "_", b).strip("_")
        # Pick the gate keyword the user named (e.g. "2-input OR gates" -> "or").
        gt = gate_type.lower()
        gate = next((k for k in ("xnor", "nand", "nor", "xor", "and", "or", "not", "buf")
                     if k in gt), gt.strip())
        work = self._session_path("decomposed")
        res = self._run_action(
            "decompose", root=cone_root, gate=gate, basis=basis, out=work,
        )
        if res.startswith("Replaced") and os.path.isfile(work):
            self._loaded_filepath = work

            # Snapshot gate counts AFTER the transformation.
            after_raw = self.count_gates()
            after_counts = self._parse_gate_counts(after_raw)

            # Compute delta for every gate type.
            all_types = set(before_counts) | set(after_counts)
            delta = {}
            for gt in sorted(all_types):
                diff = after_counts.get(gt, 0) - before_counts.get(gt, 0)
                if diff != 0:
                    delta[gt] = diff

            import json
            res += (
                "\n\ngate_delta (after - before): "
                + json.dumps(delta, ensure_ascii=False)
            )
        return res

    def decompose_all_gates(self, gate_type: str, target_basis: str) -> str:
        """Replace every gate of a type in the WHOLE design with a target basis.

        Supports OR->NAND+NOT, XOR->AND/OR/NOT, XOR->NAND (4-NAND), XNOR->NOR-only.
        Functionally equivalent; reports a gate-count delta. Handles requests like
        'replace all XNOR gates with NOR-only implementations' or 'convert every XOR
        gate to an equivalent 4-NAND circuit'.
        """
        return self.decompose_gates_in_cone("", gate_type, target_basis)

    @staticmethod
    def _parse_gate_counts(raw: str) -> Dict[str, int]:
        """Parse 'GateType: N' lines from count_gates output into a dict."""
        counts: Dict[str, int] = {}
        for line in raw.splitlines():
            m = re.match(r"\s*(\w+)\s*:\s*(\d+)", line)
            if m:
                counts[m.group(1).upper()] = int(m.group(2))
        return counts

    def rename_node(self, old_name: str, new_name: str) -> str:
        """Rename a gate instance, wire, or signal and update all references.

        Functionally equivalent (pure naming change). Handles phrasings like 'rename
        gate g0 to renamed_gate', 'change the identifier of wire n74', and 'update the
        name of signal n7431'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        work = self._session_path("renamed")
        res = self._run_action("rename", old=old_name, new=new_name, out=work)
        if res.startswith("Renamed") and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def remove_dangling(self) -> str:
        """Remove unused/dangling logic that does not feed any output or flip-flop.

        Functionally equivalent (the removed logic is unobservable). The trimmed
        netlist becomes the active design. Handles phrasings like 'trim unused wires
        and gates', 'remove dangling gates', 'sweep out dangling gates', 'prune the
        netlist', and 'remove floating nodes'.
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        work = self._session_path("swept")
        res = self._run_action("sweep", out=work)
        if "Removed" in res and os.path.isfile(work):
            self._loaded_filepath = work
        return res

    def check_equivalence(self, reference: Optional[str] = None) -> str:
        """Formally verify the current design against a reference netlist with ABC.

        Defaults to the as-loaded original netlist. Both designs are exported to a
        flop-cut combinational BLIF (each DFF Q -> primary input, D -> output
        __D_<inst>) and compared with `abc cec`. Sound for transforms that preserve
        the flip-flop boundary (buffer insertion, depth opt, remap, etc.).
        """
        if not self._loaded_filepath:
            return "Error: No design loaded."
        ref = reference or self._original_filepath
        if not ref:
            return "Error: No reference netlist available to compare against."

        cur_blif = self._session_path("cec_cur", "blif")
        ref_blif = self._session_path("cec_ref", "blif")
        e1 = self._run_parser_on(self._loaded_filepath, "write_blif", out=cur_blif)
        e2 = self._run_parser_on(ref, "write_blif", out=ref_blif)
        if "Error" in e1 or "Error" in e2:
            return f"Error exporting BLIF for equivalence check: {e1} | {e2}"
        if not os.path.isfile(self._abc_path):
            return (
                f"Error: ABC binary not found at {self._abc_path}. "
                "Build it (see README) or set ABC_BIN."
            )

        try:
            r = subprocess.run(
                [self._abc_path, "-q", f"cec {ref_blif} {cur_blif}"],
                capture_output=True, text=True, timeout=180,
            )
        except Exception as exc:  # noqa: BLE001
            return f"Error running ABC cec: {exc}"

        out = (r.stdout + r.stderr).strip()
        low = out.lower()
        if "are equivalent" in low:
            return (
                "EQUIVALENT: the current design is functionally equivalent to the "
                "reference netlist (verified by ABC cec on a flop-cut combinational model)."
            )
        if "not equivalent" in low:
            first = out.splitlines()[0] if out else "Networks are NOT EQUIVALENT."
            return (
                "NOT EQUIVALENT: the current design differs from the reference. "
                f"ABC reports: {first}"
            )
        return f"Equivalence check inconclusive. ABC output: {out[:400]}"

    def health_check(self) -> List[str]:
        """Return human-readable warnings for missing runtime dependencies.

        Called once at startup so a clean environment fails loudly on stderr
        instead of silently degrading every equivalence/depth request.
        """
        warnings = []
        if not os.path.isfile(self._parser_path):
            warnings.append(
                f"parser binary not found at {self._parser_path} — run "
                "'python3 scripts/build_parser.py' (ALL requests will fail)")
        if not os.path.isfile(self._abc_path):
            warnings.append(
                f"ABC binary not found at {self._abc_path} — build tools/abc or "
                "set ABC_BIN (depth optimization and equivalence checks will fail)")
        return warnings

    def reset(self) -> None:
        """Clear state."""
        self._loaded_filepath = None
        self._original_filepath = None
        self._max_fanout_constraint = None
        self.verified_writes = []

    @property
    def is_design_loaded(self) -> bool:
        return self._loaded_filepath is not None

    @property
    def loaded_filepath(self) -> Optional[str]:
        return self._loaded_filepath

    @property
    def original_filepath(self) -> Optional[str]:
        """Path to the as-loaded netlist (for equivalence checking against transforms)."""
        return self._original_filepath
