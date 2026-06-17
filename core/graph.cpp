#include "graph.hpp"
#include <algorithm>
#include <sstream>
#include <unordered_set>

Node* Graph::GetOrCreateNode(const std::string& name, NodeType type) {
    auto it = nodes_.find(name);
    if (it != nodes_.end()) {
        if (type != NodeType::SIGNAL && it->second->Type() == NodeType::SIGNAL) {
            it->second->SetType(type);
        }
        return it->second;
    }
    auto n = std::make_unique<Node>(name, type);
    Node* ptr = n.get();
    nodes_[name] = ptr;
    all_nodes_.push_back(std::move(n));
    return ptr;
}

void Graph::AddEdge(Node* from, Node* to) {
    from->AddOutput(to);
    to->AddInput(from);
}

Node* Graph::FindNode(const std::string& name) const {
    auto it = nodes_.find(name);
    return (it != nodes_.end()) ? it->second : nullptr;
}

int Graph::CalculateDepth(const std::string& start, const std::string& end) const {
    Node* end_node = FindNode(end);
    if (!end_node) return -1;

    std::unordered_map<Node*, int> memo;
    if (start.empty()) {
        return GetNodeDepthBackward(end_node, memo);
    }

    Node* start_node = FindNode(start);
    if (!start_node) return -1;
    return GetMaxDepthRecursive(start_node, end_node, memo);
}

int Graph::GetNodeDepthBackward(Node* curr, std::unordered_map<Node*, int>& memo) const {
    if (!curr) return 0;
    if (curr->Type() == NodeType::PRIMARY_INPUT) return 0;
    if (memo.count(curr)) return memo[curr];

    int max_d = 0;
    for (auto in : curr->Inputs()) {
        int d = GetNodeDepthBackward(in, memo);
        if (curr->Type() == NodeType::GATE) {
            max_d = std::max(max_d, d + 1);
        } else {
            max_d = std::max(max_d, d);
        }
    }
    return memo[curr] = max_d;
}

int Graph::GetMaxDepthRecursive(Node* curr, Node* target, std::unordered_map<Node*, int>& memo) const {
    if (curr == target) return 0;
    if (memo.count(curr)) return memo[curr];

    // Use a flag or a very small number that doesn't overflow easily
    // -1e6 is safe enough for depth calculations in typical netlists
    int max_d = -1000000; 
    for (auto next : curr->Outputs()) {
        int d = GetMaxDepthRecursive(next, target, memo);
        if (d > -1000000) {
            if (next->Type() == NodeType::GATE) d += 1;
            max_d = std::max(max_d, d);
        }
    }
    return memo[curr] = max_d;
}

int Graph::GetFanoutCount(const std::string& name) const {
    Node* n = FindNode(name);
    if (!n) return 0;
    
    if (n->Type() == NodeType::GATE) {
        if (n->Outputs().empty()) return 0;
        return static_cast<int>(n->Outputs()[0]->Outputs().size());
    }
    
    return static_cast<int>(n->Outputs().size());
}

std::vector<std::string> Graph::GetImmediateSuccessors(const std::string& name) const {
    Node* n = FindNode(name);
    if (!n) return {};
    
    std::unordered_set<std::string> successors;
    if (n->Type() == NodeType::GATE) {
        // A gate drives a signal, which in turn drives other gates
        for (auto sig : n->Outputs()) {
            for (auto next_gate : sig->Outputs()) {
                if (next_gate->Type() == NodeType::GATE) {
                    successors.insert(next_gate->Name());
                }
            }
        }
    } else {
        // A signal drives gates
        for (auto next_gate : n->Outputs()) {
            if (next_gate->Type() == NodeType::GATE) {
                successors.insert(next_gate->Name());
            }
        }
    }
    
    std::vector<std::string> result(successors.begin(), successors.end());
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<std::string> Graph::GetTransitiveFanin(const std::string& name) const {
    Node* start = FindNode(name);
    if (!start) return {};

    std::vector<std::string> result;
    std::unordered_set<Node*> visited;
    std::vector<Node*> stack = {start};
    visited.insert(start);

    while (!stack.empty()) {
        Node* curr = stack.back();
        stack.pop_back();
        
        // Only collect GATE nodes, and skip the start node itself
        if (curr != start && curr->Type() == NodeType::GATE) {
            result.push_back(curr->Name());
        }

        for (auto in : curr->Inputs()) {
            if (visited.find(in) == visited.end()) {
                visited.insert(in);
                stack.push_back(in);
            }
        }
    }
    std::sort(result.begin(), result.end());
    return result;
}

std::vector<std::string> Graph::GetTransitiveFanout(const std::string& name) const {
    Node* start = FindNode(name);
    if (!start) return {};

    std::vector<std::string> result;
    std::unordered_set<Node*> visited;
    std::vector<Node*> stack = {start};
    visited.insert(start);

    while (!stack.empty()) {
        Node* curr = stack.back();
        stack.pop_back();
        
        // Only collect GATE nodes, and skip the start node itself
        if (curr != start && curr->Type() == NodeType::GATE) {
            result.push_back(curr->Name());
        }

        for (auto out : curr->Outputs()) {
            if (visited.find(out) == visited.end()) {
                visited.insert(out);
                stack.push_back(out);
            }
        }
    }
    std::sort(result.begin(), result.end());
    return result;
}

int Graph::CountPaths(const std::string& start, const std::string& end, const std::string& avoid) const {
    Node* s = FindNode(start);
    Node* e = FindNode(end);
    if (!s || !e) return 0;
    Node* a = avoid.empty() ? nullptr : FindNode(avoid);

    std::unordered_map<Node*, int> memo;
    return CountPathsRecursive(s, e, a, memo);
}

int Graph::CountPathsRecursive(Node* curr, Node* target, Node* avoid, std::unordered_map<Node*, int>& memo) const {
    if (curr == target) return 1;
    if (curr == avoid) return 0;
    if (memo.count(curr)) return memo[curr];

    int count = 0;
    for (auto next : curr->Outputs()) {
        count += CountPathsRecursive(next, target, avoid, memo);
    }
    return memo[curr] = count;
}

std::string Graph::FindAllPaths(const std::string& start, const std::string& end, const std::string& avoid) const {
    Node* s = FindNode(start);
    Node* e = FindNode(end);
    if (!s || !e) return "Error: Start or end node not found.";
    Node* a = avoid.empty() ? nullptr : FindNode(avoid);

    std::vector<std::vector<Node*>> all_paths;
    std::vector<Node*> current_path;
    FindAllPathsRecursive(s, e, a, current_path, all_paths);

    if (all_paths.empty()) return "No paths found.";

    std::stringstream ss;
    ss << "Found " << all_paths.size() << " paths:\n";
    for (size_t i = 0; i < all_paths.size(); ++i) {
        ss << "Path " << i + 1 << ": ";
        bool first = true;
        for (size_t j = 0; j < all_paths[i].size(); ++j) {
            Node* n = all_paths[i][j];
            // Only output GATE nodes, or the very first/last nodes if they are PI/PO
            if (n->Type() == NodeType::GATE || j == 0 || j == all_paths[i].size() - 1) {
                if (!first) ss << " -> ";
                ss << n->Name();
                first = false;
            }
        }
        ss << "\n";
        if (i >= 100) {
            ss << "... (truncated)\n";
            break;
        }
    }
    return ss.str();
}

void Graph::FindAllPathsRecursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths) const {
    if (curr == avoid) return;
    path.push_back(curr);
    if (curr == target) {
        all_paths.push_back(path);
    } else {
        for (auto next : curr->Outputs()) {
            FindAllPathsRecursive(next, target, avoid, path, all_paths);
        }
    }
    path.pop_back();
}

int Graph::CountFaninGates(const std::string& name) const {
    Node* n = FindNode(name);
    if (!n) return 0;
    std::unordered_set<Node*> visited;
    return CountFaninGatesRecursive(n, visited);
}

int Graph::CalculateFaninDepth(const std::string& name) const {
    Node* n = FindNode(name);
    if (!n) return -1;
    
    std::unordered_map<Node*, int> memo;
    return GetNodeDepthBackward(n, memo);
}

int Graph::CountFaninGatesRecursive(Node* curr, std::unordered_set<Node*>& visited) const {
    if (!curr || visited.count(curr)) return 0;
    visited.insert(curr);

    int count = (curr->Type() == NodeType::GATE) ? 1 : 0;
    for (auto in : curr->Inputs()) {
        count += CountFaninGatesRecursive(in, visited);
    }
    return count;
}

std::string Graph::GetNodeInfo(const std::string& name) const {
    Node* n = FindNode(name);
    if (!n) return "Error: Node not found.";
    std::stringstream ss;
    if (n->Type() == NodeType::GATE) {
        ss << "Gate " << n->Name() << " [Type: " << GateUtil::ToString(n->GetGateType()) << "]";
    } else {
        ss << "Signal " << n->Name() << " [" << (n->Type() == NodeType::PRIMARY_INPUT ? "PI" : n->Type() == NodeType::PRIMARY_OUTPUT ? "PO" : "Wire") << "]";
    }
    ss << "\n  Fanin count: " << n->Inputs().size();
    ss << "\n  Fanout count: " << n->Outputs().size();
    ss << "\n  Inputs: ";
    for (auto in : n->Inputs()) ss << in->Name() << " ";
    ss << "\n  Outputs: ";
    for (auto out : n->Outputs()) ss << out->Name() << " ";
    return ss.str();
}

bool Graph::ReplaceGate(const std::string& target, const std::string& new_type) {
    Node* n = FindNode(target);
    if (!n || n->Type() != NodeType::GATE) return false;

    GateType gt = GateUtil::FromString(new_type);
    if (gt == GateType::UNKNOWN) return false;

    n->SetGateType(gt);
    return true;
}
