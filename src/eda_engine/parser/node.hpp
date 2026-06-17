#ifndef NODE_HPP
#define NODE_HPP

#include "types.hpp"
#include <string>
#include <vector>

class Node {
public:
    std::string name;
    NodeType type;
    GateType gate_type;
    std::vector<Node*> inputs;
    std::vector<Node*> outputs;
    std::vector<PinConn> pin_conns;

    Node(const std::string& n, NodeType t);
};

#endif // NODE_HPP
