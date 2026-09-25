//----------------------------------------------------------------------
//  peweaver_shared_fft: Shared 64/128-Point Radix-2^2 SDF FFT
//----------------------------------------------------------------------
module peweaver_shared_fft #(
    parameter WIDTH = 16
)(
    input               clock,  //  Master Clock
    input               reset,  //  Active High Asynchronous Reset
    input               mode,   //  0 = 64-Point, 1 = 128-Point
    input               di_en,  //  Input Data Enable
    input   [WIDTH-1:0] di_re,  //  Input Data (Real)
    input   [WIDTH-1:0] di_im,  //  Input Data (Imag)
    output              do_en,  //  Output Data Enable
    output  [WIDTH-1:0] do_re,  //  Output Data (Real)
    output  [WIDTH-1:0] do_im   //  Output Data (Imag)
);

//----------------------------------------------------------------------
//  Mode Latching & State Ownership
//----------------------------------------------------------------------
reg  mode_q;
reg  mode_locked;

wire su1_busy, su2_busy, su3_busy, su4_busy;
wire pipeline_idle = ~(su1_busy | su2_busy | su3_busy | su4_busy | do_en);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        mode_q      <= 1'b0;
        mode_locked <= 1'b0;
    end else if (!mode_locked && pipeline_idle && di_en) begin
        mode_q      <= mode;
        mode_locked <= 1'b1;
    end
end

wire eff_mode = mode_locked ? mode_q : mode;

//----------------------------------------------------------------------
//  Interstage Signals
//----------------------------------------------------------------------
wire             su1_do_en;
wire [WIDTH-1:0] su1_do_re;
wire [WIDTH-1:0] su1_do_im;

wire             su2_do_en;
wire [WIDTH-1:0] su2_do_re;
wire [WIDTH-1:0] su2_do_im;

wire             su3_do_en;
wire [WIDTH-1:0] su3_do_re;
wire [WIDTH-1:0] su3_do_im;

wire             su4_do_en;
wire [WIDTH-1:0] su4_do_re;
wire [WIDTH-1:0] su4_do_im;

//----------------------------------------------------------------------
//  Twiddle ROM Interface
//----------------------------------------------------------------------
wire [6:0]  tw0_addr, tw1_addr, tw2_addr;
wire [15:0] tw0_re, tw0_im;
wire [15:0] tw1_re, tw1_im;
wire [15:0] tw2_re, tw2_im;

TwiddleRom TW_ROM (
    .addr0  (tw0_addr   ),
    .tw0_re (tw0_re     ),
    .tw0_im (tw0_im     ),
    .addr1  (tw1_addr   ),
    .tw1_re (tw1_re     ),
    .tw1_im (tw1_im     ),
    .addr2  (tw2_addr   ),
    .tw2_re (tw2_re     ),
    .tw2_im (tw2_im     )
);

//----------------------------------------------------------------------
//  Stage 0: M=64 (mode 0) / M=128 (mode 1)
//----------------------------------------------------------------------
ConfigSdfUnit #(
    .WIDTH    (WIDTH),
    .DEPTH1_0 (32),
    .DEPTH1_1 (64),
    .DEPTH2_0 (16),
    .DEPTH2_1 (32),
    .LOG_M_0  (6),
    .LOG_M_1  (7)
) SU1 (
    .clock    (clock    ),
    .reset    (reset    ),
    .mode     (eff_mode ),
    .di_en    (di_en    ),
    .di_re    (di_re    ),
    .di_im    (di_im    ),
    .tw_addr  (tw0_addr ),
    .tw_re_in (tw0_re   ),
    .tw_im_in (tw0_im   ),
    .do_en    (su1_do_en),
    .do_re    (su1_do_re),
    .do_im    (su1_do_im),
    .busy     (su1_busy )
);

//----------------------------------------------------------------------
//  Stage 1: M=16 (mode 0) / M=32 (mode 1)
//----------------------------------------------------------------------
ConfigSdfUnit #(
    .WIDTH    (WIDTH),
    .DEPTH1_0 (8),
    .DEPTH1_1 (16),
    .DEPTH2_0 (4),
    .DEPTH2_1 (8),
    .LOG_M_0  (4),
    .LOG_M_1  (5)
) SU2 (
    .clock    (clock    ),
    .reset    (reset    ),
    .mode     (eff_mode ),
    .di_en    (su1_do_en),
    .di_re    (su1_do_re),
    .di_im    (su1_do_im),
    .tw_addr  (tw1_addr ),
    .tw_re_in (tw1_re   ),
    .tw_im_in (tw1_im   ),
    .do_en    (su2_do_en),
    .do_re    (su2_do_re),
    .do_im    (su2_do_im),
    .busy     (su2_busy )
);

//----------------------------------------------------------------------
//  Stage 2: M=4 (mode 0) / M=8 (mode 1)
//----------------------------------------------------------------------
ConfigSdfUnit #(
    .WIDTH    (WIDTH),
    .DEPTH1_0 (2),
    .DEPTH1_1 (4),
    .DEPTH2_0 (1),
    .DEPTH2_1 (2),
    .LOG_M_0  (2),
    .LOG_M_1  (3)
) SU3 (
    .clock    (clock    ),
    .reset    (reset    ),
    .mode     (eff_mode ),
    .di_en    (su2_do_en),
    .di_re    (su2_do_re),
    .di_im    (su2_do_im),
    .tw_addr  (tw2_addr ),
    .tw_re_in (tw2_re   ),
    .tw_im_in (tw2_im   ),
    .do_en    (su3_do_en),
    .do_re    (su3_do_re),
    .do_im    (su3_do_im),
    .busy     (su3_busy )
);

//----------------------------------------------------------------------
//  Stage 3: Radix-2 SdfUnit2 (Active only in 128-point mode)
//----------------------------------------------------------------------
wire su4_di_en = eff_mode ? su3_do_en : 1'b0;

SdfUnit2 #(
    .WIDTH (WIDTH),
    .BF_RH (0)
) SU4 (
    .clock (clock    ),
    .reset (reset    ),
    .di_en (su4_di_en),
    .di_re (su3_do_re),
    .di_im (su3_do_im),
    .do_en (su4_do_en),
    .do_re (su4_do_re),
    .do_im (su4_do_im),
    .busy  (su4_busy )
);

//----------------------------------------------------------------------
//  Output Selection
//----------------------------------------------------------------------
assign do_en = eff_mode ? su4_do_en : su3_do_en;
assign do_re = eff_mode ? su4_do_re : su3_do_re;
assign do_im = eff_mode ? su4_do_im : su3_do_im;

endmodule

//----------------------------------------------------------------------
//  ConfigSdfUnit: Configurable Radix-2^2 SDF Stage
//----------------------------------------------------------------------
module ConfigSdfUnit #(
    parameter WIDTH    = 16,
    parameter DEPTH1_0 = 32,
    parameter DEPTH1_1 = 64,
    parameter DEPTH2_0 = 16,
    parameter DEPTH2_1 = 32,
    parameter LOG_M_0  = 6,
    parameter LOG_M_1  = 7
)(
    input               clock,
    input               reset,
    input               mode,
    input               di_en,
    input   [WIDTH-1:0] di_re,
    input   [WIDTH-1:0] di_im,
    output  [6:0]       tw_addr,
    input   [WIDTH-1:0] tw_re_in,
    input   [WIDTH-1:0] tw_im_in,
    output              do_en,
    output  [WIDTH-1:0] do_re,
    output  [WIDTH-1:0] do_im,
    output              busy
);

wire [6:0] n_minus_1 = mode ? 7'd127 : 7'd63;

//  1st Butterfly
reg  [6:0]       di_count;
wire             bf1_bf;
wire [WIDTH-1:0] bf1_y0_re, bf1_y0_im;
wire [WIDTH-1:0] bf1_y1_re, bf1_y1_im;
wire [WIDTH-1:0] db1_di_re, db1_di_im;
wire [WIDTH-1:0] db1_do_re, db1_do_im;
wire [WIDTH-1:0] bf1_sp_re, bf1_sp_im;
reg              bf1_sp_en;
reg  [6:0]       bf1_count;
wire             bf1_start;
wire             bf1_end;
wire             bf1_mj;
reg  [WIDTH-1:0] bf1_do_re, bf1_do_im;

//  2nd Butterfly
reg              bf2_bf;
wire [WIDTH-1:0] bf2_y0_re, bf2_y0_im;
wire [WIDTH-1:0] bf2_y1_re, bf2_y1_im;
wire [WIDTH-1:0] db2_di_re, db2_di_im;
wire [WIDTH-1:0] db2_do_re, db2_do_im;
wire [WIDTH-1:0] bf2_sp_re, bf2_sp_im;
reg              bf2_sp_en;
reg  [6:0]       bf2_count;
reg              bf2_start;
wire             bf2_end;
reg  [WIDTH-1:0] bf2_do_re, bf2_do_im;
reg              bf2_do_en;

//  Multiplication
reg              mu_en;
reg  [WIDTH-1:0] tw_re, tw_im;
wire [WIDTH-1:0] mu_m_re, mu_m_im;
reg  [WIDTH-1:0] mu_do_re, mu_do_im;
reg              mu_do_en;

//----------------------------------------------------------------------
//  1st Butterfly Logic
//----------------------------------------------------------------------
always @(posedge clock or posedge reset) begin
    if (reset) begin
        di_count <= 7'd0;
    end else begin
        di_count <= di_en ? ((di_count == n_minus_1) ? 7'd0 : di_count + 7'd1) : 7'd0;
    end
end

assign bf1_bf = mode ? di_count[LOG_M_0] : di_count[LOG_M_0-1];

Butterfly #(.WIDTH(WIDTH), .RH(0)) BF1 (
    .x0_re (db1_do_re ),
    .x0_im (db1_do_im ),
    .x1_re (di_re     ),
    .x1_im (di_im     ),
    .y0_re (bf1_y0_re ),
    .y0_im (bf1_y0_im ),
    .y1_re (bf1_y1_re ),
    .y1_im (bf1_y1_im )
);

ConfigDelayBuffer #(
    .DEPTH0 (DEPTH1_0 ),
    .DEPTH1 (DEPTH1_1 ),
    .WIDTH  (WIDTH    )
) DB1 (
    .clock  (clock     ),
    .mode   (mode      ),
    .di_re  (db1_di_re ),
    .di_im  (db1_di_im ),
    .do_re  (db1_do_re ),
    .do_im  (db1_do_im )
);

assign db1_di_re = bf1_bf ? bf1_y1_re : di_re;
assign db1_di_im = bf1_bf ? bf1_y1_im : di_im;
assign bf1_sp_re = bf1_bf ? bf1_y0_re : bf1_mj ?  db1_do_im : db1_do_re;
assign bf1_sp_im = bf1_bf ? bf1_y0_im : bf1_mj ? -db1_do_re : db1_do_im;

wire [6:0] bf1_start_val = mode ? (DEPTH1_1 - 1) : (DEPTH1_0 - 1);
assign bf1_start = (di_count == bf1_start_val);
assign bf1_end   = (bf1_count == n_minus_1);

wire [1:0] mj_bits = mode ? bf1_count[LOG_M_0 : LOG_M_0-1] : bf1_count[LOG_M_0-1 : LOG_M_0-2];
assign bf1_mj = (mj_bits == 2'd3);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf1_sp_en <= 1'b0;
        bf1_count <= 7'd0;
    end else begin
        bf1_sp_en <= bf1_start ? 1'b1 : bf1_end ? 1'b0 : bf1_sp_en;
        bf1_count <= bf1_sp_en ? ((bf1_count == n_minus_1) ? 7'd0 : bf1_count + 7'd1) : 7'd0;
    end
end

always @(posedge clock) begin
    bf1_do_re <= bf1_sp_re;
    bf1_do_im <= bf1_sp_im;
end

//----------------------------------------------------------------------
//  2nd Butterfly Logic
//----------------------------------------------------------------------
always @(posedge clock) begin
    bf2_bf <= mode ? bf1_count[LOG_M_0-1] : bf1_count[LOG_M_0-2];
end

Butterfly #(.WIDTH(WIDTH), .RH(1)) BF2 (
    .x0_re (db2_do_re ),
    .x0_im (db2_do_im ),
    .x1_re (bf1_do_re ),
    .x1_im (bf1_do_im ),
    .y0_re (bf2_y0_re ),
    .y0_im (bf2_y0_im ),
    .y1_re (bf2_y1_re ),
    .y1_im (bf2_y1_im )
);

ConfigDelayBuffer #(
    .DEPTH0 (DEPTH2_0 ),
    .DEPTH1 (DEPTH2_1 ),
    .WIDTH  (WIDTH    )
) DB2 (
    .clock  (clock     ),
    .mode   (mode      ),
    .di_re  (db2_di_re ),
    .di_im  (db2_di_im ),
    .do_re  (db2_do_re ),
    .do_im  (db2_do_im )
);

assign db2_di_re = bf2_bf ? bf2_y1_re : bf1_do_re;
assign db2_di_im = bf2_bf ? bf2_y1_im : bf1_do_im;
assign bf2_sp_re = bf2_bf ? bf2_y0_re : db2_do_re;
assign bf2_sp_im = bf2_bf ? bf2_y0_im : db2_do_im;

wire [6:0] bf2_start_val = mode ? (DEPTH2_1 - 1) : (DEPTH2_0 - 1);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf2_sp_en <= 1'b0;
        bf2_count <= 7'd0;
    end else begin
        bf2_sp_en <= bf2_start ? 1'b1 : bf2_end ? 1'b0 : bf2_sp_en;
        bf2_count <= bf2_sp_en ? ((bf2_count == n_minus_1) ? 7'd0 : bf2_count + 7'd1) : 7'd0;
    end
end

always @(posedge clock) begin
    bf2_start <= (bf1_count == bf2_start_val) & bf1_sp_en;
end
assign bf2_end = (bf2_count == n_minus_1);

always @(posedge clock) begin
    bf2_do_re <= bf2_sp_re;
    bf2_do_im <= bf2_sp_im;
end

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf2_do_en <= 1'b0;
    end else begin
        bf2_do_en <= bf2_sp_en;
    end
end

//----------------------------------------------------------------------
//  Multiplication Logic
//----------------------------------------------------------------------
wire [1:0] tw_sel;
assign tw_sel[1] = mode ? bf2_count[LOG_M_0-1] : bf2_count[LOG_M_0-2];
assign tw_sel[0] = mode ? bf2_count[LOG_M_0]   : bf2_count[LOG_M_0-1];

localparam SHIFT = 6 - LOG_M_0;

wire [4:0] tw_num = mode ? ((bf2_count << SHIFT) & 5'h1f) :
                           ((bf2_count << (SHIFT + 1)) & 5'h1f);

assign tw_addr = tw_num * tw_sel;

always @(posedge clock) begin
    tw_re <= tw_re_in;
    tw_im <= tw_im_in;
    mu_en <= (tw_addr != 7'd0);
end

Multiply #(.WIDTH(WIDTH)) MU (
    .a_re (bf2_do_re ),
    .a_im (bf2_do_im ),
    .b_re (tw_re     ),
    .b_im (tw_im     ),
    .m_re (mu_m_re   ),
    .m_im (mu_m_im   )
);

always @(posedge clock) begin
    mu_do_re <= mu_en ? mu_m_re : bf2_do_re;
    mu_do_im <= mu_en ? mu_m_im : bf2_do_im;
end

always @(posedge clock or posedge reset) begin
    if (reset) begin
        mu_do_en <= 1'b0;
    end else begin
        mu_do_en <= bf2_do_en;
    end
end

wire [2:0] curr_log_m = mode ? LOG_M_1 : LOG_M_0;
wire       bypass_mul = (curr_log_m == 3'd2);

assign do_en = bypass_mul ? bf2_do_en : mu_do_en;
assign do_re = bypass_mul ? bf2_do_re : mu_do_re;
assign do_im = bypass_mul ? bf2_do_im : mu_do_im;

assign busy = bf1_sp_en | bf2_sp_en | bf2_do_en | mu_do_en | (di_count != 7'd0);

endmodule

//----------------------------------------------------------------------
//  SdfUnit2: Radix-2 SDF Dedicated for Twiddle Resolution M = 2
//----------------------------------------------------------------------
module SdfUnit2 #(
    parameter WIDTH = 16,
    parameter BF_RH = 0
)(
    input                   clock,
    input                   reset,
    input                   di_en,
    input       [WIDTH-1:0] di_re,
    input       [WIDTH-1:0] di_im,
    output  reg             do_en,
    output  reg [WIDTH-1:0] do_re,
    output  reg [WIDTH-1:0] do_im,
    output                  busy
);

reg             bf_en;
wire[WIDTH-1:0] y0_re, y0_im;
wire[WIDTH-1:0] y1_re, y1_im;
wire[WIDTH-1:0] db_di_re, db_di_im;
wire[WIDTH-1:0] db_do_re, db_do_im;
wire[WIDTH-1:0] bf_sp_re, bf_sp_im;
reg             bf_sp_en;

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf_en <= 1'b0;
    end else begin
        bf_en <= di_en ? ~bf_en : 1'b0;
    end
end

Butterfly #(.WIDTH(WIDTH), .RH(BF_RH)) BF (
    .x0_re (db_do_re ),
    .x0_im (db_do_im ),
    .x1_re (di_re    ),
    .x1_im (di_im    ),
    .y0_re (y0_re    ),
    .y0_im (y0_im    ),
    .y1_re (y1_re    ),
    .y1_im (y1_im    )
);

reg [WIDTH-1:0] db_buf_re;
reg [WIDTH-1:0] db_buf_im;

always @(posedge clock) begin
    db_buf_re <= db_di_re;
    db_buf_im <= db_di_im;
end

assign db_do_re = db_buf_re;
assign db_do_im = db_buf_im;

assign db_di_re = bf_en ? y1_re : di_re;
assign db_di_im = bf_en ? y1_im : di_im;
assign bf_sp_re = bf_en ? y0_re : db_do_re;
assign bf_sp_im = bf_en ? y0_im : db_do_im;

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf_sp_en <= 1'b0;
        do_en    <= 1'b0;
    end else begin
        bf_sp_en <= di_en;
        do_en    <= bf_sp_en;
    end
end

always @(posedge clock) begin
    do_re <= bf_sp_re;
    do_im <= bf_sp_im;
end

assign busy = bf_en | bf_sp_en | do_en;

endmodule

//----------------------------------------------------------------------
//  ConfigDelayBuffer: Constant Shift Delay with Selectable Mode Taps
//----------------------------------------------------------------------
module ConfigDelayBuffer #(
    parameter DEPTH0 = 32,
    parameter DEPTH1 = 64,
    parameter WIDTH  = 16
)(
    input               clock,
    input               mode,
    input   [WIDTH-1:0] di_re,
    input   [WIDTH-1:0] di_im,
    output  [WIDTH-1:0] do_re,
    output  [WIDTH-1:0] do_im
);

localparam MAX_DEPTH = (DEPTH1 > DEPTH0) ? DEPTH1 : DEPTH0;

reg [WIDTH-1:0] buf_re [0:MAX_DEPTH-1];
reg [WIDTH-1:0] buf_im [0:MAX_DEPTH-1];
integer n;

always @(posedge clock) begin
    for (n = MAX_DEPTH-1; n > 0; n = n - 1) begin
        buf_re[n] <= buf_re[n-1];
        buf_im[n] <= buf_im[n-1];
    end
    buf_re[0] <= di_re;
    buf_im[0] <= di_im;
end

assign do_re = mode ? buf_re[DEPTH1-1] : buf_re[DEPTH0-1];
assign do_im = mode ? buf_im[DEPTH1-1] : buf_im[DEPTH0-1];

endmodule

//----------------------------------------------------------------------
//  Butterfly: Add/Sub and Scaling
//----------------------------------------------------------------------
module Butterfly #(
    parameter WIDTH = 16,
    parameter RH    = 0   //  Round Half Up
)(
    input   signed [WIDTH-1:0] x0_re,
    input   signed [WIDTH-1:0] x0_im,
    input   signed [WIDTH-1:0] x1_re,
    input   signed [WIDTH-1:0] x1_im,
    output  signed [WIDTH-1:0] y0_re,
    output  signed [WIDTH-1:0] y0_im,
    output  signed [WIDTH-1:0] y1_re,
    output  signed [WIDTH-1:0] y1_im
);

wire signed [WIDTH:0] add_re, add_im, sub_re, sub_im;

assign add_re = x0_re + x1_re;
assign add_im = x0_im + x1_im;
assign sub_re = x0_re - x1_re;
assign sub_im = x0_im - x1_im;

assign y0_re = (add_re + RH) >>> 1;
assign y0_im = (add_im + RH) >>> 1;
assign y1_re = (sub_re + RH) >>> 1;
assign y1_im = (sub_im + RH) >>> 1;

endmodule

//----------------------------------------------------------------------
//  Multiply: Complex Multiplier
//----------------------------------------------------------------------
module Multiply #(
    parameter WIDTH = 16
)(
    input   signed [WIDTH-1:0] a_re,
    input   signed [WIDTH-1:0] a_im,
    input   signed [WIDTH-1:0] b_re,
    input   signed [WIDTH-1:0] b_im,
    output  signed [WIDTH-1:0] m_re,
    output  signed [WIDTH-1:0] m_im
);

wire signed [WIDTH*2-1:0] arbr, arbi, aibr, aibi;
wire signed [WIDTH-1:0]   sc_arbr, sc_arbi, sc_aibr, sc_aibi;

assign arbr = a_re * b_re;
assign arbi = a_re * b_im;
assign aibr = a_im * b_re;
assign aibi = a_im * b_im;

assign sc_arbr = arbr >>> (WIDTH-1);
assign sc_arbi = arbi >>> (WIDTH-1);
assign sc_aibr = aibr >>> (WIDTH-1);
assign sc_aibi = aibi >>> (WIDTH-1);

assign m_re = sc_arbr - sc_aibi;
assign m_im = sc_arbi + sc_aibr;

endmodule

//----------------------------------------------------------------------
//  TwiddleRom: 128-Point Twiddle Table with 3 Combinational Read Ports
//----------------------------------------------------------------------
module TwiddleRom (
    input  [6:0]  addr0,
    output [15:0] tw0_re,
    output [15:0] tw0_im,
    input  [6:0]  addr1,
    output [15:0] tw1_re,
    output [15:0] tw1_im,
    input  [6:0]  addr2,
    output [15:0] tw2_re,
    output [15:0] tw2_im
);

wire [15:0] wn_re[0:127];
wire [15:0] wn_im[0:127];

assign wn_re[  0] = 16'h0000; assign wn_im[  0] = 16'h0000;
assign wn_re[  1] = 16'h7FD9; assign wn_im[  1] = 16'hF9B8;
assign wn_re[  2] = 16'h7F62; assign wn_im[  2] = 16'hF374;
assign wn_re[  3] = 16'h7E9D; assign wn_im[  3] = 16'hED38;
assign wn_re[  4] = 16'h7D8A; assign wn_im[  4] = 16'hE707;
assign wn_re[  5] = 16'h7C2A; assign wn_im[  5] = 16'hE0E6;
assign wn_re[  6] = 16'h7A7D; assign wn_im[  6] = 16'hDAD8;
assign wn_re[  7] = 16'h7885; assign wn_im[  7] = 16'hD4E1;
assign wn_re[  8] = 16'h7642; assign wn_im[  8] = 16'hCF04;
assign wn_re[  9] = 16'h73B6; assign wn_im[  9] = 16'hC946;
assign wn_re[ 10] = 16'h70E3; assign wn_im[ 10] = 16'hC3A9;
assign wn_re[ 11] = 16'h6DCA; assign wn_im[ 11] = 16'hBE32;
assign wn_re[ 12] = 16'h6A6E; assign wn_im[ 12] = 16'hB8E3;
assign wn_re[ 13] = 16'h66D0; assign wn_im[ 13] = 16'hB3C0;
assign wn_re[ 14] = 16'h62F2; assign wn_im[ 14] = 16'hAECC;
assign wn_re[ 15] = 16'h5ED7; assign wn_im[ 15] = 16'hAA0A;
assign wn_re[ 16] = 16'h5A82; assign wn_im[ 16] = 16'hA57E;
assign wn_re[ 17] = 16'h55F6; assign wn_im[ 17] = 16'hA129;
assign wn_re[ 18] = 16'h5134; assign wn_im[ 18] = 16'h9D0E;
assign wn_re[ 19] = 16'h4C40; assign wn_im[ 19] = 16'h9930;
assign wn_re[ 20] = 16'h471D; assign wn_im[ 20] = 16'h9592;
assign wn_re[ 21] = 16'h41CE; assign wn_im[ 21] = 16'h9236;
assign wn_re[ 22] = 16'h3C57; assign wn_im[ 22] = 16'h8F1D;
assign wn_re[ 23] = 16'h36BA; assign wn_im[ 23] = 16'h8C4A;
assign wn_re[ 24] = 16'h30FC; assign wn_im[ 24] = 16'h89BE;
assign wn_re[ 25] = 16'h2B1F; assign wn_im[ 25] = 16'h877B;
assign wn_re[ 26] = 16'h2528; assign wn_im[ 26] = 16'h8583;
assign wn_re[ 27] = 16'h1F1A; assign wn_im[ 27] = 16'h83D6;
assign wn_re[ 28] = 16'h18F9; assign wn_im[ 28] = 16'h8276;
assign wn_re[ 29] = 16'h12C8; assign wn_im[ 29] = 16'h8163;
assign wn_re[ 30] = 16'h0C8C; assign wn_im[ 30] = 16'h809E;
assign wn_re[ 31] = 16'h0648; assign wn_im[ 31] = 16'h8027;
assign wn_re[ 32] = 16'h0000; assign wn_im[ 32] = 16'h8000;
assign wn_re[ 33] = 16'hF9B8; assign wn_im[ 33] = 16'h8027;
assign wn_re[ 34] = 16'hF374; assign wn_im[ 34] = 16'h809E;
assign wn_re[ 35] = 16'hxxxx; assign wn_im[ 35] = 16'hxxxx;
assign wn_re[ 36] = 16'hE707; assign wn_im[ 36] = 16'h8276;
assign wn_re[ 37] = 16'hxxxx; assign wn_im[ 37] = 16'hxxxx;
assign wn_re[ 38] = 16'hDAD8; assign wn_im[ 38] = 16'h8583;
assign wn_re[ 39] = 16'hD4E1; assign wn_im[ 39] = 16'h877B;
assign wn_re[ 40] = 16'hCF04; assign wn_im[ 40] = 16'h89BE;
assign wn_re[ 41] = 16'hxxxx; assign wn_im[ 41] = 16'hxxxx;
assign wn_re[ 42] = 16'hC3A9; assign wn_im[ 42] = 16'h8F1D;
assign wn_re[ 43] = 16'hxxxx; assign wn_im[ 43] = 16'hxxxx;
assign wn_re[ 44] = 16'hB8E3; assign wn_im[ 44] = 16'h9592;
assign wn_re[ 45] = 16'hB3C0; assign wn_im[ 45] = 16'h9930;
assign wn_re[ 46] = 16'hAECC; assign wn_im[ 46] = 16'h9D0E;
assign wn_re[ 47] = 16'hxxxx; assign wn_im[ 47] = 16'hxxxx;
assign wn_re[ 48] = 16'hA57E; assign wn_im[ 48] = 16'hA57E;
assign wn_re[ 49] = 16'hxxxx; assign wn_im[ 49] = 16'hxxxx;
assign wn_re[ 50] = 16'h9D0E; assign wn_im[ 50] = 16'hAECC;
assign wn_re[ 51] = 16'h9930; assign wn_im[ 51] = 16'hB3C0;
assign wn_re[ 52] = 16'h9592; assign wn_im[ 52] = 16'hB8E3;
assign wn_re[ 53] = 16'hxxxx; assign wn_im[ 53] = 16'hxxxx;
assign wn_re[ 54] = 16'h8F1D; assign wn_im[ 54] = 16'hC3A9;
assign wn_re[ 55] = 16'hxxxx; assign wn_im[ 55] = 16'hxxxx;
assign wn_re[ 56] = 16'h89BE; assign wn_im[ 56] = 16'hCF04;
assign wn_re[ 57] = 16'h877B; assign wn_im[ 57] = 16'hD4E1;
assign wn_re[ 58] = 16'h8583; assign wn_im[ 58] = 16'hDAD8;
assign wn_re[ 59] = 16'hxxxx; assign wn_im[ 59] = 16'hxxxx;
assign wn_re[ 60] = 16'h8276; assign wn_im[ 60] = 16'hE707;
assign wn_re[ 61] = 16'hxxxx; assign wn_im[ 61] = 16'hxxxx;
assign wn_re[ 62] = 16'h809E; assign wn_im[ 62] = 16'hF374;
assign wn_re[ 63] = 16'h8027; assign wn_im[ 63] = 16'hF9B8;
assign wn_re[ 64] = 16'hxxxx; assign wn_im[ 64] = 16'hxxxx;
assign wn_re[ 65] = 16'hxxxx; assign wn_im[ 65] = 16'hxxxx;
assign wn_re[ 66] = 16'h809E; assign wn_im[ 66] = 16'h0C8C;
assign wn_re[ 67] = 16'hxxxx; assign wn_im[ 67] = 16'hxxxx;
assign wn_re[ 68] = 16'hxxxx; assign wn_im[ 68] = 16'hxxxx;
assign wn_re[ 69] = 16'h83D6; assign wn_im[ 69] = 16'h1F1A;
assign wn_re[ 70] = 16'hxxxx; assign wn_im[ 70] = 16'hxxxx;
assign wn_re[ 71] = 16'hxxxx; assign wn_im[ 71] = 16'hxxxx;
assign wn_re[ 72] = 16'h89BE; assign wn_im[ 72] = 16'h30FC;
assign wn_re[ 73] = 16'hxxxx; assign wn_im[ 73] = 16'hxxxx;
assign wn_re[ 74] = 16'hxxxx; assign wn_im[ 74] = 16'hxxxx;
assign wn_re[ 75] = 16'h9236; assign wn_im[ 75] = 16'h41CE;
assign wn_re[ 76] = 16'hxxxx; assign wn_im[ 76] = 16'hxxxx;
assign wn_re[ 77] = 16'hxxxx; assign wn_im[ 77] = 16'hxxxx;
assign wn_re[ 78] = 16'h9D0E; assign wn_im[ 78] = 16'h5134;
assign wn_re[ 79] = 16'hxxxx; assign wn_im[ 79] = 16'hxxxx;
assign wn_re[ 80] = 16'hxxxx; assign wn_im[ 80] = 16'hxxxx;
assign wn_re[ 81] = 16'hAA0A; assign wn_im[ 81] = 16'h5ED7;
assign wn_re[ 82] = 16'hxxxx; assign wn_im[ 82] = 16'hxxxx;
assign wn_re[ 83] = 16'hxxxx; assign wn_im[ 83] = 16'hxxxx;
assign wn_re[ 84] = 16'hB8E3; assign wn_im[ 84] = 16'h6A6E;
assign wn_re[ 85] = 16'hxxxx; assign wn_im[ 85] = 16'hxxxx;
assign wn_re[ 86] = 16'hxxxx; assign wn_im[ 86] = 16'hxxxx;
assign wn_re[ 87] = 16'hC946; assign wn_im[ 87] = 16'h73B6;
assign wn_re[ 88] = 16'hxxxx; assign wn_im[ 88] = 16'hxxxx;
assign wn_re[ 89] = 16'hxxxx; assign wn_im[ 89] = 16'hxxxx;
assign wn_re[ 90] = 16'hDAD8; assign wn_im[ 90] = 16'h7A7D;
assign wn_re[ 91] = 16'hxxxx; assign wn_im[ 91] = 16'hxxxx;
assign wn_re[ 92] = 16'hxxxx; assign wn_im[ 92] = 16'hxxxx;
assign wn_re[ 93] = 16'hED38; assign wn_im[ 93] = 16'h7E9D;
assign wn_re[ 94] = 16'hxxxx; assign wn_im[ 94] = 16'hxxxx;
assign wn_re[ 95] = 16'hxxxx; assign wn_im[ 95] = 16'hxxxx;
assign wn_re[ 96] = 16'hxxxx; assign wn_im[ 96] = 16'hxxxx;
assign wn_re[ 97] = 16'hxxxx; assign wn_im[ 97] = 16'hxxxx;
assign wn_re[ 98] = 16'hxxxx; assign wn_im[ 98] = 16'hxxxx;
assign wn_re[ 99] = 16'hxxxx; assign wn_im[ 99] = 16'hxxxx;
assign wn_re[100] = 16'hxxxx; assign wn_im[100] = 16'hxxxx;
assign wn_re[101] = 16'hxxxx; assign wn_im[101] = 16'hxxxx;
assign wn_re[102] = 16'hxxxx; assign wn_im[102] = 16'hxxxx;
assign wn_re[103] = 16'hxxxx; assign wn_im[103] = 16'hxxxx;
assign wn_re[104] = 16'hxxxx; assign wn_im[104] = 16'hxxxx;
assign wn_re[105] = 16'hxxxx; assign wn_im[105] = 16'hxxxx;
assign wn_re[106] = 16'hxxxx; assign wn_im[106] = 16'hxxxx;
assign wn_re[107] = 16'hxxxx; assign wn_im[107] = 16'hxxxx;
assign wn_re[108] = 16'hxxxx; assign wn_im[108] = 16'hxxxx;
assign wn_re[109] = 16'hxxxx; assign wn_im[109] = 16'hxxxx;
assign wn_re[110] = 16'hxxxx; assign wn_im[110] = 16'hxxxx;
assign wn_re[111] = 16'hxxxx; assign wn_im[111] = 16'hxxxx;
assign wn_re[112] = 16'hxxxx; assign wn_im[112] = 16'hxxxx;
assign wn_re[113] = 16'hxxxx; assign wn_im[113] = 16'hxxxx;
assign wn_re[114] = 16'hxxxx; assign wn_im[114] = 16'hxxxx;
assign wn_re[115] = 16'hxxxx; assign wn_im[115] = 16'hxxxx;
assign wn_re[116] = 16'hxxxx; assign wn_im[116] = 16'hxxxx;
assign wn_re[117] = 16'hxxxx; assign wn_im[117] = 16'hxxxx;
assign wn_re[118] = 16'hxxxx; assign wn_im[118] = 16'hxxxx;
assign wn_re[119] = 16'hxxxx; assign wn_im[119] = 16'hxxxx;
assign wn_re[120] = 16'hxxxx; assign wn_im[120] = 16'hxxxx;
assign wn_re[121] = 16'hxxxx; assign wn_im[121] = 16'hxxxx;
assign wn_re[122] = 16'hxxxx; assign wn_im[122] = 16'hxxxx;
assign wn_re[123] = 16'hxxxx; assign wn_im[123] = 16'hxxxx;
assign wn_re[124] = 16'hxxxx; assign wn_im[124] = 16'hxxxx;
assign wn_re[125] = 16'hxxxx; assign wn_im[125] = 16'hxxxx;
assign wn_re[126] = 16'hxxxx; assign wn_im[126] = 16'hxxxx;
assign wn_re[127] = 16'hxxxx; assign wn_im[127] = 16'hxxxx;

assign tw0_re = wn_re[addr0];
assign tw0_im = wn_im[addr0];
assign tw1_re = wn_re[addr1];
assign tw1_im = wn_im[addr1];
assign tw2_re = wn_re[addr2];
assign tw2_im = wn_im[addr2];

endmodule
