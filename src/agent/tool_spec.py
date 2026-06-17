"""Tool definitions exposed to the LLM.

EDA_TOOLS is the canonical list in OpenAI function-calling format.
Use to_anthropic_tools() to get the equivalent Anthropic format.

Add new tools here as the real EDA engine grows; the planner's dispatch
table in planner.py must be updated in parallel.
"""

from typing import Any, Dict, List


# ── canonical tool list (OpenAI format) ──────────────────────────────────────

EDA_TOOLS: List[Dict[str, Any]] = [
    {
        "type": "function",
        "function": {
            "name": "load_design",
            "description": (
                "Load a gate-level Verilog netlist from a file into the EDA engine. "
                "Call this whenever the user asks to read, load, or import a design."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Path to the Verilog (.v) source file.",
                    }
                },
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "write_design",
            "description": (
                "Write the current in-memory netlist to a gate-level Verilog file. "
                "Call this when the user asks to output, save, or write a design."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "filepath": {
                        "type": "string",
                        "description": "Destination path for the output Verilog (.v) file.",
                    }
                },
                "required": ["filepath"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_critical_path",
            "description": (
                "Identify the critical path (the longest combinational path in terms of "
                "gate levels) between a specific start_node and end_node. Returns the "
                "maximum gate-level depth and the specific sequence of nodes along the path."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node": {
                        "type": "string",
                        "description": "Source signal name or primary input.",
                    },
                    "end_node": {
                        "type": "string",
                        "description": "Sink signal name or primary output.",
                    },
                },
                "required": ["start_node", "end_node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "analyze_depth",
            "description": (
                "Compute the maximum combinational logic depth (critical-path length in "
                "gate levels) to end_node. Use this for general depth queries where the "
                "full path of nodes is not required."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node": {
                        "type": "string",
                        "description": "Optional source signal name or primary input.",
                    },
                    "end_node": {
                        "type": "string",
                        "description": "Sink signal name or primary output.",
                    },
                },
                "required": ["end_node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_path_exists",
            "description": (
                "Determine if ANY combinational path exists from start_node to end_node, "
                "optionally avoiding a specific intermediate node. Returns 'yes' or 'no' "
                "immediately upon finding the first path. Use this for yes/no questions "
                "like 'Determine whether a combinational path from X to Y exists'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node": {
                        "type": "string",
                        "description": "Source signal name or primary input.",
                    },
                    "end_node": {
                        "type": "string",
                        "description": "Sink signal name or primary output.",
                    },
                    "avoid_node": {
                        "type": "string",
                        "description": "Optional node that no returned path may pass through.",
                    },
                },
                "required": ["start_node", "end_node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "find_paths",
            "description": (
                "Enumerate all paths from start_node to end_node in the netlist, "
                "optionally avoiding a specific intermediate node. Use this only when "
                "the user asks to 'List every path' or 'Provide a complete enumeration'. "
                "Do NOT use this for yes/no existence checks; use check_path_exists instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "start_node": {
                        "type": "string",
                        "description": "Source signal name or primary input.",
                    },
                    "end_node": {
                        "type": "string",
                        "description": "Sink signal name or primary output.",
                    },
                    "avoid_node": {
                        "type": "string",
                        "description": "Optional node that no returned path may pass through.",
                    },
                },
                "required": ["start_node", "end_node"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_fanin_gates",
            "description": (
                "Count the total number of gate instances in the transitive fanin cone "
                "(all gates that drive this node, directly or indirectly)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The target signal or gate name.",
                    }
                },
                "required": ["node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_fanout_gates",
            "description": (
                "Count the total number of gate instances in the transitive fanout cone "
                "(all gates driven by this node, directly or indirectly)."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The target signal or gate name.",
                    }
                },
                "required": ["node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fanin_cone",
            "description": (
                "Retrieve the complete list of nodes (signals and gates) in the "
                "transitive fanin cone of a specific node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The target signal or gate name.",
                    }
                },
                "required": ["node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fanout_cone",
            "description": (
                "Retrieve the complete list of nodes (signals and gates) in the "
                "transitive fanout cone of a specific node."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The target signal or gate name.",
                    }
                },
                "required": ["node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_fanin_depth",
            "description": (
                "Compute the maximum combinational logic depth within the "
                "transitive fanin cone of a specific primary output or signal."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The target signal or gate name.",
                    }
                },
                "required": ["node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_node_info",
            "description": (
                "Retrieve structural information (type, fanin, fanout, driver) "
                "about a specific signal, wire, or gate instance."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The signal or gate instance name to inspect.",
                    }
                },
                "required": ["node_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_nodes",
            "description": (
                "List all signal and gate nodes present in the currently loaded design."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "count_gates",
            "description": (
                "Count the number of gates in the design, broken down by type."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "insert_buffers",
            "description": (
                "Insert buffer (BUF) gates so that no gate drives more than a given number "
                "of loads (fanout limit), building a balanced buffer tree where needed. "
                "Functionally equivalent to the original. Call this for requests like "
                "'insert buffers so no gate drives more than 4 loads' or 'fanout optimization "
                "with maximum fanout 4'. The transformed netlist becomes the current design."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_fanout": {
                        "type": "integer",
                        "description": "Max loads any single gate may drive (e.g. 4).",
                    }
                },
                "required": ["max_fanout"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reduce_depth",
            "description": (
                "Reduce the critical-path / maximum logic depth of the design by "
                "restructuring the combinational logic with Berkeley ABC "
                "(balance/resyn2), preserving functionality. Call this for requests "
                "like 'reduce the critical path depth through restructuring', "
                "'minimize maximum path depth', or 'optimize the logic depth'. The "
                "restructured netlist becomes the current design; verify with "
                "check_equivalence afterwards."
            ),
            "parameters": {
                "type": "object",
                "properties": {},
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "remove_dangling",
            "description": (
                "Remove unused/dangling logic from the netlist: any gate or wire that "
                "does not contribute to a primary output or a flip-flop is deleted. "
                "Functionality is preserved. Call this for requests like 'trim unused "
                "wires and gates', 'remove dangling gates', 'sweep out dangling gates', "
                "'prune the netlist', or 'remove floating nodes'. The trimmed netlist "
                "becomes the current design."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "rename_node",
            "description": (
                "Rename a gate instance, wire, or signal and update all references. "
                "Functionality is preserved (pure naming change). Call this for "
                "requests like 'rename gate g0 to renamed_gate', 'change the identifier "
                "of wire n74 to renamed_wire', or 'update the name of signal n7431'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "old_name": {"type": "string", "description": "Current node name."},
                    "new_name": {"type": "string", "description": "New name to assign."},
                },
                "required": ["old_name", "new_name"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decompose_gates_in_cone",
            "description": (
                "Replace all gates of a given type within the fanin cone of a node "
                "with equivalent logic built only from a target gate basis, preserving "
                "functionality. Currently supports replacing 2-input OR gates with "
                "NAND and NOT gates. Call this for requests like 'replace all 2-input "
                "OR gates in the cone of n11[0] with equivalent logic built only from "
                "NAND and NOT gates'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cone_root": {
                        "type": "string",
                        "description": "Node whose fanin cone is processed (e.g. 'n11[0]').",
                    },
                    "gate_type": {
                        "type": "string",
                        "description": "Gate type to replace, e.g. 'OR'.",
                    },
                    "target_basis": {
                        "type": "string",
                        "description": "Allowed basis for the replacement, e.g. 'NAND_NOT'.",
                    },
                },
                "required": ["cone_root", "gate_type", "target_basis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "check_equivalence",
            "description": (
                "Formally verify that the current (possibly transformed) design is "
                "functionally equivalent to a reference netlist using Berkeley ABC. "
                "By default the reference is the original as-loaded netlist. Call this "
                "after any functionality-preserving transformation (buffer insertion, "
                "optimization, remapping, etc.) to confirm nothing changed functionally. "
                "Returns EQUIVALENT or NOT EQUIVALENT."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "reference": {
                        "type": "string",
                        "description": (
                            "Optional path to a reference Verilog netlist to compare "
                            "against. Omit to compare against the original loaded design."
                        ),
                    }
                },
                "required": [],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "replace_gate",
            "description": (
                "Replace the type of a specific gate instance in the netlist. "
                "Optionally save the modified design to a new file."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target": {
                        "type": "string",
                        "description": "The name of the gate instance to replace.",
                    },
                    "new_type": {
                        "type": "string",
                        "description": "The new gate type (e.g., 'nand', 'nor', 'and').",
                    },
                    "out_file": {
                        "type": "string",
                        "description": "Optional path to save the modified Verilog netlist.",
                    },
                },
                "required": ["target", "new_type"],
            },
        },
    },
]


# ── format conversion ─────────────────────────────────────────────────────────

def to_anthropic_tools(openai_tools: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Convert an OpenAI-format tool list to Anthropic's tool schema format.

    OpenAI uses  {"type": "function", "function": {"name": …, "parameters": …}}
    Anthropic uses  {"name": …, "description": …, "input_schema": …}
    """
    result = []
    for tool in openai_tools:
        fn = tool["function"]
        result.append(
            {
                "name": fn["name"],
                "description": fn.get("description", ""),
                "input_schema": fn.get("parameters", {"type": "object", "properties": {}}),
            }
        )
    return result
