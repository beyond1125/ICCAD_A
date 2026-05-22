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

    ~Graph() {
        for (auto node : all_nodes) {
            delete node;
        }
    }

    Node* get_or_create_node(const std::string& name, NodeType type = NodeType::SIGNAL) {
        if (nodes.find(name) != nodes.end()) {
            // Update type if it was just a signal but now we know it's a port
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

    void print() {
        for (auto node : all_nodes) {
            std::cout << "Node: " << node->name << " (";
            switch (node->type) {
                case NodeType::GATE: std::cout << "GATE"; break;
                case NodeType::SIGNAL: std::cout << "SIGNAL"; break;
                case NodeType::PRIMARY_INPUT: std::cout << "PI"; break;
                case NodeType::PRIMARY_OUTPUT: std::cout << "PO"; break;
            }
            if (node->type == NodeType::GATE) {
                std::cout << ", ";
                switch (node->gate_type) {
                    case GateType::NOT: std::cout << "NOT"; break;
                    case GateType::AND: std::cout << "AND"; break;
                    case GateType::OR: std::cout << "OR"; break;
                    case GateType::XOR: std::cout << "XOR"; break;
                    case GateType::NOR: std::cout << "NOR"; break;
                    case GateType::NAND: std::cout << "NAND"; break;
                    case GateType::BUF: std::cout << "BUF"; break;
                    case GateType::DFF: std::cout << "DFF"; break;
                    default: std::cout << "UNKNOWN"; break;
                }
            }
            std::cout << ")" << std::endl;
            std::cout << "  Inputs: ";
            for (auto in : node->inputs) std::cout << in->name << " ";
            std::cout << std::endl << "  Outputs: ";
            for (auto out : node->outputs) std::cout << out->name << " ";
            std::cout << std::endl;
        }
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
