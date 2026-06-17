#include "types.hpp"
#include <iostream>
#include <fstream>
#include <ctime>

std::string gate_type_to_string(GateType gt) {
    switch (gt) {
        case GateType::NOT: return "not"; case GateType::AND: return "and"; case GateType::OR: return "or";
        case GateType::XOR: return "xor"; case GateType::NOR: return "nor"; case GateType::NAND: return "nand";
        case GateType::XNOR: return "xnor"; case GateType::BUF: return "buf"; case GateType::DFF: return "dff";
        default: return "unknown";
    }
}

GateType string_to_gate_type(const std::string& type_str) {
    if (type_str == "not") return GateType::NOT; if (type_str == "and") return GateType::AND;
    if (type_str == "or") return GateType::OR; if (type_str == "xor") return GateType::XOR;
    if (type_str == "nor") return GateType::NOR; if (type_str == "nand") return GateType::NAND;
    if (type_str == "xnor") return GateType::XNOR; if (type_str == "buf") return GateType::BUF;
    if (type_str == "dff" || type_str == "DFF") return GateType::DFF; return GateType::UNKNOWN;
}

void log_error(const std::string& msg) {
    std::cerr << msg << std::endl;
    std::ofstream log_file("parser_error.log", std::ios::app);
    if (log_file.is_open()) {
        std::time_t now = std::time(nullptr);
        char timestamp[20];
        std::strftime(timestamp, sizeof(timestamp), "%Y-%m-%d %H:%M:%S", std::localtime(&now));
        log_file << "[" << timestamp << "] " << msg << std::endl;
    }
}
