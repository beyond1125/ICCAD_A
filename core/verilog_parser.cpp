#include "verilog_parser.hpp"
#include <fstream>
#include <sstream>
#include <regex>
#include <iostream>
#include <ctime>

namespace {
void LogError(const std::string& msg) {
    std::cerr << msg << std::endl;
    std::ofstream log_file("parser_error.log", std::ios::app);
    if (log_file.is_open()) {
        std::time_t now = std::time(nullptr);
        char timestamp[20];
        std::strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", std::localtime(&now));
        log_file << "[" << timestamp << "] " << msg << std::endl;
    }
}
} // namespace

void VerilogParser::Parse(const std::string& filename, Graph& graph) {
    std::ifstream ifs(filename);
    if (!ifs.is_open()) {
        LogError("Failed to open file: " + filename);
        return;
    }

    std::stringstream buffer;
    buffer << ifs.rdbuf();
    std::string content = buffer.str();

    content = StripComments(content);
    std::vector<std::string> statements = SplitStatements(content);

    for (const auto& stmt : statements) {
        ProcessStatement(stmt, graph);
    }
}

std::string VerilogParser::StripComments(const std::string& content) {
    std::string result = content;
    std::regex line_comment("//.*");
    result = std::regex_replace(result, line_comment, "");
    std::regex multi_line_comment("/\\*[^*]*\\*+([^/*][^*]*\\*+)*/");
    result = std::regex_replace(result, multi_line_comment, "");
    return result;
}

std::vector<std::string> VerilogParser::SplitStatements(const std::string& content) {
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

std::vector<std::string> VerilogParser::ExpandBus(const std::string& base, int msb, int lsb) {
    std::vector<std::string> expanded;
    if (msb >= lsb) {
        for (int i = msb; i >= lsb; --i) expanded.push_back(base + "[" + std::to_string(i) + "]");
    } else {
        for (int i = msb; i <= lsb; ++i) expanded.push_back(base + "[" + std::to_string(i) + "]");
    }
    return expanded;
}

std::vector<std::string> VerilogParser::ParseSignalList(const std::string& list_str) {
    std::vector<std::string> signals;
    std::regex sig_regex(R"(\w+(?:\[\d+(?::\d+)?\])?)");
    auto words_begin = std::sregex_iterator(list_str.begin(), list_str.end(), sig_regex);
    auto words_end = std::sregex_iterator();
    for (std::sregex_iterator i = words_begin; i != words_end; ++i) {
        std::string raw = (*i).str();
        std::regex range_regex(R"((\w+)\s*\[(\d+):(\d+)\])");
        std::smatch match;
        if (std::regex_search(raw, match, range_regex)) {
            auto expanded = ExpandBus(match[1], std::stoi(match[2]), std::stoi(match[3]));
            signals.insert(signals.end(), expanded.begin(), expanded.end());
        } else {
            signals.push_back(raw);
        }
    }
    return signals;
}

void VerilogParser::ProcessStatement(const std::string& stmt, Graph& graph) {
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
            graph.SetModuleName(match[1]);
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
        size_t next_kw = std::string::npos;
        std::smatch next_match;
        if (std::regex_search(remaining, next_match, kw_regex)) {
            next_kw = next_match.position();
        }
        std::string current_decl = remaining.substr(0, next_kw);

        int msb = -1, lsb = -1;
        std::regex range_regex(R"(^\s*\[(\d+):(\d+)\])");
        std::smatch range_match;
        if (std::regex_search(current_decl, range_match, range_regex)) {
            msb = std::stoi(range_match[1]);
            lsb = std::stoi(range_match[2]);
            current_decl = range_match.suffix();
        }

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
                    graph.GetOrCreateNode(base + "[" + std::to_string(k) + "]", type);
                }
            } else {
                if (msb != -1) {
                    auto expanded = ExpandBus(raw_name, msb, lsb);
                    for (const auto& sig : expanded) graph.GetOrCreateNode(sig, type);
                } else {
                    graph.GetOrCreateNode(raw_name, type);
                }
            }
        }
    }

    if (first_word != "module" && first_word != "input" && first_word != "output" && first_word != "wire" && first_word != "assign" && first_word != "endmodule") {
        GateType gt = GateUtil::FromString(first_word);
        if (gt != GateType::UNKNOWN) {
            size_t open_paren = s.find('(');
            size_t close_paren = s.find_last_of(')');
            if (open_paren != std::string::npos && close_paren != std::string::npos && close_paren > open_paren) {
                std::string inst_name = s.substr(first_word.length(), open_paren - first_word.length());
                inst_name.erase(0, inst_name.find_first_not_of(" "));
                inst_name.erase(inst_name.find_last_not_of(" ") + 1);
                
                std::string ports_str = s.substr(open_paren + 1, close_paren - open_paren - 1);
                auto ports = ParseSignalList(ports_str);
                
                if (inst_name.empty()) {
                    static int anon_count = 0;
                    inst_name = "anon_" + std::to_string(anon_count++);
                }

                Node* gate_node = graph.GetOrCreateNode(inst_name, NodeType::GATE);
                gate_node->SetGateType(gt);
                
                if (gt == GateType::DFF) {
                    if (ports.size() >= 2) {
                        Node* q_node = graph.GetOrCreateNode(ports[0], NodeType::SIGNAL);
                        Node* d_node = graph.GetOrCreateNode(ports[1], NodeType::SIGNAL);
                        graph.AddEdge(gate_node, q_node);
                        graph.AddEdge(d_node, gate_node);
                    }
                } else {
                    if (!ports.empty()) {
                        Node* out_node = graph.GetOrCreateNode(ports[0], NodeType::SIGNAL);
                        graph.AddEdge(gate_node, out_node);
                        for (size_t i = 1; i < ports.size(); ++i) {
                            Node* in_node = graph.GetOrCreateNode(ports[i], NodeType::SIGNAL);
                            graph.AddEdge(in_node, gate_node);
                        }
                    }
                }
            }
        }
    }
}
