#ifndef VERILOG_WRITER_HPP
#define VERILOG_WRITER_HPP

#include <string>
#include <vector>
#include "graph.hpp"

class VerilogWriter {
public:
    VerilogWriter() = default;
    void Write(const Graph& graph, const std::string& filename);

private:
    std::vector<std::string> GroupSignals(const std::vector<Node*>& nodes_list);
};

#endif // VERILOG_WRITER_HPP
