"""Pre-parsed fixture data for known test netlists.

Instead of parsing Verilog for real (that belongs to the real engine),
MockEDAEngine looks up the base filename here and uses this data to
return accurate, netlist-specific tool responses.

Add one entry per sample netlist file you create under design/netlist/.
"""

import os
from typing import Any, Dict


# ── fixture schema ────────────────────────────────────────────────────────────
# Each entry has:
#   "module"   : top module name
#   "inputs"   : list of primary input ports
#   "outputs"  : list of primary output ports
#   "wires"    : list of internal wire names
#   "gates"    : list of {inst, type, output, inputs}
#   "depths"   : {(start, end): {"depth": int, "path": [str]}}
#   "paths"    : {(start, end): int}   # number of paths between the pair

FIXTURES: Dict[str, Dict[str, Any]] = {
    # ── test8.v ───────────────────────────────────────────────────────────────
    "test8.v": {
        "module": "test8",
        "inputs":  ["in0", "in1"],
        "outputs": ["out3", "out_side"],
        "wires":   ["n_in0_n", "n_aux0", "n1", "n_aux1", "n2", "n_aux2", "n3", "w_side"],
        "gates": [
            {"inst": "U1",  "type": "not", "output": "n_in0_n", "inputs": ["in0"]},
            {"inst": "U3",  "type": "and", "output": "n_aux0",  "inputs": ["in0", "in1"]},
            {"inst": "U5",  "type": "and", "output": "n1",      "inputs": ["n_in0_n", "n_aux0"]},
            {"inst": "U10", "type": "buf", "output": "n_aux1",  "inputs": ["in1"]},
            {"inst": "U12", "type": "xor", "output": "n2",      "inputs": ["n1", "n_aux1"]},
            {"inst": "U15", "type": "or",  "output": "n_aux2",  "inputs": ["in0", "in1"]},
            {"inst": "U18", "type": "nor", "output": "n3",      "inputs": ["n2", "n_aux2"]},
            {"inst": "U20", "type": "buf", "output": "out3",    "inputs": ["n3"]},
            {"inst": "U30", "type": "not", "output": "w_side",  "inputs": ["in1"]},
            {"inst": "U31", "type": "buf", "output": "out_side","inputs": ["w_side"]},
        ],
        # pre-computed critical paths
        "depths": {
            ("in0", "out3"): {
                "depth": 5,
                "path": [
                    "in0",
                    "  └─[NOT]  U1:  n_in0_n  = ~in0",
                    "      └─[AND]  U5:  n1     = n_in0_n & n_aux0",
                    "          └─[XOR]  U12: n2  = n1 ^ n_aux1",
                    "              └─[NOR]  U18: n3 = ~(n2 | n_aux2)",
                    "                  └─[BUF]  U20: out3 = n3",
                ],
            },
            ("in1", "out3"): {
                "depth": 4,
                "path": [
                    "in1",
                    "  └─[BUF]  U10: n_aux1  = in1",
                    "      └─[XOR]  U12: n2  = n1 ^ n_aux1",
                    "          └─[NOR]  U18: n3 = ~(n2 | n_aux2)",
                    "              └─[BUF]  U20: out3 = n3",
                ],
            },
            ("in1", "out_side"): {
                "depth": 2,
                "path": [
                    "in1",
                    "  └─[NOT]  U30: w_side  = ~in1",
                    "      └─[BUF]  U31: out_side = w_side",
                ],
            },
        },
        "paths": {
            ("in0", "out3"):    3,
            ("in1", "out3"):    2,
            ("in1", "out_side"): 1,
        },
    },
}


def lookup(filepath: str) -> Dict[str, Any]:
    """Return fixture data for *filepath*, or an empty dict if unknown."""
    basename = os.path.basename(filepath)
    return FIXTURES.get(basename, {})
