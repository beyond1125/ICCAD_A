#include "graph.hpp"
#include <sstream>
#include <algorithm>
#include <fstream>
#include <cctype>

// Streaming path-enumeration resource caps (see stream_paths_recursive):
// whichever trips first stops the enumeration; the header then reports the
// exact DP total and marks the file INCOMPLETE.
static const long long STREAM_CAP_PATHS = 1000000;          // 1e6 paths
static const long long STREAM_CAP_BYTES = 512LL << 20;      // 512 MB

Graph::~Graph() {
    for (auto node : all_nodes) {
        delete node;
    }
}

Node* Graph::get_or_create_node(const std::string& name, NodeType type) {
    if (nodes.find(name) != nodes.end()) {
        if (type != NodeType::SIGNAL && nodes[name]->type == NodeType::SIGNAL) {
            nodes[name]->type = type;
        }
        return nodes[name];
    }
    Node* n = new Node(name, type);
    nodes[name] = n;
    all_nodes.push_back(n);
    return n;
}

void Graph::add_edge(Node* from, Node* to) {
    from->outputs.push_back(to);
    to->inputs.push_back(from);
    // Any structural change invalidates the cached topological order; keeping
    // a stale cache silently corrupts later depth/path computations in the
    // same process (node-removal passes clear it themselves).
    topological_order.clear();
}

void Graph::compute_topological_sort() {
    topological_order.clear();
    std::unordered_map<Node*, int> in_degree;
    for (auto n : all_nodes) in_degree[n] = 0;

    for (auto u : all_nodes) {
        if (u->type == NodeType::GATE && u->gate_type == GateType::DFF) continue; // Cut D input
        for (auto v : u->outputs) {
            in_degree[v]++;
        }
    }

    std::vector<Node*> q;
    for (auto n : all_nodes) {
        if (in_degree[n] == 0) {
            q.push_back(n);
        }
    }

    size_t head = 0;
    while (head < q.size()) {
        Node* u = q[head++];
        topological_order.push_back(u);
        for (auto v : u->outputs) {
            if (v->type == NodeType::GATE && v->gate_type == GateType::DFF) continue; // Cut at D input
            if (--in_degree[v] == 0) {
                q.push_back(v);
            }
        }
    }
}

std::unordered_map<Node*, int> Graph::compute_levels(Node* start) {
    if (topological_order.empty()) compute_topological_sort();
    
    std::unordered_map<Node*, int> level;
    for (auto n : all_nodes) level[n] = -1;

    if (start) {
        level[start] = (start->type == NodeType::GATE ? 1 : 0);
        bool found_start = false;
        for (auto u : topological_order) {
            if (u == start) { found_start = true; continue; }
            if (!found_start) continue;

            int max_in = -1;
            bool is_dff = (u->type == NodeType::GATE && u->gate_type == GateType::DFF);
            // Even if DFF output, if we are specifically tracing from a start node and 
            // the DFF is downstream, the path breaks at the DFF D-pin (which was cut in topo sort).
            // So we just process normal inputs.
            for (auto in : u->inputs) {
                // If it's a DFF, its inputs were cut in topological sort, but in the graph they still exist.
                // We must explicitly ignore paths entering a DFF when doing forward traversal, 
                // because the topo sort doesn't visit DFF downstream nodes if the edge was cut.
                // Actually, Kahn's cut was DFF -> outputs or inputs -> DFF?
                // In compute_topological_sort: `if (u->type == NodeType::GATE && u->gate_type == GateType::DFF) continue;`
                // Wait, it says: `if (v->type == NodeType::GATE && v->gate_type == GateType::DFF) continue;`
                // This means the edge from anywhere to a DFF is cut.
                
                if (u->type == NodeType::GATE && u->gate_type == GateType::DFF) {
                   // This node is a DFF. In our topo sort, DFFs are sources.
                   // It shouldn't get levels from its inputs during forward propagation 
                   // because that crosses the sequential boundary.
                   continue;
                }
                
                if (level[in] != -1) max_in = std::max(max_in, level[in]);
            }
            if (max_in != -1) {
                level[u] = max_in + (u->type == NodeType::GATE ? 1 : 0);
            }
        }
    } else {
        for (auto u : topological_order) {
            int max_in = 0;
            bool has_comb_input = false;
            if (u->type == NodeType::PRIMARY_INPUT || (u->type == NodeType::GATE && u->gate_type == GateType::DFF)) {
                max_in = 0;
                has_comb_input = true;
            } else {
                for (auto in : u->inputs) {
                    if (in->type == NodeType::GATE && in->gate_type == GateType::DFF) {
                        max_in = std::max(max_in, level[in]);
                        has_comb_input = true;
                    } else if (level[in] != -1) {
                        max_in = std::max(max_in, level[in]);
                        has_comb_input = true;
                    }
                }
            }
            if (has_comb_input) {
                level[u] = max_in + (u->type == NodeType::GATE && u->gate_type != GateType::DFF ? 1 : 0);
            }
        }
    }
    return level;
}

int Graph::calculate_depth(const std::string& start, const std::string& end) {
    if (nodes.find(end) == nodes.end()) return -1;
    Node* end_node = nodes[end];
    Node* start_node = start.empty() ? nullptr : (nodes.count(start) ? nodes[start] : nullptr);
    if (!start.empty() && !start_node) return -1;

    auto levels = compute_levels(start_node);
    return levels[end_node];
}

std::string Graph::get_critical_path(const std::string& start, const std::string& end) {
    if (nodes.find(end) == nodes.end()) return "Error: End node not found.";
    Node* end_node = nodes[end];
    Node* start_node = start.empty() ? nullptr : (nodes.count(start) ? nodes[start] : nullptr);
    
    auto levels = compute_levels(start_node);
    if (levels[end_node] == -1) return "No path found.";

    std::vector<Node*> path;
    Node* curr = end_node;
    while (curr) {
        path.push_back(curr);
        if (curr == start_node) break;
        if (!start_node && (curr->type == NodeType::PRIMARY_INPUT || (curr->type == NodeType::GATE && curr->gate_type == GateType::DFF))) break;
        
        Node* best_prev = nullptr;
        int max_l = -1;
        for (auto in : curr->inputs) {
            if (levels[in] != -1 && levels[in] > max_l) {
                max_l = levels[in];
                best_prev = in;
            }
        }
        if (!best_prev) break;
        curr = best_prev;
    }
    std::reverse(path.begin(), path.end());

    std::stringstream ss;
    ss << "Critical Path Depth: " << levels[end_node] << " gate levels\nNodes: ";
    for (size_t i = 0; i < path.size(); ++i) {
        ss << path[i]->name << (i == path.size() - 1 ? "" : " -> ");
    }
    return ss.str();
}

long long Graph::count_paths(const std::string& start, const std::string& end, const std::string& avoid) {
    if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return 0;
    Node* start_node = nodes[start];
    Node* end_node = nodes[end];
    Node* avoid_node = avoid.empty() ? nullptr : (nodes.count(avoid) ? nodes[avoid] : nullptr);

    if (topological_order.empty()) compute_topological_sort();

    // Path counts grow exponentially with depth; 64-bit with a saturating add
    // (signed overflow is UB) — a saturated result still means "astronomically
    // many", which is the honest answer at that scale.
    static const long long SAT = 4611686018427387904LL; // 2^62
    std::unordered_map<Node*, long long> path_count;
    for (auto n : all_nodes) path_count[n] = 0;
    path_count[start_node] = 1;

    bool found_start = false;
    for (auto u : topological_order) {
        if (u == start_node) { found_start = true; }
        if (!found_start) continue;
        if (u == avoid_node) { path_count[u] = 0; continue; }

        for (auto v : u->outputs) {
            if (v->type == NodeType::GATE && v->gate_type == GateType::DFF) continue;
            if (v == avoid_node) continue;
            if (path_count[v] > SAT - path_count[u]) path_count[v] = SAT;
            else path_count[v] += path_count[u];
        }
    }
    return path_count[end_node];
}

std::string Graph::find_all_paths(const std::string& start, const std::string& end, const std::string& avoid, const std::string& paths_out) {
    if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return "Error: Start or end node not found.";
    Node* start_node = nodes[start];
    Node* end_node = nodes[end];
    Node* avoid_node = avoid.empty() ? nullptr : (nodes.count(avoid) ? nodes[avoid] : nullptr);

    std::vector<std::vector<Node*>> all_paths;
    std::vector<Node*> current_path;

    // Target-reachability pruning: without it the DFS wanders exhaustively
    // through dead-end regions that can never reach the target (exponential
    // on large fanout cones). Reverse BFS from the target marks the productive
    // subgraph; the DFS then only descends into it, so total work is
    // proportional to the paths actually found (bounded by the 10000 cap).
    std::unordered_set<Node*> can_reach;
    {
        std::vector<Node*> st{end_node};
        can_reach.insert(end_node);
        while (!st.empty()) {
            Node* w = st.back(); st.pop_back();
            // Valid combinational paths never pass THROUGH a DFF gate.
            if (w != end_node && w->type == NodeType::GATE && w->gate_type == GateType::DFF)
                continue;
            for (Node* u : w->inputs) {
                if (avoid_node && u == avoid_node) continue;
                if (can_reach.insert(u).second) st.push_back(u);
            }
        }
    }

    // Streaming mode (--paths_out): every path is written to the file the
    // moment it is found — no in-memory collection, so the 10000 cap does not
    // apply and the file is a COMPLETE enumeration (A16). stdout carries the
    // exact total plus a 100-path preview; the caller knows the file path it
    // passed, so it is not echoed here.
    if (!paths_out.empty()) {
        std::ofstream out(paths_out);
        if (!out) return "Error: cannot open paths_out file for writing: " + paths_out;
        long long found = 0, bytes = 0;
        std::stringstream preview;
        stream_paths_recursive(start_node, end_node, avoid_node, current_path, can_reach, out, found, bytes, preview);
        out.close();
        if (found == 0) return "No paths found.";
        std::stringstream ss;
        ss << "Found " << found << " paths";
        // Resource guard tripped: the file stops at the cap. Report the DP
        // total so the caller still gets the exact count and can flag the
        // file as incomplete instead of claiming a full enumeration.
        if (found >= STREAM_CAP_PATHS || bytes >= STREAM_CAP_BYTES) {
            long long exact = count_paths(start, end, avoid);
            if (exact != found)
                ss << " (enumeration capped for resource safety; the output file is INCOMPLETE; exact total by DP: " << exact << ")";
        }
        ss << ":\n" << preview.str();
        if (found > 100) ss << "... (preview truncated; the full enumeration is in the output file)\n";
        return ss.str();
    }

    find_all_paths_recursive(start_node, end_node, avoid_node, current_path, all_paths, can_reach);

    if (all_paths.empty()) return "No paths found.";

    std::stringstream ss;
    ss << "Found " << all_paths.size() << " paths";
    if (all_paths.size() >= 10000) {
        ss << " (enumeration capped at 10000; exact total by DP: "
           << count_paths(start, end, avoid) << ")";
    }
    ss << ":\n";
    for (size_t i = 0; i < all_paths.size(); ++i) {
        ss << "Path " << i + 1 << ": ";
        for (size_t j = 0; j < all_paths[i].size(); ++j) {
            ss << all_paths[i][j]->name << (j == all_paths[i].size() - 1 ? "" : " -> ");
        }
        ss << "\n";
        if (i >= 100) { ss << "... (truncated)\n"; break; }
    }
    return ss.str();
}

int Graph::count_fanin_gates(const std::string& name, bool stop_at_dff) {
    if (nodes.find(name) == nodes.end()) return 0;
    std::unordered_set<Node*> visited;
    return count_fanin_gates_recursive(nodes[name], visited, stop_at_dff);
}

int Graph::count_fanout_gates(const std::string& name, bool stop_at_dff) {
    if (nodes.find(name) == nodes.end()) return 0;
    std::unordered_set<Node*> visited;
    int total = count_fanout_gates_recursive(nodes[name], visited, stop_at_dff);
    if (nodes[name]->type == NodeType::GATE) total--;
    return total;
}

std::string Graph::get_fanin_cone(const std::string& name, bool stop_at_dff) {
    if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
    std::unordered_set<Node*> visited;
    get_cone_recursive(nodes[name], visited, true, stop_at_dff);
    std::vector<Node*> gates;
    for (auto n : visited) {
        if (n->type == NodeType::GATE) gates.push_back(n);
    }
    std::stringstream ss;
    if (stop_at_dff)
        ss << "Combinational fanin cone of " << name << " contains " << gates.size()
           << " gates (DFF Q treated as primary input; a boundary DFF is included but not traversed):\n";
    else
        ss << "Transitive Fanin Cone of " << name << " (through DFFs) contains " << gates.size() << " gates:\n";
    for (auto n : gates) ss << n->name << " ";
    return ss.str();
}

std::string Graph::get_fanout_cone(const std::string& name, bool stop_at_dff) {
    if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
    std::unordered_set<Node*> visited;
    get_cone_recursive(nodes[name], visited, false, stop_at_dff);
    std::vector<Node*> gates;
    for (auto n : visited) {
        if (n->type == NodeType::GATE) gates.push_back(n);
    }
    std::stringstream ss;
    if (stop_at_dff)
        ss << "Combinational fanout cone of " << name << " contains " << gates.size()
           << " gates (a consuming DFF is included as the boundary but its Q side is not traversed):\n";
    else
        ss << "Transitive Fanout Cone of " << name << " (through DFFs) contains " << gates.size() << " gates:\n";
    for (auto n : gates) ss << n->name << " ";
    return ss.str();
}

int Graph::get_fanin_depth(const std::string& name) {
    if (nodes.find(name) == nodes.end()) return -1;
    auto levels = compute_levels();
    return levels[nodes[name]];
}

std::string Graph::get_node_info(const std::string& name) {
    if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
    Node* n = nodes[name];
    std::stringstream ss;
    if (n->type == NodeType::GATE) {
        ss << "Gate " << n->name << " [Type: " << gate_type_to_string(n->gate_type) << "]";
    } else {
        ss << "Signal " << n->name << " [" << (n->type == NodeType::PRIMARY_INPUT ? "PI" : n->type == NodeType::PRIMARY_OUTPUT ? "PO" : "Wire") << "]";
    }
    
    std::unordered_set<Node*> driving_gates;
    std::unordered_set<Node*> driven_gates;
    
    for (auto in : n->inputs) {
        if (in->type == NodeType::GATE) driving_gates.insert(in);
        else {
            for (auto gin : in->inputs) if (gin->type == NodeType::GATE) driving_gates.insert(gin);
        }
    }
    for (auto out : n->outputs) {
        if (out->type == NodeType::GATE) driven_gates.insert(out);
        else {
            for (auto gout : out->outputs) if (gout->type == NodeType::GATE) driven_gates.insert(gout);
        }
    }

    // Fanout count must equal the number of consumer GATES this node directly
    // drives (driven_gates.size()), not n->outputs.size(): for a gate node,
    // n->outputs is edges to its own output net/signal node — typically a
    // single edge even when that net fans out to many consumer gates — so
    // n->outputs.size() previously undercounted fanout (e.g. printing 1 while
    // 2 successor gates were listed right below it). Fanin count is left as
    // n->inputs.size() (input-pin count), which is not subject to the same
    // net-vs-gate aliasing and already matches driving_gates.size() in the
    // normal single-driver-per-net case.
    ss << "\n  Fanin count: " << n->inputs.size() << "\n  Fanout count: " << driven_gates.size();
    ss << "\n  Input drivers (fanin): ";
    for (auto g : driving_gates) ss << g->name << " ";
    ss << "\n  Driven gates (immediate successors / direct fanout): ";
    for (auto g : driven_gates) ss << g->name << " ";
    return ss.str();
}

bool Graph::replace_gate(const std::string& target, const std::string& new_type) {
    if (nodes.find(target) == nodes.end() || nodes[target]->type != NodeType::GATE) return false;
    GateType gt = string_to_gate_type(new_type);
    if (gt == GateType::UNKNOWN) return false;
    nodes[target]->gate_type = gt;
    return true;
}

bool Graph::rename_node(const std::string& old_name, const std::string& new_name) {
    if (old_name == new_name) return true;
    if (!nodes.count(old_name) || nodes.count(new_name)) return false;
    Node* n = nodes[old_name];
    nodes.erase(old_name);
    n->name = new_name;
    nodes[new_name] = n;
    for (Node* m : all_nodes)
        for (PinConn& pc : m->pin_conns)
            if (pc.signal == old_name) pc.signal = new_name;
    return true;
}

void Graph::load_logic_blif(const std::string& file) {
    std::ifstream ifs(file);
    if (!ifs.is_open()) return;
    int ctr = 0;
    std::unordered_map<Node*, Node*> inv_cache;
    Node* first_pi = nullptr;
    for (Node* n : all_nodes) if (n->type == NodeType::PRIMARY_INPUT) { first_pi = n; break; }
    auto mkgate = [&](GateType gt, std::vector<Node*> ins, const std::string& outnm) {
        Node* g = get_or_create_node("__bg" + std::to_string(ctr++), NodeType::GATE);
        g->gate_type = gt;
        Node* o = get_or_create_node(outnm);
        add_edge(g, o);
        for (Node* x : ins) add_edge(x, g);
    };
    auto inv = [&](Node* x) -> Node* {
        auto it = inv_cache.find(x);
        if (it != inv_cache.end()) return it->second;
        Node* g = get_or_create_node("__bg" + std::to_string(ctr++), NodeType::GATE);
        g->gate_type = GateType::NOT;
        Node* o = get_or_create_node("__bn" + std::to_string(ctr++));
        add_edge(x, g); add_edge(g, o);
        inv_cache[x] = o;
        return o;
    };
    auto drive_const = [&](int val, const std::string& outnm) {
        if (first_pi) mkgate(val ? GateType::OR : GateType::AND, {first_pi, inv(first_pi)}, outnm);
    };
    std::vector<std::string> toks; std::vector<std::string> rows;
    auto flush = [&]() {
        if (toks.empty()) return;
        std::string outnm = toks.back();
        int nin = (int)toks.size() - 1;
        if (nin > 2) {
            // Only <=2-input .names are representable as native primitives.
            // Falling through would build WRONG logic (first two inputs + an
            // out-of-range mask) after an O(2^nin) truth-table expansion;
            // count it and let the caller fail loudly.
            blif_unsupported++;
            log_error("Error: BLIF import: unsupported .names with " +
                      std::to_string(nin) + " inputs (output '" + outnm + "')");
            toks.clear(); rows.clear();
            return;
        }
        int N = 1 << nin;
        int rowval = rows.empty() ? 1 : (rows[0].back() == '1' ? 1 : 0);
        std::vector<int> tt(N, rows.empty() ? 0 : (1 - rowval));
        for (const std::string& r : rows) {
            std::string pat, ov; std::istringstream rs(r); rs >> pat >> ov;
            int v = (!ov.empty() && ov[0] == '1') ? 1 : (nin == 0 ? (pat == "1") : 0);
            if (nin == 0) { tt[0] = (pat == "1") ? 1 : v; continue; }
            for (int m = 0; m < N; ++m) {
                bool match = true;
                for (int b = 0; b < nin; ++b) {
                    if (b >= (int)pat.size()) { match = false; break; }
                    if (pat[b] == '-') continue;
                    if ((pat[b] == '1') != (((m >> b) & 1) == 1)) { match = false; break; }
                }
                if (match) tt[m] = v;
            }
        }
        int mask = 0;
        for (int m = 0; m < N; ++m) if (tt[m]) mask |= (1 << m);
        if (nin == 0) drive_const(mask & 1, outnm);
        else if (nin == 1) {
            Node* a = get_or_create_node(toks[0]);
            switch (mask) {
                case 0: drive_const(0, outnm); break;
                case 1: mkgate(GateType::NOT, {a}, outnm); break;
                case 2: mkgate(GateType::BUF, {a}, outnm); break;
                default: drive_const(1, outnm); break;
            }
        } else {
            Node* a = get_or_create_node(toks[0]); Node* b = get_or_create_node(toks[1]);
            switch (mask) {
                case 0x0: drive_const(0, outnm); break;
                case 0x1: mkgate(GateType::NOR, {a, b}, outnm); break;
                case 0x2: mkgate(GateType::AND, {a, inv(b)}, outnm); break;
                case 0x3: mkgate(GateType::NOT, {b}, outnm); break;
                case 0x4: mkgate(GateType::AND, {inv(a), b}, outnm); break;
                case 0x5: mkgate(GateType::NOT, {a}, outnm); break;
                case 0x6: mkgate(GateType::XOR, {a, b}, outnm); break;
                case 0x7: mkgate(GateType::NAND, {a, b}, outnm); break;
                case 0x8: mkgate(GateType::AND, {a, b}, outnm); break;
                case 0x9: mkgate(GateType::XNOR, {a, b}, outnm); break;
                case 0xA: mkgate(GateType::BUF, {a}, outnm); break;
                case 0xB: mkgate(GateType::OR, {a, inv(b)}, outnm); break;
                case 0xC: mkgate(GateType::BUF, {b}, outnm); break;
                case 0xD: mkgate(GateType::OR, {inv(a), b}, outnm); break;
                case 0xE: mkgate(GateType::OR, {a, b}, outnm); break;
                default: drive_const(1, outnm); break;
            }
        }
        toks.clear(); rows.clear();
    };
    std::string line;
    while (std::getline(ifs, line)) {
        if (!line.empty() && line.back() == '\\') {
            line.pop_back(); std::string cont;
            while (std::getline(ifs, cont)) {
                bool more = !cont.empty() && cont.back() == '\\';
                if (more) cont.pop_back();
                line += cont; if (!more) break;
            }
        }
        size_t s = line.find_first_not_of(" \t");
        if (s == std::string::npos || line[s] == '#') continue;
        if (line[s] == '.') {
            flush();
            if (line.compare(s, 6, ".names") == 0) {
                std::istringstream ss(line.substr(s)); std::string kw, t; ss >> kw;
                while (ss >> t) toks.push_back(t);
            }
        } else rows.push_back(line.substr(s));
    }
    flush();
}

void Graph::write_blif(const std::string& filename) {
    std::ofstream ofs(filename);
    bool need_c0 = false, need_c1 = false;
    auto sig = [&](const std::string& n) -> std::string {
        if (n == "1'b0" || n == "0") { need_c0 = true; return "__const0"; }
        if (n == "1'b1" || n == "1") { need_c1 = true; return "__const1"; }
        return n;
    };
    std::vector<Node*> pis, pos, dffs, comb;
    for (Node* n : all_nodes) {
        if (n->type == NodeType::PRIMARY_INPUT) pis.push_back(n);
        else if (n->type == NodeType::PRIMARY_OUTPUT) pos.push_back(n);
        else if (n->type == NodeType::GATE) {
            if (n->gate_type == GateType::DFF) dffs.push_back(n);
            else comb.push_back(n);
        }
    }
    // DFF Q nets become primary inputs in the flop-cut model. A registered primary
    // output (a PO net that is also a DFF Q) would then be both a .input and a .output,
    // which BLIF cannot express. Such an output is just the flop's free Q (trivially
    // equal between designs), so it is omitted from .outputs; the real next-state check
    // is its __D_<inst> tap.
    std::unordered_set<std::string> q_nets;
    for (Node* d : dffs) if (!d->outputs.empty()) q_nets.insert(d->outputs[0]->name);

    // Emit each input net once. A net can repeat if multiple flip-flops drive the
    // same Q (some netlists wire two DFFs to one net); in the cut it is a single
    // free primary input, while each flop still gets its own __D_<inst> tap.
    std::unordered_set<std::string> emitted_in;
    ofs << ".model top\n.inputs";
    for (Node* p : pis) if (emitted_in.insert(p->name).second) ofs << " " << p->name;
    for (Node* d : dffs)
        if (!d->outputs.empty() && emitted_in.insert(d->outputs[0]->name).second)
            ofs << " " << d->outputs[0]->name;
    ofs << "\n.outputs";
    for (Node* p : pos) if (!q_nets.count(p->name)) ofs << " " << p->name;
    for (Node* d : dffs) ofs << " __D_" << d->name;
    ofs << "\n";
    for (Node* g : comb) {
        if (g->outputs.empty()) continue;
        std::string y = g->outputs[0]->name;
        std::vector<std::string> in; for (Node* i : g->inputs) in.push_back(sig(i->name));
        size_t k = in.size(); ofs << ".names";
        for (auto& s : in) ofs << " " << s;
        ofs << " " << y << "\n";
        switch (g->gate_type) {
            case GateType::BUF: ofs << "1 1\n"; break;
            case GateType::NOT: ofs << "0 1\n"; break;
            case GateType::AND: ofs << std::string(k, '1') << " 1\n"; break;
            case GateType::NOR: ofs << std::string(k, '0') << " 1\n"; break;
            case GateType::OR: for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '1'; ofs << c << " 1\n"; } break;
            case GateType::NAND: for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '0'; ofs << c << " 1\n"; } break;
            case GateType::XOR: case GateType::XNOR: {
                bool want_odd = (g->gate_type == GateType::XOR);
                for (size_t m = 0; m < (1u << k); ++m) {
                    int par = 0; std::string c(k, '0');
                    for (size_t b = 0; b < k; ++b) if (m & (1u << b)) { c[b] = '1'; par ^= 1; }
                    if ((par == 1) == want_odd) ofs << c << " 1\n";
                }
                break;
            }
            default: break;
        }
    }
    for (Node* d : dffs) {
        std::string dn = d->inputs.empty() ? "__const0" : sig(d->inputs[0]->name);
        std::string tap = "__D_" + d->name;
        if (dn != tap) ofs << ".names " << dn << " " << tap << "\n1 1\n";
    }
    if (need_c0) ofs << ".names __const0\n";
    if (need_c1) ofs << ".names __const1\n1\n";
    ofs << ".end\n";
}

// Insert a dedicated BUF gate for every load of `signal`: each consumer pin that
// read the signal now reads its own buffer of it (signal -> buf_i -> load_i).
// Functionally transparent. Returns the number of buffers added.
int Graph::insert_dedicated_buffers(const std::string& signal) {
    if (!nodes.count(signal)) return 0;
    Node* s = nodes[signal];
    std::vector<std::pair<Node*, int>> loads;
    std::unordered_map<Node*, bool> seen;
    for (Node* c : s->outputs) {
        if (seen[c]) continue;
        seen[c] = true;
        for (int i = 0; i < (int)c->inputs.size(); ++i)
            if (c->inputs[i] == s) loads.push_back({c, i});
    }
    s->outputs.clear();                          // rebuilt to drive the new buffers
    int ctr = 0, count = 0;
    auto fresh = [&](const std::string& p) { std::string nm; do { nm = p + std::to_string(ctr++); } while (nodes.count(nm)); return nm; };
    for (auto& load : loads) {
        Node* buf = get_or_create_node(fresh("__db_g"), NodeType::GATE); buf->gate_type = GateType::BUF;
        Node* w = get_or_create_node(fresh("__db_n"));
        add_edge(s, buf); add_edge(buf, w);
        load.first->inputs[load.second] = w; w->outputs.push_back(load.first);
        ++count;
    }
    return count;
}

int Graph::insert_buffers(int max_fanout) {
    if (max_fanout < 2) return 0;
    int buf_count = 0, name_ctr = 0;
    auto fresh = [&](const std::string& pfx) {
        std::string nm; do { nm = pfx + std::to_string(name_ctr++); } while (nodes.count(nm)); return nm;
    };
    std::vector<Node*> gate_snapshot;
    for (Node* n : all_nodes) if (n->type == NodeType::GATE) gate_snapshot.push_back(n);
    struct Sink { Node* consumer; int pin; bool is_buffer; };
    for (Node* g : gate_snapshot) {
        if (g->outputs.empty()) continue;
        Node* s = g->outputs[0]; if ((int)s->outputs.size() <= max_fanout) continue;
        std::vector<Sink> pending; std::unordered_map<Node*, bool> seen;
        for (Node* c : s->outputs) {
            if (seen[c]) continue;
            seen[c] = true;
            for (int i = 0; i < (int)c->inputs.size(); ++i) if (c->inputs[i] == s) pending.push_back({c, i, false});
        }
        s->outputs.clear();
        auto assign = [&](const Sink& sk, Node* src) {
            if (sk.is_buffer) sk.consumer->inputs.assign(1, src);
            else sk.consumer->inputs[sk.pin] = src;
            src->outputs.push_back(sk.consumer);
        };
        while ((int)pending.size() > max_fanout) {
            std::vector<Sink> next;
            for (size_t i = 0; i < pending.size(); i += max_fanout) {
                size_t end = std::min(i + (size_t)max_fanout, pending.size());
                if (end - i == 1) { next.push_back(pending[i]); continue; }
                Node* buf = get_or_create_node(fresh("buf_fo_"), NodeType::GATE); buf->gate_type = GateType::BUF;
                Node* w = get_or_create_node(fresh("nbuf_"), NodeType::SIGNAL); add_edge(buf, w); buf_count++;
                for (size_t j = i; j < end; ++j) assign(pending[j], w);
                next.push_back({buf, -1, true});
            }
            pending.swap(next);
        }
        for (auto& sk : pending) assign(sk, s);
    }
    return buf_count;
}

// Buffer ONE named signal (a wire or even a primary input such as a clock/reset)
// into a balanced tree so no driver of it exceeds max_fanout loads. Returns buffers added.
int Graph::insert_buffers_on_signal(const std::string& signal, int max_fanout) {
    if (max_fanout < 2 || !nodes.count(signal)) return 0;
    Node* s = nodes[signal];
    int buf_count = 0, name_ctr = 0;
    auto fresh = [&](const std::string& pfx) { std::string nm; do { nm = pfx + std::to_string(name_ctr++); } while (nodes.count(nm)); return nm; };
    // kind 0 = gate input edge (consumer,pin); 1 = DFF control pin (consumer=DFF,
    // pin = pin_conns index; clock/reset/set drive these by name, not by edge);
    // 2 = a buffer's single input.
    struct Sink { Node* consumer; int pin; int kind; };
    std::vector<Sink> pending; std::unordered_map<Node*, bool> seen;
    for (Node* c : s->outputs) {
        if (seen[c]) continue;
        seen[c] = true;
        for (int i = 0; i < (int)c->inputs.size(); ++i) if (c->inputs[i] == s) pending.push_back({c, i, 0});
    }
    for (Node* n : all_nodes)
        if (n->type == NodeType::GATE && n->gate_type == GateType::DFF)
            for (int i = 0; i < (int)n->pin_conns.size(); ++i) {
                const PinConn& pc = n->pin_conns[i];
                if (!pc.is_const && pc.edge_dir == 0 && pc.signal == signal) pending.push_back({n, i, 1});
            }
    if ((int)pending.size() <= max_fanout) return 0;
    s->outputs.clear();
    auto assign = [&](const Sink& sk, Node* src) {
        if (sk.kind == 1) sk.consumer->pin_conns[sk.pin].signal = src->name;   // control pin
        else { if (sk.kind == 2) sk.consumer->inputs.assign(1, src);
               else sk.consumer->inputs[sk.pin] = src;
               src->outputs.push_back(sk.consumer); }
    };
    while ((int)pending.size() > max_fanout) {
        std::vector<Sink> next;
        for (size_t i = 0; i < pending.size(); i += max_fanout) {
            size_t end = std::min(i + (size_t)max_fanout, pending.size());
            if (end - i == 1) { next.push_back(pending[i]); continue; }
            Node* buf = get_or_create_node(fresh("buf_fo_"), NodeType::GATE); buf->gate_type = GateType::BUF;
            Node* w = get_or_create_node(fresh("nbuf_"), NodeType::SIGNAL); add_edge(buf, w); buf_count++;
            for (size_t j = i; j < end; ++j) assign(pending[j], w);
            next.push_back({buf, -1, 2});
        }
        pending.swap(next);
    }
    for (auto& sk : pending) assign(sk, s);
    return buf_count;
}

// Reconnect one input pin of a gate to a different signal. Pin may be a letter
// (A=input 0, B=1, …) or an index. This can change functionality, so the caller
// must verify equivalence afterward. Returns false if the gate/pin is invalid.
bool Graph::reconnect_pin(const std::string& gate, const std::string& pin, const std::string& signal) {
    if (!nodes.count(gate)) return false;
    Node* g = nodes[gate];
    if (g->type != NodeType::GATE) return false;
    int idx = -1;
    if (pin.size() == 1 && std::isalpha((unsigned char)pin[0])) idx = std::toupper((unsigned char)pin[0]) - 'A';
    else { try { idx = std::stoi(pin); } catch (...) { idx = -1; } }
    if (idx < 0 || idx >= (int)g->inputs.size()) return false;
    Node* newsig = get_or_create_node(signal, NodeType::SIGNAL);
    Node* old = g->inputs[idx];
    if (old == newsig) return true;
    auto it = std::find(old->outputs.begin(), old->outputs.end(), g);
    if (it != old->outputs.end()) old->outputs.erase(it);
    g->inputs[idx] = newsig;
    newsig->outputs.push_back(g);
    return true;
}

int Graph::sweep_dangling() {
    topological_order.clear();  // node removal invalidates the cached topo order
    std::unordered_set<Node*> live; std::vector<Node*> stack;
    for (Node* n : all_nodes) {
        bool seed = n->type == NodeType::PRIMARY_OUTPUT || (n->type == NodeType::GATE && n->gate_type == GateType::DFF);
        if (seed && live.insert(n).second) stack.push_back(n);
    }
    while (!stack.empty()) {
        Node* n = stack.back(); stack.pop_back();
        for (Node* drv : n->inputs) if (live.insert(drv).second) stack.push_back(drv);
    }
    auto keep = [&](Node* n) { return n->type == NodeType::PRIMARY_INPUT || n->type == NodeType::PRIMARY_OUTPUT || live.count(n) > 0; };
    std::vector<Node*> newall, dead;
    for (Node* n : all_nodes) (keep(n) ? newall : dead).push_back(n);
    for (Node* n : newall) {
        std::vector<Node*> o, in;
        for (Node* x : n->outputs) if (keep(x)) o.push_back(x);
        for (Node* x : n->inputs) if (keep(x)) in.push_back(x);
        n->outputs.swap(o); n->inputs.swap(in);
    }
    int removed = 0;
    for (Node* n : dead) { if (n->type == NodeType::GATE) ++removed; nodes.erase(n->name); delete n; }
    all_nodes.swap(newall); return removed;
}

std::unordered_set<Node*> Graph::fanin_cone_gates(const std::string& root) {
    std::unordered_set<Node*> cone, vis; if (!nodes.count(root)) return cone;
    std::vector<Node*> st{nodes[root]};
    while (!st.empty()) {
        Node* n = st.back(); st.pop_back();
        if (!vis.insert(n).second) continue;
        if (n->type == NodeType::GATE) cone.insert(n);
        for (Node* d : n->inputs) st.push_back(d);
    }
    return cone;
}

int Graph::decompose_in_cone(const std::string& root, const std::string& from_type, const std::string& basis) {
    std::vector<Node*> cone;                               // scope: whole design if root empty
    if (root.empty()) {
        for (Node* n : all_nodes)
            if (n->type == NodeType::GATE && n->gate_type != GateType::DFF) cone.push_back(n);
    } else {
        auto c = fanin_cone_gates(root); cone.assign(c.begin(), c.end());
    }
    int ctr = 0;
    auto fresh = [&](const std::string& pfx) {
        std::string nm; do { nm = pfx + std::to_string(ctr++); } while (nodes.count(nm)); return nm;
    };
    auto rm = [&](std::vector<Node*>& v, Node* x) { v.erase(std::remove(v.begin(), v.end(), x), v.end()); };
    auto mk = [&](GateType t, std::vector<Node*> ins) -> Node* {
        Node* g = get_or_create_node(fresh("__dec_g"), NodeType::GATE); g->gate_type = t;
        Node* o = get_or_create_node(fresh("__dec_n"));
        for (Node* x : ins) add_edge(x, g);
        add_edge(g, o); return o;
    };

    if (from_type == "or" && basis == "nand_not") {        // OR(a,b) = NAND(!a,!b)
        std::vector<Node*> targets;
        for (Node* g : cone) if (g->gate_type == GateType::OR && g->inputs.size() == 2) targets.push_back(g);
        for (Node* g : targets) {
            Node* a = g->inputs[0]; Node* b = g->inputs[1]; rm(a->outputs, g); rm(b->outputs, g);
            Node* t1 = mk(GateType::NOT, {a}); Node* t2 = mk(GateType::NOT, {b});
            g->inputs.clear(); add_edge(t1, g); add_edge(t2, g); g->gate_type = GateType::NAND;
        }
        return (int)targets.size();
    }
    if (from_type == "xor" && basis == "and_or_not") {     // XOR(a,b) = OR(a&!b, !a&b)
        std::vector<Node*> targets;
        for (Node* g : cone) if (g->gate_type == GateType::XOR && g->inputs.size() == 2) targets.push_back(g);
        for (Node* g : targets) {
            Node* a = g->inputs[0]; Node* b = g->inputs[1]; rm(a->outputs, g); rm(b->outputs, g);
            Node* na = mk(GateType::NOT, {a}); Node* nb = mk(GateType::NOT, {b});
            Node* t1 = mk(GateType::AND, {a, nb}); Node* t2 = mk(GateType::AND, {na, b});
            g->inputs.clear(); add_edge(t1, g); add_edge(t2, g); g->gate_type = GateType::OR;
        }
        return (int)targets.size();
    }
    if (from_type == "xor" && basis == "nand") {           // 4-NAND XOR
        std::vector<Node*> targets;
        for (Node* g : cone) if (g->gate_type == GateType::XOR && g->inputs.size() == 2) targets.push_back(g);
        for (Node* g : targets) {
            Node* a = g->inputs[0]; Node* b = g->inputs[1]; rm(a->outputs, g); rm(b->outputs, g);
            Node* n1 = mk(GateType::NAND, {a, b});
            Node* n2 = mk(GateType::NAND, {a, n1}); Node* n3 = mk(GateType::NAND, {b, n1});
            g->inputs.clear(); add_edge(n2, g); add_edge(n3, g); g->gate_type = GateType::NAND;
        }
        return (int)targets.size();
    }
    if (from_type == "xnor" && basis == "nor") {           // 4-NOR XNOR (NOR-only)
        std::vector<Node*> targets;
        for (Node* g : cone) if (g->gate_type == GateType::XNOR && g->inputs.size() == 2) targets.push_back(g);
        for (Node* g : targets) {
            Node* a = g->inputs[0]; Node* b = g->inputs[1]; rm(a->outputs, g); rm(b->outputs, g);
            Node* n1 = mk(GateType::NOR, {a, b});
            Node* n2 = mk(GateType::NOR, {a, n1}); Node* n3 = mk(GateType::NOR, {b, n1});
            g->inputs.clear(); add_edge(n2, g); add_edge(n3, g); g->gate_type = GateType::NOR;
        }
        return (int)targets.size();
    }
    return -1;
}

// Report primary outputs whose combinational logic depth exceeds max_depth, using a
// single levelization pass (DFF outputs are level 0). Returns a count and a sample.
std::string Graph::outputs_over_depth(int max_depth) {
    auto levels = compute_levels(nullptr);
    std::vector<std::pair<std::string, int>> over;
    for (Node* n : all_nodes)
        if (n->type == NodeType::PRIMARY_OUTPUT) {
            int d = levels.count(n) ? levels[n] : -1;
            if (d > max_depth) over.push_back({n->name, d});
        }
    std::ostringstream ss;
    ss << over.size() << " output(s) have logic depth greater than " << max_depth << ".";
    int shown = 0;
    for (auto& p : over) {
        if (shown++ >= 20) { ss << " ..."; break; }
        ss << " " << p.first << "(" << p.second << ")";
    }
    return ss.str();
}

// List every gate of a given type with its input and output signals.
std::string Graph::list_gates_by_type(const std::string& type_str) {
    GateType t = string_to_gate_type(type_str);
    std::ostringstream ss;
    ss << "{\n  \"gate_type\": \"" << type_str << "\",\n  \"gates\": [";
    bool first = true; int count = 0;
    for (Node* n : all_nodes) {
        if (n->type != NodeType::GATE || n->gate_type != t) continue;
        ++count; ss << (first ? "\n    " : ",\n    "); first = false;
        ss << "{\"name\": \"" << n->name << "\", \"inputs\": [";
        for (size_t i = 0; i < n->inputs.size(); ++i) ss << (i ? "," : "") << "\"" << n->inputs[i]->name << "\"";
        ss << "], \"output\": \"" << (n->outputs.empty() ? "" : n->outputs[0]->name) << "\"}";
    }
    ss << "\n  ],\n  \"count\": " << count << "\n}";
    return ss.str();
}

// List flip-flops whose clock pin is driven by the given clock signal.
std::string Graph::flipflops_by_clock(const std::string& clock) {
    std::ostringstream ss;
    ss << "{\n  \"clock\": \"" << clock << "\",\n  \"flip_flops\": [";
    bool first = true; int count = 0;
    for (Node* n : all_nodes) {
        if (n->type != NodeType::GATE || n->gate_type != GateType::DFF) continue;
        for (const PinConn& pc : n->pin_conns)
            if ((pc.pin == "CK" || pc.pin == "CLK") && pc.signal == clock) {
                ++count; ss << (first ? "\n    " : ",\n    "); first = false;
                ss << "{\"name\": \"" << n->name << "\", \"Q\": \"" << (n->outputs.empty() ? "" : n->outputs[0]->name) << "\"}";
                break;
            }
    }
    ss << "\n  ],\n  \"count\": " << count << "\n}";
    return ss.str();
}

// Maximum combinational logic depth from any primary input to any flip-flop D pin.
std::string Graph::max_pi_to_dff_depth() {
    auto levels = compute_levels(nullptr);
    int maxd = -1; std::string which, dnet;
    for (Node* n : all_nodes) {
        if (n->type != NodeType::GATE || n->gate_type != GateType::DFF || n->inputs.empty()) continue;
        Node* d = n->inputs[0];
        int dep = levels.count(d) ? levels[d] : -1;
        if (dep > maxd) { maxd = dep; which = n->name; dnet = d->name; }
    }
    std::ostringstream ss;
    ss << "{\"max_pi_to_dff_d_depth\": " << maxd << ", \"dff\": \"" << which
       << "\", \"d_net\": \"" << dnet << "\"}";
    return ss.str();
}

// Report floating signals: primary inputs that drive nothing, primary outputs with no
// driver, and internal signals that are read but never driven.
std::string Graph::list_floating() {
    // Signals used through DFF control pins (clock/reset/set) are referenced by name
    // in pin_conns, not by graph edges; treat those as connected.
    std::unordered_set<std::string> ctrl_used;
    for (Node* n : all_nodes)
        if (n->type == NodeType::GATE && n->gate_type == GateType::DFF)
            for (const PinConn& pc : n->pin_conns)
                if (!pc.is_const && pc.edge_dir == 0) ctrl_used.insert(pc.signal);

    std::vector<std::string> fin, fout, undriven;
    for (Node* n : all_nodes) {
        if (n->type == NodeType::PRIMARY_INPUT && n->outputs.empty() && !ctrl_used.count(n->name)) fin.push_back(n->name);
        else if (n->type == NodeType::PRIMARY_OUTPUT && n->inputs.empty()) fout.push_back(n->name);
        else if (n->type == NodeType::SIGNAL && n->inputs.empty() && !n->outputs.empty() && !ctrl_used.count(n->name)) undriven.push_back(n->name);
    }
    auto arr = [](std::ostringstream& s, const std::vector<std::string>& v) {
        s << "["; for (size_t i = 0; i < v.size(); ++i) s << (i ? "," : "") << "\"" << v[i] << "\""; s << "]";
    };
    std::ostringstream ss;
    ss << "{\n  \"floating_inputs\": "; arr(ss, fin);
    ss << ",\n  \"unconnected_outputs\": "; arr(ss, fout);
    ss << ",\n  \"undriven_signals\": "; arr(ss, undriven);
    ss << ",\n  \"count\": " << (fin.size() + fout.size() + undriven.size()) << "\n}";
    return ss.str();
}

// Does `target` depend on `source` (is source in target's transitive fanin)?
std::string Graph::signal_depends_on(const std::string& target, const std::string& source) {
    bool dep = false;
    if (nodes.count(target) && nodes.count(source)) {
        Node* src = nodes[source];
        std::unordered_set<Node*> vis; std::vector<Node*> st{nodes[target]};
        while (!st.empty()) {
            Node* n = st.back(); st.pop_back();
            if (!vis.insert(n).second) continue;
            if (n == src) { dep = true; break; }
            for (Node* d : n->inputs) st.push_back(d);
        }
    }
    std::ostringstream ss;
    ss << "{\"target\": \"" << target << "\", \"source\": \"" << source
       << "\", \"depends\": " << (dep ? "true" : "false") << "}";
    return ss.str();
}

// Primary input with the highest fanout (edge loads + DFF control-pin references).
std::string Graph::highest_fanout_pi() {
    std::unordered_map<std::string, int> ctrl;
    for (Node* n : all_nodes)
        if (n->type == NodeType::GATE && n->gate_type == GateType::DFF)
            for (const PinConn& pc : n->pin_conns)
                if (!pc.is_const && pc.edge_dir == 0) ctrl[pc.signal]++;
    std::string best; int bestf = -1;
    for (Node* n : all_nodes)
        if (n->type == NodeType::PRIMARY_INPUT) {
            int f = (int)n->outputs.size() + ctrl[n->name];
            if (f > bestf) { bestf = f; best = n->name; }
        }
    std::ostringstream ss;
    ss << "{\"primary_input\": \"" << best << "\", \"fanout\": " << bestf << "}";
    return ss.str();
}

// Merge structurally-equivalent gates: two non-DFF gates with the same type and the
// same input nets compute the same function, so one is removed and its consumers are
// rewired to the survivor. Iterates to a fixpoint (merging an input can expose new
// duplicates). Flip-flops are never merged, so the flop boundary (and flop-cut
// equivalence) is preserved. Returns the number of gates merged away.
int Graph::merge_duplicate_gates() {
    topological_order.clear();  // node removal invalidates the cached topo order
    int merged = 0; bool changed = true;
    auto rm = [&](std::vector<Node*>& v, Node* x) { v.erase(std::remove(v.begin(), v.end(), x), v.end()); };
    while (changed) {
        changed = false;
        std::unordered_map<std::string, Node*> seen;   // signature -> survivor gate
        std::unordered_set<Node*> dead;
        std::vector<Node*> snap;
        for (Node* n : all_nodes)
            if (n->type == NodeType::GATE && n->gate_type != GateType::DFF) snap.push_back(n);
        for (Node* g : snap) {
            if (dead.count(g) || g->outputs.empty()) continue;
            std::vector<std::string> ins;
            for (Node* i : g->inputs) ins.push_back(i->name);
            std::sort(ins.begin(), ins.end());          // commutative: order-independent
            std::string sig = std::to_string((int)g->gate_type);
            for (auto& s : ins) sig += "|" + s;

            auto it = seen.find(sig);
            if (it == seen.end()) { seen[sig] = g; continue; }
            Node* canon = it->second;
            Node* o_dup = g->outputs[0]; Node* o_canon = canon->outputs[0];
            if (o_dup->type == NodeType::PRIMARY_OUTPUT || o_dup == o_canon) continue;
            for (Node* c : std::vector<Node*>(o_dup->outputs)) {
                for (Node*& in : c->inputs) if (in == o_dup) in = o_canon;
                o_canon->outputs.push_back(c);
            }
            o_dup->outputs.clear();
            for (Node* i : g->inputs) rm(i->outputs, g);
            dead.insert(g); dead.insert(o_dup);
            ++merged; changed = true;
        }
        if (!dead.empty()) {
            std::vector<Node*> keep, drop;
            for (Node* n : all_nodes) (dead.count(n) ? drop : keep).push_back(n);
            for (Node* n : keep) {
                std::vector<Node*> in, out;
                for (Node* x : n->inputs)  if (!dead.count(x)) in.push_back(x);
                for (Node* x : n->outputs) if (!dead.count(x)) out.push_back(x);
                n->inputs.swap(in); n->outputs.swap(out);
            }
            for (Node* n : drop) nodes.erase(n->name);
            all_nodes.swap(keep);
            for (Node* n : drop) delete n;
        }
    }
    return merged;
}

// Detect and simplify gates with constant inputs (1'b0, 1'b1). Supports
// report (scan only) and propagate (simplify with cascading fixpoint) modes.
std::string Graph::const_propagate(const std::string& mode,
                                    const std::string& gate_type_filter,
                                    const std::string& const_value_filter) {
    auto parse_const = [](const std::string& name) -> std::pair<bool, int> {
        if (name == "1'b0") return {true, 0};
        if (name == "1'b1") return {true, 1};
        return {false, -1};
    };

    std::unordered_map<Node*, int> const_map;
    for (auto& p : nodes) {
        auto r = parse_const(p.first);
        if (r.first) const_map[p.second] = r.second;
    }

    GateType gt_filt = GateType::UNKNOWN;
    if (!gate_type_filter.empty()) {
        std::string lf = gate_type_filter;
        for (char& c : lf) c = std::tolower(c);
        gt_filt = string_to_gate_type(lf);
    }
    int cv_filt = -1;
    if (!const_value_filter.empty()) cv_filt = std::stoi(const_value_filter);

    struct CIG { Node* gate; Node* ci; Node* oi; int cv; };
    auto scan = [&]() -> std::vector<CIG> {
        std::vector<CIG> res;
        for (Node* n : all_nodes) {
            if (n->type != NodeType::GATE || n->gate_type == GateType::DFF) continue;
            if (gt_filt != GateType::UNKNOWN && n->gate_type != gt_filt) continue;
            bool is_unary = (n->gate_type == GateType::NOT || n->gate_type == GateType::BUF);
            if (is_unary) { if (n->inputs.size() != 1) continue; }
            else { if (n->inputs.size() != 2) continue; }

            Node* ci = nullptr; int cv = -1;
            for (Node* in : n->inputs) {
                auto it = const_map.find(in);
                if (it != const_map.end()) {
                    if (cv_filt >= 0 && it->second != cv_filt) continue;
                    if (!ci) { ci = in; cv = it->second; }
                }
            }
            if (!ci) continue;
            Node* oi = nullptr;
            for (Node* in : n->inputs) if (in != ci) { oi = in; break; }
            res.push_back({n, ci, oi, cv});
        }
        return res;
    };

    // ── Report mode ──
    if (mode == "report") {
        auto cgs = scan();
        std::ostringstream ss;
        ss << "{\"mode\": \"report\", \"const_gates\": [";
        for (size_t i = 0; i < cgs.size(); ++i) {
            if (i) ss << ", ";
            auto& c = cgs[i];
            ss << "{\"name\": \"" << c.gate->name << "\", \"type\": \""
               << gate_type_to_string(c.gate->gate_type) << "\", \"inputs\": [";
            for (size_t j = 0; j < c.gate->inputs.size(); ++j) {
                if (j) ss << ", ";
                ss << "\"" << c.gate->inputs[j]->name << "\"";
            }
            ss << "], \"const_input\": \"" << c.ci->name
               << "\", \"const_value\": " << c.cv << "}";
        }
        ss << "], \"total_found\": " << cgs.size() << "}";
        return ss.str();
    }

    // ── Propagate mode ──
    struct EI { std::string name, old_type, action, new_gate; std::vector<std::string> old_in, new_in; };
    std::vector<EI> elims;
    std::unordered_map<std::string, int> gdelta;
    std::unordered_set<Node*> dead;
    auto rmv = [](std::vector<Node*>& v, Node* x) { v.erase(std::remove(v.begin(), v.end(), x), v.end()); };

    bool changed = true;
    while (changed) {
        changed = false;
        auto cgs = scan();
        for (auto& cg : cgs) {
            if (dead.count(cg.gate)) continue;
            Node* g = cg.gate; Node* ci = cg.ci; Node* oi = cg.oi; int cv = cg.cv;
            GateType gt = g->gate_type;
            if (g->outputs.empty()) continue;
            Node* out = g->outputs[0];

            if (gt == GateType::BUF && out->type == NodeType::PRIMARY_OUTPUT) continue;

            EI ei; ei.name = g->name; ei.old_type = gate_type_to_string(gt);
            for (Node* in : g->inputs) ei.old_in.push_back(in->name);

            enum { TNOT, TWIRE, TCONST } act; int coval = -1;
            switch (gt) {
                case GateType::NOT:  act = TCONST; coval = 1 - cv; break;
                case GateType::BUF:  act = TCONST; coval = cv; break;
                case GateType::NAND: act = cv ? TNOT : TCONST; coval = 1; break;
                case GateType::AND:  act = cv ? TWIRE : TCONST; coval = 0; break;
                case GateType::OR:   act = cv ? TCONST : TWIRE; coval = 1; break;
                case GateType::NOR:  act = cv ? TCONST : TNOT; coval = 0; break;
                case GateType::XOR:  act = cv ? TNOT : TWIRE; break;
                case GateType::XNOR: act = cv ? TWIRE : TNOT; break;
                default: continue;
            }

            if ((act == TNOT || act == TWIRE) && !oi) {
                int c = cv;
                switch (gt) {
                    case GateType::NAND: coval = c ? 0 : 1; break;
                    case GateType::AND:  coval = c; break;
                    case GateType::OR:   coval = c; break;
                    case GateType::NOR:  coval = c ? 0 : 1; break;
                    case GateType::XOR:  coval = 0; break;
                    case GateType::XNOR: coval = 1; break;
                    default: break;
                }
                act = TCONST;
            }

            if (act == TNOT) {
                rmv(ci->outputs, g); g->inputs.clear();
                g->inputs.push_back(oi);
                g->gate_type = GateType::NOT;
                ei.action = "replaced_with_NOT"; ei.new_gate = g->name;
                for (Node* in : g->inputs) ei.new_in.push_back(in->name);
                gdelta[ei.old_type]--; gdelta["NOT"]++;
            } else if (act == TWIRE) {
                if (out->type == NodeType::PRIMARY_OUTPUT) {
                    rmv(ci->outputs, g); g->inputs.clear(); g->inputs.push_back(oi);
                    g->gate_type = GateType::BUF;
                    ei.action = "replaced_with_BUF"; ei.new_gate = g->name;
                    ei.new_in.push_back(oi->name);
                    gdelta[ei.old_type]--; gdelta["BUF"]++;
                } else {
                    for (Node* c : std::vector<Node*>(out->outputs)) {
                        for (Node*& inp : c->inputs) if (inp == out) inp = oi;
                        oi->outputs.push_back(c);
                    }
                    out->outputs.clear();
                    for (Node* in : g->inputs) rmv(in->outputs, g);
                    dead.insert(g); dead.insert(out);
                    ei.action = "replaced_with_wire";
                    gdelta[ei.old_type]--;
                }
            } else {
                std::string cn = (coval == 0) ? "1'b0" : "1'b1";
                Node* cnode = get_or_create_node(cn);
                const_map[cnode] = coval;
                if (out->type == NodeType::PRIMARY_OUTPUT) {
                    for (Node* in : g->inputs) rmv(in->outputs, g);
                    g->inputs.clear(); g->inputs.push_back(cnode); cnode->outputs.push_back(g);
                    g->gate_type = GateType::BUF;
                    ei.action = "output_const_" + std::to_string(coval);
                    ei.new_gate = g->name; ei.new_in.push_back(cn);
                    gdelta[ei.old_type]--; gdelta["BUF"]++;
                } else {
                    for (Node* c : std::vector<Node*>(out->outputs)) {
                        for (Node*& inp : c->inputs) if (inp == out) inp = cnode;
                        cnode->outputs.push_back(c);
                    }
                    out->outputs.clear();
                    for (Node* in : g->inputs) rmv(in->outputs, g);
                    dead.insert(g); dead.insert(out);
                    ei.action = "output_const_" + std::to_string(coval);
                    gdelta[ei.old_type]--;
                }
            }
            elims.push_back(ei); changed = true;
        }
    }

    if (!dead.empty()) {
        std::vector<Node*> keep, drop;
        for (Node* n : all_nodes) (dead.count(n) ? drop : keep).push_back(n);
        for (Node* n : keep) {
            std::vector<Node*> in, out;
            for (Node* x : n->inputs)  if (!dead.count(x)) in.push_back(x);
            for (Node* x : n->outputs) if (!dead.count(x)) out.push_back(x);
            n->inputs.swap(in); n->outputs.swap(out);
        }
        for (Node* n : drop) nodes.erase(n->name);
        all_nodes.swap(keep);
        for (Node* n : drop) delete n;
    }
    topological_order.clear();

    int rem_cw = 0;
    for (auto& p : const_map)
        if (!dead.count(p.first) && p.first->outputs.empty() && p.first->type == NodeType::SIGNAL) rem_cw++;

    int ec = (int)elims.size(), ac = 0;
    for (auto& e : elims) if (!e.new_gate.empty()) ac++;

    std::ostringstream ss;
    ss << "{\"mode\": \"propagate\", \"eliminated\": [";
    for (size_t i = 0; i < elims.size(); ++i) {
        if (i) ss << ", ";
        auto& e = elims[i];
        ss << "{\"name\": \"" << e.name << "\", \"old_type\": \"" << e.old_type
           << "\", \"old_inputs\": [";
        for (size_t j = 0; j < e.old_in.size(); ++j) {
            if (j) ss << ", "; ss << "\"" << e.old_in[j] << "\"";
        }
        ss << "], \"action\": \"" << e.action << "\"";
        if (!e.new_gate.empty()) {
            ss << ", \"new_gate\": \"" << e.new_gate << "\", \"new_inputs\": [";
            for (size_t j = 0; j < e.new_in.size(); ++j) {
                if (j) ss << ", "; ss << "\"" << e.new_in[j] << "\"";
            }
            ss << "]";
        }
        ss << "}";
    }
    ss << "], \"eliminated_count\": " << ec
       << ", \"added_count\": " << ac
       << ", \"gate_delta\": {";
    bool first = true;
    for (auto& p : gdelta) {
        if (!first) ss << ", "; first = false;
        ss << "\"" << p.first << "\": " << p.second;
    }
    if (rem_cw > 0) {
        if (!first) ss << ", ";
        ss << "\"removed_const_wires\": " << rem_cw;
    }
    ss << "}}";
    return ss.str();
}

// Collapse back-to-back inverters: NOT(NOT(x)) == x. g2's consumers are rewired to
// x and g2 removed; g1 removed too if it then drives nothing. Iterates to fully
// collapse chains. A pair feeding a primary output is left intact. Returns count removed.
int Graph::collapse_inverters() {
    topological_order.clear();  // node removal invalidates the cached topo order
    int removed = 0; bool changed = true;
    std::unordered_set<Node*> dead;
    auto rm = [&](std::vector<Node*>& v, Node* x) { v.erase(std::remove(v.begin(), v.end(), x), v.end()); };
    while (changed) {
        changed = false;
        std::vector<Node*> nots;
        for (Node* n : all_nodes)
            if (!dead.count(n) && n->type == NodeType::GATE && n->gate_type == GateType::NOT) nots.push_back(n);
        for (Node* g2 : nots) {
            if (dead.count(g2) || g2->inputs.empty() || g2->outputs.empty()) continue;
            Node* s = g2->inputs[0];
            if (dead.count(s) || s->inputs.size() != 1) continue;
            Node* g1 = s->inputs[0];
            if (dead.count(g1) || g1->type != NodeType::GATE || g1->gate_type != GateType::NOT || g1->inputs.empty()) continue;
            Node* x = g1->inputs[0]; Node* o = g2->outputs[0];
            if (dead.count(x) || dead.count(o) || o->type == NodeType::PRIMARY_OUTPUT || o == x) continue;
            for (Node* c : std::vector<Node*>(o->outputs)) {
                for (Node*& in : c->inputs) if (in == o) in = x;
                x->outputs.push_back(c);
            }
            o->outputs.clear(); rm(s->outputs, g2);
            dead.insert(g2); dead.insert(o); ++removed; changed = true;
            if (s->outputs.empty() && s->type != NodeType::PRIMARY_OUTPUT) {
                rm(x->outputs, g1); dead.insert(g1); dead.insert(s); ++removed;
            }
        }
    }
    if (!dead.empty()) {
        std::vector<Node*> keep, drop;
        for (Node* n : all_nodes) (dead.count(n) ? drop : keep).push_back(n);
        for (Node* n : keep) {
            std::vector<Node*> in, out;
            for (Node* x : n->inputs)  if (!dead.count(x)) in.push_back(x);
            for (Node* x : n->outputs) if (!dead.count(x)) out.push_back(x);
            n->inputs.swap(in); n->outputs.swap(out);
        }
        for (Node* n : drop) nodes.erase(n->name);
        all_nodes.swap(keep);
        for (Node* n : drop) delete n;
    }
    return removed;
}

// Convert gates to use only a target basis. If `root` is empty the whole netlist
// is processed; otherwise just the fanin cone of `root`. Supports:
//   nor_not: AND=NOR(!a,!b), OR=NOT(NOR(a,b)), NAND=NOT(NOR(!a,!b)), BUF=NOT(!a), …
//   and_not: NOR=AND(!a,!b), NAND=NOT(AND(a,b)), OR=NOT(AND(!a,!b)), BUF=NOT(!a), …
// XOR/XNOR are decomposed into the basis; inverters are shared. NOT and the basis's
// kept gate stay as-is. Returns the number of gates rewritten, or -1 if unsupported.
int Graph::remap_cone_to_basis(const std::string& root, const std::string& basis) {
    bool nor_b = (basis == "nor_not"), and_b = (basis == "and_not"), nand_b = (basis == "nand_not");
    if (!nor_b && !and_b && !nand_b) return -1;

    std::vector<Node*> scope;
    if (root.empty()) {
        for (Node* n : all_nodes)
            if (n->type == NodeType::GATE && n->gate_type != GateType::DFF) scope.push_back(n);
    } else {
        auto cone = fanin_cone_gates(root);
        scope.assign(cone.begin(), cone.end());
    }
    std::vector<Node*> targets;
    for (Node* g : scope) {
        GateType t = g->gate_type;
        bool kept = (t == GateType::NOT) || (nor_b && t == GateType::NOR) ||
                    (and_b && t == GateType::AND) || (nand_b && t == GateType::NAND);
        if (!kept && t != GateType::DFF && t != GateType::UNKNOWN) targets.push_back(g);
    }

    int ctr = 0;
    auto fresh = [&](const std::string& p) { std::string nm; do { nm = p + std::to_string(ctr++); } while (nodes.count(nm)); return nm; };
    auto rm = [&](std::vector<Node*>& v, Node* x) { v.erase(std::remove(v.begin(), v.end(), x), v.end()); };
    std::unordered_map<Node*, Node*> inv_cache;
    auto inv = [&](Node* x) -> Node* {
        auto it = inv_cache.find(x); if (it != inv_cache.end()) return it->second;
        Node* gg = get_or_create_node(fresh("__rm_g"), NodeType::GATE); gg->gate_type = GateType::NOT;
        Node* o = get_or_create_node(fresh("__rm_n")); add_edge(x, gg); add_edge(gg, o);
        inv_cache[x] = o; return o;
    };
    auto mk2 = [&](GateType ty, Node* a, Node* b) -> Node* {
        Node* gg = get_or_create_node(fresh("__rm_g"), NodeType::GATE); gg->gate_type = ty;
        Node* o = get_or_create_node(fresh("__rm_n")); add_edge(a, gg); add_edge(b, gg); add_edge(gg, o);
        return o;
    };

    for (Node* g : targets) {
        GateType t = g->gate_type;
        Node* a = g->inputs[0]; Node* b = (g->inputs.size() > 1 ? g->inputs[1] : nullptr);
        rm(a->outputs, g); if (b) rm(b->outputs, g); g->inputs.clear();
        if (t == GateType::BUF) {                          // BUF = NOT(!a) in both bases
            add_edge(inv(a), g); g->gate_type = GateType::NOT;
            continue;
        }
        if (nor_b) {
            if (t == GateType::AND) { add_edge(inv(a), g); add_edge(inv(b), g); g->gate_type = GateType::NOR; }
            else if (t == GateType::OR) { add_edge(mk2(GateType::NOR, a, b), g); g->gate_type = GateType::NOT; }
            else if (t == GateType::NAND) { add_edge(mk2(GateType::NOR, inv(a), inv(b)), g); g->gate_type = GateType::NOT; }
            else if (t == GateType::XOR) {                 // XNOR = NOR(a&!b, !a&b); XOR = NOT(XNOR)
                Node* p = mk2(GateType::NOR, inv(a), b), * q = mk2(GateType::NOR, a, inv(b));
                add_edge(mk2(GateType::NOR, p, q), g); g->gate_type = GateType::NOT;
            } else if (t == GateType::XNOR) {
                Node* p = mk2(GateType::NOR, inv(a), b), * q = mk2(GateType::NOR, a, inv(b));
                add_edge(p, g); add_edge(q, g); g->gate_type = GateType::NOR;
            }
        } else if (and_b) {  // and_not
            if (t == GateType::NOR) { add_edge(inv(a), g); add_edge(inv(b), g); g->gate_type = GateType::AND; }
            else if (t == GateType::NAND) { add_edge(mk2(GateType::AND, a, b), g); g->gate_type = GateType::NOT; }
            else if (t == GateType::OR) { add_edge(mk2(GateType::AND, inv(a), inv(b)), g); g->gate_type = GateType::NOT; }
            else if (t == GateType::XOR) {                 // XOR = NOT(AND(!(a&!b), !(!a&b)))
                Node* p = inv(mk2(GateType::AND, a, inv(b))), * q = inv(mk2(GateType::AND, inv(a), b));
                add_edge(mk2(GateType::AND, p, q), g); g->gate_type = GateType::NOT;
            } else if (t == GateType::XNOR) {              // XNOR = AND(!(a&!b), !(!a&b))
                Node* p = inv(mk2(GateType::AND, a, inv(b))), * q = inv(mk2(GateType::AND, inv(a), b));
                add_edge(p, g); add_edge(q, g); g->gate_type = GateType::AND;
            }
        } else {  // nand_not
            if (t == GateType::AND) { add_edge(mk2(GateType::NAND, a, b), g); g->gate_type = GateType::NOT; }
            else if (t == GateType::OR) { add_edge(inv(a), g); add_edge(inv(b), g); g->gate_type = GateType::NAND; }
            else if (t == GateType::NOR) { add_edge(mk2(GateType::NAND, inv(a), inv(b)), g); g->gate_type = GateType::NOT; }
            else if (t == GateType::XOR) {                 // 4-NAND XOR
                Node* n1 = mk2(GateType::NAND, a, b);
                Node* n2 = mk2(GateType::NAND, a, n1), * n3 = mk2(GateType::NAND, b, n1);
                add_edge(n2, g); add_edge(n3, g); g->gate_type = GateType::NAND;
            } else if (t == GateType::XNOR) {              // XNOR = NOT(4-NAND XOR)
                Node* n1 = mk2(GateType::NAND, a, b);
                Node* n2 = mk2(GateType::NAND, a, n1), * n3 = mk2(GateType::NAND, b, n1);
                add_edge(mk2(GateType::NAND, n2, n3), g); g->gate_type = GateType::NOT;
            }
        }
    }
    return (int)targets.size();
}

void Graph::find_all_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths, const std::unordered_set<Node*>& can_reach) {
    if (curr == avoid) return;
    // Hard cap: enumeration is exponential in the worst case; without this the
    // collection phase can exhaust time/memory long before the display-side
    // truncation is reached (count_paths provides exact totals via DP).
    if (all_paths.size() >= 10000) return;
    path.push_back(curr);
    if (curr == target) all_paths.push_back(path);
    else {
        for (auto next : curr->outputs) {
            if (next->type == NodeType::GATE && next->gate_type == GateType::DFF) continue;
            // Only descend into the subgraph that can still reach the target.
            if (!can_reach.count(next)) continue;
            find_all_paths_recursive(next, target, avoid, path, all_paths, can_reach);
        }
    }
    path.pop_back();
}

void Graph::stream_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, const std::unordered_set<Node*>& can_reach, std::ostream& out, long long& found, long long& bytes, std::stringstream& preview) {
    if (curr == avoid) return;
    // Resource guard: enumeration streams to disk, so the limits are time and
    // disk, not memory. Without a cap a pathological pair can write tens of
    // GB before the 150s action timeout fires (shared machine, NFS home).
    if (found >= STREAM_CAP_PATHS || bytes >= STREAM_CAP_BYTES) return;
    path.push_back(curr);
    if (curr == target) {
        ++found;
        std::stringstream line;
        line << "Path " << found << ": ";
        for (size_t j = 0; j < path.size(); ++j) {
            line << path[j]->name << (j == path.size() - 1 ? "" : " -> ");
        }
        // Stream to file immediately — no in-memory accumulation, so the
        // enumeration file is complete (up to the resource cap) no matter
        // how many paths exist.
        out << line.str() << "\n";
        bytes += (long long)line.str().size() + 1;
        if (found <= 100) preview << line.str() << "\n";
    } else {
        for (auto next : curr->outputs) {
            if (next->type == NodeType::GATE && next->gate_type == GateType::DFF) continue;
            // Only descend into the subgraph that can still reach the target.
            if (!can_reach.count(next)) continue;
            stream_paths_recursive(next, target, avoid, path, can_reach, out, found, bytes, preview);
        }
    }
    path.pop_back();
}

int Graph::count_fanin_gates_recursive(Node* curr, std::unordered_set<Node*>& visited, bool stop_at_dff) {
    if (!curr || visited.count(curr)) return 0;
    visited.insert(curr);
    int count = (curr->type == NodeType::GATE) ? 1 : 0;
    // Combinational boundary: the DFF is counted, its D/CK/RN/SN side is not
    // entered (Q behaves as a primary input, contest Q&A A21.2).
    if (stop_at_dff && curr->type == NodeType::GATE && curr->gate_type == GateType::DFF)
        return count;
    for (auto in : curr->inputs) count += count_fanin_gates_recursive(in, visited, stop_at_dff);
    return count;
}

int Graph::count_fanout_gates_recursive(Node* curr, std::unordered_set<Node*>& visited, bool stop_at_dff) {
    if (!curr || visited.count(curr)) return 0;
    visited.insert(curr);
    int count = (curr->type == NodeType::GATE) ? 1 : 0;
    if (stop_at_dff && curr->type == NodeType::GATE && curr->gate_type == GateType::DFF)
        return count;
    for (auto out : curr->outputs) count += count_fanout_gates_recursive(out, visited, stop_at_dff);
    return count;
}

void Graph::get_cone_recursive(Node* curr, std::unordered_set<Node*>& visited, bool backward, bool stop_at_dff) {
    if (!curr || visited.count(curr)) return;
    visited.insert(curr);
    if (stop_at_dff && curr->type == NodeType::GATE && curr->gate_type == GateType::DFF)
        return;
    const auto& next_nodes = backward ? curr->inputs : curr->outputs;
    for (auto next : next_nodes) get_cone_recursive(next, visited, backward, stop_at_dff);
}

// ── list_pio: JSON-formatted PI/PO listing with vector grouping ─────────────
std::string Graph::list_pio() {
    // Collect PIs and POs
    std::vector<Node*> pis, pos;
    for (Node* n : all_nodes) {
        if (n->type == NodeType::PRIMARY_INPUT) pis.push_back(n);
        else if (n->type == NodeType::PRIMARY_OUTPUT) pos.push_back(n);
    }
    // Sort for deterministic output
    auto cmp = [](Node* a, Node* b) { return a->name < b->name; };
    std::sort(pis.begin(), pis.end(), cmp);
    std::sort(pos.begin(), pos.end(), cmp);

    // Detect vector groupings: names like "data[0]", "data[1]" share base "data"
    // Returns: ordered list of { base, vector<bit_name> }
    struct VecInfo { std::string base; int width; std::vector<std::string> bits; };
    auto group_vectors = [](const std::vector<Node*>& nodes) -> std::pair<std::vector<VecInfo>, std::vector<std::string>> {
        std::unordered_map<std::string, std::vector<std::string>> base_map;
        std::vector<std::string> scalars;
        std::vector<std::string> order;  // track first-seen order of bases
        std::unordered_set<std::string> seen;
        for (Node* n : nodes) {
            size_t br = n->name.find('[');
            if (br != std::string::npos) {
                std::string base = n->name.substr(0, br);
                if (seen.insert(base).second) order.push_back(base);
                base_map[base].push_back(n->name);
            } else {
                scalars.push_back(n->name);
            }
        }
        std::vector<VecInfo> vecs;
        for (const std::string& base : order) {
            auto& bits = base_map[base];
            std::sort(bits.begin(), bits.end());
            vecs.push_back({base, (int)bits.size(), bits});
        }
        return {vecs, scalars};
    };

    auto [pi_vecs, pi_scalars] = group_vectors(pis);
    auto [po_vecs, po_scalars] = group_vectors(pos);

    // Build JSON manually (no external JSON lib)
    std::ostringstream ss;
    ss << "{\n";

    // primary_inputs array
    ss << "  \"primary_inputs\": [";
    bool first = true;
    for (Node* n : pis) {
        if (!first) ss << ", ";
        ss << "{\"name\": \"" << n->name << "\", \"width\": 1}";
        first = false;
    }
    ss << "],\n";

    // primary_outputs array
    ss << "  \"primary_outputs\": [";
    first = true;
    for (Node* n : pos) {
        if (!first) ss << ", ";
        ss << "{\"name\": \"" << n->name << "\", \"width\": 1}";
        first = false;
    }
    ss << "],\n";

    // pi_vectors
    ss << "  \"pi_vectors\": [";
    first = true;
    for (auto& v : pi_vecs) {
        if (!first) ss << ", ";
        ss << "{\"base\": \"" << v.base << "\", \"width\": " << v.width << ", \"bits\": [";
        for (int i = 0; i < (int)v.bits.size(); ++i) {
            if (i) ss << ", ";
            ss << "\"" << v.bits[i] << "\"";
        }
        ss << "]}";
        first = false;
    }
    ss << "],\n";

    // po_vectors
    ss << "  \"po_vectors\": [";
    first = true;
    for (auto& v : po_vecs) {
        if (!first) ss << ", ";
        ss << "{\"base\": \"" << v.base << "\", \"width\": " << v.width << ", \"bits\": [";
        for (int i = 0; i < (int)v.bits.size(); ++i) {
            if (i) ss << ", ";
            ss << "\"" << v.bits[i] << "\"";
        }
        ss << "]}";
        first = false;
    }
    ss << "],\n";

    ss << "  \"pi_count\": " << pis.size() << ",\n";
    ss << "  \"po_count\": " << pos.size() << "\n";
    ss << "}";
    return ss.str();
}

// ── deepest_cone_output: find PO with deepest fanin cone ────────────────────
// Reuses compute_levels() (one global levelization pass) to get depth for all POs.
// Returns JSON with the deepest output and all depths sorted descending.
std::string Graph::deepest_cone_output() {
    auto levels = compute_levels(nullptr);

    struct PoDepth { std::string name; int depth; };
    std::vector<PoDepth> all_po;
    for (Node* n : all_nodes) {
        if (n->type == NodeType::PRIMARY_OUTPUT) {
            int d = levels.count(n) ? levels[n] : 0;
            all_po.push_back({n->name, d});
        }
    }
    // Sort by depth descending, then name ascending for ties
    std::sort(all_po.begin(), all_po.end(), [](const PoDepth& a, const PoDepth& b) {
        return a.depth != b.depth ? a.depth > b.depth : a.name < b.name;
    });

    std::string deepest_name = all_po.empty() ? "" : all_po[0].name;
    int deepest_depth = all_po.empty() ? 0 : all_po[0].depth;

    std::ostringstream ss;
    ss << "{\n";
    ss << "  \"deepest_output\": \"" << deepest_name << "\",\n";
    ss << "  \"depth\": " << deepest_depth << ",\n";
    ss << "  \"total_outputs\": " << all_po.size() << ",\n";
    ss << "  \"all_depths\": [";
    for (int i = 0; i < (int)all_po.size(); ++i) {
        if (i) ss << ", ";
        ss << "{\"name\": \"" << all_po[i].name << "\", \"depth\": " << all_po[i].depth << "}";
    }
    ss << "]\n";
    ss << "}";
    return ss.str();
}

std::string Graph::r2r_paths() {
    const int MAX_PATHS_PER_PAIR = 5;
    const int MAX_TOTAL_PATHS = 200;

    struct DFFInfo {
        Node* dff;
        std::string q_wire;
        std::string d_wire;
        std::string q_pin;
        std::string d_pin;
    };

    std::vector<DFFInfo> dffs;
    for (Node* n : all_nodes) {
        if (n->type != NodeType::GATE || n->gate_type != GateType::DFF) continue;
        DFFInfo info;
        info.dff = n;
        info.q_pin = "Q";
        info.d_pin = "D";
        if (!n->pin_conns.empty()) {
            for (auto& pc : n->pin_conns) {
                if (pc.pin == "Q" || pc.pin == "QN") {
                    info.q_wire = pc.signal;
                    info.q_pin = pc.pin;
                }
                if (pc.pin == "D") info.d_wire = pc.signal;
            }
        } else {
            if (!n->outputs.empty()) info.q_wire = n->outputs[0]->name;
            if (!n->inputs.empty()) info.d_wire = n->inputs[0]->name;
        }
        if (!info.q_wire.empty() && !info.d_wire.empty()) dffs.push_back(info);
    }

    if (dffs.empty()) {
        return "{\"r2r_paths\": [], \"total_r2r_pairs\": 0, \"total_paths\": 0, "
               "\"message\": \"No DFFs found in design\"}";
    }

    std::unordered_set<std::string> d_wires;
    for (auto& di : dffs) d_wires.insert(di.d_wire);

    std::unordered_map<std::string, std::string> d_wire_to_dff;
    std::unordered_map<std::string, std::string> d_wire_to_pin;
    for (auto& di : dffs) {
        d_wire_to_dff[di.d_wire] = di.dff->name;
        d_wire_to_pin[di.d_wire] = di.d_pin;
    }

    struct R2REntry {
        std::string from_dff, from_pin, to_dff, to_pin;
        std::vector<std::vector<std::string>> paths;
    };

    std::vector<R2REntry> results;
    int total_paths = 0;
    bool truncated = false;

    for (auto& src : dffs) {
        if (truncated) break;
        Node* q_node = nodes.count(src.q_wire) ? nodes[src.q_wire] : nullptr;
        if (!q_node) continue;

        std::unordered_map<std::string, std::vector<std::vector<std::string>>> found;

        struct Frame { Node* node; std::vector<std::string> path; };
        std::vector<Frame> stack;
        stack.push_back({q_node, {src.dff->name + "/" + src.q_pin, q_node->name}});

        while (!stack.empty() && !truncated) {
            Frame f = std::move(stack.back());
            stack.pop_back();

            if (d_wires.count(f.node->name) && f.path.size() > 2) {
                std::string dest_dff = d_wire_to_dff[f.node->name];
                std::string dest_pin = d_wire_to_pin[f.node->name];
                std::string key = dest_dff + "/" + dest_pin;
                auto& pvec = found[key];
                if ((int)pvec.size() < MAX_PATHS_PER_PAIR) {
                    auto p = f.path;
                    p.push_back(dest_dff + "/" + dest_pin);
                    pvec.push_back(std::move(p));
                    total_paths++;
                    if (total_paths >= MAX_TOTAL_PATHS) { truncated = true; break; }
                }
                continue;
            }

            for (Node* next : f.node->outputs) {
                if (next->type == NodeType::GATE && next->gate_type == GateType::DFF) {
                    if (d_wires.count(f.node->name)) {
                        std::string dest_dff = d_wire_to_dff[f.node->name];
                        std::string dest_pin = d_wire_to_pin[f.node->name];
                        std::string key = dest_dff + "/" + dest_pin;
                        auto& pvec = found[key];
                        if ((int)pvec.size() < MAX_PATHS_PER_PAIR) {
                            auto p = f.path;
                            p.push_back(dest_dff + "/" + dest_pin);
                            pvec.push_back(std::move(p));
                            total_paths++;
                            if (total_paths >= MAX_TOTAL_PATHS) { truncated = true; }
                        }
                    }
                    continue;
                }
                if (f.path.size() > 200) continue;
                auto np = f.path;
                np.push_back(next->name);
                stack.push_back({next, std::move(np)});
            }
        }

        for (auto& kv : found) {
            R2REntry e;
            e.from_dff = src.dff->name;
            e.from_pin = src.q_pin;
            size_t slash = kv.first.find('/');
            e.to_dff = kv.first.substr(0, slash);
            e.to_pin = kv.first.substr(slash + 1);
            e.paths = std::move(kv.second);
            results.push_back(std::move(e));
        }
    }

    int total_r2r_pairs = (int)results.size();

    std::ostringstream ss;
    ss << "{\n  \"r2r_paths\": [\n";
    for (int i = 0; i < (int)results.size(); ++i) {
        auto& e = results[i];
        ss << "    {\"from_dff\": \"" << e.from_dff
           << "\", \"from_pin\": \"" << e.from_pin
           << "\", \"to_dff\": \"" << e.to_dff
           << "\", \"to_pin\": \"" << e.to_pin
           << "\", \"path_count\": " << e.paths.size()
           << ", \"paths\": [";
        for (int j = 0; j < (int)e.paths.size(); ++j) {
            ss << "[";
            for (int k = 0; k < (int)e.paths[j].size(); ++k) {
                ss << "\"" << e.paths[j][k] << "\"";
                if (k + 1 < (int)e.paths[j].size()) ss << ", ";
            }
            ss << "]";
            if (j + 1 < (int)e.paths.size()) ss << ", ";
        }
        ss << "]}";
        if (i + 1 < (int)results.size()) ss << ",";
        ss << "\n";
    }
    ss << "  ],\n  \"total_r2r_pairs\": " << total_r2r_pairs
       << ",\n  \"total_paths\": " << total_paths;
    if (truncated) ss << ",\n  \"truncated\": true, \"message\": \"Results truncated to limit\"";
    else ss << ",\n  \"truncated\": false";
    ss << "\n}";
    return ss.str();
}


// ── Functional constant analysis support (P1-8, official Q&A A21.1) ──────
// "Constant" per the official ruling means FUNCTIONALLY constant (provable
// for all inputs, DFF initial state = 0, X ignored) — not merely a net tied
// to 1'b0/1'b1. The SAT proofs run in ABC, driven by the Python engine; the
// actions below supply everything the engine needs from the netlist in one
// parse each: single-output flop-cut cone BLIFs (write_cone_blifs), random
// sequential simulation for cheap non-constancy witnesses (sim_consts,
// report_stuck_inputs), and DFF D/Q wiring for the init-0 fixed-point
// iteration (list_dffs).

static std::string blif_sanitize(const std::string& n) {
    std::string s = n;
    for (char& c : s) if (c == '[' || c == ']' || c == '\'') c = '_';
    return s;
}

static std::vector<std::string> split_csv(const std::string& csv) {
    std::vector<std::string> out;
    std::stringstream ss(csv);
    std::string item;
    while (std::getline(ss, item, ',')) if (!item.empty()) out.push_back(item);
    return out;
}

std::string Graph::write_cone_blifs(const std::string& nets_csv, const std::string& out_dir, const std::string& tie0_csv) {
    std::vector<std::string> nets = split_csv(nets_csv);
    if (nets.empty()) return "Error: --nets required for write_cone_blifs.";
    if (out_dir.empty()) return "Error: --out_dir required for write_cone_blifs.";
    std::unordered_set<std::string> tie0;
    for (const auto& t : split_csv(tie0_csv)) tie0.insert(t);

    std::stringstream res;
    int idx = 0;
    for (const auto& target : nets) {
        ++idx;
        if (!nodes.count(target)) { res << "CONE " << target << " error=not_found\n"; continue; }

        // Collect the combinational fanin cone of `target`. Boundary inputs:
        // PIs / undriven nets, DFF Q nets (flop-cut), tie0 nets (forced 0),
        // and the 1'b0/1'b1 constants.
        std::vector<Node*> cone_gates;
        std::unordered_set<Node*> seen_gates;
        std::vector<std::string> boundary;          // free BLIF .inputs
        std::unordered_set<std::string> seen_nets, bound_set;
        bool has_c0 = false, has_c1 = false, has_tied = false;
        std::unordered_set<std::string> tied_here;
        std::vector<std::string> stack{target};
        seen_nets.insert(target);
        while (!stack.empty()) {
            std::string net = stack.back(); stack.pop_back();
            if (net == "1'b0") { has_c0 = true; continue; }
            if (net == "1'b1") { has_c1 = true; continue; }
            if (tie0.count(net)) { has_tied = true; tied_here.insert(net); continue; }
            Node* n = nodes.count(net) ? nodes[net] : nullptr;
            Node* driver = nullptr;
            if (n) for (Node* g : n->inputs)
                if (g->type == NodeType::GATE) { driver = g; break; }
            if (!driver || driver->gate_type == GateType::DFF) {
                if (bound_set.insert(net).second) boundary.push_back(net);
                continue;
            }
            if (seen_gates.insert(driver).second) cone_gates.push_back(driver);
            for (Node* in : driver->inputs)
                if (seen_nets.insert(in->name).second) stack.push_back(in->name);
        }

        // Emit both polarities: <k>.blif proves "can o be 1", <k>_inv.blif
        // proves "can o be 0" (UNSAT on one side = constant of the other).
        std::string base = out_dir + "/cone_" + std::to_string(idx);
        for (int inv = 0; inv <= 1; ++inv) {
            std::ofstream ofs(base + (inv ? "_inv.blif" : ".blif"));
            if (!ofs) return "Error: cannot open cone BLIF for writing under " + out_dir;
            ofs << ".model cone" << idx << (inv ? "_inv" : "") << "\n.inputs";
            std::vector<std::string> sorted_bound = boundary;
            std::sort(sorted_bound.begin(), sorted_bound.end());
            for (const auto& b : sorted_bound) ofs << " " << blif_sanitize(b);
            ofs << "\n.outputs o\n";
            if (has_c0) ofs << ".names " << blif_sanitize("1'b0") << "_c0\n";
            if (has_c1) ofs << ".names " << blif_sanitize("1'b1") << "_c1\n1\n";
            for (const auto& t : tied_here) ofs << ".names " << blif_sanitize(t) << "\n";
            auto sig = [&](const std::string& nm) -> std::string {
                if (nm == "1'b0") return blif_sanitize(nm) + "_c0";
                if (nm == "1'b1") return blif_sanitize(nm) + "_c1";
                return blif_sanitize(nm);
            };
            for (Node* g : cone_gates) {
                if (g->outputs.empty()) continue;
                ofs << ".names";
                for (Node* in : g->inputs) ofs << " " << sig(in->name);
                ofs << " " << blif_sanitize(g->outputs[0]->name) << "\n";
                size_t k = g->inputs.size();
                switch (g->gate_type) {
                    case GateType::BUF: ofs << "1 1\n"; break;
                    case GateType::NOT: ofs << "0 1\n"; break;
                    case GateType::AND: ofs << std::string(k, '1') << " 1\n"; break;
                    case GateType::NOR: ofs << std::string(k, '0') << " 1\n"; break;
                    case GateType::OR:  for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '1'; ofs << c << " 1\n"; } break;
                    case GateType::NAND:for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '0'; ofs << c << " 1\n"; } break;
                    case GateType::XOR: case GateType::XNOR: {
                        bool want_odd = (g->gate_type == GateType::XOR);
                        for (size_t m = 0; m < (1u << k); ++m) {
                            int par = 0; std::string c(k, '0');
                            for (size_t b = 0; b < k; ++b) if (m & (1u << b)) { c[b] = '1'; par ^= 1; }
                            if ((par == 1) == want_odd) ofs << c << " 1\n";
                        }
                        break;
                    }
                    default: return "Error: unsupported gate type in cone of " + target;
                }
            }
            ofs << ".names " << sig(target) << " o\n" << (inv ? "0 1" : "1 1") << "\n.end\n";
        }
        res << "CONE " << target << " gates=" << cone_gates.size()
            << " file=" << base << ".blif file_inv=" << base << "_inv.blif\n";
        (void)has_tied;
    }
    return res.str();
}

// Sequential BLIF export (".latch <D> <Q> 0" per DFF) — the bridge that lets
// Berkeley ABC's sequential engines (scleanup ternary simulation, pdr,
// scorr) run on our netlists, which ABC cannot parse directly (named-pin dff
// instances). Unlike write_blif (flop-cut), flip-flops stay in the model:
// .inputs are the real PIs only and every DFF becomes a .latch with initial
// value 0. Semantic boundary: DFF RN/SN/CK control pins are IGNORED — the
// same convention as run_random_sim and the flop-cut model, so proofs over
// this model share the project's declared sequential semantics (DFF initial
// state 0, X ignored) and add no new soundness gap. Documented cases:
//   - registered PO (a PO net that is a DFF Q) is legal here — it is simply
//     a latch output listed in .outputs; no flop-cut tap needed.
//   - multiple DFFs driving one Q net: the last one in parse order keeps
//     the .latch (matching run_random_sim's last-writer-wins cycle-start
//     ordering); earlier duplicates are dropped and counted in the result.
//   - constants become dedicated .names nodes (__const0 empty cover,
//     __const1 single '1' row), like write_blif.
// --expose nets are added to .outputs through a BUF-style .names alias
// ("__expose_<net>", or "__expose_inv_<net>" with an inverting cover for
// "!net" items) — a deterministic PO name for the Python layer that cannot
// clash with real ports. expose_only=true drops the real POs so a pdr
// property miter has the exposed net as its sole output.
std::string Graph::write_seq_blif(const std::string& filename, const std::string& expose_csv, bool expose_only) {
    std::vector<Node*> pis, pos, dffs, comb;
    for (Node* n : all_nodes) {
        if (n->type == NodeType::PRIMARY_INPUT) pis.push_back(n);
        else if (n->type == NodeType::PRIMARY_OUTPUT) pos.push_back(n);
        else if (n->type == NodeType::GATE) {
            if (n->gate_type == GateType::DFF) dffs.push_back(n);
            else comb.push_back(n);
        }
    }
    struct Expose { std::string net; bool inv; std::string po; };
    std::vector<Expose> exposes;
    for (const auto& item : split_csv(expose_csv)) {
        bool inv = item[0] == '!';
        std::string net = inv ? item.substr(1) : item;
        if (net.empty()) return "Error: empty --expose entry.";
        if (net != "1'b0" && net != "1'b1" && !nodes.count(net))
            return "Error: expose net '" + net + "' not found.";
        exposes.push_back({net, inv,
                           std::string(inv ? "__expose_inv_" : "__expose_") + blif_sanitize(net)});
    }
    bool need_c0 = false, need_c1 = false;
    auto sig = [&](const std::string& n) -> std::string {
        if (n == "1'b0" || n == "0") { need_c0 = true; return "__const0"; }
        if (n == "1'b1" || n == "1") { need_c1 = true; return "__const1"; }
        return n;
    };
    // Gate covers stream to a buffer first: an unsupported gate type must
    // fail loudly (write_cone_blifs convention) instead of leaving a
    // truncated .names block in a half-written file.
    std::stringstream body;
    for (Node* g : comb) {
        if (g->outputs.empty()) continue;
        body << ".names";
        for (Node* in : g->inputs) body << " " << sig(in->name);
        body << " " << g->outputs[0]->name << "\n";
        size_t k = g->inputs.size();
        switch (g->gate_type) {
            case GateType::BUF: body << "1 1\n"; break;
            case GateType::NOT: body << "0 1\n"; break;
            case GateType::AND: body << std::string(k, '1') << " 1\n"; break;
            case GateType::NOR: body << std::string(k, '0') << " 1\n"; break;
            case GateType::OR:  for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '1'; body << c << " 1\n"; } break;
            case GateType::NAND:for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '0'; body << c << " 1\n"; } break;
            case GateType::XOR: case GateType::XNOR: {
                bool want_odd = (g->gate_type == GateType::XOR);
                for (size_t m = 0; m < (1u << k); ++m) {
                    int par = 0; std::string c(k, '0');
                    for (size_t b = 0; b < k; ++b) if (m & (1u << b)) { c[b] = '1'; par ^= 1; }
                    if ((par == 1) == want_odd) body << c << " 1\n";
                }
                break;
            }
            default:
                return "Error: unsupported gate type in sequential BLIF export ("
                       + g->name + ").";
        }
    }
    // Multiple DFFs on one Q net: the last one in all_nodes order wins
    // (run_random_sim loads DFF states in that order, so the last write is
    // the value the rest of the netlist actually observes).
    std::unordered_map<std::string, Node*> q_owner;
    for (Node* d : dffs) if (!d->outputs.empty()) q_owner[d->outputs[0]->name] = d;
    int latches = 0, dup_q = 0;
    std::stringstream lat;
    for (Node* d : dffs) {
        if (d->outputs.empty()) continue;      // dangling Q drives nothing observable
        const std::string& q = d->outputs[0]->name;
        if (q_owner[q] != d) { ++dup_q; continue; }
        std::string dn;
        if (d->inputs.empty()) { need_c0 = true; dn = "__const0"; }
        else dn = sig(d->inputs[0]->name);
        lat << ".latch " << dn << " " << q << " 0\n";
        ++latches;
    }
    for (const auto& e : exposes)
        body << ".names " << sig(e.net) << " " << e.po << "\n"
             << (e.inv ? "0 1" : "1 1") << "\n";

    std::ofstream ofs(filename);
    if (!ofs) return "Error: cannot open '" + filename + "' for writing.";
    std::unordered_set<std::string> emitted_in;
    int npi = 0, npo = 0;
    ofs << ".model top_seq\n.inputs";
    for (Node* p : pis) if (emitted_in.insert(p->name).second) { ofs << " " << p->name; ++npi; }
    ofs << "\n.outputs";
    if (!expose_only)
        for (Node* p : pos) { ofs << " " << p->name; ++npo; }
    for (const auto& e : exposes) { ofs << " " << e.po; ++npo; }
    ofs << "\n" << lat.str() << body.str();
    if (need_c0) ofs << ".names __const0\n";
    if (need_c1) ofs << ".names __const1\n1\n";
    ofs << ".end\n";
    if (!ofs.good()) return "Error: write failed for '" + filename + "'.";

    std::stringstream res;
    res << "SEQBLIF inputs=" << npi << " outputs=" << npo << " latches=" << latches
        << " dup_q_dropped=" << dup_q << " file=" << filename << "\n";
    for (const auto& e : exposes)
        res << "EXPOSE " << (e.inv ? "!" : "") << e.net << " po=" << e.po << "\n";
    return res.str();
}

// Random sequential simulation, DFF initial state = 0 (official ruling
// A21.1), X ignored (every PI gets a random 0/1 each cycle). Fills `counts`
// with (times seen 0, times seen 1) per net node. Simulation is a SOUND
// witness of non-constancy (a value actually reached under init-0 semantics)
// — the cheap filter before any SAT proof attempt.
void Graph::run_random_sim(int cycles, int trials, unsigned seed,
                           std::unordered_map<Node*, std::pair<long, long>>& counts) {
    if (topological_order.empty()) compute_topological_sort();
    // Simple deterministic LCG so results are reproducible across platforms.
    unsigned long long rng = seed ? seed : 0x2545F4914F6CDD1DULL;
    auto rnd_bit = [&]() -> int {
        rng = rng * 6364136223846793005ULL + 1442695040888963407ULL;
        return (int)((rng >> 33) & 1ULL);
    };

    // Dense node indexing. The per-cycle inner loop must be pure array
    // arithmetic: an unordered_map<Node*,int> value store costs a hash op
    // per input read / output write / count bump, which put a 16x64-cycle
    // scan at ~90s on a 100k-node netlist. Slot N is a permanent-zero
    // sentinel so a node missing from all_nodes reads as 0 (the old
    // undriven -> 0 behavior).
    const int N = (int)all_nodes.size();
    std::unordered_map<Node*, int> idx;
    idx.reserve((size_t)N * 2);
    for (int i = 0; i < N; ++i) idx[all_nodes[i]] = i;
    auto idx_of = [&](Node* n) -> int {
        auto it = idx.find(n);
        return it == idx.end() ? N : it->second;
    };

    // Static per-cycle work, precompiled once: constant loads, DFF Q/D slot
    // pairs, PI randomization order (topological order — keeps the RNG
    // stream identical to the map-based version), flat gate program.
    std::vector<std::pair<int, int>> const_loads;  // (slot, value)
    if (nodes.count("1'b0")) const_loads.push_back({idx_of(nodes["1'b0"]), 0});
    if (nodes.count("1'b1")) const_loads.push_back({idx_of(nodes["1'b1"]), 1});

    std::vector<std::pair<int, int>> dff_qd;       // (Q slot, D slot; D==N if absent)
    for (Node* n : all_nodes)
        if (n->type == NodeType::GATE && n->gate_type == GateType::DFF && !n->outputs.empty())
            dff_qd.push_back({idx_of(n->outputs[0]),
                              n->inputs.empty() ? N : idx_of(n->inputs[0])});

    // preset = slots the map version pre-loaded into val each cycle (consts
    // + DFF state); a PI in that set did NOT consume a random bit.
    std::vector<char> preset((size_t)N + 1, 0);
    for (auto& p : const_loads) preset[p.first] = 1;
    for (auto& p : dff_qd) preset[p.first] = 1;

    struct Op { GateType gt; int out; int in_begin; int in_count; };
    std::vector<int> pis;
    std::vector<Op> prog;
    std::vector<int> op_inputs;
    for (Node* n : topological_order) {
        if (n->type == NodeType::PRIMARY_INPUT) {
            int i = idx_of(n);
            if (i < N && !preset[i]) pis.push_back(i);
            continue;
        }
        if (n->type != NodeType::GATE || n->gate_type == GateType::DFF) continue;
        size_t k = n->inputs.size();
        if (k == 0 || n->outputs.empty()) continue;
        switch (n->gate_type) {
            case GateType::BUF: case GateType::NOT: case GateType::AND:
            case GateType::NAND: case GateType::OR: case GateType::NOR:
            case GateType::XOR: case GateType::XNOR: break;
            default: continue;
        }
        prog.push_back({n->gate_type, idx_of(n->outputs[0]),
                        (int)op_inputs.size(), (int)k});
        for (size_t i = 0; i < k; ++i) op_inputs.push_back(idx_of(n->inputs[i]));
    }

    // written = exactly the slots the map version's per-cycle val ended up
    // holding (deduped); counts are reported for these only.
    std::vector<int> written;
    std::vector<char> seen((size_t)N + 1, 0);
    auto mark = [&](int i) { if (i < N && !seen[i]) { seen[i] = 1; written.push_back(i); } };
    for (auto& p : const_loads) mark(p.first);
    for (auto& p : dff_qd) mark(p.first);
    for (int i : pis) mark(i);
    for (auto& op : prog) mark(op.out);

    std::vector<int8_t> val((size_t)N + 1, 0);
    std::vector<int8_t> state(dff_qd.size(), 0);
    std::vector<long> c0((size_t)N, 0), c1((size_t)N, 0);
    for (int t = 0; t < trials; ++t) {
        // DFF init 0: every Q net starts each trial at 0.
        std::fill(state.begin(), state.end(), (int8_t)0);
        for (int c = 0; c < cycles; ++c) {
            std::fill(val.begin(), val.end(), (int8_t)0);  // fresh cycle, like val.clear()
            for (auto& p : const_loads) val[p.first] = (int8_t)p.second;
            for (size_t i = 0; i < dff_qd.size(); ++i) val[dff_qd[i].first] = state[i];
            for (int i : pis) val[i] = (int8_t)rnd_bit();
            for (const Op& op : prog) {
                const int* in = op_inputs.data() + op.in_begin;
                const int k = op.in_count;
                int v = 0;
                switch (op.gt) {
                    case GateType::BUF: v = val[in[0]]; break;
                    case GateType::NOT: v = 1 - val[in[0]]; break;
                    case GateType::AND: { v = 1; for (int i = 0; i < k; ++i) v &= val[in[i]]; break; }
                    case GateType::NAND:{ v = 1; for (int i = 0; i < k; ++i) v &= val[in[i]]; v = 1 - v; break; }
                    case GateType::OR:  { v = 0; for (int i = 0; i < k; ++i) v |= val[in[i]]; break; }
                    case GateType::NOR: { v = 0; for (int i = 0; i < k; ++i) v |= val[in[i]]; v = 1 - v; break; }
                    case GateType::XOR: { v = 0; for (int i = 0; i < k; ++i) v ^= val[in[i]]; break; }
                    case GateType::XNOR:{ v = 0; for (int i = 0; i < k; ++i) v ^= val[in[i]]; v = 1 - v; break; }
                    default: v = 0; break;
                }
                val[op.out] = (int8_t)v;
            }
            for (int i : written) { if (val[i]) ++c1[i]; else ++c0[i]; }
            // Clock edge: Q <- D (inputs[0] is the D net by convention).
            for (size_t i = 0; i < dff_qd.size(); ++i) state[i] = val[dff_qd[i].second];
        }
    }
    for (int i : written) {
        auto& cnt = counts[all_nodes[i]];
        cnt.first += c0[i];
        cnt.second += c1[i];
    }
}

std::string Graph::sim_consts(const std::string& nets_csv, int cycles, int trials, unsigned seed) {
    std::vector<std::string> nets = split_csv(nets_csv);
    if (nets.empty()) return "Error: --nets required for sim_consts.";
    std::unordered_map<Node*, std::pair<long, long>> counts;
    run_random_sim(cycles, trials, seed, counts);
    std::stringstream ss;
    for (const auto& nm : nets) {
        if (!nodes.count(nm)) { ss << "SIM " << nm << " error=not_found\n"; continue; }
        auto it = counts.find(nodes[nm]);
        long s0 = it == counts.end() ? 0 : it->second.first;
        long s1 = it == counts.end() ? 0 : it->second.second;
        ss << "SIM " << nm << " saw0=" << s0 << " saw1=" << s1 << "\n";
    }
    return ss.str();
}

std::string Graph::list_dffs(const std::string& scope_net) {
    // Without --scope_net: every DFF. With it: only DFFs in the SEQUENTIAL
    // transitive fanin of that net (walk backward crossing DFF D edges) —
    // the exact set whose init-0 fixed point can influence the net.
    std::unordered_set<Node*> scope;
    bool scoped = !scope_net.empty();
    if (scoped) {
        if (!nodes.count(scope_net)) return "Error: Node not found.";
        std::vector<Node*> st{nodes[scope_net]};
        std::unordered_set<Node*> seen{nodes[scope_net]};
        while (!st.empty()) {
            Node* n = st.back(); st.pop_back();
            if (n->type == NodeType::GATE && n->gate_type == GateType::DFF) scope.insert(n);
            for (Node* in : n->inputs) if (seen.insert(in).second) st.push_back(in);
        }
    }
    std::stringstream ss;
    int count = 0;
    for (Node* n : all_nodes) {
        if (n->type != NodeType::GATE || n->gate_type != GateType::DFF) continue;
        if (scoped && !scope.count(n)) continue;
        ++count;
        ss << "DFF " << n->name
           << " D=" << (n->inputs.empty() ? "-" : n->inputs[0]->name)
           << " Q=" << (n->outputs.empty() ? "-" : n->outputs[0]->name) << "\n";
    }
    return "Found " + std::to_string(count) + " DFFs:\n" + ss.str();
}

std::string Graph::report_stuck_inputs(const std::string& gate_type_str, int cycles, int trials, unsigned seed) {
    // Candidate filter for functional constant-input reports: a gate input
    // net that TOGGLED in simulation is provably not constant; the ones that
    // never toggled are the only SAT-proof candidates. `structural=yes`
    // marks nets already tied to 1'b0/1'b1 (no proof needed).
    GateType gt = GateType::UNKNOWN;
    if (!gate_type_str.empty()) {
        std::string lf = gate_type_str;
        for (char& c : lf) c = (char)std::tolower((unsigned char)c);
        gt = string_to_gate_type(lf);
        if (gt == GateType::UNKNOWN) return "Error: unknown gate type '" + gate_type_str + "'.";
    }
    std::unordered_map<Node*, std::pair<long, long>> counts;
    run_random_sim(cycles, trials, seed, counts);
    std::stringstream ss;
    int cand = 0;
    for (Node* n : all_nodes) {
        if (n->type != NodeType::GATE || n->gate_type == GateType::DFF) continue;
        if (gt != GateType::UNKNOWN && n->gate_type != gt) continue;
        for (Node* in : n->inputs) {
            bool structural = (in->name == "1'b0" || in->name == "1'b1");
            long s0 = 0, s1 = 0;
            auto it = counts.find(in);
            if (it != counts.end()) { s0 = it->second.first; s1 = it->second.second; }
            if (!structural && s0 > 0 && s1 > 0) continue;  // toggled -> not constant
            int stuck = structural ? (in->name == "1'b1" ? 1 : 0) : (s1 > 0 ? 1 : 0);
            ss << "CAND gate=" << n->name << " type=" << gate_type_to_string(n->gate_type)
               << " input=" << in->name << " stuck=" << stuck
               << " structural=" << (structural ? "yes" : "no") << "\n";
            ++cand;
        }
    }
    return "Found " + std::to_string(cand) + " candidate constant inputs:\n" + ss.str();
}

std::string Graph::tie_nets_const(const std::string& assign_csv) {
    // Rewire every consumer of each given net to the 1'b0/1'b1 constant node
    // instead. Used by functional constant propagation (P1-8): the caller
    // must only pass nets PROVEN combinationally constant (flop-cut SAT with
    // free flop states) — tying merely-sequentially-constant nets would make
    // the flop-cut cec model report a false inequivalence.
    auto assigns = split_csv(assign_csv);
    if (assigns.empty()) return "Error: --assign required (format: net=0,net=1).";
    int tied = 0, rewired = 0;
    for (const auto& a : assigns) {
        auto eq = a.find('=');
        if (eq == std::string::npos) return "Error: bad assignment '" + a + "' (want net=0 or net=1).";
        std::string nm = a.substr(0, eq), vs = a.substr(eq + 1);
        if (vs != "0" && vs != "1") return "Error: bad const value in '" + a + "'.";
        if (!nodes.count(nm)) return "Error: net '" + nm + "' not found.";
        Node* x = nodes[nm];
        Node* c = get_or_create_node(vs == "0" ? "1'b0" : "1'b1", NodeType::SIGNAL);
        if (x == c) continue;
        std::unordered_set<Node*> seen;
        for (Node* consumer : x->outputs) {
            if (!seen.insert(consumer).second) continue;
            for (auto& in : consumer->inputs)
                if (in == x) { in = c; ++rewired; }
            for (auto& pc : consumer->pin_conns)
                if (pc.signal == nm && pc.edge_dir == 1) { pc.signal = c->name; pc.is_const = true; }
            c->outputs.push_back(consumer);
        }
        x->outputs.clear();
        ++tied;
    }
    topological_order.clear();
    return "Success: tied " + std::to_string(tied) + " net(s) to constants ("
         + std::to_string(rewired) + " consumer connections rewired).";
}
