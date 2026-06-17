#include "verilog_writer.hpp"
#include <fstream>
#include <sstream>
#include <regex>
#include <algorithm>
#include <unordered_map>

void VerilogWriter::Write(const Graph& graph, const std::string& filename) {
    std::ofstream ofs(filename);
    
    std::vector<Node*> pi, po, wires;
    for (auto& n : graph.AllNodes()) {
        if (n->Type() == NodeType::PRIMARY_INPUT) pi.push_back(n.get());
        else if (n->Type() == NodeType::PRIMARY_OUTPUT) po.push_back(n.get());
        else if (n->Type() == NodeType::SIGNAL) wires.push_back(n.get());
    }

    std::vector<std::string> port_names;
    auto get_base_names = [&](const std::vector<Node*>& nodes) {
        std::unordered_map<std::string, bool> seen;
        std::regex vec_regex(R"(^(.+)\[(\d+)\]$)");
        for (auto n : nodes) {
            std::smatch match;
            std::string base = n->Name();
            if (std::regex_match(n->Name(), match, vec_regex)) base = match[1];
            if (!seen[base]) {
                port_names.push_back(base);
                seen[base] = true;
            }
        }
    };
    get_base_names(pi);
    get_base_names(po);

    ofs << "module " << graph.GetModuleName() << " (";
    for (size_t i = 0; i < port_names.size(); ++i) {
        ofs << port_names[i] << (i == port_names.size() - 1 ? "" : ", ");
    }
    ofs << ");\n\n";

    auto grouped_pi = GroupSignals(pi);
    auto grouped_po = GroupSignals(po);

    for (const auto& s : grouped_pi) ofs << "    input " << s << ";\n";
    for (const auto& s : grouped_po) ofs << "    output " << s << ";\n";
    ofs << "\n";

    std::vector<Node*> filtered_wires;
    for (auto n : wires) {
        bool is_pi_po = false;
        for (auto p : pi) if (p->Name() == n->Name()) { is_pi_po = true; break; }
        if (is_pi_po) continue;
        for (auto p : po) if (p->Name() == n->Name()) { is_pi_po = true; break; }
        if (is_pi_po) continue;
        filtered_wires.push_back(n);
    }
    auto grouped_wires = GroupSignals(filtered_wires);
    for (const auto& w : grouped_wires) ofs << "    wire " << w << ";\n";
    ofs << "\n";

    for (auto& n : graph.AllNodes()) {
        if (n->Type() == NodeType::GATE) {
            ofs << "    " << GateUtil::ToString(n->GetGateType()) << " " << n->Name() << " (";
            if (!n->Outputs().empty()) ofs << n->Outputs()[0]->Name();
            for (auto in : n->Inputs()) ofs << ", " << in->Name();
            ofs << ");\n";
        }
    }
    ofs << "\nendmodule\n";
}

std::vector<std::string> VerilogWriter::GroupSignals(const std::vector<Node*>& nodes_list) {
    std::unordered_map<std::string, std::vector<int>> groups;
    std::vector<std::string> scalars;
    std::regex vec_regex(R"(^(.+)\[(\d+)\]$)");

    for (auto n : nodes_list) {
        std::smatch match;
        std::string name = n->Name();
        if (std::regex_match(name, match, vec_regex)) {
            groups[match[1]].push_back(std::stoi(match[2]));
        } else {
            scalars.push_back(name);
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
