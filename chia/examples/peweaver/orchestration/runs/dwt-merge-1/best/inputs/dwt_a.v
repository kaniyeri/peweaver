// DWT reference A: Context A, one db2 analysis bank with 2:1 decimation.
// Frozen benchmark input; do not modify.
//
// Semantics (see campaigns/dwt_campaign/TIGHTENED_CAMPAIGN_SPEC.md):
// - latest-first 4-tap window, zero prehistory;
// - pinned signed Q15 db2 low/high coefficients;
// - accepted-sample index odd => level-1 pair updates and l1_valid pulses;
// - 40-bit wrapping result, no saturation or rounding.
module dwt_a (
    input  wire               clock,
    input  wire               reset,
    input  wire               en,
    input  wire signed [15:0] x,
    output reg  signed [39:0] l1_lo,
    output reg  signed [39:0] l1_hi,
    output reg                l1_valid
);
    localparam signed [15:0] H0 = 15826;
    localparam signed [15:0] H1 = 27411;
    localparam signed [15:0] H2 = 7345;
    localparam signed [15:0] H3 = -4240;
    localparam signed [15:0] G0 = -4240;
    localparam signed [15:0] G1 = -7345;
    localparam signed [15:0] G2 = 27411;
    localparam signed [15:0] G3 = -15826;

    reg signed [15:0] w0, w1, w2, w3;
    reg ph;

    wire signed [15:0] n0 = x;
    wire signed [15:0] n1 = w0;
    wire signed [15:0] n2 = w1;
    wire signed [15:0] n3 = w2;
    wire signed [39:0] lo_new = H0 * n0 + H1 * n1 + H2 * n2 + H3 * n3;
    wire signed [39:0] hi_new = G0 * n0 + G1 * n1 + G2 * n2 + G3 * n3;

    always @(posedge clock) begin
        if (reset) begin
            w0 <= 16'sd0;
            w1 <= 16'sd0;
            w2 <= 16'sd0;
            w3 <= 16'sd0;
            l1_lo <= 40'sd0;
            l1_hi <= 40'sd0;
            l1_valid <= 1'b0;
            ph <= 1'b0;
        end else if (en) begin
            w0 <= n0;
            w1 <= n1;
            w2 <= n2;
            w3 <= n3;
            l1_valid <= 1'b0;
            if (ph) begin
                l1_lo <= lo_new;
                l1_hi <= hi_new;
                l1_valid <= 1'b1;
            end
            ph <= ~ph;
        end else begin
            l1_valid <= 1'b0;
        end
    end
endmodule
