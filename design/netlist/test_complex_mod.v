module test_complex (clk, in, out);

    input [1:0] in;
    input clk;
    output [1:0] out;

    wire [1:0] bus_wire;
    wire n1;
    wire n2;

    nand u_and (bus_wire[0], in[0], in[1]);
    dff u_dff (bus_wire[1], bus_wire[0]);
    not u_not (out[0], bus_wire[1]);
    buf u_buf (out[1], bus_wire[0]);

endmodule
