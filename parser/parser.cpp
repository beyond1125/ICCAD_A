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
    // Basic comment stripping (both // and /* */)
    std::string result = content;
    std::regex line_comment("//.*");
    result = std::regex_replace(result, line_comment, "");

    // Multi-line comments: /* ... */
    // Note: This regex might be slow on very large files, but is accurate.
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
    // Matches: name, name[index], name[msb:lsb]
    std::regex sig_regex(R"(\w+(?:\[\d+(?::\d+)?\])?)");
    auto words_begin = std::sregex_iterator(list_str.begin(), list_str.end(), sig_regex);
    auto words_end = std::sregex_iterator();

    for (std::sregex_iterator i = words_begin; i != words_end; ++i) {
        std::string raw = (*i).str();
        // If it's a bus range name[msb:lsb], expand it
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
    // Trim
    s.erase(0, s.find_first_not_of(" "));
    s.erase(s.find_last_not_of(" ") + 1);
    if (s.empty()) return;

    std::stringstream ss(s);
    std::string first_word;
    ss >> first_word;

    if (first_word == "endmodule") return;

    if (first_word == "module" || first_word == "input" || first_word == "output" || first_word == "wire") {
        // Find all occurrences of input/output/wire declarations
        // In ANSI Verilog, these can be inside the module statement.
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
                    for (const auto& sig : expanded) {
                        graph.get_or_create_node(sig, type);
                    }
                } else {
                    graph.get_or_create_node(name, type);
                }
            }
        }
    } else {
        // Gate instantiation?
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
                    // For ICCAD/ABC, treating DFF as pseudo-PI/PO.
                    // d pin (usually 1st or 2nd) -> pseudo-output (end of combinational path)
                    // q pin -> pseudo-input (start of combinational path)
                    // Assuming simplified DFF (q, d, clk) or (q, d)
                    if (ports.size() >= 2) {
                        Node* q_node = graph.get_or_create_node(ports[0], NodeType::SIGNAL);
                        Node* d_node = graph.get_or_create_node(ports[1], NodeType::SIGNAL);
                        
                        // Combinational view:
                        // DFF drives Q (so Q is a pseudo-input to the rest of the circuit)
                        // DFF is driven by D (so D is a pseudo-output of the rest of the circuit)
                        graph.add_edge(gate_node, q_node); // Q is output of DFF
                        graph.add_edge(d_node, gate_node); // D is input to DFF
                    }
                } else {
                    // Primitive gates: first port is output, others are inputs
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
    if (argc < 2) {
        std::cout << "Usage: " << argv[0] << " <verilog_file>" << std::endl;
        return 1;
    }

    Graph g;
    VerilogParser parser;
    parser.parse(argv[1], g);
    g.print();

    return 0;
}
