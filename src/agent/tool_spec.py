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
            "name": "find_paths",
            "description": (
                "Enumerate paths from start_node to end_node in the netlist, "
                "optionally avoiding a specific intermediate node."
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
            "name": "count_gates_in_cone",
            "description": (
                "Count gates by type within the fanin or fanout cone of a specified node. "
                "Returns per-type breakdown (AND, OR, NOT, NAND, NOR, XOR, XNOR, BUF, DFF) "
                "and total count."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node_name": {
                        "type": "string",
                        "description": "The cone root node (signal or gate name).",
                    },
                    "direction": {
                        "type": "string",
                        "enum": ["fanin", "fanout"],
                        "description": "Whether to traverse the fanin or fanout cone (default: fanin).",
                    },
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
            "name": "insert_dedicated_buffers",
            "description": (
                "Insert a dedicated BUF gate for every load of a given signal, so each "
                "load is driven through its own buffer. Functionality is preserved. Call "
                "this for 'insert a BUF gate on signal n2 so that each load of n2 is "
                "driven through a dedicated buffer'. (Different from insert_buffers, "
                "which limits maximum fanout with a buffer tree.)"
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "signal": {"type": "string", "description": "Signal whose loads get dedicated buffers (e.g. 'n2')."},
                },
                "required": ["signal"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "buffer_signal",
            "description": (
                "Insert a balanced buffer tree on ONE named signal (a wire, or a "
                "primary input such as a clock or reset) so no single driver of it "
                "exceeds a maximum fanout. Functionality is preserved. Call this for "
                "'insert buffers on the reset signal n1 to reduce its fanout to at most "
                "4 loads per driver'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "signal": {"type": "string", "description": "Signal to buffer (e.g. 'n1')."},
                    "max_fanout": {"type": "integer", "description": "Max loads per driver (e.g. 4)."},
                },
                "required": ["signal", "max_fanout"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconnect_pin",
            "description": (
                "Reconnect one input pin of a gate to a different signal, applied only "
                "if it preserves functionality (verified by equivalence check; reverted "
                "otherwise). Call this for 'try to reconnect input pin A of gate g0 to "
                "internal signal n24[0], ensure functionality does not change'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gate": {"type": "string", "description": "Gate instance name (e.g. 'g0')."},
                    "pin": {"type": "string", "description": "Input pin, a letter (A=first input, B=second) or index."},
                    "signal": {"type": "string", "description": "Signal to connect the pin to (e.g. 'n24[0]')."},
                },
                "required": ["gate", "pin", "signal"],
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
                "functionality. Replaces e.g. 2-input OR gates with "
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
            "name": "collapse_inverters",
            "description": (
                "Find all back-to-back inverter pairs (a NOT gate feeding another NOT "
                "gate) and collapse them into a direct wire, since NOT(NOT(x)) = x. "
                "Functionality is preserved. Call this for 'find all back-to-back "
                "inverter pairs and collapse them into a wire'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "decompose_all_gates",
            "description": (
                "Replace EVERY gate of a given type in the whole design with equivalent "
                "logic from a target basis, preserving functionality. Supports "
                "XNOR->NOR-only, XOR->NAND (4-NAND per XOR), XOR->AND/OR/NOT, "
                "OR->NAND+NOT. Call this for 'replace all XNOR gates with NOR-only "
                "implementations' or 'convert every XOR gate to an equivalent 4-NAND "
                "circuit'. For one node's cone, use decompose_gates_in_cone instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "gate_type": {"type": "string", "description": "Gate type to replace, e.g. 'XNOR' or 'XOR'."},
                    "target_basis": {"type": "string", "description": "Target basis, e.g. 'NOR-only', 'NAND' (4-NAND), 'AND/OR/NOT'."},
                },
                "required": ["gate_type", "target_basis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "merge_equivalent_gates",
            "description": (
                "Find and merge all gate pairs that compute the same function "
                "(structural duplicates: same gate type and same inputs), keeping one "
                "and rewiring the rest. Functionality is preserved; flip-flops are not "
                "merged. Call this for 'find and merge all gate pairs that are "
                "functionally equivalent' or 'merge structural duplicate gates'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "convert_cone_to_basis",
            "description": (
                "Convert every gate in the fanin cone of a node to use only a target "
                "gate basis (e.g. NOR and NOT), preserving functionality. Call this for "
                "'convert the logic cone of n10 to use only NOR and NOT gates'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "cone_root": {"type": "string", "description": "Node whose cone is converted (e.g. 'n10')."},
                    "target_basis": {"type": "string", "description": "Allowed basis, e.g. 'NOR_NOT'."},
                },
                "required": ["cone_root", "target_basis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "reconstruct_netlist_to_basis",
            "description": (
                "Reconstruct the ENTIRE netlist using only a target gate basis "
                "(AND+NOT, NOR+NOT, or NAND+NOT), preserving functionality. Call this for "
                "'reconstruct the entire netlist using only AND and NOT gates'. For a "
                "single node's cone, use convert_cone_to_basis instead."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "target_basis": {"type": "string", "description": "Basis, e.g. 'AND_NOT', 'NOR_NOT', or 'NAND_NOT'."},
                },
                "required": ["target_basis"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "restructure_to_depth",
            "description": (
                "Best-effort attempt to restructure a node's logic cone to a target "
                "depth, reporting the current depth and whether it already meets the "
                "target. Call this for 'try to restructure n10 with a target depth of 4, "
                "report original if already optimal'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "node": {"type": "string", "description": "Node whose cone depth is targeted (e.g. 'n10')."},
                    "target_depth": {"type": "integer", "description": "Target maximum logic depth (e.g. 4)."},
                },
                "required": ["node", "target_depth"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "optimize_outputs_to_depth",
            "description": (
                "Report which primary outputs still have logic depth greater than a "
                "limit after depth optimization (best effort). Call this for 'for each "
                "output with depth greater than 4, optimize its cone to meet the depth "
                "constraint'."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "max_depth": {"type": "integer", "description": "Maximum allowed logic depth (e.g. 4)."},
                },
                "required": ["max_depth"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "const_propagate",
            "description": (
                "Detect and simplify gates with constant inputs. Use mode='report' to "
                "list without modifying, mode='propagate' to apply simplification. Can "
                "filter by gate_type and const_value. Handles cascading: if simplification "
                "creates new constant signals, they are propagated iteratively."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "mode": {
                        "type": "string",
                        "enum": ["report", "propagate"],
                        "description": "report: scan only, no modification; propagate: apply simplification (default).",
                    },
                    "gate_type": {
                        "type": "string",
                        "description": "Optional gate type filter, e.g. 'NAND'. Only process gates of this type.",
                    },
                    "const_value": {
                        "type": "string",
                        "enum": ["0", "1"],
                        "description": "Optional: only process gates whose constant input has this value (0 or 1).",
                    },
                },
                "required": [],
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
    {
        "type": "function",
        "function": {
            "name": "list_pio",
            "description": (
                "List all primary inputs (PI) and primary outputs (PO) in the "
                "current design, with their bit widths. Also groups bus signals "
                "(e.g. data[0]..data[7]) into vectors. Returns JSON with "
                "pi_count, po_count, primary_inputs, primary_outputs, "
                "pi_vectors, and po_vectors. Call this for 'how many primary "
                "inputs/outputs', 'list all PIs with bit widths', 'determine "
                "the number of primary inputs and outputs'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "r2r_paths",
            "description": (
                "List all register-to-register paths through combinational logic. "
                "Finds paths from DFF Q outputs to DFF D inputs, traversing only "
                "combinational gates. Use for timing path analysis and sequential "
                "design understanding."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "deepest_cone_output",
            "description": (
                "Find which primary output has the deepest (largest) fanin "
                "logic cone in terms of combinational gate levels. Returns "
                "JSON with the deepest output name, its depth, and all output "
                "depths sorted descending. Call this for 'which output bit has "
                "the deepest fanin logic cone', 'which output has the largest "
                "fanin cone', or 'what is the maximum combinational depth'."
            ),
            "parameters": {"type": "object", "properties": {}, "required": []},
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
