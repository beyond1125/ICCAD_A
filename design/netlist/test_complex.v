module test_complex (
    input clk,
    input [1:0] in,
    output [1:0] out
);

    wire n1, n2;
    wire [1:0] bus_wire;

    // Multi-line and multi-signal
    and u_and (
        bus_wire[0], 
        in[0], 
        in[1]
    );

    dff u_dff (bus_wire[1], bus_wire[0], clk);

    not u_not (out[0], bus_wire[1]);
    buf u_buf (out[1], bus_wire[0]);

endmodule
