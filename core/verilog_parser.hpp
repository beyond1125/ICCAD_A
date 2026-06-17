#ifndef VERILOG_PARSER_HPP
#define VERILOG_PARSER_HPP

#include <string>
#include <vector>
#include "graph.hpp"

class VerilogParser {
public:
    VerilogParser() = default;
    void Parse(const std::string& filename, Graph& graph);

private:
    std::string StripComments(const std::string& content);
    std::vector<std::string> SplitStatements(const std::string& content);
    void ProcessStatement(const std::string& stmt, Graph& graph);
    std::vector<std::string> ParseSignalList(const std::string& list_str);
    std::vector<std::string> ExpandBus(const std::string& base, int msb, int lsb);
};

#endif // VERILOG_PARSER_HPP
