// Merged DWT implementation sharing a single 8-multiplier filter bank
// between Context A (Level 1) and Context B (Level 1 and Level 2).
module dwt_shared (
    input  wire               clock,
    input  wire               reset,
    input  wire               ctx,
    input  wire               en,
    input  wire signed [15:0] x,
    output reg  signed [39:0] a_l1_lo,
    output reg  signed [39:0] a_l1_hi,
    output reg                a_l1_valid,
    output reg  signed [39:0] b_l1_lo,
    output reg  signed [39:0] b_l1_hi,
    output reg                b_l1_valid,
    output reg  signed [39:0] b_l2_lo,
    output reg  signed [39:0] b_l2_hi,
    output reg                b_l2_valid
);
    // Pinned signed Q15 db2 low/high coefficients
    localparam signed [15:0] H0 = 15826;
    localparam signed [15:0] H1 = 27411;
    localparam signed [15:0] H2 = 7345;
    localparam signed [15:0] H3 = -4240;
    localparam signed [15:0] G0 = -4240;
    localparam signed [15:0] G1 = -7345;
    localparam signed [15:0] G2 = 27411;
    localparam signed [15:0] G3 = -15826;

    // Context A state
    reg signed [15:0] a_w0, a_w1, a_w2;
    reg               a_ph;

    // Context B state
    reg signed [15:0] b_w0, b_w1, b_w2;
    reg signed [15:0] b_q0, b_q1, b_q2, b_q3;
    reg               b_ph;
    reg               b_mpar;
    reg               b_pending;

    // Operation decode
    wire sel_b_l2 = ctx && (!b_ph) && b_pending;

    // Shared filter bank input multiplexing
    wire signed [15:0] in0 = sel_b_l2 ? b_q0 : x;
    wire signed [15:0] in1 = sel_b_l2 ? b_q1 : (ctx ? b_w0 : a_w0);
    wire signed [15:0] in2 = sel_b_l2 ? b_q2 : (ctx ? b_w1 : a_w1);
    wire signed [15:0] in3 = sel_b_l2 ? b_q3 : (ctx ? b_w2 : a_w2);

    // Shared arithmetic: 8 multipliers and 2 adder trees
    wire signed [39:0] mult_lo0 = H0 * in0;
    wire signed [39:0] mult_lo1 = H1 * in1;
    wire signed [39:0] mult_lo2 = H2 * in2;
    wire signed [39:0] mult_lo3 = H3 * in3;

    wire signed [39:0] mult_hi0 = G0 * in0;
    wire signed [39:0] mult_hi1 = G1 * in1;
    wire signed [39:0] mult_hi2 = G2 * in2;
    wire signed [39:0] mult_hi3 = G3 * in3;

    wire signed [39:0] lo_sum = mult_lo0 + mult_lo1 + mult_lo2 + mult_lo3;
    wire signed [39:0] hi_sum = mult_hi0 + mult_hi1 + mult_hi2 + mult_hi3;

    always @(posedge clock) begin
        if (reset) begin
            a_w0       <= 16'sd0;
            a_w1       <= 16'sd0;
            a_w2       <= 16'sd0;
            a_ph       <= 1'b0;
            a_l1_lo    <= 40'sd0;
            a_l1_hi    <= 40'sd0;
            a_l1_valid <= 1'b0;

            b_w0       <= 16'sd0;
            b_w1       <= 16'sd0;
            b_w2       <= 16'sd0;
            b_q0       <= 16'sd0;
            b_q1       <= 16'sd0;
            b_q2       <= 16'sd0;
            b_q3       <= 16'sd0;
            b_ph       <= 1'b0;
            b_mpar     <= 1'b0;
            b_pending  <= 1'b0;
            b_l1_lo    <= 40'sd0;
            b_l1_hi    <= 40'sd0;
            b_l1_valid <= 1'b0;
            b_l2_lo    <= 40'sd0;
            b_l2_hi    <= 40'sd0;
            b_l2_valid <= 1'b0;
        end else begin
            // Valids are single-cycle pulses
            a_l1_valid <= 1'b0;
            b_l1_valid <= 1'b0;
            b_l2_valid <= 1'b0;

            if (en) begin
                if (!ctx) begin
                    // Context A active
                    a_w0 <= x;
                    a_w1 <= a_w0;
                    a_w2 <= a_w1;
                    if (a_ph) begin
                        a_l1_lo    <= lo_sum;
                        a_l1_hi    <= hi_sum;
                        a_l1_valid <= 1'b1;
                    end
                    a_ph <= ~a_ph;
                end else begin
                    // Context B active
                    b_w0 <= x;
                    b_w1 <= b_w0;
                    b_w2 <= b_w1;
                    if (b_ph) begin
                        b_l1_lo    <= lo_sum;
                        b_l1_hi    <= hi_sum;
                        b_l1_valid <= 1'b1;
                        b_q3       <= b_q2;
                        b_q2       <= b_q1;
                        b_q1       <= b_q0;
                        b_q0       <= lo_sum[30:15];
                        if (b_mpar)
                            b_pending <= 1'b1;
                        b_mpar <= ~b_mpar;
                    end else if (b_pending) begin
                        b_l2_lo    <= lo_sum;
                        b_l2_hi    <= hi_sum;
                        b_l2_valid <= 1'b1;
                        b_pending  <= 1'b0;
                    end
                    b_ph <= ~b_ph;
                end
            end
        end
    end
endmodule
