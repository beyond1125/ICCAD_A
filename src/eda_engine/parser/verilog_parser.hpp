#ifndef VERILOG_PARSER_HPP
#define VERILOG_PARSER_HPP

#include "graph.hpp"
#include <string>
#include <vector>

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

#endif // VERILOG_PARSER_HPP
