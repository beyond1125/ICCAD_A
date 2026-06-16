#ifndef PARSER_HPP
#define PARSER_HPP

#include <string>
#include <vector>
#include <unordered_map>
#include <unordered_set>
#include <iostream>
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>

enum class NodeType {
    GATE,
    SIGNAL,
    PRIMARY_INPUT,
    PRIMARY_OUTPUT
};

enum class GateType {
    NOT, AND, OR, XOR, NOR, NAND, XNOR, BUF, DFF, UNKNOWN
};

// One connection of a named-port instance, e.g. ".CK(n0)" or ".SN(1'b1)".
// edge_dir records whether a graph edge was built for this pin so write_verilog
// can refresh it from the (possibly transformed) graph instead of the stale name:
//   0 = no edge (constants, DFF control pins), 1 = input edge, 2 = output edge.
struct PinConn {
    std::string pin;
    std::string signal;
    bool is_const;
    int edge_dir;
};

class Node {
public:
    std::string name;
    NodeType type;
    GateType gate_type;
    std::vector<Node*> inputs;
    std::vector<Node*> outputs;
    // Non-empty for instances written with named ports (e.g. DFFs). Preserves the
    // original pin order, names, and constant connections for faithful round-trip.
    std::vector<PinConn> pin_conns;

    Node(const std::string& n, NodeType t) : name(n), type(t), gate_type(GateType::UNKNOWN) {}
};

class Graph {
public:
    std::unordered_map<std::string, Node*> nodes;
    std::vector<Node*> all_nodes;
    std::string module_name;

    ~Graph() {
        for (auto node : all_nodes) {
            delete node;
        }
    }

    Node* get_or_create_node(const std::string& name, NodeType type = NodeType::SIGNAL) {
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

    void add_edge(Node* from, Node* to) {
        from->outputs.push_back(to);
        to->inputs.push_back(from);
    }

    // --- Algorithms ---

    int calculate_depth(const std::string& start, const std::string& end) {
        if (nodes.find(end) == nodes.end()) return -1;
        
        std::unordered_map<Node*, int> memo;
        if (start.empty()) {
            return get_node_depth_backward(nodes[end], memo);
        }
        
        if (nodes.find(start) == nodes.end()) return -1;
        int d = get_max_depth_recursive(nodes[start], nodes[end], memo);
        return (d < 0) ? -1 : d;
    }

    std::string get_critical_path(const std::string& start, const std::string& end) {
        if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) 
            return "Error: Start or end node not found.";
        
        std::unordered_map<Node*, int> memo;
        std::unordered_map<Node*, Node*> next_node_map;
        
        int depth = get_max_depth_with_path(nodes[start], nodes[end], memo, next_node_map);
        if (depth < 0) return "No path found.";

        std::stringstream ss;
        ss << "Critical Path Depth: " << depth << " gate levels\nNodes: ";
        Node* curr = nodes[start];
        while (curr) {
            ss << curr->name;
            if (curr == nodes[end]) break;
            ss << " -> ";
            curr = next_node_map[curr];
        }
        return ss.str();
    }

    int get_node_depth_backward(Node* curr, std::unordered_map<Node*, int>& memo) {
        if (!curr) return 0;
        if (curr->type == NodeType::PRIMARY_INPUT) return 0;
        if (memo.count(curr)) return memo[curr];

        int max_d = 0;
        for (auto in : curr->inputs) {
            int d = get_node_depth_backward(in, memo);
            if (curr->type == NodeType::GATE) {
                max_d = std::max(max_d, d + 1);
            } else {
                max_d = std::max(max_d, d);
            }
        }
        return memo[curr] = max_d;
    }

    int count_paths(const std::string& start, const std::string& end, const std::string& avoid = "") {
        if (nodes.find(start) == nodes.end() || nodes.find(end) == nodes.end()) return 0;
        Node* avoid_node = avoid.empty() ? nullptr : (nodes.count(avoid) ? nodes[avoid] : nullptr);
        
        std::unordered_map<Node*, int> memo;
        return count_paths_recursive(nodes[start], nodes[end], avoid_node, memo);
    }

    std::string find_all_paths(const std::string& start, const std::string& end, const std::string& avoid = "") {
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
            if (i >= 100) { // Limit to 100 paths to avoid huge output
                ss << "... (truncated)\n";
                break;
            }
        }
        return ss.str();
    }

    int count_fanin_gates(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return 0;
        std::unordered_set<Node*> visited;
        return count_fanin_gates_recursive(nodes[name], visited);
    }

    int count_fanout_gates(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return 0;
        std::unordered_set<Node*> visited;
        // Don't count the start node itself if it's a gate
        int total = count_fanout_gates_recursive(nodes[name], visited);
        if (nodes[name]->type == NodeType::GATE) total--;
        return total;
    }

    std::string get_fanin_cone(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
        std::unordered_set<Node*> visited;
        get_cone_recursive(nodes[name], visited, true);
        std::stringstream ss;
        ss << "Transitive Fanin Cone of " << name << " contains " << visited.size() << " nodes:\n";
        for (auto n : visited) ss << n->name << " ";
        return ss.str();
    }

    std::string get_fanout_cone(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
        std::unordered_set<Node*> visited;
        get_cone_recursive(nodes[name], visited, false);
        std::stringstream ss;
        ss << "Transitive Fanout Cone of " << name << " contains " << visited.size() << " nodes:\n";
        for (auto n : visited) ss << n->name << " ";
        return ss.str();
    }

    int get_fanin_depth(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return -1;
        std::unordered_map<Node*, int> memo;
        return get_node_depth_backward(nodes[name], memo);
    }

    std::string get_node_info(const std::string& name) {
        if (nodes.find(name) == nodes.end()) return "Error: Node not found.";
        Node* n = nodes[name];
        std::stringstream ss;
        if (n->type == NodeType::GATE) {
            ss << "Gate " << n->name << " [Type: " << gate_type_to_string(n->gate_type) << "]";
        } else {
            ss << "Signal " << n->name << " [" << (n->type == NodeType::PRIMARY_INPUT ? "PI" : n->type == NodeType::PRIMARY_OUTPUT ? "PO" : "Wire") << "]";
        }
        ss << "\n  Fanin count: " << n->inputs.size();
        ss << "\n  Fanout count: " << n->outputs.size();
        ss << "\n  Inputs: ";
        for (auto in : n->inputs) ss << in->name << " ";
        ss << "\n  Outputs: ";
        for (auto out : n->outputs) ss << out->name << " ";
        return ss.str();
    }

    // --- Modifications ---

    bool replace_gate(const std::string& target, const std::string& new_type) {
        if (nodes.find(target) == nodes.end() || nodes[target]->type != NodeType::GATE) return false;

        GateType gt = string_to_gate_type_static(new_type);
        if (gt == GateType::UNKNOWN) return false;

        nodes[target]->gate_type = gt;
        return true;
    }

    // Emit a BLIF that ABC can read, as a flop-cut COMBINATIONAL view:
    // each DFF's Q net becomes a primary input and its D net becomes a primary
    // output named __D_<instance>. Comparing two such BLIFs with ABC `cec` proves
    // the combinational logic (incl. every flop's next-state function) is identical
    // — exactly sound for transforms that preserve the flop boundary (e.g. buffer
    // insertion). Names are kept stable across designs so `cec` matches by name.
    // Read a (flop-cut) logic BLIF produced by ABC and build the corresponding
    // combinational gates into this graph. Each .names node is a complete k-input
    // (k<=2) function; we compute its truth table and emit the matching primitive,
    // inserting shared inverters for the four "mixed-polarity" AND/OR cases.
    // PI/PO nodes are expected to be pre-created (their types are preserved); every
    // other referenced net becomes a SIGNAL. Used by the depth-reduction round-trip.
    void load_logic_blif(const std::string& file) {
        std::ifstream ifs(file);
        if (!ifs.is_open()) return;

        int ctr = 0;
        std::unordered_map<Node*, Node*> inv_cache;
        Node* first_pi = nullptr;
        for (Node* n : all_nodes)
            if (n->type == NodeType::PRIMARY_INPUT) { first_pi = n; break; }

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
        // const0 = AND(p, !p), const1 = OR(p, !p), synthesised from any PI.
        auto drive_const = [&](int val, const std::string& outnm) {
            if (first_pi) mkgate(val ? GateType::OR : GateType::AND, {first_pi, inv(first_pi)}, outnm);
        };

        std::vector<std::string> toks;          // current .names: inputs..., output
        std::vector<std::string> rows;          // cover rows
        auto flush = [&]() {
            if (toks.empty()) return;
            std::string outnm = toks.back();
            int nin = (int)toks.size() - 1;
            int N = 1 << nin;
            int rowval = rows.empty() ? 1 : (rows[0].back() == '1' ? 1 : 0);
            std::vector<int> tt(N, rows.empty() ? 0 : (1 - rowval));
            for (const std::string& r : rows) {
                std::string pat; std::string ov;
                std::istringstream rs(r); rs >> pat >> ov;
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

            if (nin == 0) {
                drive_const(mask & 1, outnm);
            } else if (nin == 1) {
                Node* a = get_or_create_node(toks[0]);
                switch (mask) {              // bit0: a=0, bit1: a=1
                    case 0: drive_const(0, outnm); break;
                    case 1: mkgate(GateType::NOT, {a}, outnm); break;
                    case 2: mkgate(GateType::BUF, {a}, outnm); break;
                    default: drive_const(1, outnm); break;
                }
            } else {                          // nin == 2; index = a + 2*b
                Node* a = get_or_create_node(toks[0]);
                Node* b = get_or_create_node(toks[1]);
                switch (mask) {
                    case 0x0: drive_const(0, outnm); break;
                    case 0x1: mkgate(GateType::NOR,  {a, b}, outnm); break;
                    case 0x2: mkgate(GateType::AND,  {a, inv(b)}, outnm); break;
                    case 0x3: mkgate(GateType::NOT,  {b}, outnm); break;
                    case 0x4: mkgate(GateType::AND,  {inv(a), b}, outnm); break;
                    case 0x5: mkgate(GateType::NOT,  {a}, outnm); break;
                    case 0x6: mkgate(GateType::XOR,  {a, b}, outnm); break;
                    case 0x7: mkgate(GateType::NAND, {a, b}, outnm); break;
                    case 0x8: mkgate(GateType::AND,  {a, b}, outnm); break;
                    case 0x9: mkgate(GateType::XNOR, {a, b}, outnm); break;
                    case 0xA: mkgate(GateType::BUF,  {a}, outnm); break;
                    case 0xB: mkgate(GateType::OR,   {a, inv(b)}, outnm); break;
                    case 0xC: mkgate(GateType::BUF,  {b}, outnm); break;
                    case 0xD: mkgate(GateType::OR,   {inv(a), b}, outnm); break;
                    case 0xE: mkgate(GateType::OR,   {a, b}, outnm); break;
                    default:  drive_const(1, outnm); break;
                }
            }
            toks.clear(); rows.clear();
        };

        std::string line;
        while (std::getline(ifs, line)) {
            if (!line.empty() && line.back() == '\\') {   // BLIF line continuation
                line.pop_back();
                std::string cont;
                while (std::getline(ifs, cont)) {
                    bool more = !cont.empty() && cont.back() == '\\';
                    if (more) cont.pop_back();
                    line += cont;
                    if (!more) break;
                }
            }
            size_t s = line.find_first_not_of(" \t");
            if (s == std::string::npos) continue;
            if (line[s] == '#') continue;
            if (line[s] == '.') {
                flush();
                if (line.compare(s, 6, ".names") == 0) {
                    std::istringstream ss(line.substr(s));
                    std::string kw, t; ss >> kw;
                    while (ss >> t) toks.push_back(t);
                }
                // .model/.inputs/.outputs/.end are ignored: types come from the
                // pre-created PI/PO nodes; other nets are created on demand.
            } else {
                rows.push_back(line.substr(s));
            }
        }
        flush();
    }

    void write_blif(const std::string& filename) {
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

        ofs << ".model top\n.inputs";
        for (Node* p : pis) ofs << " " << p->name;
        for (Node* d : dffs) if (!d->outputs.empty()) ofs << " " << d->outputs[0]->name; // Q nets
        ofs << "\n.outputs";
        for (Node* p : pos) ofs << " " << p->name;
        for (Node* d : dffs) ofs << " __D_" << d->name;
        ofs << "\n";

        for (Node* g : comb) {
            if (g->outputs.empty()) continue;
            std::string y = g->outputs[0]->name;
            std::vector<std::string> in;
            for (Node* i : g->inputs) in.push_back(sig(i->name));
            size_t k = in.size();
            ofs << ".names";
            for (auto& s : in) ofs << " " << s;
            ofs << " " << y << "\n";
            switch (g->gate_type) {
                case GateType::BUF:  ofs << "1 1\n"; break;
                case GateType::NOT:  ofs << "0 1\n"; break;
                case GateType::AND:  ofs << std::string(k, '1') << " 1\n"; break;
                case GateType::NOR:  ofs << std::string(k, '0') << " 1\n"; break;
                case GateType::OR:
                    for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '1'; ofs << c << " 1\n"; }
                    break;
                case GateType::NAND:
                    for (size_t j = 0; j < k; ++j) { std::string c(k, '-'); c[j] = '0'; ofs << c << " 1\n"; }
                    break;
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
        // Tap each DFF's D net out as a per-instance primary output. If the D net is
        // already named __D_<inst> (e.g. a netlist rebuilt from a flop-cut BLIF), it
        // is its own output — emitting a buffer would redefine the net.
        for (Node* d : dffs) {
            std::string dn = d->inputs.empty() ? "__const0" : sig(d->inputs[0]->name);
            std::string tap = "__D_" + d->name;
            if (dn != tap) ofs << ".names " << dn << " " << tap << "\n1 1\n";
        }
        if (need_c0) ofs << ".names __const0\n";
        if (need_c1) ofs << ".names __const1\n1\n";
        ofs << ".end\n";
    }

    // Insert BUF gates so that no gate drives more than max_fanout loads, building
    // a balanced buffer tree for each over-driven net. Functionally transparent
    // (BUF out = in). Only nets driven by a GATE are buffered; primary-input nets
    // (e.g. clock/reset) are out of scope here. Returns the number of BUF gates added.
    int insert_buffers(int max_fanout) {
        if (max_fanout < 2) return 0;  // a tree needs branching factor >= 2
        int buf_count = 0;
        int name_ctr = 0;

        auto fresh = [&](const std::string& prefix) {
            std::string nm;
            do { nm = prefix + std::to_string(name_ctr++); } while (nodes.count(nm));
            return nm;
        };

        // Snapshot existing gates; buffers we add are already within the limit.
        std::vector<Node*> gate_snapshot;
        for (Node* n : all_nodes) if (n->type == NodeType::GATE) gate_snapshot.push_back(n);

        // A sink is something needing a driver: either a consumer gate's input pin
        // (is_buffer=false, identified by consumer+pin) or a buffer's single input
        // (is_buffer=true).
        struct Sink { Node* consumer; int pin; bool is_buffer; };

        for (Node* g : gate_snapshot) {
            if (g->outputs.empty()) continue;
            Node* s = g->outputs[0];
            if ((int)s->outputs.size() <= max_fanout) continue;

            // Collect every load pin currently driven by s (handles a consumer that
            // taps s on multiple input pins).
            std::vector<Sink> pending;
            std::unordered_map<Node*, bool> seen;
            for (Node* c : s->outputs) {
                if (seen[c]) continue;
                seen[c] = true;
                for (int i = 0; i < (int)c->inputs.size(); ++i)
                    if (c->inputs[i] == s) pending.push_back({c, i, false});
            }
            s->outputs.clear();  // survivors are re-attached as the top tree level

            auto assign = [&](const Sink& sk, Node* src) {
                if (sk.is_buffer) sk.consumer->inputs.assign(1, src);
                else sk.consumer->inputs[sk.pin] = src;
                src->outputs.push_back(sk.consumer);
            };

            // Bottom-up: repeatedly group sinks into chunks of max_fanout behind a
            // new buffer until the top level fits, then drive the top from s.
            while ((int)pending.size() > max_fanout) {
                std::vector<Sink> next;
                for (size_t i = 0; i < pending.size(); i += max_fanout) {
                    size_t end = std::min(i + (size_t)max_fanout, pending.size());
                    if (end - i == 1) { next.push_back(pending[i]); continue; }
                    Node* buf = get_or_create_node(fresh("buf_fo_"), NodeType::GATE);
                    buf->gate_type = GateType::BUF;
                    Node* w = get_or_create_node(fresh("nbuf_"), NodeType::SIGNAL);
                    add_edge(buf, w);  // buffer drives its new net
                    buf_count++;
                    for (size_t j = i; j < end; ++j) assign(pending[j], w);
                    next.push_back({buf, -1, true});
                }
                pending.swap(next);
            }
            for (auto& sk : pending) assign(sk, s);
        }
        return buf_count;
    }

    void write_verilog(const std::string& filename) {
        std::ofstream ofs(filename);
        
        std::vector<Node*> pi, po, wires;
        for (auto n : all_nodes) {
            if (n->type == NodeType::PRIMARY_INPUT) pi.push_back(n);
            else if (n->type == NodeType::PRIMARY_OUTPUT) po.push_back(n);
            else if (n->type == NodeType::SIGNAL) wires.push_back(n);
        }

        // Get unique base names for ports to put in module header
        std::vector<std::string> port_names;
        auto get_base_names = [&](const std::vector<Node*>& nodes) {
            std::unordered_map<std::string, bool> seen;
            std::regex vec_regex(R"(^(.+)\[(\d+)\]$)");
            for (auto n : nodes) {
                std::smatch match;
                std::string base = n->name;
                if (std::regex_match(n->name, match, vec_regex)) base = match[1];
                if (!seen[base]) {
                    port_names.push_back(base);
                    seen[base] = true;
                }
            }
        };
        get_base_names(pi);
        get_base_names(po);

        ofs << "module " << module_name << " (";
        for (size_t i = 0; i < port_names.size(); ++i) {
            ofs << port_names[i] << (i == port_names.size() - 1 ? "" : ", ");
        }
        ofs << ");\n\n";

        auto grouped_pi = group_signals(pi);
        auto grouped_po = group_signals(po);

        for (const auto& s : grouped_pi) ofs << "    input " << s << ";\n";
        for (const auto& s : grouped_po) ofs << "    output " << s << ";\n";
        ofs << "\n";

        // For wires, exclude PIs and POs
        std::vector<Node*> filtered_wires;
        for (auto n : wires) {
            bool is_pi_po = false;
            for (auto p : pi) if (p->name == n->name) { is_pi_po = true; break; }
            if (is_pi_po) continue;
            for (auto p : po) if (p->name == n->name) { is_pi_po = true; break; }
            if (is_pi_po) continue;
            filtered_wires.push_back(n);
        }
        auto grouped_wires = group_signals(filtered_wires);
        for (const auto& w : grouped_wires) ofs << "    wire " << w << ";\n";
        ofs << "\n";

        for (auto n : all_nodes) {
            if (n->type == NodeType::GATE) {
                ofs << "    " << gate_type_to_string(n->gate_type) << " " << n->name << " (";
                if (!n->pin_conns.empty()) {
                    // Named-port instance (e.g. DFF): preserve pin names/constants,
                    // but refresh edge-backed pins from the current graph so any
                    // rewiring (e.g. buffer insertion on the D input) is reflected.
                    size_t in_idx = 0, out_idx = 0;
                    for (size_t i = 0; i < n->pin_conns.size(); ++i) {
                        const PinConn& pc = n->pin_conns[i];
                        std::string sig = pc.signal;
                        if (pc.edge_dir == 2 && out_idx < n->outputs.size()) sig = n->outputs[out_idx++]->name;
                        else if (pc.edge_dir == 1 && in_idx < n->inputs.size()) sig = n->inputs[in_idx++]->name;
                        ofs << "." << pc.pin << "(" << sig << ")";
                        if (i + 1 < n->pin_conns.size()) ofs << ", ";
                    }
                } else {
                    // Positional instance: output first, then inputs.
                    if (!n->outputs.empty()) ofs << n->outputs[0]->name;
                    for (auto in : n->inputs) ofs << ", " << in->name;
                }
                ofs << ");\n";
            }
        }
        ofs << "\nendmodule\n";
    }

    std::string gate_type_to_string_public(GateType gt) {
        switch (gt) {
            case GateType::NOT: return "not";
            case GateType::AND: return "and";
            case GateType::OR: return "or";
            case GateType::XOR: return "xor";
            case GateType::NOR: return "nor";
            case GateType::NAND: return "nand";
            case GateType::XNOR: return "xnor";
            case GateType::BUF: return "buf";
            case GateType::DFF: return "dff";
            default: return "unknown";
        }
    }

private:
    int get_max_depth_recursive(Node* curr, Node* target, std::unordered_map<Node*, int>& memo) {
        if (curr == target) return 0;
        if (memo.count(curr)) return memo[curr];

        int max_d = -1e9;
        for (auto next : curr->outputs) {
            int d = get_max_depth_recursive(next, target, memo);
            if (next->type == NodeType::GATE) d += 1;
            max_d = std::max(max_d, d);
        }
        return memo[curr] = max_d;
    }

    int get_max_depth_with_path(Node* curr, Node* target, std::unordered_map<Node*, int>& memo, std::unordered_map<Node*, Node*>& next_node_map) {
        if (curr == target) return 0;
        if (memo.count(curr)) return memo[curr];

        int max_d = -1e9;
        Node* best_next = nullptr;
        for (auto next : curr->outputs) {
            int d = get_max_depth_with_path(next, target, memo, next_node_map);
            if (next->type == NodeType::GATE) d += 1;
            if (d > max_d) {
                max_d = d;
                best_next = next;
            }
        }
        next_node_map[curr] = best_next;
        return memo[curr] = max_d;
    }

    int count_paths_recursive(Node* curr, Node* target, Node* avoid, std::unordered_map<Node*, int>& memo) {
        if (curr == target) return 1;
        if (curr == avoid) return 0;
        if (memo.count(curr)) return memo[curr];

        int count = 0;
        for (auto next : curr->outputs) {
            count += count_paths_recursive(next, target, avoid, memo);
        }
        return memo[curr] = count;
    }

    void find_all_paths_recursive(Node* curr, Node* target, Node* avoid, std::vector<Node*>& path, std::vector<std::vector<Node*>>& all_paths) {
        if (curr == avoid) return;
        path.push_back(curr);
        if (curr == target) {
            all_paths.push_back(path);
        } else {
            for (auto next : curr->outputs) {
                find_all_paths_recursive(next, target, avoid, path, all_paths);
            }
        }
        path.pop_back();
    }

    int count_fanin_gates_recursive(Node* curr, std::unordered_set<Node*>& visited) {
        if (!curr || visited.count(curr)) return 0;
        visited.insert(curr);

        int count = (curr->type == NodeType::GATE) ? 1 : 0;
        for (auto in : curr->inputs) {
            count += count_fanin_gates_recursive(in, visited);
        }
        return count;
    }

    int count_fanout_gates_recursive(Node* curr, std::unordered_set<Node*>& visited) {
        if (!curr || visited.count(curr)) return 0;
        visited.insert(curr);

        int count = (curr->type == NodeType::GATE) ? 1 : 0;
        for (auto out : curr->outputs) {
            count += count_fanout_gates_recursive(out, visited);
        }
        return count;
    }

    void get_cone_recursive(Node* curr, std::unordered_set<Node*>& visited, bool backward) {
        if (!curr || visited.count(curr)) return;
        visited.insert(curr);
        const auto& next_nodes = backward ? curr->inputs : curr->outputs;
        for (auto next : next_nodes) {
            get_cone_recursive(next, visited, backward);
        }
    }

    std::string gate_type_to_string(GateType gt) {
        switch (gt) {
            case GateType::NOT: return "not";
            case GateType::AND: return "and";
            case GateType::OR: return "or";
            case GateType::XOR: return "xor";
            case GateType::NOR: return "nor";
            case GateType::NAND: return "nand";
            case GateType::XNOR: return "xnor";
            case GateType::BUF: return "buf";
            case GateType::DFF: return "dff";
            default: return "unknown";
        }
    }

    static GateType string_to_gate_type_static(const std::string& type_str) {
        if (type_str == "not") return GateType::NOT;
        if (type_str == "and") return GateType::AND;
        if (type_str == "or") return GateType::OR;
        if (type_str == "xor") return GateType::XOR;
        if (type_str == "nor") return GateType::NOR;
        if (type_str == "nand") return GateType::NAND;
        if (type_str == "xnor") return GateType::XNOR;
        if (type_str == "buf") return GateType::BUF;
        if (type_str == "dff") return GateType::DFF;
        return GateType::UNKNOWN;
    }

    struct SignalGroup {
        std::string base;
        int min_idx;
        int max_idx;
        bool is_vector;
    };

    std::vector<std::string> group_signals(const std::vector<Node*>& nodes_list) {
        std::unordered_map<std::string, std::vector<int>> groups;
        std::vector<std::string> scalars;
        std::regex vec_regex(R"(^(.+)\[(\d+)\]$)");

        for (auto n : nodes_list) {
            std::smatch match;
            if (std::regex_match(n->name, match, vec_regex)) {
                groups[match[1]].push_back(std::stoi(match[2]));
            } else {
                scalars.push_back(n->name);
            }
        }

        std::vector<std::string> result;
        for (auto& pair : groups) {
            auto& indices = pair.second;
            std::sort(indices.begin(), indices.end());
            int min_idx = indices.front();
            int max_idx = indices.back();
            if (max_idx - min_idx + 1 == (int)indices.size()) {
                std::stringstream ss;
                ss << "[" << max_idx << ":" << min_idx << "] " << pair.first;
                result.push_back(ss.str());
            } else {
                for (int idx : indices) {
                    result.push_back(pair.first + "[" + std::to_string(idx) + "]");
                }
            }
        }
        result.insert(result.end(), scalars.begin(), scalars.end());
        std::sort(result.begin(), result.end());
        return result;
    }
};

class VerilogParser {
public:
    void parse(const std::string& filename, Graph& graph);

private:
    std::string strip_comments(const std::string& content);
    std::vector<std::string> split_statements(const std::string& content);
    void process_statement(const std::string& stmt, Graph& graph);
    GateType string_to_gate_type(const std::string& type_str);
    std::vector<std::string> parse_signal_list(const std::string& list_str);
    std::vector<std::string> expand_bus(const std::string& base, int msb, int lsb);
};

#endif
