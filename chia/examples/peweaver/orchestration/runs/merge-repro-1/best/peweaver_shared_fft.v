//----------------------------------------------------------------------
//  peweaver_shared_fft: Merged 64/128-Point Radix-2^2 SDF FFT Core
//----------------------------------------------------------------------
module peweaver_shared_fft #(
    parameter integer WIDTH = 16
)(
    input               clock,
    input               reset,
    input               mode,
    input               di_en,
    input       [15:0]  di_re,
    input       [15:0]  di_im,
    output              do_en,
    output      [15:0]  do_re,
    output      [15:0]  do_im
);

//----------------------------------------------------------------------
//  Mode Capture and Outstanding Counter Logic
//----------------------------------------------------------------------
reg         mode_q;
reg [8:0]   outstanding;

wire        idle = (outstanding == 9'd0);
wire        cur_mode = idle ? mode : mode_q;

always @(posedge clock or posedge reset) begin
    if (reset) begin
        mode_q      <= 1'b0;
        outstanding <= 9'd0;
    end else begin
        if (idle && di_en) begin
            mode_q <= mode;
        end
        case ({di_en, do_en})
            2'b10:   outstanding <= outstanding + 1'b1;
            2'b01:   outstanding <= outstanding - 1'b1;
            default: outstanding <= outstanding;
        endcase
    end
end

//----------------------------------------------------------------------
//  Pipeline Interconnect
//----------------------------------------------------------------------
wire        su0_do_en;
wire [15:0] su0_do_re;
wire [15:0] su0_do_im;

wire        su1_do_en;
wire [15:0] su1_do_re;
wire [15:0] su1_do_im;

wire        su2_do_en;
wire [15:0] su2_do_re;
wire [15:0] su2_do_im;

wire        su3_do_en;
wire [15:0] su3_do_re;
wire [15:0] su3_do_im;

// CSDF0: 64-mode: N=64, M=64 (DB1=32, DB2=16); 128-mode: N=128, M=128 (DB1=64, DB2=32)
CSDFStage #(
    .LM_64      (6),
    .DB1_D0     (32),
    .DB1_D1     (64),
    .DB2_D0     (16),
    .DB2_D1     (32),
    .SHIFT      (0),
    .BYPASS_M0  (0)
) CSDF0 (
    .clock      (clock),
    .reset      (reset),
    .mode       (cur_mode),
    .di_en      (di_en),
    .di_re      (di_re),
    .di_im      (di_im),
    .do_en      (su0_do_en),
    .do_re      (su0_do_re),
    .do_im      (su0_do_im)
);

// CSDF1: 64-mode: N=64, M=16 (DB1=8, DB2=4); 128-mode: N=128, M=32 (DB1=16, DB2=8)
CSDFStage #(
    .LM_64      (4),
    .DB1_D0     (8),
    .DB1_D1     (16),
    .DB2_D0     (4),
    .DB2_D1     (8),
    .SHIFT      (2),
    .BYPASS_M0  (0)
) CSDF1 (
    .clock      (clock),
    .reset      (reset),
    .mode       (cur_mode),
    .di_en      (su0_do_en),
    .di_re      (su0_do_re),
    .di_im      (su0_do_im),
    .do_en      (su1_do_en),
    .do_re      (su1_do_re),
    .do_im      (su1_do_im)
);

// CSDF2: 64-mode: N=64, M=4 (DB1=2, DB2=1, bypass mult); 128-mode: N=128, M=8 (DB1=4, DB2=2)
CSDFStage #(
    .LM_64      (2),
    .DB1_D0     (2),
    .DB1_D1     (4),
    .DB2_D0     (1),
    .DB2_D1     (2),
    .SHIFT      (4),
    .BYPASS_M0  (1)
) CSDF2 (
    .clock      (clock),
    .reset      (reset),
    .mode       (cur_mode),
    .di_en      (su1_do_en),
    .di_re      (su1_do_re),
    .di_im      (su1_do_im),
    .do_en      (su2_do_en),
    .do_re      (su2_do_re),
    .do_im      (su2_do_im)
);

// R2_FINAL: Radix-2 stage for 128-point mode only (bypassed in 64-point mode)
wire su3_di_en = cur_mode ? su2_do_en : 1'b0;

SdfUnit2 #(
    .WIDTH      (16),
    .BF_RH      (0)
) R2_FINAL (
    .clock      (clock),
    .reset      (reset),
    .di_en      (su3_di_en),
    .di_re      (su2_do_re),
    .di_im      (su2_do_im),
    .do_en      (su3_do_en),
    .do_re      (su3_do_re),
    .do_im      (su3_do_im)
);

assign do_en = cur_mode ? su3_do_en : su2_do_en;
assign do_re = cur_mode ? su3_do_re : su2_do_re;
assign do_im = cur_mode ? su3_do_im : su2_do_im;

endmodule

//----------------------------------------------------------------------
//  CSDFStage: Configurable Radix-2^2 Single-Path Delay Feedback Stage
//----------------------------------------------------------------------
module CSDFStage #(
    parameter LM_64      = 6,
    parameter DB1_D0     = 32,
    parameter DB1_D1     = 64,
    parameter DB2_D0     = 16,
    parameter DB2_D1     = 32,
    parameter SHIFT      = 0,
    parameter BYPASS_M0  = 0
)(
    input               clock,
    input               reset,
    input               mode,
    input               di_en,
    input       [15:0]  di_re,
    input       [15:0]  di_im,
    output              do_en,
    output      [15:0]  do_re,
    output      [15:0]  do_im
);

// 1st Butterfly
reg  [6:0]  di_count;
wire        bf1_bf;
wire [15:0] db1_di_re;
wire [15:0] db1_di_im;
wire [15:0] db1_do_re;
wire [15:0] db1_do_im;
wire [15:0] bf1_y0_re;
wire [15:0] bf1_y0_im;
wire [15:0] bf1_y1_re;
wire [15:0] bf1_y1_im;
wire [15:0] bf1_sp_re;
wire [15:0] bf1_sp_im;
reg         bf1_sp_en;
reg  [6:0]  bf1_count;
wire        bf1_start;
wire        bf1_end;
wire        bf1_mj;
reg  [15:0] bf1_do_re;
reg  [15:0] bf1_do_im;

// 2nd Butterfly
reg         bf2_bf;
wire [15:0] db2_di_re;
wire [15:0] db2_di_im;
wire [15:0] db2_do_re;
wire [15:0] db2_do_im;
wire [15:0] bf2_y0_re;
wire [15:0] bf2_y0_im;
wire [15:0] bf2_y1_re;
wire [15:0] bf2_y1_im;
wire [15:0] bf2_sp_re;
wire [15:0] bf2_sp_im;
reg         bf2_sp_en;
reg  [6:0]  bf2_count;
reg         bf2_start;
wire        bf2_end;
reg  [15:0] bf2_do_re;
reg  [15:0] bf2_do_im;
reg         bf2_do_en;

// Multiplication
wire [1:0]  tw_sel;
wire [3:0]  tw_num_6;
wire [5:0]  tw_addr_6;
wire [4:0]  tw_num_7;
wire [6:0]  tw_addr_7;
wire [6:0]  rom_addr;
wire [15:0] tw_re;
wire [15:0] tw_im;
reg         mu_en;
wire [15:0] mu_m_re;
wire [15:0] mu_m_im;
reg  [15:0] mu_do_re;
reg  [15:0] mu_do_im;
reg         mu_do_en;

//----------------------------------------------------------------------
// 1st Butterfly
//----------------------------------------------------------------------
wire [6:0] count_max = mode ? 7'd127 : 7'd63;

always @(posedge clock or posedge reset) begin
    if (reset) begin
        di_count <= 7'd0;
    end else begin
        di_count <= di_en ? (mode ? (di_count + 1'b1) : {1'b0, di_count[5:0] + 1'b1}) : 7'd0;
    end
end

assign bf1_bf = mode ? di_count[LM_64] : di_count[LM_64 - 1];

Butterfly #(.WIDTH(16), .RH(0)) BF1 (
    .x0_re  (db1_do_re),
    .x0_im  (db1_do_im),
    .x1_re  (di_re),
    .x1_im  (di_im),
    .y0_re  (bf1_y0_re),
    .y0_im  (bf1_y0_im),
    .y1_re  (bf1_y1_re),
    .y1_im  (bf1_y1_im)
);

ShiftDelayBuffer #(.DEPTH0(DB1_D0), .DEPTH1(DB1_D1), .WIDTH(16)) DB1 (
    .clock  (clock),
    .sel    (mode),
    .di_re  (db1_di_re),
    .di_im  (db1_di_im),
    .do_re  (db1_do_re),
    .do_im  (db1_do_im)
);

assign db1_di_re = bf1_bf ? bf1_y1_re : di_re;
assign db1_di_im = bf1_bf ? bf1_y1_im : di_im;
assign bf1_sp_re = bf1_bf ? bf1_y0_re : bf1_mj ?  db1_do_im : db1_do_re;
assign bf1_sp_im = bf1_bf ? bf1_y0_im : bf1_mj ? -db1_do_re : db1_do_im;

wire [6:0] bf1_start_val = mode ? ((7'd1 << LM_64) - 1'b1) : ((7'd1 << (LM_64 - 1)) - 1'b1);
assign bf1_start = (di_count == bf1_start_val);
assign bf1_end   = (bf1_count == count_max);

wire [1:0] bf1_mj_sel = mode ? bf1_count[LM_64 : LM_64 - 1] : bf1_count[LM_64 - 1 : LM_64 - 2];
assign bf1_mj = (bf1_mj_sel == 2'd3);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf1_sp_en <= 1'b0;
        bf1_count <= 7'd0;
    end else begin
        bf1_sp_en <= bf1_start ? 1'b1 : bf1_end ? 1'b0 : bf1_sp_en;
        bf1_count <= bf1_sp_en ? (mode ? (bf1_count + 1'b1) : {1'b0, bf1_count[5:0] + 1'b1}) : 7'd0;
    end
end

always @(posedge clock) begin
    bf1_do_re <= bf1_sp_re;
    bf1_do_im <= bf1_sp_im;
end

//----------------------------------------------------------------------
// 2nd Butterfly
//----------------------------------------------------------------------
always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf2_bf <= 1'b0;
    end else begin
        bf2_bf <= mode ? bf1_count[LM_64 - 1] : bf1_count[LM_64 - 2];
    end
end

Butterfly #(.WIDTH(16), .RH(1)) BF2 (
    .x0_re  (db2_do_re),
    .x0_im  (db2_do_im),
    .x1_re  (bf1_do_re),
    .x1_im  (bf1_do_im),
    .y0_re  (bf2_y0_re),
    .y0_im  (bf2_y0_im),
    .y1_re  (bf2_y1_re),
    .y1_im  (bf2_y1_im)
);

ShiftDelayBuffer #(.DEPTH0(DB2_D0), .DEPTH1(DB2_D1), .WIDTH(16)) DB2 (
    .clock  (clock),
    .sel    (mode),
    .di_re  (db2_di_re),
    .di_im  (db2_di_im),
    .do_re  (db2_do_re),
    .do_im  (db2_do_im)
);

assign db2_di_re = bf2_bf ? bf2_y1_re : bf1_do_re;
assign db2_di_im = bf2_bf ? bf2_y1_im : bf1_do_im;
assign bf2_sp_re = bf2_bf ? bf2_y0_re : db2_do_re;
assign bf2_sp_im = bf2_bf ? bf2_y0_im : db2_do_im;

wire [6:0] bf2_start_val = mode ? ((7'd1 << (LM_64 - 1)) - 1'b1) : ((7'd1 << (LM_64 - 2)) - 1'b1);
assign bf2_end = (bf2_count == count_max);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf2_start <= 1'b0;
    end else begin
        bf2_start <= (bf1_count == bf2_start_val) & bf1_sp_en;
    end
end

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf2_sp_en <= 1'b0;
        bf2_count <= 7'd0;
    end else begin
        bf2_sp_en <= bf2_start ? 1'b1 : bf2_end ? 1'b0 : bf2_sp_en;
        bf2_count <= bf2_sp_en ? (mode ? (bf2_count + 1'b1) : {1'b0, bf2_count[5:0] + 1'b1}) : 7'd0;
    end
end

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
// Multiplication
//----------------------------------------------------------------------
assign tw_sel[1] = mode ? bf2_count[LM_64 - 1] : bf2_count[LM_64 - 2];
assign tw_sel[0] = mode ? bf2_count[LM_64]     : bf2_count[LM_64 - 1];

assign tw_num_6  = bf2_count << SHIFT;
assign tw_addr_6 = tw_num_6 * tw_sel;

assign tw_num_7  = bf2_count << SHIFT;
assign tw_addr_7 = tw_num_7 * tw_sel;

assign rom_addr  = mode ? tw_addr_7 : {tw_addr_6, 1'b0};

TwiddleRom TW (
    .clock  (clock),
    .addr   (rom_addr),
    .tw_re  (tw_re),
    .tw_im  (tw_im)
);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        mu_en <= 1'b0;
    end else begin
        mu_en <= (rom_addr != 7'd0);
    end
end

Multiply #(.WIDTH(16)) MU (
    .a_re   (bf2_do_re),
    .a_im   (bf2_do_im),
    .b_re   (tw_re),
    .b_im   (tw_im),
    .m_re   (mu_m_re),
    .m_im   (mu_m_im)
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

assign do_en = (BYPASS_M0 && !mode) ? bf2_do_en : mu_do_en;
assign do_re = (BYPASS_M0 && !mode) ? bf2_do_re : mu_do_re;
assign do_im = (BYPASS_M0 && !mode) ? bf2_do_im : mu_do_im;

endmodule

//----------------------------------------------------------------------
//  SdfUnit2: Radix-2 SDF Dedicated for Twiddle Resolution M = 2
//----------------------------------------------------------------------
module SdfUnit2 #(
    parameter   WIDTH = 16,
    parameter   BF_RH = 0
)(
    input                   clock,
    input                   reset,
    input                   di_en,
    input       [WIDTH-1:0] di_re,
    input       [WIDTH-1:0] di_im,
    output  reg             do_en,
    output  reg [WIDTH-1:0] do_re,
    output  reg [WIDTH-1:0] do_im
);

reg             bf_en;
wire[WIDTH-1:0] y0_re;
wire[WIDTH-1:0] y0_im;
wire[WIDTH-1:0] y1_re;
wire[WIDTH-1:0] y1_im;
wire[WIDTH-1:0] db_di_re;
wire[WIDTH-1:0] db_di_im;
wire[WIDTH-1:0] db_do_re;
wire[WIDTH-1:0] db_do_im;
wire[WIDTH-1:0] bf_sp_re;
wire[WIDTH-1:0] bf_sp_im;
reg             bf_sp_en;

always @(posedge clock or posedge reset) begin
    if (reset) begin
        bf_en <= 1'b0;
    end else begin
        bf_en <= di_en ? ~bf_en : 1'b0;
    end
end

Butterfly #(.WIDTH(WIDTH), .RH(BF_RH)) BF (
    .x0_re  (db_do_re),
    .x0_im  (db_do_im),
    .x1_re  (di_re),
    .x1_im  (di_im),
    .y0_re  (y0_re),
    .y0_im  (y0_im),
    .y1_re  (y1_re),
    .y1_im  (y1_im)
);

DelayBuffer #(.DEPTH(1), .WIDTH(WIDTH)) DB (
    .clock  (clock),
    .di_re  (db_di_re),
    .di_im  (db_di_im),
    .do_re  (db_do_re),
    .do_im  (db_do_im)
);

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

endmodule

//----------------------------------------------------------------------
//  Butterfly: Add/Sub and Scaling
//----------------------------------------------------------------------
module Butterfly #(
    parameter   WIDTH = 16,
    parameter   RH    = 0
)(
    input   signed  [WIDTH-1:0] x0_re,
    input   signed  [WIDTH-1:0] x0_im,
    input   signed  [WIDTH-1:0] x1_re,
    input   signed  [WIDTH-1:0] x1_im,
    output  signed  [WIDTH-1:0] y0_re,
    output  signed  [WIDTH-1:0] y0_im,
    output  signed  [WIDTH-1:0] y1_re,
    output  signed  [WIDTH-1:0] y1_im
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
//  ShiftDelayBuffer: Mode-Tapped Shift Register Delay
//----------------------------------------------------------------------
module ShiftDelayBuffer #(
    parameter DEPTH0 = 32,
    parameter DEPTH1 = 64,
    parameter WIDTH  = 16
)(
    input               clock,
    input               sel,
    input   [WIDTH-1:0] di_re,
    input   [WIDTH-1:0] di_im,
    output  [WIDTH-1:0] do_re,
    output  [WIDTH-1:0] do_im
);

reg [WIDTH-1:0] buf_re [0:DEPTH1-1];
reg [WIDTH-1:0] buf_im [0:DEPTH1-1];
integer n;

always @(posedge clock) begin
    for (n = DEPTH1-1; n > 0; n = n - 1) begin
        buf_re[n] <= buf_re[n-1];
        buf_im[n] <= buf_im[n-1];
    end
    buf_re[0] <= di_re;
    buf_im[0] <= di_im;
end

assign do_re = sel ? buf_re[DEPTH1-1] : buf_re[DEPTH0-1];
assign do_im = sel ? buf_im[DEPTH1-1] : buf_im[DEPTH0-1];

endmodule

//----------------------------------------------------------------------
//  DelayBuffer: Fixed-Depth Shift Register Delay
//----------------------------------------------------------------------
module DelayBuffer #(
    parameter DEPTH = 1,
    parameter WIDTH = 16
)(
    input               clock,
    input   [WIDTH-1:0] di_re,
    input   [WIDTH-1:0] di_im,
    output  [WIDTH-1:0] do_re,
    output  [WIDTH-1:0] do_im
);

reg [WIDTH-1:0] buf_re [0:DEPTH-1];
reg [WIDTH-1:0] buf_im [0:DEPTH-1];
integer n;

always @(posedge clock) begin
    for (n = DEPTH-1; n > 0; n = n - 1) begin
        buf_re[n] <= buf_re[n-1];
        buf_im[n] <= buf_im[n-1];
    end
    buf_re[0] <= di_re;
    buf_im[0] <= di_im;
end

assign do_re = buf_re[DEPTH-1];
assign do_im = buf_im[DEPTH-1];

endmodule

//----------------------------------------------------------------------
//  Multiply: Complex Multiplier
//----------------------------------------------------------------------
module Multiply #(
    parameter   WIDTH = 16
)(
    input   signed  [WIDTH-1:0] a_re,
    input   signed  [WIDTH-1:0] a_im,
    input   signed  [WIDTH-1:0] b_re,
    input   signed  [WIDTH-1:0] b_im,
    output  signed  [WIDTH-1:0] m_re,
    output  signed  [WIDTH-1:0] m_im
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
//  TwiddleRom: 128-Point Twiddle Coefficient ROM
//----------------------------------------------------------------------
module TwiddleRom (
    input               clock,
    input       [6:0]   addr,
    output reg  [15:0]  tw_re,
    output reg  [15:0]  tw_im
);

reg [15:0] lut_re;
reg [15:0] lut_im;

always @(*) begin
    case (addr)
        7'd0:   begin lut_re = 16'h0000; lut_im = 16'h0000; end
        7'd1:   begin lut_re = 16'h7FD9; lut_im = 16'hF9B8; end
        7'd2:   begin lut_re = 16'h7F62; lut_im = 16'hF374; end
        7'd3:   begin lut_re = 16'h7E9D; lut_im = 16'hED38; end
        7'd4:   begin lut_re = 16'h7D8A; lut_im = 16'hE707; end
        7'd5:   begin lut_re = 16'h7C2A; lut_im = 16'hE0E6; end
        7'd6:   begin lut_re = 16'h7A7D; lut_im = 16'hDAD8; end
        7'd7:   begin lut_re = 16'h7885; lut_im = 16'hD4E1; end
        7'd8:   begin lut_re = 16'h7642; lut_im = 16'hCF04; end
        7'd9:   begin lut_re = 16'h73B6; lut_im = 16'hC946; end
        7'd10:  begin lut_re = 16'h70E3; lut_im = 16'hC3A9; end
        7'd11:  begin lut_re = 16'h6DCA; lut_im = 16'hBE32; end
        7'd12:  begin lut_re = 16'h6A6E; lut_im = 16'hB8E3; end
        7'd13:  begin lut_re = 16'h66D0; lut_im = 16'hB3C0; end
        7'd14:  begin lut_re = 16'h62F2; lut_im = 16'hAECC; end
        7'd15:  begin lut_re = 16'h5ED7; lut_im = 16'hAA0A; end
        7'd16:  begin lut_re = 16'h5A82; lut_im = 16'hA57E; end
        7'd17:  begin lut_re = 16'h55F6; lut_im = 16'hA129; end
        7'd18:  begin lut_re = 16'h5134; lut_im = 16'h9D0E; end
        7'd19:  begin lut_re = 16'h4C40; lut_im = 16'h9930; end
        7'd20:  begin lut_re = 16'h471D; lut_im = 16'h9592; end
        7'd21:  begin lut_re = 16'h41CE; lut_im = 16'h9236; end
        7'd22:  begin lut_re = 16'h3C57; lut_im = 16'h8F1D; end
        7'd23:  begin lut_re = 16'h36BA; lut_im = 16'h8C4A; end
        7'd24:  begin lut_re = 16'h30FC; lut_im = 16'h89BE; end
        7'd25:  begin lut_re = 16'h2B1F; lut_im = 16'h877B; end
        7'd26:  begin lut_re = 16'h2528; lut_im = 16'h8583; end
        7'd27:  begin lut_re = 16'h1F1A; lut_im = 16'h83D6; end
        7'd28:  begin lut_re = 16'h18F9; lut_im = 16'h8276; end
        7'd29:  begin lut_re = 16'h12C8; lut_im = 16'h8163; end
        7'd30:  begin lut_re = 16'h0C8C; lut_im = 16'h809E; end
        7'd31:  begin lut_re = 16'h0648; lut_im = 16'h8027; end
        7'd32:  begin lut_re = 16'h0000; lut_im = 16'h8000; end
        7'd33:  begin lut_re = 16'hF9B8; lut_im = 16'h8027; end
        7'd34:  begin lut_re = 16'hF374; lut_im = 16'h809E; end
        7'd36:  begin lut_re = 16'hE707; lut_im = 16'h8276; end
        7'd38:  begin lut_re = 16'hDAD8; lut_im = 16'h8583; end
        7'd39:  begin lut_re = 16'hD4E1; lut_im = 16'h877B; end
        7'd40:  begin lut_re = 16'hCF04; lut_im = 16'h89BE; end
        7'd42:  begin lut_re = 16'hC3A9; lut_im = 16'h8F1D; end
        7'd44:  begin lut_re = 16'hB8E3; lut_im = 16'h9592; end
        7'd45:  begin lut_re = 16'hB3C0; lut_im = 16'h9930; end
        7'd46:  begin lut_re = 16'hAECC; lut_im = 16'h9D0E; end
        7'd48:  begin lut_re = 16'hA57E; lut_im = 16'hA57E; end
        7'd50:  begin lut_re = 16'h9D0E; lut_im = 16'hAECC; end
        7'd51:  begin lut_re = 16'h9930; lut_im = 16'hB3C0; end
        7'd52:  begin lut_re = 16'h9592; lut_im = 16'hB8E3; end
        7'd54:  begin lut_re = 16'h8F1D; lut_im = 16'hC3A9; end
        7'd56:  begin lut_re = 16'h89BE; lut_im = 16'hCF04; end
        7'd57:  begin lut_re = 16'h877B; lut_im = 16'hD4E1; end
        7'd58:  begin lut_re = 16'h8583; lut_im = 16'hDAD8; end
        7'd60:  begin lut_re = 16'h8276; lut_im = 16'hE707; end
        7'd62:  begin lut_re = 16'h809E; lut_im = 16'hF374; end
        7'd63:  begin lut_re = 16'h8027; lut_im = 16'hF9B8; end
        7'd66:  begin lut_re = 16'h809E; lut_im = 16'h0C8C; end
        7'd69:  begin lut_re = 16'h83D6; lut_im = 16'h1F1A; end
        7'd72:  begin lut_re = 16'h89BE; lut_im = 16'h30FC; end
        7'd75:  begin lut_re = 16'h9236; lut_im = 16'h41CE; end
        7'd78:  begin lut_re = 16'h9D0E; lut_im = 16'h5134; end
        7'd81:  begin lut_re = 16'hAA0A; lut_im = 16'h5ED7; end
        7'd84:  begin lut_re = 16'hB8E3; lut_im = 16'h6A6E; end
        7'd87:  begin lut_re = 16'hC946; lut_im = 16'h73B6; end
        7'd90:  begin lut_re = 16'hDAD8; lut_im = 16'h7A7D; end
        7'd93:  begin lut_re = 16'hED38; lut_im = 16'h7E9D; end
        default: begin lut_re = 16'h0000; lut_im = 16'h0000; end
    endcase
end

always @(posedge clock) begin
    tw_re <= lut_re;
    tw_im <= lut_im;
end

endmodule
