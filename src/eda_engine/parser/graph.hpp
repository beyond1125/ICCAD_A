#ifndef GRAPH_HPP
#define GRAPH_HPP

#include "node.hpp"
#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>

class Graph {
public:
    std::unordered_map<std::string, Node*> nodes;
    std::vector<Node*> all_nodes;
    std::vector<Node*> topological_order;
    std::string module_name;

    ~Graph();

    Node* get_or_create_node(const std::string& name, NodeType type = NodeType::SIGNAL);
    void add_edge(Node* from, Node* to);

    // --- Topological Sort ---
    void compute_topological_sort();

    // --- Algorithms ---
    std::unordered_map<Node*, int> compute_levels(Node* start = nullptr);
    int calculate_depth(const std::string& start, const std::string& end);
    std::string get_critical_path(const std::string& start, const std::string& end);
    int count_paths(const std::string& start, const std::string& end, const std::string& avoid = "");
    std::string find_all_paths(const std::string& start, const std::string& end, const std::string& avoid = "");
    int count_fanin_gates(const std::string& name);
    int count_fanout_gates(const std::string& name);
    std::string get_fanin_cone(const std::string& name);
    std::string get_fanout_cone(const std::string& name);
    int get_fanin_depth(const std::string& name);
    std::string get_node_info(const std::string& name);
    bool replace_gate(const std::string& target, const std::string& new_type);
    bool rename_node(const std::string& old_name, const std::string& new_name);
    
    void load_logic_blif(const std::string& file);
    void write_blif(const std::string& filename);
    int insert_buffers(int max_fanout);
    int sweep_dangling();
    std::unordered_set<Node*> fanin_cone_gates(const std::string& root);
    int decompose_in_cone(const std::string& root, const std::string& from_type, const std::string& basis);
    int collapse_inverters();
    int remap_cone_to_basis(const std::string& root, const std::string& basis);
    std::string outputs_over_depth(int max_depth);

private:
    void find_all_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths);
    int count_fanin_gates_recursive(Node* curr, std::unordered_set<Node*>& visited);
    int count_fanout_gates_recursive(Node* curr, std::unordered_set<Node*>& visited);
    void get_cone_recursive(Node* curr, std::unordered_set<Node*>& visited, bool backward);
};

#endif // GRAPH_HPP
