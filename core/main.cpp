#include <iostream>
#include <unordered_map>
#include <vector>
#include "graph.hpp"
#include "verilog_parser.hpp"
#include "verilog_writer.hpp"

int main(int argc, char** argv) {
    std::unordered_map<std::string, std::string> args;
    for (int i = 1; i < argc; ++i) {
        if (std::string(argv[i]).substr(0, 2) == "--") {
            if (i + 1 < argc) args[argv[i]] = argv[i+1];
        }
    }
    if (args.find("--in") == args.end()) {
        std::cerr << "Usage: " << argv[0] << " --in <file.v> --action <action> [options]" << std::endl;
        return 1;
    }

    Graph g;
    VerilogParser parser;
    parser.Parse(args["--in"], g);

    std::string action = args["--action"];
    if (action == "load") {
        int pi = 0, po = 0, gates = 0;
        for (auto& n : g.AllNodes()) {
            if (n->Type() == NodeType::PRIMARY_INPUT) pi++;
            else if (n->Type() == NodeType::PRIMARY_OUTPUT) po++;
            else if (n->Type() == NodeType::GATE) gates++;
        }
        std::cout << "Success. PI: " << pi << ", PO: " << po << ", Gates: " << gates << std::endl;
    } else if (action == "calc_depth") {
        int d = g.CalculateDepth(args["--start"], args["--end"]);
        if (d < -500000) {
            std::cout << "No path found from " << args["--start"] << " to " << args["--end"] << std::endl;
        } else {
            std::cout << "Depth: " << d << std::endl;
        }
    } else if (action == "get_fanout") {
        int c = g.GetFanoutCount(args["--node"]);
        std::cout << "Fanout: " << c << std::endl;
    } else if (action == "get_successors") {
        auto succs = g.GetImmediateSuccessors(args["--node"]);
        std::cout << "Successors: ";
        for (const auto& s : succs) std::cout << s << " ";
        std::cout << std::endl;
    } else if (action == "get_tfanin") {
        auto nodes = g.GetTransitiveFanin(args["--node"]);
        std::cout << "Transitive Fanin (" << nodes.size() << " nodes): ";
        for (const auto& n : nodes) std::cout << n << " ";
        std::cout << std::endl;
    } else if (action == "get_tfanout") {
        auto nodes = g.GetTransitiveFanout(args["--node"]);
        std::cout << "Transitive Fanout (" << nodes.size() << " nodes): ";
        for (const auto& n : nodes) std::cout << n << " ";
        std::cout << std::endl;
    } else if (action == "count_paths") {
        int c = g.CountPaths(args["--start"], args["--end"], args["--avoid"]);
        std::cout << "Paths: " << c << std::endl;
    } else if (action == "list_paths") {
        std::cout << g.FindAllPaths(args["--start"], args["--end"], args["--avoid"]) << std::endl;
    } else if (action == "count_fanin") {
        int c = g.CountFaninGates(args["--node"]);
        std::cout << "Fanin Gates: " << c << std::endl;
    } else if (action == "fanin_depth") {
        int d = g.CalculateFaninDepth(args["--node"]);
        std::cout << "Fanin Depth: " << d << std::endl;
    } else if (action == "path_exists") {
        int c = g.CountPaths(args["--start"], args["--end"], args["--avoid"]);
        std::cout << (c > 0 ? "True" : "False") << std::endl;
    } else if (action == "get_info") {
        std::cout << g.GetNodeInfo(args["--node"]) << std::endl;
    } else if (action == "list_nodes") {
        for (auto& n : g.AllNodes()) {
            std::cout << n->Name() << " (" << (n->Type() == NodeType::GATE ? "GATE" : "SIGNAL") << ")" << std::endl;
        }
    } else if (action == "replace_gate") {
        if (g.ReplaceGate(args["--target"], args["--new_type"])) {
            if (args.count("--out")) {
                VerilogWriter writer;
                writer.Write(g, args["--out"]);
            }
            std::cout << "Success" << std::endl;
        } else {
            std::cout << "Failure" << std::endl;
        }
    } else if (action == "write") {
        if (args.count("--out")) {
            VerilogWriter writer;
            writer.Write(g, args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            std::cerr << "Error: --out required for write action" << std::endl;
        }
    } else if (action == "count_gates") {
        std::unordered_map<GateType, int> counts;
        for (auto& n : g.AllNodes()) {
            if (n->Type() == NodeType::GATE) counts[n->GetGateType()]++;
        }
        std::cout << "Gate counts:\n";
        std::vector<GateType> types = {GateType::NOT, GateType::AND, GateType::OR, GateType::XOR, GateType::NOR, GateType::NAND, GateType::XNOR, GateType::BUF, GateType::DFF};
        for (auto t : types) {
            std::cout << GateUtil::ToString(t) << ": " << counts[t] << "\n";
        }
    } else {
        std::cerr << "Unknown action: " << action << std::endl;
        return 1;
    }

    return 0;
}
