import sys
import os

# Add project root to path
sys.path.append(os.getcwd())

from eda_engine.mock_engine import MockEDAEngine

def test_integration():
    engine = MockEDAEngine()
    
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
