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

from typing import Any, Dict, Optional

from eda_engine.fixtures import lookup


class MockEDAEngine:
    """Stub EDA engine.  Known netlists return fixture-accurate data;
    unknown netlists return generic placeholder strings."""

    def __init__(self) -> None:
        self._loaded_filepath: Optional[str] = None
        self._fixture: Dict[str, Any] = {}   # populated on load_design

    # ----------------------------------------------------------------- public

    def load_design(self, filepath: str) -> str:
        """Simulate loading a gate-level Verilog design from *filepath*."""
        self._loaded_filepath = filepath
        self._fixture = lookup(filepath)

        if self._fixture:
            mod     = self._fixture["module"]
            inputs  = ", ".join(self._fixture["inputs"])
            outputs = ", ".join(self._fixture["outputs"])
            ngates  = len(self._fixture["gates"])
            return (
                f'Loaded gate-level Verilog from "{filepath}" successfully.\n'
                f"- Top module       : {mod}\n"
                f"- Primary inputs   : {inputs}\n"
                f"- Primary outputs  : {outputs}\n"
                f"- Gate instances   : {ngates}\n"
                f"- Supported primitives and DFF model recognized.\n"
                f"Design state has been updated."
            )

        # Generic fallback for files not in fixtures.py
        return (
            f'Loaded gate-level Verilog from "{filepath}" successfully.\n'
            f"- Detected a single top module (flat netlist).\n"
            f"- Supported primitives and DFF model recognized.\n"
            f"Design state has been updated."
        )

    def write_design(self, filepath: str) -> str:
        """Simulate writing the current design to *filepath*."""
        if self._loaded_filepath is None:
            return (
                f'Warning: No design currently loaded. '
                f'Wrote an empty netlist placeholder to "{filepath}".'
            )
        return f'Wrote the modified netlist to "{filepath}" successfully.'

    def analyze_depth(self, start_node: str, end_node: str) -> str:
        """Return the maximum logic depth from *start_node* to *end_node*.

        Uses fixture data when available; falls back to a generic 5-level mock.
        """
        key = (start_node, end_node)
        depths = self._fixture.get("depths", {})

        if key in depths:
            info  = depths[key]
            depth = info["depth"]
            path  = "\n".join(info["path"])
            return (
                f"The maximum logic depth from {start_node} to {end_node} "
                f"is {depth}.\n"
                f"One example of a longest combinational path "
                f"({depth} gate levels):\n"
                f"{path}"
            )

        # Generic fallback
        return (
            f"The maximum logic depth from {start_node} to {end_node} is 5.\n"
            f"One example of a longest combinational path (5 gate levels):\n"
            f"{start_node}\n"
            f"  └─[NOT]  U1:  n_in0_n  = ~{start_node}\n"
            f"      └─[AND]  U5:  n1     = n_in0_n & n_aux0\n"
            f"          └─[XOR]  U12: n2  = n1 ^ n_aux1\n"
            f"              └─[NOR]  U18: n3 = ~(n2 | n_aux2)\n"
            f"                  └─[BUF]  U20: {end_node} = n3"
        )

    def find_paths(
        self, start_node: str, end_node: str, avoid_node: Optional[str] = None
    ) -> str:
        """Return path count between two nodes (fixture-accurate when known)."""
        key = (start_node, end_node)
        path_counts = self._fixture.get("paths", {})

        n = path_counts.get(key)
        if n is not None:
            if avoid_node:
                return (
                    f"Found {max(1, n - 1)} path(s) from {start_node} to "
                    f"{end_node} that do not pass through {avoid_node}."
                )
            return f"Found {n} path(s) from {start_node} to {end_node}."

        # Generic fallback
        if avoid_node:
            return (
                f"Found 1 path from {start_node} to {end_node} "
                f"that does not pass through {avoid_node}."
            )
        return f"Found 3 paths from {start_node} to {end_node}."

    def get_node_info(self, node_name: str) -> str:
        """Return structural information about *node_name*."""
        gates = self._fixture.get("gates", [])

        # Check if it's a gate output
        for g in gates:
            if g["output"] == node_name:
                fanout = sum(
                    1 for other in gates if node_name in other["inputs"]
                )
                return (
                    f"Node '{node_name}': output of {g['type'].upper()} gate "
                    f"{g['inst']}, driven by inputs {g['inputs']}, "
                    f"fanout={fanout}."
                )

        # Check ports
        inputs  = self._fixture.get("inputs",  [])
        outputs = self._fixture.get("outputs", [])
        if node_name in inputs:
            fanout = sum(1 for g in gates if node_name in g["inputs"])
            return f"Node '{node_name}': primary input, fanout={fanout}."
        if node_name in outputs:
            return f"Node '{node_name}': primary output."

        # Generic fallback
        return (
            f"Node '{node_name}': wire signal, fanin=1, fanout=2, "
            f"driven by gate U_mock."
        )

    def list_nodes(self) -> str:
        """List all signals and gate instances in the loaded design."""
        if self._loaded_filepath is None:
            return "No design loaded — node list is empty."

        if self._fixture:
            ports   = self._fixture["inputs"] + self._fixture["outputs"]
            wires   = self._fixture["wires"]
            insts   = [g["inst"] for g in self._fixture["gates"]]
            return (
                f"Nodes in current design ({self._fixture['module']}):\n"
                f"  Ports  : {', '.join(ports)}\n"
                f"  Wires  : {', '.join(wires)}\n"
                f"  Gates  : {', '.join(insts)}"
            )

        return (
            "Nodes in current design: "
            "[in0, in1, out0, out1, n1, n2, n3, U1, U2, U3, clk, rst_n]"
        )

    def reset(self) -> None:
        """Clear all design state (called at the start of each testcase)."""
        self._loaded_filepath = None
        self._fixture = {}

    # ---------------------------------------------------------------- property

    @property
    def is_design_loaded(self) -> bool:
        return self._loaded_filepath is not None

    @property
    def loaded_filepath(self) -> Optional[str]:
        return self._loaded_filepath
