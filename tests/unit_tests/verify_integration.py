import sys
import os
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(PROJECT_ROOT / "src"))
os.chdir(PROJECT_ROOT)

from eda_engine.engine import EDAEngine

def test_integration():
    engine = EDAEngine()
    
    print("--- Loading design ---")
    res = engine.load_design("design/netlist/test_complex.v")
    print(res)
    
    print("\n--- Listing nodes ---")
    res = engine.list_nodes()
    print(res)
    
    print("\n--- Node info for u_dff ---")
    res = engine.get_node_info("u_dff")
    print(res)
    
    print("\n--- Depth analysis from in[0] to out[1] ---")
    res = engine.analyze_depth("in[0]", "out[1]")
    print(res)

    print("\n--- Replacing gate u_and with nand ---")
    res = engine.replace_gate("u_and", "nand", out_file="design/netlist/test_complex_mod.v")
    print(res)
    if os.path.exists("design/netlist/test_complex_mod.v"):
        print("Modified Verilog written successfully.")

if __name__ == "__main__":
    test_integration()
