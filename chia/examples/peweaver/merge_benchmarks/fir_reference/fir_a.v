// FIR reference a: 8-tap fixed-coefficient streaming FIR.
// Coefficients are Q15 signed literals, pinned per design (a differs
// from the sibling only in these literals). This file is a pinned input;
// do not modify.
module fir_a #(
    parameter WIDTH = 16
) (
    input  wire                 clock,
    input  wire                 reset,
    input  wire                 en,
    input  wire signed [15:0]   x,
    output reg  signed [39:0]   y
);
    localparam signed [15:0] C0 = 16384;
    localparam signed [15:0] C1 = -8192;
    localparam signed [15:0] C2 = 4096;
    localparam signed [15:0] C3 = 2048;
    localparam signed [15:0] C4 = 1024;
    localparam signed [15:0] C5 = 512;
    localparam signed [15:0] C6 = 256;
    localparam signed [15:0] C7 = 128;
    reg signed [15:0] z [0:7];

    integer i;
    wire signed [39:0] acc = $signed(C0) * $signed(z[0]) + $signed(C1) * $signed(z[1]) + $signed(C2) * $signed(z[2]) + $signed(C3) * $signed(z[3]) + $signed(C4) * $signed(z[4]) + $signed(C5) * $signed(z[5]) + $signed(C6) * $signed(z[6]) + $signed(C7) * $signed(z[7]);
    always @(posedge clock) begin
        if (reset) begin
            for (i = 0; i < 8; i = i + 1) z[i] <= 16'sd0;
            y <= 40'sd0;
        end else if (en) begin
            for (i = 7; i > 0; i = i - 1) z[i] <= z[i-1];
            z[0] <= x;
            y <= acc;
        end
    end
endmodule
