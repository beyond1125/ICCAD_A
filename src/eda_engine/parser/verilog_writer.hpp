#ifndef VERILOG_WRITER_HPP
#define VERILOG_WRITER_HPP

#include "graph.hpp"
#include <string>
#include <vector>

class VerilogWriter {
public:
    static void write_verilog(const Graph& graph, const std::string& filename);

private:
    static std::vector<std::string> group_signals(const std::vector<Node*>& nodes_list);
};

#endif // VERILOG_WRITER_HPP
