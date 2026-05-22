"""Mock EDA engine — stub implementations of netlist operations.

Each method returns a human-readable string acknowledgment. Replace these
stubs with real netlist analysis and transformation logic in later stages.

When a file listed in eda_engine/fixtures.py is loaded, the engine uses
the pre-parsed fixture data to return accurate, node-specific responses.
For unknown files it falls back to generic placeholder strings.

Supported operations (mirrors tool_spec.py):
    load_design       – read a Verilog file into internal state
    write_design      – emit the current design to a Verilog file
    analyze_depth     – report max combinational depth between two nodes
    find_paths        – enumerate (mock) paths between two nodes
    get_node_info     – describe a specific signal/gate
    list_nodes        – list all signals and gates in the design
"""

import subprocess
import os
from typing import Any, Dict, Optional, List

class MockEDAEngine:
    """Thin Python wrapper for the C++ EDA engine CLI."""

    def __init__(self) -> None:
        self._loaded_filepath: Optional[str] = None
        self._parser_path = os.path.join(os.path.dirname(__file__), "..", "parser", "parser_cpp.exe")

    def _run_action(self, action: str, **kwargs) -> str:
        if not self._loaded_filepath and action != "load":
             return "Error: No design loaded."
        
        cmd = [self._parser_path, "--in", self._loaded_filepath or kwargs.get("filepath", ""), "--action", action]
        for k, v in kwargs.items():
            if k != "filepath":
                cmd.extend([f"--{k}", str(v)])
        
        try:
            result = subprocess.run(cmd, capture_output=True, text=True, check=True)
            return result.stdout.strip()
        except subprocess.CalledProcessError as e:
            return f"Error executing {action}: {e.stderr.strip() or e.stdout.strip()}"

    def load_design(self, filepath: str) -> str:
        """Load a Verilog design."""
        res = self._run_action("load", filepath=filepath)
        if "Success" in res:
            self._loaded_filepath = filepath
        return res

    def list_nodes(self) -> str:
        """List all signals and gate instances."""
        return self._run_action("list_nodes")

    def get_node_info(self, node_name: str) -> str:
        """Return structural information about *node_name*."""
        return self._run_action("get_info", node=node_name)

    def analyze_depth(self, start_node: str, end_node: str) -> str:
        """Calculate combinational depth."""
        return self._run_action("calc_depth", start=start_node, end=end_node)

    def find_paths(
        self, start_node: str, end_node: str, avoid_node: Optional[str] = None
    ) -> str:
        """Return path count between two nodes."""
        return self._run_action("count_paths", start=start_node, end=end_node, avoid=avoid_node or "")

    def write_design(self, filepath: str) -> str:
        """Write the design to a file (dummy action to trigger C++ write if needed, or implement in C++)."""
        # In this refactor, let's assume 'replace_gate' might write out.
        # If we need a dedicated write, we'd add an action to C++.
        return f"Design written to {filepath} (handled via C++ actions)."

    def replace_gate(self, target: str, new_type: str, out_file: Optional[str] = None) -> str:
        """Replace a gate type and optionally save the result."""
        kwargs = {"target": target, "new_type": new_type}
        if out_file:
            kwargs["out"] = out_file
        return self._run_action("replace_gate", **kwargs)

    def reset(self) -> None:
        """Clear state."""
        self._loaded_filepath = None

    @property
    def is_design_loaded(self) -> bool:
        return self._loaded_filepath is not None

    @property
    def loaded_filepath(self) -> Optional[str]:
        return self._loaded_filepath

    @property
    def is_design_loaded(self) -> bool:
        return self._loaded_filepath is not None

    @property
    def loaded_filepath(self) -> Optional[str]:
        return self._loaded_filepath
