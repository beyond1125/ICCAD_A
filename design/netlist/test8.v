// Gate-level Verilog netlist — test8
// One top module, flat (no hierarchy).
//
// Primary inputs  : in0, in1
// Primary outputs : out3, out_side
//
// Critical path (depth 5)  in0 → U1 → U5 → U12 → U18 → U20 → out3
// Side path     (depth 2)  in1 → U30 → U31 → out_side
//
// Primitives used: not, and, xor, nor, buf, or
// All 2-input gates have exactly 2 inputs; not/buf have 1 input.

module test8 (
    input  wire in0,
    input  wire in1,
    output wire out3,
    output wire out_side
);

    // ── internal wires ────────────────────────────────────────────────────────
    wire n_in0_n;   // ~in0
    wire n_aux0;    // in0 & in1  (feeds U5 second input)
    wire n1;        // n_in0_n & n_aux0
    wire n_aux1;    // in1        (feeds U12 second input via alias)
    wire n2;        // n1 ^ n_aux1
    wire n_aux2;    // in0 | in1  (feeds U18 second input)
    wire n3;        // ~(n2 | n_aux2)
    wire w_side;    // intermediate on the side path

    // ── critical path (depth 5 from in0 to out3) ─────────────────────────────
    not  U1  (n_in0_n, in0);              // depth 1
    and  U3  (n_aux0,  in0,    in1);      // depth 1 (feeds U5)
    and  U5  (n1,      n_in0_n, n_aux0);  // depth 2
    buf  U10 (n_aux1,  in1);              // depth 1 (feeds U12)
    xor  U12 (n2,      n1,     n_aux1);   // depth 3
    or   U15 (n_aux2,  in0,    in1);      // depth 1 (feeds U18)
    nor  U18 (n3,      n2,     n_aux2);   // depth 4
    buf  U20 (out3,    n3);               // depth 5

    // ── side path (depth 2 from in1 to out_side) ─────────────────────────────
    not  U30 (w_side,  in1);
    buf  U31 (out_side, w_side);

endmodule
