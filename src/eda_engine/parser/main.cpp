#include "graph.hpp"
#include "verilog_parser.hpp"
#include "verilog_writer.hpp"
#include "types.hpp"
#include <iostream>
#include <string>
#include <unordered_map>
#include <queue>
#include <cstdlib>

// Parse an integer CLI flag; a malformed value exits cleanly instead of
// crashing with an uncaught std::invalid_argument from std::stoi.
static int int_flag(std::unordered_map<std::string, std::string>& args,
                    const std::string& key, int dflt) {
    if (!args.count(key)) return dflt;
    try {
        return std::stoi(args[key]);
    } catch (const std::exception&) {
        log_error("Error: invalid integer value for " + key + ": '" + args[key] + "'");
        std::exit(1);
    }
}

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
        long long c = g.count_paths(args["--start"], args["--end"], args["--avoid"]);
        std::cout << "Paths: " << c << std::endl;
    } else if (action == "list_paths") {
        std::cout << g.find_all_paths(args["--start"], args["--end"], args["--avoid"], args["--paths_out"]) << std::endl;
    } else if (action == "write_cone_blifs") {
        std::cout << g.write_cone_blifs(args["--nets"], args["--out_dir"], args["--tie0"]) << std::endl;
    } else if (action == "write_seq_blif") {
        if (!args.count("--out")) {
            log_error("Error: --out required for write_seq_blif");
            return 1;
        }
        std::cout << g.write_seq_blif(args["--out"], args["--expose"],
                                      args["--expose_only"] == "1") << std::endl;
    } else if (action == "sim_consts") {
        std::cout << g.sim_consts(args["--nets"], int_flag(args, "--cycles", 64),
                                  int_flag(args, "--trials", 16),
                                  (unsigned)int_flag(args, "--seed", 1)) << std::endl;
    } else if (action == "tie_nets_const") {
        std::string r = g.tie_nets_const(args["--assign"]);
        if (r.rfind("Success", 0) == 0 && args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << r << std::endl;
    } else if (action == "list_dffs") {
        std::cout << g.list_dffs(args["--scope_net"]) << std::endl;
    } else if (action == "report_stuck_inputs") {
        std::cout << g.report_stuck_inputs(args["--gate_type"], int_flag(args, "--cycles", 64),
                                           int_flag(args, "--trials", 16),
                                           (unsigned)int_flag(args, "--seed", 1)) << std::endl;
    } else if (action == "count_fanin") {
        // Analysis cones are combinational by default (Q&A A21.2): DFF Q = PI,
        // the boundary DFF counts but is not traversed. --stop_at_dff 0 gives
        // the legacy through-DFF transitive cone (debug/parity only).
        bool stop = int_flag(args, "--stop_at_dff", 1) != 0;
        int c = g.count_fanin_gates(args["--node"], stop);
        std::cout << (stop ? "Fanin Gates (combinational cone, DFF Q = PI): "
                           : "Fanin Gates (through DFFs): ") << c << std::endl;
    } else if (action == "count_fanout") {
        bool stop = int_flag(args, "--stop_at_dff", 1) != 0;
        int c = g.count_fanout_gates(args["--node"], stop);
        std::cout << (stop ? "Fanout Gates (combinational cone, stops at DFFs): "
                           : "Fanout Gates (through DFFs): ") << c << std::endl;
    } else if (action == "get_fanin_cone") {
        std::cout << g.get_fanin_cone(args["--node"], int_flag(args, "--stop_at_dff", 1) != 0) << std::endl;
    } else if (action == "get_fanout_cone") {
        std::cout << g.get_fanout_cone(args["--node"], int_flag(args, "--stop_at_dff", 1) != 0) << std::endl;
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
        int mf = int_flag(args, "--max_fanout", 4);
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
            std::cout << "Replaced " << n << " " << args["--gate"] << " gate(s) "
                      << (args["--root"].empty() ? "in the design"
                                                 : "in the cone of " + args["--root"])
                      << " with " << args["--basis"] << " logic." << std::endl;
        }
    } else if (action == "sweep") {
        int removed = g.sweep_dangling();
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Removed " << removed << " dangling gate(s) not contributing to any output."
                  << std::endl;
    } else if (action == "outputs_over_depth") {
        int mx = int_flag(args, "--max", 4);
        std::cout << g.outputs_over_depth(mx) << std::endl;
    } else if (action == "buffer_signal") {
        int mf = int_flag(args, "--max_fanout", 4);
        int n = g.insert_buffers_on_signal(args["--signal"], mf);
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Inserted " << n << " buffer(s) on signal " << args["--signal"]
                  << " so no driver exceeds " << mf << " loads." << std::endl;
    } else if (action == "reconnect_pin") {
        bool ok = g.reconnect_pin(args["--gate"], args["--pin"], args["--signal"]);
        if (ok && args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << (ok ? "Reconnected pin " + args["--pin"] + " of " + args["--gate"] +
                           " to " + args["--signal"] + "."
                         : "Failure: gate or pin not found.") << std::endl;
    } else if (action == "dedicated_buffers") {
        int n = g.insert_dedicated_buffers(args["--signal"]);
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Added " << n << " dedicated buffer(s) on signal " << args["--signal"]
                  << " (one per load)." << std::endl;
    } else if (action == "list_gates_by_type") {
        std::cout << g.list_gates_by_type(args["--gate"]) << std::endl;
    } else if (action == "flipflops_by_clock") {
        std::cout << g.flipflops_by_clock(args["--clock"]) << std::endl;
    } else if (action == "max_pi_to_dff_depth") {
        std::cout << g.max_pi_to_dff_depth() << std::endl;
    } else if (action == "list_floating") {
        std::cout << g.list_floating() << std::endl;
    } else if (action == "signal_depends_on") {
        std::cout << g.signal_depends_on(args["--target"], args["--source"]) << std::endl;
    } else if (action == "highest_fanout_pi") {
        std::cout << g.highest_fanout_pi() << std::endl;
    } else if (action == "merge_dup") {
        int n = g.merge_duplicate_gates();
        if (args.count("--out")) VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << "Merged " << n << " duplicate gate(s) computing the same function."
                  << std::endl;
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
            return 1;
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
        if (R.blif_unsupported > 0) {
            std::cout << "Failure: BLIF import contained " << R.blif_unsupported
                      << " unsupported .names block(s) (>2 inputs); rebuild aborted "
                      << "to avoid emitting functionally wrong logic." << std::endl;
            return 1;
        }
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
            return 1;
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
    } else if (action == "count_gates_in_cone") {
        if (!args.count("--node")) { std::cout << "Error: --node required\n"; return 1; }
        std::string dir = args.count("--direction") ? args["--direction"] : "fanin";
        bool backward = (dir != "fanout");
        bool stop_at_dff = int_flag(args, "--stop_at_dff", 1) != 0;
        if (g.nodes.find(args["--node"]) == g.nodes.end()) {
            std::cout << "Error: Node not found.\n"; return 1;
        }
        // BFS cone traversal; combinational by default (Q&A A21.2): a DFF is
        // included as the cone boundary but its far side is never entered.
        std::unordered_set<Node*> visited;
        std::queue<Node*> bfsq;
        bfsq.push(g.nodes[args["--node"]]);
        while (!bfsq.empty()) {
            Node* cur = bfsq.front(); bfsq.pop();
            if (visited.count(cur)) continue;
            visited.insert(cur);
            if (stop_at_dff && cur->type == NodeType::GATE && cur->gate_type == GateType::DFF)
                continue;
            const auto& nexts = backward ? cur->inputs : cur->outputs;
            for (auto n : nexts) if (!visited.count(n)) bfsq.push(n);
        }
        std::unordered_map<GateType, int> counts;
        int total_gates = 0, total_signals = 0;
        for (auto n : visited) {
            if (n->type == NodeType::GATE) { counts[n->gate_type]++; total_gates++; }
            else total_signals++;
        }
        std::cout << "{\n";
        std::cout << "  \"cone_root\": \"" << args["--node"] << "\",\n";
        std::cout << "  \"direction\": \"" << dir << "\",\n";
        std::cout << "  \"semantics\": \"" << (stop_at_dff
                      ? "combinational (DFF Q = PI; boundary DFFs included, not traversed)"
                      : "transitive through DFFs") << "\",\n";
        std::cout << "  \"total_gates\": " << total_gates << ",\n";
        std::cout << "  \"by_type\": {\n";
        std::vector<GateType> types = {GateType::NOT, GateType::AND, GateType::OR, GateType::XOR, GateType::NOR, GateType::NAND, GateType::XNOR, GateType::BUF, GateType::DFF};
        bool first = true;
        for (auto t : types) {
            if (counts[t] > 0) {
                if (!first) std::cout << ",\n";
                std::cout << "    \"" << gate_type_to_string(t) << "\": " << counts[t];
                first = false;
            }
        }
        std::cout << "\n  },\n";
        std::cout << "  \"total_signals\": " << total_signals << "\n";
        std::cout << "}\n";
    } else if (action == "list_pio") {
        std::cout << g.list_pio() << std::endl;
    } else if (action == "deepest_cone_output") {
        std::cout << g.deepest_cone_output() << std::endl;
    } else if (action == "r2r_paths") {
        std::cout << g.r2r_paths() << std::endl;
    } else if (action == "const_propagate") {
        std::string m = args.count("--mode") ? args["--mode"] : "propagate";
        std::string gtf = args.count("--gate_type") ? args["--gate_type"] : "";
        std::string cvf = args.count("--const_value") ? args["--const_value"] : "";
        std::string result = g.const_propagate(m, gtf, cvf);
        if (m == "propagate" && args.count("--out"))
            VerilogWriter::write_verilog(g, args["--out"]);
        std::cout << result << std::endl;
    } else {
        log_error("Unknown action: " + action);
        return 1;
    }
    return 0;
}
