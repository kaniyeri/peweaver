// DWT reference B: Context B, two db2 analysis banks with 2:1 decimation
// per level. The level-2 bank is scheduled so its output register exposes the
// frozen level-2 latency even though spatial hardware could compute earlier.
// Frozen benchmark input; do not modify.
//
// Semantics (see campaigns/dwt_campaign/TIGHTENED_CAMPAIGN_SPEC.md):
// - level-1 exactly as reference A, with q(v) = signed16(v[30:15]) pushed into
//   the latest-first level-2 window on every level-1 pair;
// - level-2 job created on odd level-1 pair indices (pairs 1, 3, 5, ...);
// - job consumed at the next enabled sample with no level-1 output due, using
//   the level-2 window as of that edge; pending work survives en=0.
module dwt_b (
    input  wire               clock,
    input  wire               reset,
    input  wire               en,
    input  wire signed [15:0] x,
    output reg  signed [39:0] l1_lo,
    output reg  signed [39:0] l1_hi,
    output reg                l1_valid,
    output reg  signed [39:0] l2_lo,
    output reg  signed [39:0] l2_hi,
    output reg                l2_valid
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
    reg signed [15:0] q0, q1, q2, q3;
    reg mpar;
    reg pending;

    wire signed [15:0] n0 = x;
    wire signed [15:0] n1 = w0;
    wire signed [15:0] n2 = w1;
    wire signed [15:0] n3 = w2;
    wire signed [39:0] lo_new = H0 * n0 + H1 * n1 + H2 * n2 + H3 * n3;
    wire signed [39:0] hi_new = G0 * n0 + G1 * n1 + G2 * n2 + G3 * n3;
    wire signed [15:0] qn0 = lo_new[30:15];
    wire signed [39:0] l2_lo_new = H0 * q0 + H1 * q1 + H2 * q2 + H3 * q3;
    wire signed [39:0] l2_hi_new = G0 * q0 + G1 * q1 + G2 * q2 + G3 * q3;

    always @(posedge clock) begin
        if (reset) begin
            w0 <= 16'sd0;
            w1 <= 16'sd0;
            w2 <= 16'sd0;
            w3 <= 16'sd0;
            q0 <= 16'sd0;
            q1 <= 16'sd0;
            q2 <= 16'sd0;
            q3 <= 16'sd0;
            l1_lo <= 40'sd0;
            l1_hi <= 40'sd0;
            l1_valid <= 1'b0;
            l2_lo <= 40'sd0;
            l2_hi <= 40'sd0;
            l2_valid <= 1'b0;
            ph <= 1'b0;
            mpar <= 1'b0;
            pending <= 1'b0;
        end else if (en) begin
            w0 <= n0;
            w1 <= n1;
            w2 <= n2;
            w3 <= n3;
            l1_valid <= 1'b0;
            l2_valid <= 1'b0;
            if (ph) begin
                l1_lo <= lo_new;
                l1_hi <= hi_new;
                l1_valid <= 1'b1;
                q3 <= q2;
                q2 <= q1;
                q1 <= q0;
                q0 <= qn0;
                if (mpar)
                    pending <= 1'b1;
                mpar <= ~mpar;
            end else if (pending) begin
                l2_lo <= l2_lo_new;
                l2_hi <= l2_hi_new;
                l2_valid <= 1'b1;
                pending <= 1'b0;
            end
            ph <= ~ph;
        end else begin
            l1_valid <= 1'b0;
            l2_valid <= 1'b0;
        end
    end
endmodule
