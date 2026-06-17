#ifndef TYPES_HPP
#define TYPES_HPP

#include <string>

enum class NodeType {
    GATE,
    SIGNAL,
    PRIMARY_INPUT,
    PRIMARY_OUTPUT
};

enum class GateType {
    NOT, AND, OR, XOR, NOR, NAND, XNOR, BUF, DFF, UNKNOWN
};

namespace GateUtil {

inline std::string ToString(GateType gt) {
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

inline GateType FromString(const std::string& type_str) {
    if (type_str == "not") return GateType::NOT;
    if (type_str == "and") return GateType::AND;
    if (type_str == "or") return GateType::OR;
    if (type_str == "xor") return GateType::XOR;
    if (type_str == "nor") return GateType::NOR;
    if (type_str == "nand") return GateType::NAND;
    if (type_str == "xnor") return GateType::XNOR;
    if (type_str == "buf") return GateType::BUF;
    if (type_str == "dff" || type_str == "DFF") return GateType::DFF;
    return GateType::UNKNOWN;
}

} // namespace GateUtil

#endif // TYPES_HPP
