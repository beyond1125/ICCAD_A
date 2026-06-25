#include "graph.hpp"
#include <sstream>
#include <algorithm>
#include <fstream>

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

int Graph::count_paths(const std::string& start, const std::string& end, const std::string& avoid) {
    if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return 0;
    Node* start_node = nodes[start];
    Node* end_node = nodes[end];
    Node* avoid_node = avoid.empty() ? nullptr : (nodes.count(avoid) ? nodes[avoid] : nullptr);
    
    if (topological_order.empty()) compute_topological_sort();

    std::unordered_map<Node*, int> path_count;
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
            path_count[v] += path_count[u];
        }
    }
    return path_count[end_node];
}

std::string Graph::find_all_paths(const std::string& start, const std::string& end, const std::string& avoid) {
    if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return "Error: Start or end node not found.";
    Node* start_node = nodes[start];
    Node* end_node = nodes[end];
    Node* avoid_node = avoid.empty() ? nullptr : (nodes.count(avoid) ? nodes[avoid] : nullptr);

    std::vector<std::vector<Node*>> all_paths;
    std::vector<Node*> current_path;
    find_all_paths_recursive(start_node, end_node, avoid_node, current_path, all_paths);

    if (all_paths.empty()) return "No paths found.";

    std::stringstream ss;
    ss << "Found " << all_paths.size() << " paths:\n";
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

int Graph::count_fanin_gates(const std::string& name) {
    if (nodes.find(name) == nodes.end()) return 0;
    std::unordered_set<Node*> visited;
    return count_fanin_gates_recursive(nodes[name], visited);
}

int Graph::count_fanout_gates(const std::string& name) {
    if (nodes.find(name) == nodes.end()) return 0;
    std::unordered_set<Node*> visited;
    int total = count_fanout_gates_recursive(nodes[name], visited);
    if (nodes[name]->type == NodeType::GATE) total--;
    return total;
}

std::string Graph::get_fanin_cone(const std::string& name) {
    if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
    std::unordered_set<Node*> visited;
    get_cone_recursive(nodes[name], visited, true);
    std::vector<Node*> gates;
    for (auto n : visited) {
        if (n->type == NodeType::GATE) gates.push_back(n);
    }
    std::stringstream ss;
    ss << "Transitive Fanin Cone of " << name << " contains " << gates.size() << " gates:\n";
    for (auto n : gates) ss << n->name << " ";
    return ss.str();
}

std::string Graph::get_fanout_cone(const std::string& name) {
    if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
    std::unordered_set<Node*> visited;
    get_cone_recursive(nodes[name], visited, false);
    std::vector<Node*> gates;
    for (auto n : visited) {
        if (n->type == NodeType::GATE) gates.push_back(n);
    }
    std::stringstream ss;
    ss << "Transitive Fanout Cone of " << name << " contains " << gates.size() << " gates:\n";
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

    ss << "\n  Fanin count: " << n->inputs.size() << "\n  Fanout count: " << n->outputs.size();
    ss << "\n  Driving Gates: ";
    for (auto g : driving_gates) ss << g->name << " ";
    ss << "\n  Driven Gates (Immediate Successors): ";
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

int Graph::sweep_dangling() {
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

// Merge structurally-equivalent gates: two non-DFF gates with the same type and the
// same input nets compute the same function, so one is removed and its consumers are
// rewired to the survivor. Iterates to a fixpoint (merging an input can expose new
// duplicates). Flip-flops are never merged, so the flop boundary (and flop-cut
// equivalence) is preserved. Returns the number of gates merged away.
int Graph::merge_duplicate_gates() {
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

void Graph::find_all_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths) {
    if (curr == avoid) return;
    path.push_back(curr);
    if (curr == target) all_paths.push_back(path);
    else {
        for (auto next : curr->outputs) {
            if (next->type == NodeType::GATE && next->gate_type == GateType::DFF) continue;
            find_all_paths_recursive(next, target, avoid, path, all_paths);
        }
    }
    path.pop_back();
}

int Graph::count_fanin_gates_recursive(Node* curr, std::unordered_set<Node*>& visited) {
    if (!curr || visited.count(curr)) return 0;
    visited.insert(curr);
    int count = (curr->type == NodeType::GATE) ? 1 : 0;
    for (auto in : curr->inputs) count += count_fanin_gates_recursive(in, visited);
    return count;
}

int Graph::count_fanout_gates_recursive(Node* curr, std::unordered_set<Node*>& visited) {
    if (!curr || visited.count(curr)) return 0;
    visited.insert(curr);
    int count = (curr->type == NodeType::GATE) ? 1 : 0;
    for (auto out : curr->outputs) count += count_fanout_gates_recursive(out, visited);
    return count;
}

void Graph::get_cone_recursive(Node* curr, std::unordered_set<Node*>& visited, bool backward) {
    if (!curr || visited.count(curr)) return;
    visited.insert(curr);
    const auto& next_nodes = backward ? curr->inputs : curr->outputs;
    for (auto next : next_nodes) get_cone_recursive(next, visited, backward);
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

