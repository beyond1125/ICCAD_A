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
            "name": "analyze_depth",
            "description": (
                "Compute the maximum combinational logic depth (critical-path length in "
                "gate levels) to end_node. If start_node is provided, compute depth "
                "from start_node to end_node. If omitted, compute the maximum depth "
                "from any primary input to end_node."
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
                "Count the number of gate instances in the transitive fanin cone "
                "of a specific node (signal or gate)."
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
                        "description": "Maximum number of loads any single gate may drive (e.g. 4).",
                    }
                },
                "required": ["max_fanout"],
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
