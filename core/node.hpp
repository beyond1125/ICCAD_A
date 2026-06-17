#ifndef NODE_HPP
#define NODE_HPP

#include <string>
#include <vector>
#include "types.hpp"

class Node {
public:
    Node(const std::string& name, NodeType type)
        : name_(name), type_(type), gate_type_(GateType::UNKNOWN) {}

    const std::string& Name() const { return name_; }
    NodeType Type() const { return type_; }
    GateType GetGateType() const { return gate_type_; }

    void SetType(NodeType type) { type_ = type; }
    void SetGateType(GateType gate_type) { gate_type_ = gate_type; }

    const std::vector<Node*>& Inputs() const { return inputs_; }
    const std::vector<Node*>& Outputs() const { return outputs_; }

    void AddInput(Node* input) { inputs_.push_back(input); }
    void AddOutput(Node* output) { outputs_.push_back(output); }

private:
    std::string name_;
    NodeType type_;
    GateType gate_type_;
    std::vector<Node*> inputs_;
    std::vector<Node*> outputs_;
};

#endif // NODE_HPP
