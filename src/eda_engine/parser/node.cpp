#include "node.hpp"

Node::Node(const std::string& n, NodeType t) : name(n), type(t), gate_type(GateType::UNKNOWN) {}
