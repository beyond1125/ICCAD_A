#include "graph.hpp"
#include "verilog_parser.hpp"
#include "verilog_writer.hpp"
#include "types.hpp"
#include <iostream>
#include <string>
#include <unordered_map>

int main(int argc, char** argv) {
    std::unordered_map<std::string, std::string> args;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]).substr(0, 2) == "--") {
            if (i + 1 < argc) args[argv[i]] = argv[i+1];
        }
    }
    if (args.find("--in") == args.end()) {
        log_error("Usage: " + std::string(argv[0]) + " --in <file.v> --action <action> [options]");
        return 1;
    }
    Graph g;
    VerilogParser parser;
    parser.parse(args["--in"], g);
    std::string action = args["--action"];
    if (action == "load") {
        int pi = 0, po = 0, gates = 0;
        for (auto n : g.all_nodes) {
            if (n->type == NodeType::PRIMARY_INPUT) pi++;
            else if (n->type == NodeType::PRIMARY_OUTPUT) po++;
            else if (n->type == NodeType::GATE) gates++;
        }
        std::cout << "Success. PI: " << pi << ", PO: " << po << ", Gates: " << gates << std::endl;
    } else if (action == "calc_depth") {
        int d = g.calculate_depth(args["--start"], args["--end"]);
        std::cout << "Depth: " << d << std::endl;
    } else if (action == "get_critical_path") {
        std::cout << g.get_critical_path(args["--start"], args["--end"]) << std::endl;
    } else if (action == "count_paths") {
        int c = g.count_paths(args["--start"], args["--end"], args["--avoid"]);
        std::cout << "Paths: " << c << std::endl;
    } else if (action == "list_paths") {
        std::cout << g.find_all_paths(args["--start"], args["--end"], args["--avoid"]) << std::endl;
    } else if (action == "count_fanin") {
        int c = g.count_fanin_gates(args["--node"]);
        std::cout << "Fanin Gates: " << c << std::endl;
    } else if (action == "count_fanout") {
        int c = g.count_fanout_gates(args["--node"]);
        std::cout << "Fanout Gates: " << c << std::endl;
    } else if (action == "get_fanin_cone") {
        std::cout << g.get_fanin_cone(args["--node"]) << std::endl;
    } else if (action == "get_fanout_cone") {
        std::cout << g.get_fanout_cone(args["--node"]) << std::endl;
    } else if (action == "get_fanin_depth") {
        std::cout << "Fanin Depth: " << g.get_fanin_depth(args["--node"]) << std::endl;
    } else if (action == "get_info") {
        std::cout << g.get_node_info(args["--node"]) << std::endl;
    } else if (action == "list_nodes") {
        for (auto n : g.all_nodes) std::cout << n->name << " (" << (n->type == NodeType::GATE ? "GATE" : "SIGNAL") << ")" << std::endl;
    } else if (action == "replace_gate") {
        if (g.replace_gate(args["--target"], args["--new_type"])) {
            if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            log_error("Failure: Could not replace gate " + (args.count("--target") ? args["--target"] : "unknown"));
            std::cout << "Failure" << std::endl;
        }
    } else if (action == "insert_buffers") {
        int mf = args.count("--max_fanout") ? std::stoi(args["--max_fanout"]) : 4;
        int added = g.insert_buffers(mf);
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Inserted " << added << " buffer(s) so no gate drives more than "
                  << mf << " loads." << std::endl;
    } else if (action == "rename") {
        bool ok = g.rename_node(args["--old"], args["--new"]);
        if (ok && args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        if (ok) std::cout << "Renamed " << args["--old"] << " to " << args["--new"] << "." << std::endl;
        else std::cout << "Failure: node '" << args["--old"]
                       << "' not found or new name already in use." << std::endl;
    } else if (action == "decompose") {
        int n = g.decompose_in_cone(args["--root"], args["--gate"], args["--basis"]);
        if (n < 0) {
            std::cout << "Failure: unsupported decomposition (gate '" << args["--gate"]
                      << "' to basis '" << args["--basis"] << "')." << std::endl;
        } else {
            if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
            std::cout << "Replaced " << n << " " << args["--gate"] << " gate(s) in the cone of "
                      << args["--root"] << " with " << args["--basis"] << " logic." << std::endl;
        }
    } else if (action == "sweep") {
        int removed = g.sweep_dangling();
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Removed " << removed << " dangling gate(s) not contributing to any output."
                  << std::endl;
    } else if (action == "outputs_over_depth") {
        int mx = args.count("--max") ? std::stoi(args["--max"]) : 4;
        std::cout << g.outputs_over_depth(mx) << std::endl;
    } else if (action == "collapse_inv") {
        int n = g.collapse_inverters();
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Collapsed " << n << " redundant inverter(s) from back-to-back pairs."
                  << std::endl;
    } else if (action == "remap_all") {
        int n = g.remap_cone_to_basis("", args["--basis"]);
        if (n < 0) {
            std::cout << "Failure: unsupported basis '" << args["--basis"] << "'." << std::endl;
        } else {
            if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
            std::cout << "Reconstructed the netlist: converted " << n << " gate(s) to "
                      << args["--basis"] << " logic." << std::endl;
        }
    } else if (action == "remap_cone") {
        int n = g.remap_cone_to_basis(args["--root"], args["--basis"]);
        if (n < 0) {
            std::cout << "Failure: unsupported basis '" << args["--basis"] << "'." << std::endl;
        } else {
            if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
            std::cout << "Converted " << n << " gate(s) in the cone of " << args["--root"]
                      << " to " << args["--basis"] << " logic." << std::endl;
        }
    } else if (action == "write_blif") {
        if (args.count("--out")) {
            g.write_blif(args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            log_error("Error: --out required for write_blif action");
        }
    } else if (action == "rebuild") {
        // Reconstruct a full sequential netlist: combinational logic comes from an
        // ABC-optimized flop-cut BLIF (--blif); flip-flops (with their CK/RN/SN
        // pins) are reattached from the original netlist parsed into g (--in).
        if (!args.count("--blif") || !args.count("--out")) {
            log_error("Error: rebuild requires --blif and --out");
            return 1;
        }
        Graph R;
        R.module_name = g.module_name;
        // Carry over primary input/output declarations (types and bit names).
        for (Node* n : g.all_nodes) {
            if (n->type == NodeType::PRIMARY_INPUT) R.get_or_create_node(n->name, NodeType::PRIMARY_INPUT);
            else if (n->type == NodeType::PRIMARY_OUTPUT) R.get_or_create_node(n->name, NodeType::PRIMARY_OUTPUT);
        }
        R.load_logic_blif(args["--blif"]);
        // Reattach each DFF: Q drives its original net, D is fed by the BLIF's
        // __D_<inst> net, and CK/RN/SN are preserved verbatim via the original
        // pin_conns. The feeder net is renamed to a neutral name first, so it can
        // never collide with the __D_<inst> tap that write_blif emits later (the
        // feeder is a real net that may fan out and get buffered).
        for (Node* n : g.all_nodes) {
            if (n->type == NodeType::GATE && n->gate_type == GateType::DFF) {
                Node* d = R.get_or_create_node(n->name, NodeType::GATE);
                d->gate_type = GateType::DFF;
                d->pin_conns = n->pin_conns;
                if (!n->outputs.empty()) R.add_edge(d, R.get_or_create_node(n->outputs[0]->name));
                std::string tap = "__D_" + n->name;
                std::string feeder = n->name + "__din";
                if (R.nodes.count(tap)) {            // rename __D_<inst> -> <inst>__din
                    Node* fn = R.nodes[tap];
                    R.nodes.erase(tap);
                    fn->name = feeder;
                    R.nodes[feeder] = fn;
                }
                R.add_edge(R.get_or_create_node(feeder), d);
            }
        }
        VerilogWriter::write_verilog(R, args["--out"]);
        std::cout << "Success" << std::endl;
    } else if (action == "write") {
        if (args.count("--out")) {
            VerilogWriter::write_verilog(g, args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            log_error("Error: --out required for write action");
        }
    } else if (action == "count_gates") {
        std::unordered_map<GateType, int> counts;
        for (auto n : g.all_nodes) {
            if (n->type == NodeType::GATE) counts[n->gate_type]++;
        }
        std::cout << "Gate counts:\n";
        std::vector<GateType> types = {GateType::NOT, GateType::AND, GateType::OR, GateType::XOR, GateType::NOR, GateType::NAND, GateType::XNOR, GateType::BUF, GateType::DFF};
        for (auto t : types) {
            std::cout << gate_type_to_string(t) << ": " << counts[t] << "\n";
        }
    } else {
        log_error("Unknown action: " + action);
        return 1;
    }
    return 0;
}
