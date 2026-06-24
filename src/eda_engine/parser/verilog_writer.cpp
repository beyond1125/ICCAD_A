#include "verilog_writer.hpp"
#include "types.hpp"
#include <fstream>
#include <regex>
#include <sstream>
#include <algorithm>

std::vector<std::string> VerilogWriter::group_signals(const std::vector<Node*>& nodes_list) {
    std::unordered_map<std::string, std::vector<int>> groups; std::vector<std::string> scalars;
    std::regex vec_regex(R"(^(.+)\[(\d+)\]$)");
    for (auto n : nodes_list) {
        std::smatch match;
        if (std::regex_match(n->name, match, vec_regex)) groups[match[1]].push_back(std::stoi(match[2]));
        else scalars.push_back(n->name);
    }
    std::vector<std::string> result;
    for (auto& pair : groups) {
        auto& indices = pair.second; std::sort(indices.begin(), indices.end());
        int min_idx = indices.front(), max_idx = indices.back();
        if (max_idx - min_idx + 1 == (int)indices.size()) {
            std::stringstream ss; ss << "[" << max_idx << ":" << min_idx << "] " << pair.first; result.push_back(ss.str());
        } else { for (int idx : indices) result.push_back(pair.first + "[" + std::to_string(idx) + "]"); }
    }
    result.insert(result.end(), scalars.begin(), scalars.end()); std::sort(result.begin(), result.end()); return result;
}

void VerilogWriter::write_verilog(const Graph& graph, const std::string& filename) {
    std::ofstream ofs(filename); std::vector<Node*> pi, po, wires;
    for (auto n : graph.all_nodes) {
        if (n->type == NodeType::PRIMARY_INPUT) pi.push_back(n);
        else if (n->type == NodeType::PRIMARY_OUTPUT) po.push_back(n);
        else if (n->type == NodeType::SIGNAL) wires.push_back(n);
    }
    std::vector<std::string> port_names; auto get_base_names = [&](const std::vector<Node*>& nodes) {
        std::unordered_map<std::string, bool> seen; std::regex vec_regex(R"(^(.+)\[(\d+)\]$)");
        for (auto n : nodes) {
            std::smatch match; std::string base = n->name;
            if (std::regex_match(n->name, match, vec_regex)) base = match[1];
            if (!seen[base]) { port_names.push_back(base); seen[base] = true; }
        }
    };
    get_base_names(pi); get_base_names(po);
    ofs << "module " << graph.module_name << " (";
    for (size_t i = 0; i < port_names.size(); ++i) ofs << port_names[i] << (i == port_names.size() - 1 ? "" : ", ");
    ofs << ");\n\n";
    auto grouped_pi = group_signals(pi); auto grouped_po = group_signals(po);
    for (const auto& s : grouped_pi) ofs << "    input " << s << ";\n";
    for (const auto& s : grouped_po) ofs << "    output " << s << ";\n";
    ofs << "\n";
    std::vector<Node*> filtered_wires;
    for (auto n : wires) {
        if (n->name.find('\'') != std::string::npos) continue;
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
    for (auto n : graph.all_nodes) {
        if (n->type == NodeType::GATE) {
            ofs << "    " << gate_type_to_string(n->gate_type) << " " << n->name << " (";
            if (!n->pin_conns.empty()) {
                size_t in_idx = 0, out_idx = 0;
                for (size_t i = 0; i < n->pin_conns.size(); ++i) {
                    const PinConn& pc = n->pin_conns[i]; std::string sig = pc.signal;
                    if (pc.edge_dir == 2 && out_idx < n->outputs.size()) sig = n->outputs[out_idx++]->name;
                    else if (pc.edge_dir == 1 && in_idx < n->inputs.size()) sig = n->inputs[in_idx++]->name;
                    ofs << "." << pc.pin << "(" << sig << ")";
                    if (i + 1 < n->pin_conns.size()) ofs << ", ";
                }
            } else {
                if (!n->outputs.empty()) ofs << n->outputs[0]->name;
                for (auto in : n->inputs) ofs << ", " << in->name;
            }
            ofs << ");\n";
        }
    }
    ofs << "\nendmodule\n";
}
