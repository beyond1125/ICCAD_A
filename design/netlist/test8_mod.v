module test8 (
    input in0,
    input in1,
    output out3,
    output out_side
);

    wire n_in0_n;
    wire n_aux0;
    wire n1;
    wire n_aux1;
    wire n2;
    wire n_aux2;
    wire n3;
    wire w_side;

    and U1 (n_in0_n, in0);
    and U3 (n_aux0, in0, in1);
    and U5 (n1, n_in0_n, n_aux0);
    buf U10 (n_aux1, in1);
    xor U12 (n2, n1, n_aux1);
    or U15 (n_aux2, in0, in1);
    nor U18 (n3, n2, n_aux2);
    buf U20 (out3, n3);
    not U30 (w_side, in1);
    buf U31 (out_side, w_side);

endmodule
