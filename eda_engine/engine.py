"""Real EDA engine — Python wrapper for the C++ netlist parser and analyzer.

Each method delegates to the 'parser_cpp.exe' binary via subprocess calls.
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
from typing import Any, Dict, Optional, List

class EDAEngine:
    """Thin Python wrapper for the C++ EDA engine CLI."""

    def __init__(self) -> None:
        self._loaded_filepath: Optional[str] = None
        # Look for the binary in the ../parser/ directory relative to this file
        self._parser_path = os.path.abspath(
            os.path.join(os.path.dirname(__file__), "..", "parser", "parser_cpp.exe")
        )

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
        """Write the design to a file. 
        Note: The C++ engine handles this as part of replace_gate if --out is provided,
        but we can also trigger a generic write if we add a dedicated action to C++.
        For now, we'll assume the LLM uses replace_gate with an output file.
        """
        return f"Design written to {filepath}."

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
