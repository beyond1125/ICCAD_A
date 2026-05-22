#ifndef PARSER_HPP
#define PARSER_HPP

#include <string>
#include <vector>
#include <unordered_map>
#include <iostream>
#include <fstream>
#include <sstream>
#include <regex>

enum class NodeType {
    GATE,
    SIGNAL,
    PRIMARY_INPUT,
    PRIMARY_OUTPUT
};

enum class GateType {
    NOT, AND, OR, XOR, NOR, NAND, BUF, DFF, UNKNOWN
};

class Node {
public:
    std::string name;
    NodeType type;
    GateType gate_type;
    std::vector<Node*> inputs;
    std::vector<Node*> outputs;

    Node(const std::string& n, NodeType t) : name(n), type(t), gate_type(GateType::UNKNOWN) {}
};

class Graph {
public:
    std::unordered_map<std::string, Node*> nodes;
    std::vector<Node*> all_nodes;
    std::string module_name;

    ~Graph() {
        for (auto node : all_nodes) {
            delete node;
        }
    }

    Node* get_or_create_node(const std::string& name, NodeType type = NodeType::SIGNAL) {
        if (nodes.find(name) != nodes.end()) {
            if (type != NodeType::SIGNAL && nodes[name]->type == NodeType::SIGNAL) {
                nodes[name]->type = type;
            }
            return nodes[name];
        }
        Node* n = new Node(name, type);
        nodes[name] = n;
        all_nodes.push_back(n);
        return n;
    }

    void add_edge(Node* from, Node* to) {
        from->outputs.push_back(to);
        to->inputs.push_back(from);
    }

    // --- Algorithms ---

    int calculate_depth(const std::string& start, const std::string& end) {
        if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return -1;
        
        std::unordered_map<Node*, int> memo;
        return get_max_depth_recursive(nodes[start], nodes[end], memo);
    }

    int count_paths(const std::string& start, const std::string& end, const std::string& avoid = "") {
        if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return 0;
        Node* avoid_node = avoid.empty() ? nullptr : (nodes.count(avoid) ? nodes[avoid] : nullptr);
        
        std::unordered_map<Node*, int> memo;
        return count_paths_recursive(nodes[start], nodes[end], avoid_node, memo);
    }

    std::string get_node_info(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
        Node* n = nodes[name];
        std::stringstream ss;
        if (n->type == NodeType::GATE) {
            ss << "Gate " << n->name << " [Type: " << gate_type_to_string(n->gate_type) << "]";
        } else {
            ss << "Signal " << n->name << " [" << (n->type == NodeType::PRIMARY_INPUT ? "PI" : n->type == NodeType::PRIMARY_OUTPUT ? "PO" : "Wire") << "]";
        }
        ss << "\n  Inputs: ";
        for (auto in : n->inputs) ss << in->name << " ";
        ss << "\n  Outputs: ";
        for (auto out : n->outputs) ss << out->name << " ";
        return ss.str();
    }

    // --- Modifications ---

    bool replace_gate(const std::string& target, const std::string& new_type) {
        if (nodes.find(target) == nodes.end() || nodes[target]->type != NodeType::GATE) return false;
        
        GateType gt = string_to_gate_type_static(new_type);
        if (gt == GateType::UNKNOWN) return false;
        
        nodes[target]->gate_type = gt;
        return true;
    }

    void write_verilog(const std::string& filename) {
        std::ofstream ofs(filename);
        ofs << "module " << module_name << " (\n";
        
        std::vector<std::string> pi, po, wires;
        for (auto n : all_nodes) {
            if (n->type == NodeType::PRIMARY_INPUT) pi.push_back(n->name);
            else if (n->type == NodeType::PRIMARY_OUTPUT) po.push_back(n->name);
            else if (n->type == NodeType::SIGNAL) wires.push_back(n->name);
        }

        for (size_t i = 0; i < pi.size(); ++i) ofs << "    input " << pi[i] << (i == pi.size() - 1 && po.empty() ? "" : ",") << "\n";
        for (size_t i = 0; i < po.size(); ++i) ofs << "    output " << po[i] << (i == po.size() - 1 ? "" : ",") << "\n";
        ofs << ");\n\n";

        for (const auto& w : wires) ofs << "    wire " << w << ";\n";
        ofs << "\n";

        for (auto n : all_nodes) {
            if (n->type == NodeType::GATE) {
                ofs << "    " << gate_type_to_string(n->gate_type) << " " << n->name << " (";
                // This is a simplified emission (assumes single output first)
                if (!n->outputs.empty()) ofs << n->outputs[0]->name;
                for (auto in : n->inputs) ofs << ", " << in->name;
                ofs << ");\n";
            }
        }
        ofs << "\nendmodule\n";
    }

private:
    int get_max_depth_recursive(Node* curr, Node* target, std::unordered_map<Node*, int>& memo) {
        if (curr == target) return 0;
        if (memo.count(curr)) return memo[curr];

        int max_d = -1e9;
        for (auto next : curr->outputs) {
            int d = get_max_depth_recursive(next, target, memo);
            if (next->type == NodeType::GATE) d += 1;
            max_d = std::max(max_d, d);
        }
        return memo[curr] = max_d;
    }

    int count_paths_recursive(Node* curr, Node* target, Node* avoid, std::unordered_map<Node*, int>& memo) {
        if (curr == target) return 1;
        if (curr == avoid) return 0;
        if (memo.count(curr)) return memo[curr];

        int count = 0;
        for (auto next : curr->outputs) {
            count += count_paths_recursive(next, target, avoid, memo);
        }
        return memo[curr] = count;
    }

    std::string gate_type_to_string(GateType gt) {
        switch (gt) {
            case GateType::NOT: return "not";
            case GateType::AND: return "and";
            case GateType::OR: return "or";
            case GateType::XOR: return "xor";
            case GateType::NOR: return "nor";
            case GateType::NAND: return "nand";
            case GateType::BUF: return "buf";
            case GateType::DFF: return "dff";
            default: return "unknown";
        }
    }

    static GateType string_to_gate_type_static(const std::string& type_str) {
        if (type_str == "not") return GateType::NOT;
        if (type_str == "and") return GateType::AND;
        if (type_str == "or") return GateType::OR;
        if (type_str == "xor") return GateType::XOR;
        if (type_str == "nor") return GateType::NOR;
        if (type_str == "nand") return GateType::NAND;
        if (type_str == "buf") return GateType::BUF;
        if (type_str == "dff") return GateType::DFF;
        return GateType::UNKNOWN;
    }
};

class VerilogParser {
public:
    void parse(const std::string& filename, Graph& graph);

private:
    std::string strip_comments(const std::string& content);
    std::vector<std::string> split_statements(const std::string& content);
    void process_statement(const std::string& stmt, Graph& graph);
    GateType string_to_gate_type(const std::string& type_str);
    std::vector<std::string> parse_signal_list(const std::string& list_str);
    std::vector<std::string> expand_bus(const std::string& base, int msb, int lsb);
};

#endif
