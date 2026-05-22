module test_complex (
    input clk,
    input in[1],
    input in[0],
    output out[1],
    output out[0]
);

    wire n1;
    wire bus_wire[1];
    wire bus_wire[0];

    nand u_and (bus_wire[0], in[0], in[1]);
    dff u_dff (bus_wire[1], bus_wire[0]);
    not u_not (out[0], bus_wire[1]);
    buf u_buf (out[1], bus_wire[0]);

endmodule
