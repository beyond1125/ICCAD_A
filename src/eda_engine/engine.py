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
import sys
import tempfile
from typing import Any, Dict, Optional, List


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
    """Resolve the Berkeley ABC executable used for equivalence checking."""
    env_path = os.environ.get("ABC_BIN")
    if env_path and os.path.isfile(env_path):
        return os.path.abspath(env_path)
    root = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    for cand in (
        os.path.join(root, "abc", "abc"),
        os.path.join(root, "tools", "abc", "abc"),
        os.path.join(root, "abc", "abc.exe"),
    ):
        if os.path.isfile(cand):
            return cand
    return os.path.join(root, "abc", "abc")


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

    def _session_path(self, tag: str, ext: str = "v") -> str:
        self._xform_seq += 1
        return os.path.join(self._session_dir, f"{tag}_{self._xform_seq}.{ext}")

    def _run_parser_on(self, in_file: str, action: str, **kwargs) -> str:
        """Run a parser action on an explicit input file (not the loaded design)."""
        cmd = [self._parser_path, "--in", os.path.normpath(in_file), "--action", action]
        for k, v in kwargs.items():
            cmd.extend([f"--{k}", str(v)])
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
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
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
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

    def analyze_depth(self, start_node: Optional[str] = None, end_node: str = "") -> str:
        """Calculate combinational depth."""
        kwargs = {"end": end_node}
        if start_node:
            kwargs["start"] = start_node
        return self._run_action("calc_depth", **kwargs)

    def analyze_critical_path(self, start_node: str, end_node: str) -> str:
        """Analyze the critical path between two nodes, returning depth and nodes."""
        return self._run_action("get_critical_path", start=start_node, end=end_node)

    def find_paths(
        self, start_node: str, end_node: str, avoid_node: Optional[str] = None
    ) -> str:
        """Return all paths between two nodes."""
        return self._run_action(
            "list_paths", start=start_node, end=end_node, avoid=avoid_node or ""
        )

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

    def get_fanin_depth(self, node_name: str) -> str:
        """Calculate the maximum logic depth within the fanin cone of a node."""
        return self._run_action("get_fanin_depth", node=node_name)

    def write_design(self, filepath: str) -> str:
        """Write the design to a file."""
        res = self._run_action("write", out=filepath)
        if "Success" in res:
            return f"Design written to {filepath}."
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
                capture_output=True, text=True, timeout=300,
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

    def reset(self) -> None:
        """Clear state."""
        self._loaded_filepath = None
        self._original_filepath = None

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
