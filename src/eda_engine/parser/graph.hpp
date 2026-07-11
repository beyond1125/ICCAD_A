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
    // Count of .names blocks the BLIF importer could not represent (>2 inputs).
    // Checked by the rebuild action so unsupported logic fails loudly instead of
    // being silently dropped.
    int blif_unsupported = 0;

    ~Graph();

    Node* get_or_create_node(const std::string& name, NodeType type = NodeType::SIGNAL);
    void add_edge(Node* from, Node* to);

    // --- Topological Sort ---
    void compute_topological_sort();

    // --- Algorithms ---
    std::unordered_map<Node*, int> compute_levels(Node* start = nullptr);
    int calculate_depth(const std::string& start, const std::string& end);
    std::string get_critical_path(const std::string& start, const std::string& end);
    long long count_paths(const std::string& start, const std::string& end, const std::string& avoid = "");
    std::string find_all_paths(const std::string& start, const std::string& end, const std::string& avoid = "", const std::string& paths_out = "");
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
    int insert_dedicated_buffers(const std::string& signal);
    int insert_buffers_on_signal(const std::string& signal, int max_fanout);
    bool reconnect_pin(const std::string& gate, const std::string& pin, const std::string& signal);
    int sweep_dangling();
    std::unordered_set<Node*> fanin_cone_gates(const std::string& root);
    int decompose_in_cone(const std::string& root, const std::string& from_type, const std::string& basis);
    int collapse_inverters();
    int remap_cone_to_basis(const std::string& root, const std::string& basis);
    std::string outputs_over_depth(int max_depth);
    std::string list_gates_by_type(const std::string& type_str);
    std::string flipflops_by_clock(const std::string& clock);
    std::string max_pi_to_dff_depth();
    std::string list_floating();
    std::string signal_depends_on(const std::string& target, const std::string& source);
    std::string highest_fanout_pi();
    int merge_duplicate_gates();
    std::string const_propagate(const std::string& mode, const std::string& gate_type_filter, const std::string& const_value_filter);
    std::string list_pio();
    std::string deepest_cone_output();
    std::string r2r_paths();
    std::string write_cone_blifs(const std::string& nets_csv, const std::string& out_dir, const std::string& tie0_csv);
    std::string write_seq_blif(const std::string& filename, const std::string& expose_csv, bool expose_only);
    std::string tie_nets_const(const std::string& assign_csv);
    std::string sim_consts(const std::string& nets_csv, int cycles, int trials, unsigned seed);
    std::string list_dffs(const std::string& scope_net);
    std::string report_stuck_inputs(const std::string& gate_type_str, int cycles, int trials, unsigned seed);

private:
    void find_all_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths, const std::unordered_set<Node*>& can_reach);
    void stream_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, const std::unordered_set<Node*>& can_reach, std::ostream& out, long long& found, long long& bytes, std::stringstream& preview);
    int count_fanin_gates_recursive(Node* curr, std::unordered_set<Node*>& visited);
    int count_fanout_gates_recursive(Node* curr, std::unordered_set<Node*>& visited);
    void get_cone_recursive(Node* curr, std::unordered_set<Node*>& visited, bool backward);
    void run_random_sim(int cycles, int trials, unsigned seed,
                        std::unordered_map<Node*, std::pair<long, long>>& counts);
};

#endif // GRAPH_HPP
