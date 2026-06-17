#ifndef TYPES_HPP
#define TYPES_HPP

#include <string>

enum class NodeType {
    GATE,
    SIGNAL,
    PRIMARY_INPUT,
    PRIMARY_OUTPUT
};

enum class GateType {
    NOT, AND, OR, XOR, NOR, NAND, XNOR, BUF, DFF, UNKNOWN
};

struct PinConn {
    std::string pin;
    std::string signal;
    bool is_const;
    int edge_dir;
};

std::string gate_type_to_string(GateType gt);
GateType string_to_gate_type(const std::string& type_str);
void log_error(const std::string& msg);

#endif // TYPES_HPP
