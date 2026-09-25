// Conservative one-for-one mapping of Yosys fine-grain logic cells onto
// simple sky130_fd_sc_hd cells. This avoids compound-cell technology mapping
// while keeping gate-level behavior equivalent to Yosys's generic netlist.

module \$_NOT_ (input A, output Y);
  sky130_fd_sc_hd__inv_1 _TECHMAP_REPLACE_ (.A(A), .Y(Y));
endmodule

module \$_AND_ (input A, input B, output Y);
  sky130_fd_sc_hd__and2_1 _TECHMAP_REPLACE_ (.A(A), .B(B), .X(Y));
endmodule

module \$_ANDNOT_ (input A, input B, output Y);
  wire not_b;
  sky130_fd_sc_hd__inv_1 invert_b (.A(B), .Y(not_b));
  sky130_fd_sc_hd__and2_1 and_gate (.A(A), .B(not_b), .X(Y));
endmodule

module \$_NAND_ (input A, input B, output Y);
  sky130_fd_sc_hd__nand2_1 _TECHMAP_REPLACE_ (.A(A), .B(B), .Y(Y));
endmodule

module \$_OR_ (input A, input B, output Y);
  sky130_fd_sc_hd__or2_1 _TECHMAP_REPLACE_ (.A(A), .B(B), .X(Y));
endmodule

module \$_ORNOT_ (input A, input B, output Y);
  wire not_b;
  sky130_fd_sc_hd__inv_1 invert_b (.A(B), .Y(not_b));
  sky130_fd_sc_hd__or2_1 or_gate (.A(A), .B(not_b), .X(Y));
endmodule

module \$_NOR_ (input A, input B, output Y);
  sky130_fd_sc_hd__nor2_1 _TECHMAP_REPLACE_ (.A(A), .B(B), .Y(Y));
endmodule

module \$_XOR_ (input A, input B, output Y);
  sky130_fd_sc_hd__xor2_1 _TECHMAP_REPLACE_ (.A(A), .B(B), .X(Y));
endmodule

module \$_XNOR_ (input A, input B, output Y);
  sky130_fd_sc_hd__xnor2_1 _TECHMAP_REPLACE_ (.A(A), .B(B), .Y(Y));
endmodule

module \$_MUX_ (input A, input B, input S, output Y);
  sky130_fd_sc_hd__mux2_1 _TECHMAP_REPLACE_ (.A0(A), .A1(B), .S(S), .X(Y));
endmodule
