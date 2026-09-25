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
    localparam signed [15:0] H0 = 16'sd15826;
    localparam signed [15:0] H1 = 16'sd27411;
    localparam signed [15:0] H2 = 16'sd7345;
    localparam signed [15:0] H3 = -16'sd4240;
    localparam signed [15:0] G0 = -16'sd4240;
    localparam signed [15:0] G1 = -16'sd7345;
    localparam signed [15:0] G2 = 16'sd27411;
    localparam signed [15:0] G3 = -16'sd15826;

    // Context A state
    reg signed [15:0] a_w0, a_w1, a_w2;
    reg               a_ph;

    // Context B state
    reg signed [15:0] b_w0, b_w1, b_w2;
    reg               b_ph;
    reg signed [15:0] b_q0, b_q1, b_q2, b_q3;
    reg               b_mpar;
    reg               b_pending;

    // Shared datapath operand selection
    wire sel_b_l2 = ctx & ~b_ph & b_pending;

    wire signed [15:0] s0 = sel_b_l2 ? b_q0 : x;
    wire signed [15:0] s1 = sel_b_l2 ? b_q1 : (ctx ? b_w0 : a_w0);
    wire signed [15:0] s2 = sel_b_l2 ? b_q2 : (ctx ? b_w1 : a_w1);
    wire signed [15:0] s3 = sel_b_l2 ? b_q3 : (ctx ? b_w2 : a_w2);

    // Single shared 4-tap low/high filter bank (8 multipliers total)
    wire signed [31:0] p_h0 = H0 * s0;
    wire signed [31:0] p_h1 = H1 * s1;
    wire signed [31:0] p_h2 = H2 * s2;
    wire signed [31:0] p_h3 = H3 * s3;

    wire signed [31:0] p_g0 = G0 * s0;
    wire signed [31:0] p_g1 = G1 * s1;
    wire signed [31:0] p_g2 = G2 * s2;
    wire signed [31:0] p_g3 = G3 * s3;

    wire signed [39:0] lo_sum = ({{8{p_h0[31]}}, p_h0} + {{8{p_h1[31]}}, p_h1}) +
                                ({{8{p_h2[31]}}, p_h2} + {{8{p_h3[31]}}, p_h3});

    wire signed [39:0] hi_sum = ({{8{p_g0[31]}}, p_g0} + {{8{p_g1[31]}}, p_g1}) +
                                ({{8{p_g2[31]}}, p_g2} + {{8{p_g3[31]}}, p_g3});

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
            b_ph       <= 1'b0;
            b_q0       <= 16'sd0;
            b_q1       <= 16'sd0;
            b_q2       <= 16'sd0;
            b_q3       <= 16'sd0;
            b_mpar     <= 1'b0;
            b_pending  <= 1'b0;
            b_l1_lo    <= 40'sd0;
            b_l1_hi    <= 40'sd0;
            b_l1_valid <= 1'b0;
            b_l2_lo    <= 40'sd0;
            b_l2_hi    <= 40'sd0;
            b_l2_valid <= 1'b0;
        end else begin
            a_l1_valid <= 1'b0;
            b_l1_valid <= 1'b0;
            b_l2_valid <= 1'b0;

            if (en) begin
                if (!ctx) begin
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
                    b_w0 <= x;
                    b_w1 <= b_w0;
                    b_w2 <= b_w1;
                    if (b_ph) begin
                        b_l1_lo    <= lo_sum;
                        b_l1_hi    <= hi_sum;
                        b_l1_valid <= 1'b1;
                        b_q0       <= lo_sum[30:15];
                        b_q1       <= b_q0;
                        b_q2       <= b_q1;
                        b_q3       <= b_q2;
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
