#ifndef GRAPH_HPP
#define GRAPH_HPP

#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <memory>
#include "node.hpp"

class Graph {
public:
    Graph() = default;
    ~Graph() = default;

    // Delete copy/move to ensure uniqueness of Nodes
    Graph(const Graph&) = delete;
    Graph& operator=(const Graph&) = delete;

    Node* GetOrCreateNode(const std::string& name, NodeType type = NodeType::SIGNAL);
    void AddEdge(Node* from, Node* to);

    // Algorithms
    int CalculateDepth(const std::string& start, const std::string& end) const;
    int CountPaths(const std::string& start, const std::string& end, const std::string& avoid = "") const;
    std::string FindAllPaths(const std::string& start, const std::string& end, const std::string& avoid = "") const;
    int CountFaninGates(const std::string& name) const;
    int CalculateFaninDepth(const std::string& name) const;
    int GetFanoutCount(const std::string& name) const;
    std::vector<std::string> GetImmediateSuccessors(const std::string& name) const;
    std::vector<std::string> GetTransitiveFanin(const std::string& name) const;
    std::vector<std::string> GetTransitiveFanout(const std::string& name) const;
    std::string GetNodeInfo(const std::string& name) const;

    // Modifications
    bool ReplaceGate(const std::string& target, const std::string& new_type);

    // Accessors
    const std::string& GetModuleName() const { return module_name_; }
    void SetModuleName(const std::string& name) { module_name_ = name; }
    const std::vector<std::unique_ptr<Node>>& AllNodes() const { return all_nodes_; }
    Node* FindNode(const std::string& name) const;

private:
    int GetNodeDepthBackward(Node* curr, std::unordered_map<Node*, int>& memo) const;
    int GetMaxDepthRecursive(Node* curr, Node* target, std::unordered_map<Node*, int>& memo) const;
    int CountPathsRecursive(Node* curr, Node* target, Node* avoid, std::unordered_map<Node*, int>& memo) const;
    void FindAllPathsRecursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths) const;
    int CountFaninGatesRecursive(Node* curr, std::unordered_set<Node*>& visited) const;

    std::unordered_map<std::string, Node*> nodes_;
    std::vector<std::unique_ptr<Node>> all_nodes_;
    std::string module_name_;
};

#endif // GRAPH_HPP
