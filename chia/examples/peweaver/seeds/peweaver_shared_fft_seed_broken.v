//----------------------------------------------------------------------
// PEWeaver Shared Configurable FFT (Phase 4)
//
// Mode-selectable r2²SDF: 64-point (mode=0) or 128-point (mode=1).
//
// PEWeaver-owned RTL. Architecture follows the pinned SdfUnit.v control/
// register timing exactly, with mode-muxed parameters. Three shared stages
// + a 128-mode-only final radix-2 (SdfUnit2 pattern). One Twiddle128 ROM.
//
// Delay buffers: max-depth (128-mode size), mode-muxed read tap serves
// both the butterfly x0 input and the single-path output mux. In 64-mode
// the tap is at half-depth, giving the correct shorter delay.
//
// Twiddle addressing:
//   128-mode: addr = (tw_num * tw_sel) & 0x7F, direct Twiddle128 lookup
//   64-mode:  addr = 2 * ((tw_num_64 * tw_sel_64) & 0x3F), Twiddle128 lookup
//   because W64[n] = W128[2n] (same angle, same Q1.15 rounding).
//
// Mode is held for a frame set; reset is required between mode changes.
//----------------------------------------------------------------------

`timescale 1ns/1ps

module peweaver_shared_fft #(parameter WIDTH = 16) (
    input  wire             clock,
    input  wire             reset,
    input  wire             mode,       // 0 = 64-point, 1 = 128-point
    input  wire             di_en,
    input  wire [WIDTH-1:0] di_re,
    input  wire [WIDTH-1:0] di_im,
    output wire             do_en,
    output wire [WIDTH-1:0] do_re,
    output wire [WIDTH-1:0] do_im
);

//----------------------------------------------------------------------
// Stage 1: LOG_M = 6 (64-pt) / 7 (128-pt); db1=32/64, db2=16/32
//----------------------------------------------------------------------

reg [6:0] s1_cnt;
always @(posedge clock or posedge reset) begin
    if (reset) s1_cnt <= 0;
    else if (di_en) s1_cnt <= s1_cnt + 1;
    else s1_cnt <= 0;
end

// control signals (mode-muxed)
wire s1_bf = mode ? s1_cnt[6] : s1_cnt[5];
wire s1_start = (s1_cnt == (mode ? 7'd63 : 7'd31));
wire s1_mj = mode ? (s1_cnt[6:5] == 2'd3) : (s1_cnt[5:4] == 2'd3);

// delay buffer 1: 64-deep
reg [WIDTH-1:0] s1_db1_re [0:63];
reg [WIDTH-1:0] s1_db1_im [0:63];

// bf1 (RH=0)
wire signed [WIDTH-1:0] s1_b1x0r = s1_bf ? signed'(s1_db1_re[mode ? 63 : 31]) : 0;
wire signed [WIDTH-1:0] s1_b1x0i = s1_bf ? signed'(s1_db1_im[mode ? 63 : 31]) : 0;
wire signed [WIDTH-1:0] s1_b1x1r = s1_bf ? signed'(di_re) : 0;
wire signed [WIDTH-1:0] s1_b1x1i = s1_bf ? signed'(di_im) : 0;
wire signed [WIDTH:0] s1_b1ar = s1_b1x0r + s1_b1x1r;
wire signed [WIDTH:0] s1_b1ai = s1_b1x0i + s1_b1x1i;
wire signed [WIDTH:0] s1_b1sr = s1_b1x0r - s1_b1x1r;
wire signed [WIDTH:0] s1_b1si = s1_b1x0i - s1_b1x1i;
wire [WIDTH-1:0] s1_b1y0r = s1_b1ar >>> 1;
wire [WIDTH-1:0] s1_b1y0i = s1_b1ai >>> 1;
wire [WIDTH-1:0] s1_b1y1r = s1_b1sr >>> 1;
wire [WIDTH-1:0] s1_b1y1i = s1_b1si >>> 1;

// db1 input + shift
wire [WIDTH-1:0] s1_db1in_r = s1_bf ? s1_b1y1r : di_re;
wire [WIDTH-1:0] s1_db1in_i = s1_bf ? s1_b1y1i : di_im;
integer ia1;
always @(posedge clock) begin
    for (ia1 = 63; ia1 > 0; ia1 = ia1 - 1) begin
        s1_db1_re[ia1] <= s1_db1_re[ia1-1];
        s1_db1_im[ia1] <= s1_db1_im[ia1-1];
    end
    s1_db1_re[0] <= s1_db1in_r;
    s1_db1_im[0] <= s1_db1in_i;
end

// mode-muxed read tap (used by BOTH butterfly x0 and sp output mux)
wire [WIDTH-1:0] s1_db1or = mode ? s1_db1_re[63] : s1_db1_re[31];
wire [WIDTH-1:0] s1_db1oi = mode ? s1_db1_im[63] : s1_db1_im[31];

// single-path output (with -j)
wire [WIDTH-1:0] s1_bf1spr = s1_bf ? s1_b1y0r :
    s1_mj ? s1_db1oi : s1_db1or;
wire [WIDTH-1:0] s1_bf1spi = s1_bf ? s1_b1y0i :
    s1_mj ? (0 - s1_db1or) : s1_db1oi;

// bf1 enable/counter (end: 64-mode cnt==63, 128-mode cnt==127)
reg s1_bf1spe;
reg [6:0] s1_bf1cnt;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s1_bf1spe <= 0;
        s1_bf1cnt <= 0;
    end else begin
        s1_bf1spe <= s1_start ? 1 :
            (s1_bf1cnt == (mode ? 7'd127 : 7'd63)) ? 0 : s1_bf1spe;
        s1_bf1cnt <= s1_bf1spe ? (s1_bf1cnt + 1) : 0;
    end
end

reg [WIDTH-1:0] s1_bf1dor, s1_bf1doi;
always @(posedge clock) begin
    s1_bf1dor <= s1_bf1spr;
    s1_bf1doi <= s1_bf1spi;
end

// bf2 enable (mode-muxed from bf1_count)
reg s1_bf2bf;
always @(posedge clock) begin
    s1_bf2bf <= mode ? s1_bf1cnt[5] : s1_bf1cnt[4];
end

// delay buffer 2: 32-deep
reg [WIDTH-1:0] s1_db2_re [0:31];
reg [WIDTH-1:0] s1_db2_im [0:31];

// bf2 (RH=1)
wire signed [WIDTH-1:0] s1_b2x0r = s1_bf2bf ? signed'(s1_db2_re[mode ? 31 : 15]) : 0;
wire signed [WIDTH-1:0] s1_b2x0i = s1_bf2bf ? signed'(s1_db2_im[mode ? 31 : 15]) : 0;
wire signed [WIDTH-1:0] s1_b2x1r = s1_bf2bf ? signed'(s1_bf1dor) : 0;
wire signed [WIDTH-1:0] s1_b2x1i = s1_bf2bf ? signed'(s1_bf1doi) : 0;
wire signed [WIDTH:0] s1_b2ar = s1_b2x0r + s1_b2x1r;
wire signed [WIDTH:0] s1_b2ai = s1_b2x0i + s1_b2x1i;
wire signed [WIDTH:0] s1_b2sr = s1_b2x0r - s1_b2x1r;
wire signed [WIDTH:0] s1_b2si = s1_b2x0i - s1_b2x1i;
wire [WIDTH-1:0] s1_b2y0r = (s1_b2ar + 1) >>> 1;
wire [WIDTH-1:0] s1_b2y0i = (s1_b2ai + 1) >>> 1;
wire [WIDTH-1:0] s1_b2y1r = (s1_b2sr + 1) >>> 1;
wire [WIDTH-1:0] s1_b2y1i = (s1_b2si + 1) >>> 1;

wire [WIDTH-1:0] s1_db2in_r = s1_bf2bf ? s1_b2y1r : s1_bf1dor;
wire [WIDTH-1:0] s1_db2in_i = s1_bf2bf ? s1_b2y1i : s1_bf1doi;
wire [WIDTH-1:0] s1_bf2spr = s1_bf2bf ? s1_b2y0r : s1_db2_re[mode ? 31 : 15];
wire [WIDTH-1:0] s1_bf2spi = s1_bf2bf ? s1_b2y0i : s1_db2_im[mode ? 31 : 15];

integer ib1;
always @(posedge clock) begin
    for (ib1 = 31; ib1 > 0; ib1 = ib1 - 1) begin
        s1_db2_re[ib1] <= s1_db2_re[ib1-1];
        s1_db2_im[ib1] <= s1_db2_im[ib1-1];
    end
    s1_db2_re[0] <= s1_db2in_r;
    s1_db2_im[0] <= s1_db2in_i;
end

// mode-muxed read tap (used by BOTH butterfly x0 and sp output mux)
wire [WIDTH-1:0] s1_db2or = mode ? s1_db2_re[31] : s1_db2_re[15];
wire [WIDTH-1:0] s1_db2oi = mode ? s1_db2_im[31] : s1_db2_im[15];

reg [WIDTH-1:0] s1_bf2dor, s1_bf2doi;
always @(posedge clock) begin
    s1_bf2dor <= s1_bf2spr;
    s1_bf2doi <= s1_bf2spi;
end

// bf2 enables (mode-muxed start/end)
wire s1_bf2start = (s1_bf1cnt == (mode ? 7'd31 : 7'd15)) & s1_bf1spe;
wire s1_bf2end = (s1_bf2cnt == (mode ? 7'd127 : 7'd63));
reg s1_bf2spe, s1_bf2doen;
reg [6:0] s1_bf2cnt;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s1_bf2spe <= 0;
        s1_bf2cnt <= 0;
        s1_bf2doen <= 0;
    end else begin
        s1_bf2spe <= s1_bf2start ? 1 : s1_bf2end ? 0 : s1_bf2spe;
        s1_bf2cnt <= s1_bf2spe ? (s1_bf2cnt + 1) : 0;
        s1_bf2doen <= s1_bf2spe;
    end
end

// twiddle addressing (mode-muxed)
wire [1:0] s1_twsel = mode ?
    {s1_bf2cnt[4], s1_bf2cnt[5]} :
    {s1_bf2cnt[3], s1_bf2cnt[4]};
wire [4:0] s1_twnum = mode ?
    (s1_bf2cnt << 0) & 5'h1F :
    (s1_bf2cnt << 1) & 5'h0F;
// 64-mode: compute 64-pt address then double for the 128-entry ROM
wire [5:0] s1_twaddr_64 = (s1_twnum[3:0] * s1_twsel) & 6'h3F;
wire [6:0] s1_twaddr_128 = (s1_twnum * s1_twsel) & 7'h7F;
wire [6:0] s1_twaddr = mode ? s1_twaddr_128 : {s1_twaddr_64, 1'b0};

// twiddle ROM (single 128-entry, from pinned Twiddle128.v)
reg [WIDTH-1:0] s1_twr, s1_twi;
always @(posedge clock) begin
    case (s1_twaddr)
            7'h00: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h01: begin s1_twr <= 16'h7FD9; s1_twi <= 16'hF9B8; end
            7'h02: begin s1_twr <= 16'h7F62; s1_twi <= 16'hF374; end
            7'h03: begin s1_twr <= 16'h7E9D; s1_twi <= 16'hED38; end
            7'h04: begin s1_twr <= 16'h7D8A; s1_twi <= 16'hE707; end
            7'h05: begin s1_twr <= 16'h7C2A; s1_twi <= 16'hE0E6; end
            7'h06: begin s1_twr <= 16'h7A7D; s1_twi <= 16'hDAD8; end
            7'h07: begin s1_twr <= 16'h7885; s1_twi <= 16'hD4E1; end
            7'h08: begin s1_twr <= 16'h7642; s1_twi <= 16'hCF04; end
            7'h09: begin s1_twr <= 16'h73B6; s1_twi <= 16'hC946; end
            7'h0A: begin s1_twr <= 16'h70E3; s1_twi <= 16'hC3A9; end
            7'h0B: begin s1_twr <= 16'h6DCA; s1_twi <= 16'hBE32; end
            7'h0C: begin s1_twr <= 16'h6A6E; s1_twi <= 16'hB8E3; end
            7'h0D: begin s1_twr <= 16'h66D0; s1_twi <= 16'hB3C0; end
            7'h0E: begin s1_twr <= 16'h62F2; s1_twi <= 16'hAECC; end
            7'h0F: begin s1_twr <= 16'h5ED7; s1_twi <= 16'hAA0A; end
            7'h10: begin s1_twr <= 16'h5A82; s1_twi <= 16'hA57E; end
            7'h11: begin s1_twr <= 16'h55F6; s1_twi <= 16'hA129; end
            7'h12: begin s1_twr <= 16'h5134; s1_twi <= 16'h9D0E; end
            7'h13: begin s1_twr <= 16'h4C40; s1_twi <= 16'h9930; end
            7'h14: begin s1_twr <= 16'h471D; s1_twi <= 16'h9592; end
            7'h15: begin s1_twr <= 16'h41CE; s1_twi <= 16'h9236; end
            7'h16: begin s1_twr <= 16'h3C57; s1_twi <= 16'h8F1D; end
            7'h17: begin s1_twr <= 16'h36BA; s1_twi <= 16'h8C4A; end
            7'h18: begin s1_twr <= 16'h30FC; s1_twi <= 16'h89BE; end
            7'h19: begin s1_twr <= 16'h2B1F; s1_twi <= 16'h877B; end
            7'h1A: begin s1_twr <= 16'h2528; s1_twi <= 16'h8583; end
            7'h1B: begin s1_twr <= 16'h1F1A; s1_twi <= 16'h83D6; end
            7'h1C: begin s1_twr <= 16'h18F9; s1_twi <= 16'h8276; end
            7'h1D: begin s1_twr <= 16'h12C8; s1_twi <= 16'h8163; end
            7'h1E: begin s1_twr <= 16'h0C8C; s1_twi <= 16'h809E; end
            7'h1F: begin s1_twr <= 16'h0648; s1_twi <= 16'h8027; end
            7'h20: begin s1_twr <= 16'h0000; s1_twi <= 16'h8000; end
            7'h21: begin s1_twr <= 16'hF9B8; s1_twi <= 16'h8027; end
            7'h22: begin s1_twr <= 16'hF374; s1_twi <= 16'h809E; end
            7'h23: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h24: begin s1_twr <= 16'hE707; s1_twi <= 16'h8276; end
            7'h25: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h26: begin s1_twr <= 16'hDAD8; s1_twi <= 16'h8583; end
            7'h27: begin s1_twr <= 16'hD4E1; s1_twi <= 16'h877B; end
            7'h28: begin s1_twr <= 16'hCF04; s1_twi <= 16'h89BE; end
            7'h29: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h2A: begin s1_twr <= 16'hC3A9; s1_twi <= 16'h8F1D; end
            7'h2B: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h2C: begin s1_twr <= 16'hB8E3; s1_twi <= 16'h9592; end
            7'h2D: begin s1_twr <= 16'hB3C0; s1_twi <= 16'h9930; end
            7'h2E: begin s1_twr <= 16'hAECC; s1_twi <= 16'h9D0E; end
            7'h2F: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h30: begin s1_twr <= 16'hA57E; s1_twi <= 16'hA57E; end
            7'h31: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h32: begin s1_twr <= 16'h9D0E; s1_twi <= 16'hAECC; end
            7'h33: begin s1_twr <= 16'h9930; s1_twi <= 16'hB3C0; end
            7'h34: begin s1_twr <= 16'h9592; s1_twi <= 16'hB8E3; end
            7'h35: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h36: begin s1_twr <= 16'h8F1D; s1_twi <= 16'hC3A9; end
            7'h37: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h38: begin s1_twr <= 16'h89BE; s1_twi <= 16'hCF04; end
            7'h39: begin s1_twr <= 16'h877B; s1_twi <= 16'hD4E1; end
            7'h3A: begin s1_twr <= 16'h8583; s1_twi <= 16'hDAD8; end
            7'h3B: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h3C: begin s1_twr <= 16'h8276; s1_twi <= 16'hE707; end
            7'h3D: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h3E: begin s1_twr <= 16'h809E; s1_twi <= 16'hF374; end
            7'h3F: begin s1_twr <= 16'h8027; s1_twi <= 16'hF9B8; end
            7'h40: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h41: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h42: begin s1_twr <= 16'h809E; s1_twi <= 16'h0C8C; end
            7'h43: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h44: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h45: begin s1_twr <= 16'h83D6; s1_twi <= 16'h1F1A; end
            7'h46: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h47: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h48: begin s1_twr <= 16'h89BE; s1_twi <= 16'h30FC; end
            7'h49: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h4A: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h4B: begin s1_twr <= 16'h9236; s1_twi <= 16'h41CE; end
            7'h4C: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h4D: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h4E: begin s1_twr <= 16'h9D0E; s1_twi <= 16'h5134; end
            7'h4F: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h50: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h51: begin s1_twr <= 16'hAA0A; s1_twi <= 16'h5ED7; end
            7'h52: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h53: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h54: begin s1_twr <= 16'hB8E3; s1_twi <= 16'h6A6E; end
            7'h55: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h56: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h57: begin s1_twr <= 16'hC946; s1_twi <= 16'h73B6; end
            7'h58: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h59: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h5A: begin s1_twr <= 16'hDAD8; s1_twi <= 16'h7A7D; end
            7'h5B: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h5C: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h5D: begin s1_twr <= 16'hED38; s1_twi <= 16'h7E9D; end
            7'h5E: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h5F: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h60: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h61: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h62: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h63: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h64: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h65: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h66: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h67: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h68: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h69: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h6A: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h6B: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h6C: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h6D: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h6E: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h6F: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h70: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h71: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h72: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h73: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h74: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h75: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h76: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h77: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h78: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h79: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h7A: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h7B: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h7C: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h7D: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h7E: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
            7'h7F: begin s1_twr <= 16'h0000; s1_twi <= 16'h0000; end
        default: begin s1_twr <= 0; s1_twi <= 0; end
    endcase
end

// multiplier
reg s1_muen;
always @(posedge clock) begin
    s1_muen <= (s1_twaddr != 0);
end

wire signed [WIDTH-1:0] s1_muar = s1_muen ? signed'(s1_bf2dor) : 0;
wire signed [WIDTH-1:0] s1_muai = s1_muen ? signed'(s1_bf2doi) : 0;
wire signed [WIDTH-1:0] s1_mubr = signed'(s1_twr);
wire signed [WIDTH-1:0] s1_mubi = signed'(s1_twi);
wire signed [2*WIDTH-1:0] s1_murr = s1_muar * s1_mubr;
wire signed [2*WIDTH-1:0] s1_muri = s1_muar * s1_mubi;
wire signed [2*WIDTH-1:0] s1_muir = s1_muai * s1_mubr;
wire signed [2*WIDTH-1:0] s1_muii = s1_muai * s1_mubi;
wire [WIDTH-1:0] s1_mumr = (s1_murr >>> 15) - (s1_muii >>> 15);
wire [WIDTH-1:0] s1_mumi = (s1_muri >>> 15) + (s1_muir >>> 15);

reg [WIDTH-1:0] s1_mudor, s1_mudoi;
always @(posedge clock) begin
    s1_mudor <= s1_muen ? s1_mumr : s1_bf2dor;
    s1_mudoi <= s1_muen ? s1_mumi : s1_bf2doi;
end

reg s1_mudoen;
always @(posedge clock or posedge reset) begin
    if (reset) s1_mudoen <= 0;
    else s1_mudoen <= s1_bf2doen;
end

wire s1_do_en = s1_mudoen;
wire [WIDTH-1:0] s1_do_re = s1_mudor;
wire [WIDTH-1:0] s1_do_im = s1_mudoi;

//----------------------------------------------------------------------
// Stage 2: LOG_M = 4 (64-pt) / 5 (128-pt); db1=8/16, db2=4/8
//----------------------------------------------------------------------

reg [6:0] s2_cnt;
always @(posedge clock or posedge reset) begin
    if (reset) s2_cnt <= 0;
    else if (s1_do_en) s2_cnt <= s2_cnt + 1;
    else s2_cnt <= 0;
end

wire s2_bf = mode ? s2_cnt[5] : s2_cnt[4];
wire s2_start = (s2_cnt == (mode ? 7'd31 : 7'd15));
wire s2_mj = mode ? (s2_cnt[5:4] == 2'd3) : (s2_cnt[4:3] == 2'd3);

reg [WIDTH-1:0] s2_db1_re [0:31];
reg [WIDTH-1:0] s2_db1_im [0:31];

wire signed [WIDTH-1:0] s2_b1x0r = s2_bf ? signed'(s2_db1_re[mode ? 31 : 15]) : 0;
wire signed [WIDTH-1:0] s2_b1x0i = s2_bf ? signed'(s2_db1_im[mode ? 31 : 15]) : 0;
wire signed [WIDTH-1:0] s2_b1x1r = s2_bf ? signed'(s1_do_re) : 0;
wire signed [WIDTH-1:0] s2_b1x1i = s2_bf ? signed'(s1_do_im) : 0;
wire signed [WIDTH:0] s2_b1ar = s2_b1x0r + s2_b1x1r;
wire signed [WIDTH:0] s2_b1ai = s2_b1x0i + s2_b1x1i;
wire signed [WIDTH:0] s2_b1sr = s2_b1x0r - s2_b1x1r;
wire signed [WIDTH:0] s2_b1si = s2_b1x0i - s2_b1x1i;
wire [WIDTH-1:0] s2_b1y0r = s2_b1ar >>> 1;
wire [WIDTH-1:0] s2_b1y0i = s2_b1ai >>> 1;
wire [WIDTH-1:0] s2_b1y1r = s2_b1sr >>> 1;
wire [WIDTH-1:0] s2_b1y1i = s2_b1si >>> 1;

wire [WIDTH-1:0] s2_db1in_r = s2_bf ? s2_b1y1r : s1_do_re;
wire [WIDTH-1:0] s2_db1in_i = s2_bf ? s2_b1y1i : s1_do_im;
wire [WIDTH-1:0] s2_bf1spr = s2_bf ? s2_b1y0r :
    s2_mj ? s2_db1_im[mode ? 31 : 15] : s2_db1_re[mode ? 31 : 15];
wire [WIDTH-1:0] s2_bf1spi = s2_bf ? s2_b1y0i :
    s2_mj ? (0 - s2_db1_re[mode ? 31 : 15]) : s2_db1_im[mode ? 31 : 15];

integer ia2;
always @(posedge clock) begin
    for (ia2 = 31; ia2 > 0; ia2 = ia2 - 1) begin
        s2_db1_re[ia2] <= s2_db1_re[ia2-1];
        s2_db1_im[ia2] <= s2_db1_im[ia2-1];
    end
    s2_db1_re[0] <= s2_db1in_r;
    s2_db1_im[0] <= s2_db1in_i;
end

wire [WIDTH-1:0] s2_db1or = mode ? s2_db1_re[31] : s2_db1_re[15];
wire [WIDTH-1:0] s2_db1oi = mode ? s2_db1_im[31] : s2_db1_im[15];

reg s2_bf1spe;
reg [6:0] s2_bf1cnt;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s2_bf1spe <= 0;
        s2_bf1cnt <= 0;
    end else begin
        s2_bf1spe <= s2_start ? 1 :
            (s2_bf1cnt == (mode ? 7'd127 : 7'd63)) ? 0 : s2_bf1spe;
        s2_bf1cnt <= s2_bf1spe ? (s2_bf1cnt + 1) : 0;
    end
end

reg [WIDTH-1:0] s2_bf1dor, s2_bf1doi;
always @(posedge clock) begin
    s2_bf1dor <= s2_bf1spr;
    s2_bf1doi <= s2_bf1spi;
end

reg s2_bf2bf;
always @(posedge clock) begin
    s2_bf2bf <= mode ? s2_bf1cnt[4] : s2_bf1cnt[3];
end

reg [WIDTH-1:0] s2_db2_re [0:15];
reg [WIDTH-1:0] s2_db2_im [0:15];

wire signed [WIDTH-1:0] s2_b2x0r = s2_bf2bf ? signed'(s2_db2_re[mode ? 15 : 7]) : 0;
wire signed [WIDTH-1:0] s2_b2x0i = s2_bf2bf ? signed'(s2_db2_im[mode ? 15 : 7]) : 0;
wire signed [WIDTH-1:0] s2_b2x1r = s2_bf2bf ? signed'(s2_bf1dor) : 0;
wire signed [WIDTH-1:0] s2_b2x1i = s2_bf2bf ? signed'(s2_bf1doi) : 0;
wire signed [WIDTH:0] s2_b2ar = s2_b2x0r + s2_b2x1r;
wire signed [WIDTH:0] s2_b2ai = s2_b2x0i + s2_b2x1i;
wire signed [WIDTH:0] s2_b2sr = s2_b2x0r - s2_b2x1r;
wire signed [WIDTH:0] s2_b2si = s2_b2x0i - s2_b2x1i;
wire [WIDTH-1:0] s2_b2y0r = (s2_b2ar + 1) >>> 1;
wire [WIDTH-1:0] s2_b2y0i = (s2_b2ai + 1) >>> 1;
wire [WIDTH-1:0] s2_b2y1r = (s2_b2sr + 1) >>> 1;
wire [WIDTH-1:0] s2_b2y1i = (s2_b2si + 1) >>> 1;

wire [WIDTH-1:0] s2_db2in_r = s2_bf2bf ? s2_b2y1r : s2_bf1dor;
wire [WIDTH-1:0] s2_db2in_i = s2_bf2bf ? s2_b2y1i : s2_bf1doi;
wire [WIDTH-1:0] s2_bf2spr = s2_bf2bf ? s2_b2y0r : s2_db2_re[mode ? 15 : 7];
wire [WIDTH-1:0] s2_bf2spi = s2_bf2bf ? s2_b2y0i : s2_db2_im[mode ? 15 : 7];

integer ib2;
always @(posedge clock) begin
    for (ib2 = 15; ib2 > 0; ib2 = ib2 - 1) begin
        s2_db2_re[ib2] <= s2_db2_re[ib2-1];
        s2_db2_im[ib2] <= s2_db2_im[ib2-1];
    end
    s2_db2_re[0] <= s2_db2in_r;
    s2_db2_im[0] <= s2_db2in_i;
end

wire [WIDTH-1:0] s2_db2or = mode ? s2_db2_re[15] : s2_db2_re[7];
wire [WIDTH-1:0] s2_db2oi = mode ? s2_db2_im[15] : s2_db2_im[7];

reg [WIDTH-1:0] s2_bf2dor, s2_bf2doi;
always @(posedge clock) begin
    s2_bf2dor <= s2_bf2spr;
    s2_bf2doi <= s2_bf2spi;
end

wire s2_bf2start = (s2_bf1cnt == (mode ? 7'd15 : 7'd7)) & s2_bf1spe;
wire s2_bf2end = (s2_bf2cnt == (mode ? 7'd127 : 7'd63));
reg s2_bf2spe, s2_bf2doen;
reg [6:0] s2_bf2cnt;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s2_bf2spe <= 0;
        s2_bf2cnt <= 0;
        s2_bf2doen <= 0;
    end else begin
        s2_bf2spe <= s2_bf2start ? 1 : s2_bf2end ? 0 : s2_bf2spe;
        s2_bf2cnt <= s2_bf2spe ? (s2_bf2cnt + 1) : 0;
        s2_bf2doen <= s2_bf2spe;
    end
end

// twiddle addressing (mode-muxed)
wire [1:0] s2_twsel = mode ?
    {s2_bf2cnt[3], s2_bf2cnt[4]} :
    {s2_bf2cnt[2], s2_bf2cnt[3]};
wire [4:0] s2_twnum = mode ?
    (s2_bf2cnt << 2) & 5'h1F :
    (s2_bf2cnt << 3) & 5'h07;
wire [5:0] s2_twaddr_64 = ((s2_twnum[2:0] * s2_twsel) & 6'h3F);
wire [6:0] s2_twaddr_128 = (s2_twnum * s2_twsel) & 7'h7F;
wire [6:0] s2_twaddr = mode ? s2_twaddr_128 : {s2_twaddr_64, 1'b0};

// twiddle ROM
reg [WIDTH-1:0] s2_twr, s2_twi;
always @(posedge clock) begin
    case (s2_twaddr)
            7'h00: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h01: begin s2_twr <= 16'h7FD9; s2_twi <= 16'hF9B8; end
            7'h02: begin s2_twr <= 16'h7F62; s2_twi <= 16'hF374; end
            7'h03: begin s2_twr <= 16'h7E9D; s2_twi <= 16'hED38; end
            7'h04: begin s2_twr <= 16'h7D8A; s2_twi <= 16'hE707; end
            7'h05: begin s2_twr <= 16'h7C2A; s2_twi <= 16'hE0E6; end
            7'h06: begin s2_twr <= 16'h7A7D; s2_twi <= 16'hDAD8; end
            7'h07: begin s2_twr <= 16'h7885; s2_twi <= 16'hD4E1; end
            7'h08: begin s2_twr <= 16'h7642; s2_twi <= 16'hCF04; end
            7'h09: begin s2_twr <= 16'h73B6; s2_twi <= 16'hC946; end
            7'h0A: begin s2_twr <= 16'h70E3; s2_twi <= 16'hC3A9; end
            7'h0B: begin s2_twr <= 16'h6DCA; s2_twi <= 16'hBE32; end
            7'h0C: begin s2_twr <= 16'h6A6E; s2_twi <= 16'hB8E3; end
            7'h0D: begin s2_twr <= 16'h66D0; s2_twi <= 16'hB3C0; end
            7'h0E: begin s2_twr <= 16'h62F2; s2_twi <= 16'hAECC; end
            7'h0F: begin s2_twr <= 16'h5ED7; s2_twi <= 16'hAA0A; end
            7'h10: begin s2_twr <= 16'h5A82; s2_twi <= 16'hA57E; end
            7'h11: begin s2_twr <= 16'h55F6; s2_twi <= 16'hA129; end
            7'h12: begin s2_twr <= 16'h5134; s2_twi <= 16'h9D0E; end
            7'h13: begin s2_twr <= 16'h4C40; s2_twi <= 16'h9930; end
            7'h14: begin s2_twr <= 16'h471D; s2_twi <= 16'h9592; end
            7'h15: begin s2_twr <= 16'h41CE; s2_twi <= 16'h9236; end
            7'h16: begin s2_twr <= 16'h3C57; s2_twi <= 16'h8F1D; end
            7'h17: begin s2_twr <= 16'h36BA; s2_twi <= 16'h8C4A; end
            7'h18: begin s2_twr <= 16'h30FC; s2_twi <= 16'h89BE; end
            7'h19: begin s2_twr <= 16'h2B1F; s2_twi <= 16'h877B; end
            7'h1A: begin s2_twr <= 16'h2528; s2_twi <= 16'h8583; end
            7'h1B: begin s2_twr <= 16'h1F1A; s2_twi <= 16'h83D6; end
            7'h1C: begin s2_twr <= 16'h18F9; s2_twi <= 16'h8276; end
            7'h1D: begin s2_twr <= 16'h12C8; s2_twi <= 16'h8163; end
            7'h1E: begin s2_twr <= 16'h0C8C; s2_twi <= 16'h809E; end
            7'h1F: begin s2_twr <= 16'h0648; s2_twi <= 16'h8027; end
            7'h20: begin s2_twr <= 16'h0000; s2_twi <= 16'h8000; end
            7'h21: begin s2_twr <= 16'hF9B8; s2_twi <= 16'h8027; end
            7'h22: begin s2_twr <= 16'hF374; s2_twi <= 16'h809E; end
            7'h23: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h24: begin s2_twr <= 16'hE707; s2_twi <= 16'h8276; end
            7'h25: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h26: begin s2_twr <= 16'hDAD8; s2_twi <= 16'h8583; end
            7'h27: begin s2_twr <= 16'hD4E1; s2_twi <= 16'h877B; end
            7'h28: begin s2_twr <= 16'hCF04; s2_twi <= 16'h89BE; end
            7'h29: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h2A: begin s2_twr <= 16'hC3A9; s2_twi <= 16'h8F1D; end
            7'h2B: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h2C: begin s2_twr <= 16'hB8E3; s2_twi <= 16'h9592; end
            7'h2D: begin s2_twr <= 16'hB3C0; s2_twi <= 16'h9930; end
            7'h2E: begin s2_twr <= 16'hAECC; s2_twi <= 16'h9D0E; end
            7'h2F: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h30: begin s2_twr <= 16'hA57E; s2_twi <= 16'hA57E; end
            7'h31: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h32: begin s2_twr <= 16'h9D0E; s2_twi <= 16'hAECC; end
            7'h33: begin s2_twr <= 16'h9930; s2_twi <= 16'hB3C0; end
            7'h34: begin s2_twr <= 16'h9592; s2_twi <= 16'hB8E3; end
            7'h35: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h36: begin s2_twr <= 16'h8F1D; s2_twi <= 16'hC3A9; end
            7'h37: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h38: begin s2_twr <= 16'h89BE; s2_twi <= 16'hCF04; end
            7'h39: begin s2_twr <= 16'h877B; s2_twi <= 16'hD4E1; end
            7'h3A: begin s2_twr <= 16'h8583; s2_twi <= 16'hDAD8; end
            7'h3B: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h3C: begin s2_twr <= 16'h8276; s2_twi <= 16'hE707; end
            7'h3D: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h3E: begin s2_twr <= 16'h809E; s2_twi <= 16'hF374; end
            7'h3F: begin s2_twr <= 16'h8027; s2_twi <= 16'hF9B8; end
            7'h40: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h41: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h42: begin s2_twr <= 16'h809E; s2_twi <= 16'h0C8C; end
            7'h43: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h44: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h45: begin s2_twr <= 16'h83D6; s2_twi <= 16'h1F1A; end
            7'h46: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h47: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h48: begin s2_twr <= 16'h89BE; s2_twi <= 16'h30FC; end
            7'h49: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h4A: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h4B: begin s2_twr <= 16'h9236; s2_twi <= 16'h41CE; end
            7'h4C: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h4D: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h4E: begin s2_twr <= 16'h9D0E; s2_twi <= 16'h5134; end
            7'h4F: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h50: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h51: begin s2_twr <= 16'hAA0A; s2_twi <= 16'h5ED7; end
            7'h52: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h53: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h54: begin s2_twr <= 16'hB8E3; s2_twi <= 16'h6A6E; end
            7'h55: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h56: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h57: begin s2_twr <= 16'hC946; s2_twi <= 16'h73B6; end
            7'h58: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h59: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h5A: begin s2_twr <= 16'hDAD8; s2_twi <= 16'h7A7D; end
            7'h5B: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h5C: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h5D: begin s2_twr <= 16'hED38; s2_twi <= 16'h7E9D; end
            7'h5E: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h5F: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h60: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h61: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h62: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h63: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h64: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h65: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h66: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h67: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h68: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h69: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h6A: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h6B: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h6C: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h6D: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h6E: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h6F: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h70: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h71: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h72: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h73: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h74: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h75: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h76: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h77: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h78: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h79: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h7A: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h7B: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h7C: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h7D: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h7E: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
            7'h7F: begin s2_twr <= 16'h0000; s2_twi <= 16'h0000; end
        default: begin s2_twr <= 0; s2_twi <= 0; end
    endcase
end

// multiplier
reg s2_muen;
always @(posedge clock) begin
    s2_muen <= (s2_twaddr != 0);
end

wire signed [WIDTH-1:0] s2_muar = s2_muen ? signed'(s2_bf2dor) : 0;
wire signed [WIDTH-1:0] s2_muai = s2_muen ? signed'(s2_bf2doi) : 0;
wire signed [WIDTH-1:0] s2_mubr = signed'(s2_twr);
wire signed [WIDTH-1:0] s2_mubi = signed'(s2_twi);
wire signed [2*WIDTH-1:0] s2_murr = s2_muar * s2_mubr;
wire signed [2*WIDTH-1:0] s2_muri = s2_muar * s2_mubi;
wire signed [2*WIDTH-1:0] s2_muir = s2_muai * s2_mubr;
wire signed [2*WIDTH-1:0] s2_muii = s2_muai * s2_mubi;
wire [WIDTH-1:0] s2_mumr = (s2_murr >>> 15) - (s2_muii >>> 15);
wire [WIDTH-1:0] s2_mumi = (s2_muri >>> 15) + (s2_muir >>> 15);

reg [WIDTH-1:0] s2_mudor, s2_mudoi;
always @(posedge clock) begin
    s2_mudor <= s2_muen ? s2_mumr : s2_bf2dor;
    s2_mudoi <= s2_muen ? s2_mumi : s2_bf2doi;
end

reg s2_mudoen;
always @(posedge clock or posedge reset) begin
    if (reset) s2_mudoen <= 0;
    else s2_mudoen <= s2_bf2doen;
end

wire s2_do_en = s2_mudoen;
wire [WIDTH-1:0] s2_do_re = s2_mudor;
wire [WIDTH-1:0] s2_do_im = s2_mudoi;

//----------------------------------------------------------------------
// Stage 3: LOG_M = 2 (64-pt, NO multiply) / 3 (128-pt, WITH multiply)
// db1=2/4, db2=1/2
//----------------------------------------------------------------------

reg [6:0] s3_cnt;
always @(posedge clock or posedge reset) begin
    if (reset) s3_cnt <= 0;
    else if (s2_do_en) s3_cnt <= s3_cnt + 1;
    else s3_cnt <= 0;
end

wire s3_bf = mode ? s3_cnt[2] : s3_cnt[1];
wire s3_start = (s3_cnt == (mode ? 7'd3 : 7'd1));
wire s3_mj = mode ? (s3_cnt[2:1] == 2'd3) : (s3_cnt[1:0] == 2'd3);

reg [WIDTH-1:0] s3_db1_re [0:3];
reg [WIDTH-1:0] s3_db1_im [0:3];

// bf1: 64-mode tap at [1], 128-mode tap at [3]
wire signed [WIDTH-1:0] s3_b1x0r = s3_bf ? signed'(s3_db1_re[mode ? 3 : 1]) : 0;
wire signed [WIDTH-1:0] s3_b1x0i = s3_bf ? signed'(s3_db1_im[mode ? 3 : 1]) : 0;
wire signed [WIDTH-1:0] s3_b1x1r = s3_bf ? signed'(s2_do_re) : 0;
wire signed [WIDTH-1:0] s3_b1x1i = s3_bf ? signed'(s2_do_im) : 0;
wire signed [WIDTH:0] s3_b1ar = s3_b1x0r + s3_b1x1r;
wire signed [WIDTH:0] s3_b1ai = s3_b1x0i + s3_b1x1i;
wire signed [WIDTH:0] s3_b1sr = s3_b1x0r - s3_b1x1r;
wire signed [WIDTH:0] s3_b1si = s3_b1x0i - s3_b1x1i;
wire [WIDTH-1:0] s3_b1y0r = s3_b1ar >>> 1;
wire [WIDTH-1:0] s3_b1y0i = s3_b1ai >>> 1;
wire [WIDTH-1:0] s3_b1y1r = s3_b1sr >>> 1;
wire [WIDTH-1:0] s3_b1y1i = s3_b1si >>> 1;

wire [WIDTH-1:0] s3_db1in_r = s3_bf ? s3_b1y1r : s2_do_re;
wire [WIDTH-1:0] s3_db1in_i = s3_bf ? s3_b1y1i : s2_do_im;
// single-path output uses the SAME mode-muxed tap
wire [WIDTH-1:0] s3_bf1spr = s3_bf ? s3_b1y0r :
    s3_mj ? s3_db1_im[mode ? 3 : 1] : s3_db1_re[mode ? 3 : 1];
wire [WIDTH-1:0] s3_bf1spi = s3_bf ? s3_b1y0i :
    s3_mj ? (0 - s3_db1_re[mode ? 3 : 1]) : s3_db1_im[mode ? 3 : 1];

integer ia3;
always @(posedge clock) begin
    for (ia3 = 3; ia3 > 0; ia3 = ia3 - 1) begin
        s3_db1_re[ia3] <= s3_db1_re[ia3-1];
        s3_db1_im[ia3] <= s3_db1_im[ia3-1];
    end
    s3_db1_re[0] <= s3_db1in_r;
    s3_db1_im[0] <= s3_db1in_i;
end

wire [WIDTH-1:0] s3_db1or = mode ? s3_db1_re[3] : s3_db1_re[1];
wire [WIDTH-1:0] s3_db1oi = mode ? s3_db1_im[3] : s3_db1_im[1];

reg s3_bf1spe;
reg [6:0] s3_bf1cnt;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s3_bf1spe <= 0;
        s3_bf1cnt <= 0;
    end else begin
        s3_bf1spe <= s3_start ? 1 :
            (s3_bf1cnt == (mode ? 7'd127 : 7'd63)) ? 0 : s3_bf1spe;
        s3_bf1cnt <= s3_bf1spe ? (s3_bf1cnt + 1) : 0;
    end
end

reg [WIDTH-1:0] s3_bf1dor, s3_bf1doi;
always @(posedge clock) begin
    s3_bf1dor <= s3_bf1spr;
    s3_bf1doi <= s3_bf1spi;
end

reg s3_bf2bf;
always @(posedge clock) begin
    s3_bf2bf <= mode ? s3_bf1cnt[1] : s3_bf1cnt[0];
end

reg [WIDTH-1:0] s3_db2_re [0:1];
reg [WIDTH-1:0] s3_db2_im [0:1];

// bf2: 64-mode tap at [0], 128-mode tap at [1]
wire signed [WIDTH-1:0] s3_b2x0r = s3_bf2bf ? signed'(s3_db2_re[mode ? 1 : 0]) : 0;
wire signed [WIDTH-1:0] s3_b2x0i = s3_bf2bf ? signed'(s3_db2_im[mode ? 1 : 0]) : 0;
wire signed [WIDTH-1:0] s3_b2x1r = s3_bf2bf ? signed'(s3_bf1dor) : 0;
wire signed [WIDTH-1:0] s3_b2x1i = s3_bf2bf ? signed'(s3_bf1doi) : 0;
wire signed [WIDTH:0] s3_b2ar = s3_b2x0r + s3_b2x1r;
wire signed [WIDTH:0] s3_b2ai = s3_b2x0i + s3_b2x1i;
wire signed [WIDTH:0] s3_b2sr = s3_b2x0r - s3_b2x1r;
wire signed [WIDTH:0] s3_b2si = s3_b2x0i - s3_b2x1i;
wire [WIDTH-1:0] s3_b2y0r = (s3_b2ar + 1) >>> 1;
wire [WIDTH-1:0] s3_b2y0i = (s3_b2ai + 1) >>> 1;
wire [WIDTH-1:0] s3_b2y1r = (s3_b2sr + 1) >>> 1;
wire [WIDTH-1:0] s3_b2y1i = (s3_b2si + 1) >>> 1;

wire [WIDTH-1:0] s3_db2in_r = s3_bf2bf ? s3_b2y1r : s3_bf1dor;
wire [WIDTH-1:0] s3_db2in_i = s3_bf2bf ? s3_b2y1i : s3_bf1doi;
// single-path output uses the SAME mode-muxed tap
wire [WIDTH-1:0] s3_bf2spr = s3_bf2bf ? s3_b2y0r : s3_db2_re[mode ? 1 : 0];
wire [WIDTH-1:0] s3_bf2spi = s3_bf2bf ? s3_b2y0i : s3_db2_im[mode ? 1 : 0];

integer ib3;
always @(posedge clock) begin
    for (ib3 = 1; ib3 > 0; ib3 = ib3 - 1) begin
        s3_db2_re[ib3] <= s3_db2_re[ib3-1];
        s3_db2_im[ib3] <= s3_db2_im[ib3-1];
    end
    s3_db2_re[0] <= s3_db2in_r;
    s3_db2_im[0] <= s3_db2in_i;
end

wire [WIDTH-1:0] s3_db2or = mode ? s3_db2_re[1] : s3_db2_re[0];
wire [WIDTH-1:0] s3_db2oi = mode ? s3_db2_im[1] : s3_db2_im[0];

reg [WIDTH-1:0] s3_bf2dor, s3_bf2doi;
always @(posedge clock) begin
    s3_bf2dor <= s3_bf2spr;
    s3_bf2doi <= s3_bf2spi;
end

wire s3_bf2start = (s3_bf1cnt == (mode ? 7'd1 : 7'd0)) & s3_bf1spe;
wire s3_bf2end = (s3_bf2cnt == (mode ? 7'd127 : 7'd63));
reg s3_bf2spe, s3_bf2doen;
reg [6:0] s3_bf2cnt;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s3_bf2spe <= 0;
        s3_bf2cnt <= 0;
        s3_bf2doen <= 0;
    end else begin
        s3_bf2spe <= s3_bf2start ? 1 : s3_bf2end ? 0 : s3_bf2spe;
        s3_bf2cnt <= s3_bf2spe ? (s3_bf2cnt + 1) : 0;
        s3_bf2doen <= s3_bf2spe;
    end
end

// Stage 3 twiddle: 128-mode has multiply, 64-mode does NOT (LOG_M=2)
reg s3_muen;
always @(posedge clock or posedge reset) begin
    if (reset) s3_muen <= 0;
    else s3_muen <= mode & s3_bf2doen;
end

// 128-mode S3 twiddle: tw_num=(cnt<<4)&0x1F, tw_sel=2*cnt[1]+cnt[2]
wire [1:0] s3_twsel = {s3_bf2cnt[1], s3_bf2cnt[2]};
wire [5:0] s3_twnum = (s3_bf2cnt << 4) & 6'h1F;
wire [6:0] s3_twaddr = (s3_twnum * s3_twsel) & 7'h7F;

reg [WIDTH-1:0] s3_twr, s3_twi;
always @(posedge clock) begin
    case (s3_twaddr)
            7'h00: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h01: begin s3_twr <= 16'h7FD9; s3_twi <= 16'hF9B8; end
            7'h02: begin s3_twr <= 16'h7F62; s3_twi <= 16'hF374; end
            7'h03: begin s3_twr <= 16'h7E9D; s3_twi <= 16'hED38; end
            7'h04: begin s3_twr <= 16'h7D8A; s3_twi <= 16'hE707; end
            7'h05: begin s3_twr <= 16'h7C2A; s3_twi <= 16'hE0E6; end
            7'h06: begin s3_twr <= 16'h7A7D; s3_twi <= 16'hDAD8; end
            7'h07: begin s3_twr <= 16'h7885; s3_twi <= 16'hD4E1; end
            7'h08: begin s3_twr <= 16'h7642; s3_twi <= 16'hCF04; end
            7'h09: begin s3_twr <= 16'h73B6; s3_twi <= 16'hC946; end
            7'h0A: begin s3_twr <= 16'h70E3; s3_twi <= 16'hC3A9; end
            7'h0B: begin s3_twr <= 16'h6DCA; s3_twi <= 16'hBE32; end
            7'h0C: begin s3_twr <= 16'h6A6E; s3_twi <= 16'hB8E3; end
            7'h0D: begin s3_twr <= 16'h66D0; s3_twi <= 16'hB3C0; end
            7'h0E: begin s3_twr <= 16'h62F2; s3_twi <= 16'hAECC; end
            7'h0F: begin s3_twr <= 16'h5ED7; s3_twi <= 16'hAA0A; end
            7'h10: begin s3_twr <= 16'h5A82; s3_twi <= 16'hA57E; end
            7'h11: begin s3_twr <= 16'h55F6; s3_twi <= 16'hA129; end
            7'h12: begin s3_twr <= 16'h5134; s3_twi <= 16'h9D0E; end
            7'h13: begin s3_twr <= 16'h4C40; s3_twi <= 16'h9930; end
            7'h14: begin s3_twr <= 16'h471D; s3_twi <= 16'h9592; end
            7'h15: begin s3_twr <= 16'h41CE; s3_twi <= 16'h9236; end
            7'h16: begin s3_twr <= 16'h3C57; s3_twi <= 16'h8F1D; end
            7'h17: begin s3_twr <= 16'h36BA; s3_twi <= 16'h8C4A; end
            7'h18: begin s3_twr <= 16'h30FC; s3_twi <= 16'h89BE; end
            7'h19: begin s3_twr <= 16'h2B1F; s3_twi <= 16'h877B; end
            7'h1A: begin s3_twr <= 16'h2528; s3_twi <= 16'h8583; end
            7'h1B: begin s3_twr <= 16'h1F1A; s3_twi <= 16'h83D6; end
            7'h1C: begin s3_twr <= 16'h18F9; s3_twi <= 16'h8276; end
            7'h1D: begin s3_twr <= 16'h12C8; s3_twi <= 16'h8163; end
            7'h1E: begin s3_twr <= 16'h0C8C; s3_twi <= 16'h809E; end
            7'h1F: begin s3_twr <= 16'h0648; s3_twi <= 16'h8027; end
            7'h20: begin s3_twr <= 16'h0000; s3_twi <= 16'h8000; end
            7'h21: begin s3_twr <= 16'hF9B8; s3_twi <= 16'h8027; end
            7'h22: begin s3_twr <= 16'hF374; s3_twi <= 16'h809E; end
            7'h23: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h24: begin s3_twr <= 16'hE707; s3_twi <= 16'h8276; end
            7'h25: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h26: begin s3_twr <= 16'hDAD8; s3_twi <= 16'h8583; end
            7'h27: begin s3_twr <= 16'hD4E1; s3_twi <= 16'h877B; end
            7'h28: begin s3_twr <= 16'hCF04; s3_twi <= 16'h89BE; end
            7'h29: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h2A: begin s3_twr <= 16'hC3A9; s3_twi <= 16'h8F1D; end
            7'h2B: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h2C: begin s3_twr <= 16'hB8E3; s3_twi <= 16'h9592; end
            7'h2D: begin s3_twr <= 16'hB3C0; s3_twi <= 16'h9930; end
            7'h2E: begin s3_twr <= 16'hAECC; s3_twi <= 16'h9D0E; end
            7'h2F: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h30: begin s3_twr <= 16'hA57E; s3_twi <= 16'hA57E; end
            7'h31: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h32: begin s3_twr <= 16'h9D0E; s3_twi <= 16'hAECC; end
            7'h33: begin s3_twr <= 16'h9930; s3_twi <= 16'hB3C0; end
            7'h34: begin s3_twr <= 16'h9592; s3_twi <= 16'hB8E3; end
            7'h35: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h36: begin s3_twr <= 16'h8F1D; s3_twi <= 16'hC3A9; end
            7'h37: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h38: begin s3_twr <= 16'h89BE; s3_twi <= 16'hCF04; end
            7'h39: begin s3_twr <= 16'h877B; s3_twi <= 16'hD4E1; end
            7'h3A: begin s3_twr <= 16'h8583; s3_twi <= 16'hDAD8; end
            7'h3B: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h3C: begin s3_twr <= 16'h8276; s3_twi <= 16'hE707; end
            7'h3D: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h3E: begin s3_twr <= 16'h809E; s3_twi <= 16'hF374; end
            7'h3F: begin s3_twr <= 16'h8027; s3_twi <= 16'hF9B8; end
            7'h40: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h41: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h42: begin s3_twr <= 16'h809E; s3_twi <= 16'h0C8C; end
            7'h43: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h44: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h45: begin s3_twr <= 16'h83D6; s3_twi <= 16'h1F1A; end
            7'h46: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h47: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h48: begin s3_twr <= 16'h89BE; s3_twi <= 16'h30FC; end
            7'h49: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h4A: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h4B: begin s3_twr <= 16'h9236; s3_twi <= 16'h41CE; end
            7'h4C: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h4D: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h4E: begin s3_twr <= 16'h9D0E; s3_twi <= 16'h5134; end
            7'h4F: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h50: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h51: begin s3_twr <= 16'hAA0A; s3_twi <= 16'h5ED7; end
            7'h52: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h53: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h54: begin s3_twr <= 16'hB8E3; s3_twi <= 16'h6A6E; end
            7'h55: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h56: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h57: begin s3_twr <= 16'hC946; s3_twi <= 16'h73B6; end
            7'h58: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h59: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h5A: begin s3_twr <= 16'hDAD8; s3_twi <= 16'h7A7D; end
            7'h5B: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h5C: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h5D: begin s3_twr <= 16'hED38; s3_twi <= 16'h7E9D; end
            7'h5E: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h5F: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h60: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h61: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h62: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h63: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h64: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h65: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h66: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h67: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h68: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h69: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h6A: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h6B: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h6C: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h6D: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h6E: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h6F: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h70: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h71: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h72: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h73: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h74: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h75: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h76: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h77: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h78: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h79: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h7A: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h7B: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h7C: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h7D: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h7E: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
            7'h7F: begin s3_twr <= 16'h0000; s3_twi <= 16'h0000; end
        default: begin s3_twr <= 0; s3_twi <= 0; end
    endcase
end

wire signed [WIDTH-1:0] s3_muar = s3_muen ? signed'(s3_bf2dor) : 0;
wire signed [WIDTH-1:0] s3_muai = s3_muen ? signed'(s3_bf2doi) : 0;
wire signed [WIDTH-1:0] s3_mubr = signed'(s3_twr);
wire signed [WIDTH-1:0] s3_mubi = signed'(s3_twi);
wire signed [2*WIDTH-1:0] s3_murr = s3_muar * s3_mubr;
wire signed [2*WIDTH-1:0] s3_muri = s3_muar * s3_mubi;
wire signed [2*WIDTH-1:0] s3_muir = s3_muai * s3_mubr;
wire signed [2*WIDTH-1:0] s3_muii = s3_muai * s3_mubi;
wire [WIDTH-1:0] s3_mumr = (s3_murr >>> 15) - (s3_muii >>> 15);
wire [WIDTH-1:0] s3_mumi = (s3_muri >>> 15) + (s3_muir >>> 15);

reg [WIDTH-1:0] s3_mudor, s3_mudoi;
always @(posedge clock) begin
    s3_mudor <= s3_muen ? s3_mumr : s3_bf2dor;
    s3_mudoi <= s3_muen ? s3_mumi : s3_bf2doi;
end

reg s3_mudoen;
always @(posedge clock or posedge reset) begin
    if (reset) s3_mudoen <= 0;
    else s3_mudoen <= s3_bf2doen;
end

wire s3_do_en = s3_mudoen;
wire [WIDTH-1:0] s3_do_re = s3_mudor;
wire [WIDTH-1:0] s3_do_im = s3_mudoi;

//----------------------------------------------------------------------
// Final radix-2 (SdfUnit2 pattern): 128-mode only
//----------------------------------------------------------------------
reg s4_bfen;
always @(posedge clock or posedge reset) begin
    if (reset) s4_bfen <= 0;
    else s4_bfen <= (s3_do_en & mode) ? ~s4_bfen : 0;
end

reg [WIDTH-1:0] s4_db_re, s4_db_im;
wire s4_bf_active = s4_bfen & mode;

wire signed [WIDTH-1:0] s4_bfx0r = s4_bf_active ? signed'(s4_db_re) : 0;
wire signed [WIDTH-1:0] s4_bfx0i = s4_bf_active ? signed'(s4_db_im) : 0;
wire signed [WIDTH-1:0] s4_bfx1r = s4_bf_active ? signed'(s3_do_re) : 0;
wire signed [WIDTH-1:0] s4_bfx1i = s4_bf_active ? signed'(s3_do_im) : 0;
wire signed [WIDTH:0] s4_bfar = s4_bfx0r + s4_bfx1r;
wire signed [WIDTH:0] s4_bfai = s4_bfx0i + s4_bfx1i;
wire signed [WIDTH:0] s4_bfsr = s4_bfx0r - s4_bfx1r;
wire signed [WIDTH:0] s4_bfsi = s4_bfx0i - s4_bfx1i;
wire [WIDTH-1:0] s4_bfy0r = s4_bfar >>> 1;
wire [WIDTH-1:0] s4_bfy0i = s4_bfai >>> 1;
wire [WIDTH-1:0] s4_bfy1r = s4_bfsr >>> 1;
wire [WIDTH-1:0] s4_bfy1i = s4_bfsi >>> 1;

wire [WIDTH-1:0] s4_dbin_r = s4_bf_active ? s4_bfy1r : s3_do_re;
wire [WIDTH-1:0] s4_dbin_i = s4_bf_active ? s4_bfy1i : s3_do_im;
wire [WIDTH-1:0] s4_bfspr = s4_bf_active ? s4_bfy0r : s4_db_re;
wire [WIDTH-1:0] s4_bfspi = s4_bf_active ? s4_bfy0i : s4_db_im;

always @(posedge clock) begin
    s4_db_re <= s4_dbin_r;
    s4_db_im <= s4_dbin_i;
end

reg s4_bfspen;
always @(posedge clock or posedge reset) begin
    if (reset) s4_bfspen <= 0;
    else s4_bfspen <= (s3_do_en & mode);
end

reg s4_do_en;
reg [WIDTH-1:0] s4_do_re, s4_do_im;
always @(posedge clock) begin
    s4_do_re <= s4_bfspr;
    s4_do_im <= s4_bfspi;
end
always @(posedge clock or posedge reset) begin
    if (reset) s4_do_en <= 0;
    else s4_do_en <= s4_bfspen;
end

// Output mux: 64-mode → SU3 output; 128-mode → SdfUnit2 output
assign do_en = mode ? s4_do_en : s3_do_en;
assign do_re = mode ? s4_do_re : s3_do_re;
assign do_im = mode ? s4_do_im : s3_do_im;

endmodule
