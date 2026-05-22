#include "parser.hpp"
#include <algorithm>

void VerilogParser::parse(const std::string& filename, Graph& graph) {
    std::ifstream ifs(filename);
    if (!ifs.is_open()) {
        std::cerr << "Failed to open file: " << filename << std::endl;
        return;
    }

    std::stringstream buffer;
    buffer << ifs.rdbuf();
    std::string content = buffer.str();

    content = strip_comments(content);
    std::vector<std::string> statements = split_statements(content);

    for (const auto& stmt : statements) {
        process_statement(stmt, graph);
    }
}

std::string VerilogParser::strip_comments(const std::string& content) {
    std::string result = content;
    std::regex line_comment("//.*");
    result = std::regex_replace(result, line_comment, "");
    std::regex multi_line_comment("/\\*[^*]*\\*+([^/*][^*]*\\*+)*/");
    result = std::regex_replace(result, multi_line_comment, "");
    return result;
}

std::vector<std::string> VerilogParser::split_statements(const std::string& content) {
    std::vector<std::string> statements;
    std::string current;
    for (char c : content) {
        if (c == ';') {
            statements.push_back(current);
            current.clear();
        } else {
            current += c;
        }
    }
    return statements;
}

GateType VerilogParser::string_to_gate_type(const std::string& type_str) {
    if (type_str == "not") return GateType::NOT;
    if (type_str == "and") return GateType::AND;
    if (type_str == "or") return GateType::OR;
    if (type_str == "xor") return GateType::XOR;
    if (type_str == "nor") return GateType::NOR;
    if (type_str == "nand") return GateType::NAND;
    if (type_str == "buf") return GateType::BUF;
    if (type_str == "dff" || type_str == "DFF") return GateType::DFF;
    return GateType::UNKNOWN;
}

std::vector<std::string> VerilogParser::expand_bus(const std::string& base, int msb, int lsb) {
    std::vector<std::string> expanded;
    if (msb >= lsb) {
        for (int i = msb; i >= lsb; --i) expanded.push_back(base + "[" + std::to_string(i) + "]");
    } else {
        for (int i = msb; i <= lsb; ++i) expanded.push_back(base + "[" + std::to_string(i) + "]");
    }
    return expanded;
}

std::vector<std::string> VerilogParser::parse_signal_list(const std::string& list_str) {
    std::vector<std::string> signals;
    std::regex sig_regex(R"(\w+(?:\[\d+(?::\d+)?\])?)");
    auto words_begin = std::sregex_iterator(list_str.begin(), list_str.end(), sig_regex);
    auto words_end = std::sregex_iterator();
    for (std::sregex_iterator i = words_begin; i != words_end; ++i) {
        std::string raw = (*i).str();
        std::regex range_regex(R"((\w+)\s*\[(\d+):(\d+)\])");
        std::smatch match;
        if (std::regex_search(raw, match, range_regex)) {
            auto expanded = expand_bus(match[1], std::stoi(match[2]), std::stoi(match[3]));
            signals.insert(signals.end(), expanded.begin(), expanded.end());
        } else {
            signals.push_back(raw);
        }
    }
    return signals;
}

void VerilogParser::process_statement(const std::string& stmt, Graph& graph) {
    std::regex ws(R"(\s+)");
    std::string s = std::regex_replace(stmt, ws, " ");
    s.erase(0, s.find_first_not_of(" "));
    s.erase(s.find_last_not_of(" ") + 1);
    if (s.empty()) return;

    std::stringstream ss(s);
    std::string first_word;
    ss >> first_word;

    if (first_word == "endmodule") return;
    if (first_word == "module") {
        std::regex mod_name_regex(R"(module\s+(\w+))");
        std::smatch match;
        if (std::regex_search(s, match, mod_name_regex)) {
            graph.module_name = match[1];
        }
    }

    if (first_word == "module" || first_word == "input" || first_word == "output" || first_word == "wire") {
        std::regex decl_regex(R"((input|output|wire)\s+(?:wire\s+)?(?:\[(\d+):(\d+)\]\s+)?([^,;\)]+))");
        auto decls_begin = std::sregex_iterator(s.begin(), s.end(), decl_regex);
        auto decls_end = std::sregex_iterator();
        for (std::sregex_iterator i = decls_begin; i != decls_end; ++i) {
            std::smatch match = *i;
            std::string kw = match[1];
            NodeType type = (kw == "input") ? NodeType::PRIMARY_INPUT :
                            (kw == "output") ? NodeType::PRIMARY_OUTPUT : NodeType::SIGNAL;
            int msb = -1, lsb = -1;
            if (match[2].matched) {
                msb = std::stoi(match[2]);
                lsb = std::stoi(match[3]);
            }
            std::string names_str = match[4];
            std::regex name_regex(R"(\w+)");
            auto names_begin = std::sregex_iterator(names_str.begin(), names_str.end(), name_regex);
            auto names_end = std::sregex_iterator();
            for (std::sregex_iterator j = names_begin; j != names_end; ++j) {
                std::string name = (*j).str();
                if (msb != -1) {
                    auto expanded = expand_bus(name, msb, lsb);
                    for (const auto& sig : expanded) graph.get_or_create_node(sig, type);
                } else {
                    graph.get_or_create_node(name, type);
                }
            }
        }
    } else {
        GateType gt = string_to_gate_type(first_word);
        if (gt != GateType::UNKNOWN) {
            std::string inst_name;
            ss >> inst_name;
            size_t open_paren = s.find('(');
            size_t close_paren = s.find(')');
            if (open_paren != std::string::npos && close_paren != std::string::npos) {
                std::string ports_str = s.substr(open_paren + 1, close_paren - open_paren - 1);
                auto ports = parse_signal_list(ports_str);
                Node* gate_node = graph.get_or_create_node(inst_name, NodeType::GATE);
                gate_node->gate_type = gt;
                if (gt == GateType::DFF) {
                    if (ports.size() >= 2) {
                        Node* q_node = graph.get_or_create_node(ports[0], NodeType::SIGNAL);
                        Node* d_node = graph.get_or_create_node(ports[1], NodeType::SIGNAL);
                        graph.add_edge(gate_node, q_node);
                        graph.add_edge(d_node, gate_node);
                    }
                } else {
                    if (!ports.empty()) {
                        Node* out_node = graph.get_or_create_node(ports[0], NodeType::SIGNAL);
                        graph.add_edge(gate_node, out_node);
                        for (size_t i = 1; i < ports.size(); ++i) {
                            Node* in_node = graph.get_or_create_node(ports[i], NodeType::SIGNAL);
                            graph.add_edge(in_node, gate_node);
                        }
                    }
                }
            }
        }
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
        std::cerr << "Usage: " << argv[0] << " --in <file.v> --action <action> [options]" << std::endl;
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
    } else if (action == "count_paths") {
        int c = g.count_paths(args["--start"], args["--end"], args["--avoid"]);
        std::cout << "Paths: " << c << std::endl;
    } else if (action == "get_info") {
        std::cout << g.get_node_info(args["--node"]) << std::endl;
    } else if (action == "list_nodes") {
        for (auto n : g.all_nodes) std::cout << n->name << " (" << (n->type == NodeType::GATE ? "GATE" : "SIGNAL") << ")" << std::endl;
    } else if (action == "replace_gate") {
        if (g.replace_gate(args["--target"], args["--new_type"])) {
            if (args.count("--out")) g.write_verilog(args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            std::cout << "Failure" << std::endl;
        }
    } else {
        std::cerr << "Unknown action: " << action << std::endl;
        return 1;
    }
    return 0;
}
