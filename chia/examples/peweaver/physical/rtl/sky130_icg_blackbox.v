// Sky130 integrated clock gate cell blackbox declaration for Yosys synthesis
// and behavioral simulation model for RTL simulation when PDK primitives are absent.

`timescale 1ns/1ps

`ifndef SKY130_FD_SC_HD__DLCLKP_4_V
`define SKY130_FD_SC_HD__DLCLKP_4_V

`ifdef YOSYS
(* blackbox *)
module sky130_fd_sc_hd__dlclkp_4 (
    input  wire CLK,
    input  wire GATE,
    output wire GCLK
);
endmodule
`elsif FUNCTIONAL
// in GLS, sky130_fd_sc_hd.v provides the UDP gate-level model
`else
module sky130_fd_sc_hd__dlclkp_4 (
    input  wire CLK,
    input  wire GATE,
    output wire GCLK
);
    reg en_latch;
    always @(CLK or GATE) begin
        if (!CLK)
            en_latch <= GATE;
    end
    assign GCLK = CLK & en_latch;
endmodule
`endif

`endif
