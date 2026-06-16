#include "parser.hpp"
#include <algorithm>
#include <ctime>

void log_error(const std::string& msg) {
    std::cerr << msg << std::endl;
    std::ofstream log_file("parser_error.log", std::ios::app);
    if (log_file.is_open()) {
        std::time_t now = std::time(nullptr);
        char timestamp[20];
        std::strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", std::localtime(&now));
        log_file << "[" << timestamp << "] " << msg << std::endl;
    }
}

void VerilogParser::parse(const std::string& filename, Graph& graph) {
    std::ifstream ifs(filename);
    if (!ifs.is_open()) {
        log_error("Failed to open file: " + filename);
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
    if (type_str == "xnor") return GateType::XNOR;
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

    if (s.find("endmodule") != std::string::npos) return;

    std::stringstream ss_fw(s);
    std::string first_word;
    ss_fw >> first_word;

    if (s.substr(0, 6) == "module") {
        std::regex mod_name_regex(R"(module\s+(\w+))");
        std::smatch match;
        if (std::regex_search(s, match, mod_name_regex)) {
            graph.module_name = match[1];
        }
    }

    // Process input, output, wire
    std::regex kw_regex(R"(\b(input|output|wire)\b)");
    auto kw_begin = std::sregex_iterator(s.begin(), s.end(), kw_regex);
    auto kw_end = std::sregex_iterator();

    for (std::sregex_iterator i = kw_begin; i != kw_end; ++i) {
        std::string kw = (*i)[1];
        NodeType type = (kw == "input") ? NodeType::PRIMARY_INPUT :
                        (kw == "output") ? NodeType::PRIMARY_OUTPUT : NodeType::SIGNAL;
        
        std::string remaining = i->suffix().str();
        // We only want to process until the next keyword or end of statement
        size_t next_kw = std::string::npos;
        std::smatch next_match;
        if (std::regex_search(remaining, next_match, kw_regex)) {
            next_kw = next_match.position();
        }
        std::string current_decl = remaining.substr(0, next_kw);

        // Check for range [msb:lsb]
        int msb = -1, lsb = -1;
        std::regex range_regex(R"(^\s*\[(\d+):(\d+)\])");
        std::smatch range_match;
        if (std::regex_search(current_decl, range_match, range_regex)) {
            msb = std::stoi(range_match[1]);
            lsb = std::stoi(range_match[2]);
            current_decl = range_match.suffix();
        }

        // Parse comma-separated names
        std::regex name_regex(R"(\w+(?:\s*\[\d+\])?)");
        auto names_begin = std::sregex_iterator(current_decl.begin(), current_decl.end(), name_regex);
        auto names_end = std::sregex_iterator();
        for (std::sregex_iterator j = names_begin; j != names_end; ++j) {
            std::string raw_name = (*j).str();
            std::regex unpacked_regex(R"((\w+)\s*\[(\d+)\])");
            std::smatch unpacked_match;
            if (std::regex_search(raw_name, unpacked_match, unpacked_regex)) {
                std::string base = unpacked_match[1];
                int count = std::stoi(unpacked_match[2]);
                for (int k = 0; k < count; ++k) {
                    graph.get_or_create_node(base + "[" + std::to_string(k) + "]", type);
                }
            } else {
                if (msb != -1) {
                    auto expanded = expand_bus(raw_name, msb, lsb);
                    for (const auto& sig : expanded) graph.get_or_create_node(sig, type);
                } else {
                    graph.get_or_create_node(raw_name, type);
                }
            }
        }
    }

    // Process gates
    if (first_word != "module" && first_word != "input" && first_word != "output" && first_word != "wire" && first_word != "assign" && first_word != "endmodule") {
        GateType gt = string_to_gate_type(first_word);
        if (gt != GateType::UNKNOWN) {
            size_t open_paren = s.find('(');
            size_t close_paren = s.find_last_of(')');
            if (open_paren != std::string::npos && close_paren != std::string::npos && close_paren > open_paren) {
                // Instance name is between gate type and '('
                std::string inst_name = s.substr(first_word.length(), open_paren - first_word.length());
                inst_name.erase(0, inst_name.find_first_not_of(" "));
                inst_name.erase(inst_name.find_last_not_of(" ") + 1);
                
                std::string ports_str = s.substr(open_paren + 1, close_paren - open_paren - 1);

                if (inst_name.empty()) {
                    static int anon_count = 0;
                    inst_name = "anon_" + std::to_string(anon_count++);
                }

                Node* gate_node = graph.get_or_create_node(inst_name, NodeType::GATE);
                gate_node->gate_type = gt;

                // Detect named-port connections, e.g. ".CK(n0), .D(n244), .Q(n10)".
                // DFFs in these netlists use this style (with constants like 1'b1).
                std::regex named_port_regex(R"(\.(\w+)\s*\(\s*([^()]*?)\s*\))");
                auto np_begin = std::sregex_iterator(ports_str.begin(), ports_str.end(), named_port_regex);
                auto np_end = std::sregex_iterator();

                if (np_begin != np_end) {
                    // Named-port instance: preserve every pin for faithful write-back,
                    // and only build graph edges for data pins (D -> in, Q -> out).
                    // Control pins (CK/RN/SN) and constants get no combinational edge,
                    // keeping depth/path semantics identical to before.
                    for (std::sregex_iterator it = np_begin; it != np_end; ++it) {
                        std::string pin = (*it)[1];
                        std::string sig = (*it)[2];
                        bool is_const = sig.find('\'') != std::string::npos;
                        bool is_out = (pin == "Q" || pin == "QN");
                        bool is_data_in = (gt == GateType::DFF) ? (pin == "D")
                                                               : (!is_out);
                        int edge_dir = 0;
                        if (!is_const) {
                            Node* sig_node = graph.get_or_create_node(sig, NodeType::SIGNAL);
                            if (is_out) { graph.add_edge(gate_node, sig_node); edge_dir = 2; }
                            else if (is_data_in) { graph.add_edge(sig_node, gate_node); edge_dir = 1; }
                        }
                        gate_node->pin_conns.push_back({pin, sig, is_const, edge_dir});
                    }
                } else {
                    auto ports = parse_signal_list(ports_str);
                    if (gt == GateType::DFF) {
                        if (ports.size() >= 2) {
                            Node* q_node = graph.get_or_create_node(ports[0], NodeType::SIGNAL);
                            Node* d_node = graph.get_or_create_node(ports[1], NodeType::SIGNAL);
                            graph.add_edge(gate_node, q_node);
                            graph.add_edge(d_node, gate_node);
                        }
                    } else if (!ports.empty()) {
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
    } else if (action == "count_paths") {
        int c = g.count_paths(args["--start"], args["--end"], args["--avoid"]);
        std::cout << "Paths: " << c << std::endl;
    } else if (action == "list_paths") {
        std::cout << g.find_all_paths(args["--start"], args["--end"], args["--avoid"]) << std::endl;
    } else if (action == "count_fanin") {
        int c = g.count_fanin_gates(args["--node"]);
        std::cout << "Fanin Gates: " << c << std::endl;
    } else if (action == "get_info") {
        std::cout << g.get_node_info(args["--node"]) << std::endl;
    } else if (action == "list_nodes") {
        for (auto n : g.all_nodes) std::cout << n->name << " (" << (n->type == NodeType::GATE ? "GATE" : "SIGNAL") << ")" << std::endl;
    } else if (action == "replace_gate") {
        if (g.replace_gate(args["--target"], args["--new_type"])) {
            if (args.count("--out")) g.write_verilog(args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            log_error("Failure: Could not replace gate " + (args.count("--target") ? args["--target"] : "unknown"));
            std::cout << "Failure" << std::endl;
        }
    } else if (action == "insert_buffers") {
        int mf = args.count("--max_fanout") ? std::stoi(args["--max_fanout"]) : 4;
        int added = g.insert_buffers(mf);
        if (args.count("--out")) g.write_verilog(args["--out"]);
        std::cout << "Inserted " << added << " buffer(s) so no gate drives more than "
                  << mf << " loads." << std::endl;
    } else if (action == "write_blif") {
        if (args.count("--out")) {
            g.write_blif(args["--out"]);
            std::cout << "Success" << std::endl;
        } else {
            log_error("Error: --out required for write_blif action");
        }
    } else if (action == "write") {
        if (args.count("--out")) {
            g.write_verilog(args["--out"]);
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
            std::cout << g.gate_type_to_string_public(t) << ": " << counts[t] << "\n";
        }
    } else {
        log_error("Unknown action: " + action);
        return 1;
    }
    return 0;
}
