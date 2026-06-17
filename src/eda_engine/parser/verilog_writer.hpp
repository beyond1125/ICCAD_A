#ifndef VERILOG_WRITER_HPP
#define VERILOG_WRITER_HPP

#include "graph.hpp"
#include <string>
#include <vector>

class VerilogWriter {
public:
    static void write_verilog(const Graph& graph, const std::string& filename);

private:
    struct SignalGroup { std::string base; int min_idx, max_idx; bool is_vector; };
    static std::vector<std::string> group_signals(const std::vector<Node*>& nodes_list);
};

#endif // VERILOG_WRITER_HPP
