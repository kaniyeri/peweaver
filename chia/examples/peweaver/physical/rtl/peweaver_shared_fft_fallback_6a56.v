
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


reg mode_active;
reg busy;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        mode_active <= 0;
        busy <= 0;
    end else begin
        if (!busy && di_en) begin
            mode_active <= mode;
            busy <= 1;
        end
    end
end
wire effective_mode = busy ? mode_active : mode;



//----------------------------------------------------------------------
// Stage 1: 128=(N=128, M=128), 64=(N=64, M=64)
//----------------------------------------------------------------------
reg [6:0] s1_di_count_1;
reg [5:0] s1_di_count_0;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s1_di_count_1 <= 0;
        s1_di_count_0 <= 0;
    end else begin
        if (effective_mode)
            s1_di_count_1 <= di_en ? (s1_di_count_1 + 1'b1) : 0;
        else
            s1_di_count_0 <= di_en ? (s1_di_count_0 + 1'b1) : 0;
    end
end

wire s1_bf1_bf_1 = s1_di_count_1[6];
wire s1_bf1_bf_0 = s1_di_count_0[5];
wire s1_bf1_bf   = effective_mode ? s1_bf1_bf_1 : s1_bf1_bf_0;

wire [WIDTH-1:0] s1_db1_do_re_1, s1_db1_do_im_1;
wire [WIDTH-1:0] s1_db1_do_re_0, s1_db1_do_im_0;

reg [WIDTH-1:0] s1_db1_re [0:63];
reg [WIDTH-1:0] s1_db1_im [0:63];

assign s1_db1_do_re_1 = s1_db1_re[63];
assign s1_db1_do_im_1 = s1_db1_im[63];
assign s1_db1_do_re_0 = s1_db1_re[31];
assign s1_db1_do_im_0 = s1_db1_im[31];

wire [WIDTH-1:0] s1_db1_do_re = effective_mode ? s1_db1_do_re_1 : s1_db1_do_re_0;
wire [WIDTH-1:0] s1_db1_do_im = effective_mode ? s1_db1_do_im_1 : s1_db1_do_im_0;

wire [WIDTH-1:0] s1_bf1_x0_re = s1_bf1_bf ? s1_db1_do_re : 16'b0;
wire [WIDTH-1:0] s1_bf1_x0_im = s1_bf1_bf ? s1_db1_do_im : 16'b0;
wire [WIDTH-1:0] s1_bf1_x1_re = s1_bf1_bf ? di_re : 16'b0;
wire [WIDTH-1:0] s1_bf1_x1_im = s1_bf1_bf ? di_im : 16'b0;


wire signed [WIDTH-1:0] s1_bf1_x0r = $signed(s1_bf1_x0_re);
wire signed [WIDTH-1:0] s1_bf1_x0i = $signed(s1_bf1_x0_im);
wire signed [WIDTH-1:0] s1_bf1_x1r = $signed(s1_bf1_x1_re);
wire signed [WIDTH-1:0] s1_bf1_x1i = $signed(s1_bf1_x1_im);
wire signed [WIDTH:0] s1_bf1_ar = s1_bf1_x0r + s1_bf1_x1r;
wire signed [WIDTH:0] s1_bf1_ai = s1_bf1_x0i + s1_bf1_x1i;
wire signed [WIDTH:0] s1_bf1_sr = s1_bf1_x0r - s1_bf1_x1r;
wire signed [WIDTH:0] s1_bf1_si = s1_bf1_x0i - s1_bf1_x1i;
wire [WIDTH-1:0] s1_bf1_y0_re = (s1_bf1_ar + 0) >>> 1;
wire [WIDTH-1:0] s1_bf1_y0_im = (s1_bf1_ai + 0) >>> 1;
wire [WIDTH-1:0] s1_bf1_y1_re = (s1_bf1_sr + 0) >>> 1;
wire [WIDTH-1:0] s1_bf1_y1_im = (s1_bf1_si + 0) >>> 1;


wire [WIDTH-1:0] s1_db1_di_re = s1_bf1_bf ? s1_bf1_y1_re : di_re;
wire [WIDTH-1:0] s1_db1_di_im = s1_bf1_bf ? s1_bf1_y1_im : di_im;

integer s1_i1;
always @(posedge clock) begin
    if (effective_mode) begin
        for (s1_i1=63; s1_i1>0; s1_i1=s1_i1-1) begin
            s1_db1_re[s1_i1] <= s1_db1_re[s1_i1-1];
            s1_db1_im[s1_i1] <= s1_db1_im[s1_i1-1];
        end
        s1_db1_re[0] <= s1_db1_di_re;
        s1_db1_im[0] <= s1_db1_di_im;
    end else begin
        for (s1_i1=31; s1_i1>0; s1_i1=s1_i1-1) begin
            s1_db1_re[s1_i1] <= s1_db1_re[s1_i1-1];
            s1_db1_im[s1_i1] <= s1_db1_im[s1_i1-1];
        end
        s1_db1_re[0] <= s1_db1_di_re;
        s1_db1_im[0] <= s1_db1_di_im;
    end
end

wire s1_bf1_start_1 = (s1_di_count_1 == 63);
wire s1_bf1_start_0 = (s1_di_count_0 == 31);
wire s1_bf1_start   = effective_mode ? s1_bf1_start_1 : s1_bf1_start_0;

reg s1_bf1_sp_en_1, s1_bf1_sp_en_0;
reg [6:0] s1_bf1_count_1;
reg [5:0] s1_bf1_count_0;

wire s1_bf1_end_1 = (s1_bf1_count_1 == 127);
wire s1_bf1_end_0 = (s1_bf1_count_0 == 63);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s1_bf1_sp_en_1 <= 0;
        s1_bf1_count_1 <= 0;
        s1_bf1_sp_en_0 <= 0;
        s1_bf1_count_0 <= 0;
    end else begin
        if (effective_mode) begin
            s1_bf1_sp_en_1 <= s1_bf1_start_1 ? 1'b1 : s1_bf1_end_1 ? 1'b0 : s1_bf1_sp_en_1;
            s1_bf1_count_1 <= s1_bf1_sp_en_1 ? (s1_bf1_count_1 + 1'b1) : 0;
        end else begin
            s1_bf1_sp_en_0 <= s1_bf1_start_0 ? 1'b1 : s1_bf1_end_0 ? 1'b0 : s1_bf1_sp_en_0;
            s1_bf1_count_0 <= s1_bf1_sp_en_0 ? (s1_bf1_count_0 + 1'b1) : 0;
        end
    end
end

wire s1_bf1_mj_1 = (s1_bf1_count_1[6:5] == 2'd3);
wire s1_bf1_mj_0 = (s1_bf1_count_0[5:4] == 2'd3);
wire s1_bf1_mj   = effective_mode ? s1_bf1_mj_1 : s1_bf1_mj_0;

wire [WIDTH-1:0] s1_bf1_sp_re = s1_bf1_bf ? s1_bf1_y0_re : s1_bf1_mj ? s1_db1_do_im : s1_db1_do_re;
wire [WIDTH-1:0] s1_bf1_sp_im = s1_bf1_bf ? s1_bf1_y0_im : s1_bf1_mj ? (0 - s1_db1_do_re) : s1_db1_do_im;

reg [WIDTH-1:0] s1_bf1_do_re, s1_bf1_do_im;
always @(posedge clock) begin
    s1_bf1_do_re <= s1_bf1_sp_re;
    s1_bf1_do_im <= s1_bf1_sp_im;
end

// 2nd Butterfly
reg s1_bf2_bf_1, s1_bf2_bf_0, s1_bf2_bf;
always @(posedge clock) begin
    s1_bf2_bf_1 <= s1_bf1_count_1[5];
    s1_bf2_bf_0 <= s1_bf1_count_0[4];
    s1_bf2_bf   <= effective_mode ? s1_bf1_count_1[5] : s1_bf1_count_0[4];
end

wire [WIDTH-1:0] s1_db2_do_re_1, s1_db2_do_im_1;
wire [WIDTH-1:0] s1_db2_do_re_0, s1_db2_do_im_0;
reg [WIDTH-1:0] s1_db2_re [0:31];
reg [WIDTH-1:0] s1_db2_im [0:31];

assign s1_db2_do_re_1 = s1_db2_re[31];
assign s1_db2_do_im_1 = s1_db2_im[31];
assign s1_db2_do_re_0 = s1_db2_re[15];
assign s1_db2_do_im_0 = s1_db2_im[15];

wire [WIDTH-1:0] s1_db2_do_re = effective_mode ? s1_db2_do_re_1 : s1_db2_do_re_0;
wire [WIDTH-1:0] s1_db2_do_im = effective_mode ? s1_db2_do_im_1 : s1_db2_do_im_0;

wire [WIDTH-1:0] s1_bf2_x0_re = s1_bf2_bf ? s1_db2_do_re : 16'b0;
wire [WIDTH-1:0] s1_bf2_x0_im = s1_bf2_bf ? s1_db2_do_im : 16'b0;
wire [WIDTH-1:0] s1_bf2_x1_re = s1_bf2_bf ? s1_bf1_do_re : 16'b0;
wire [WIDTH-1:0] s1_bf2_x1_im = s1_bf2_bf ? s1_bf1_do_im : 16'b0;


wire signed [WIDTH-1:0] s1_bf2_x0r = $signed(s1_bf2_x0_re);
wire signed [WIDTH-1:0] s1_bf2_x0i = $signed(s1_bf2_x0_im);
wire signed [WIDTH-1:0] s1_bf2_x1r = $signed(s1_bf2_x1_re);
wire signed [WIDTH-1:0] s1_bf2_x1i = $signed(s1_bf2_x1_im);
wire signed [WIDTH:0] s1_bf2_ar = s1_bf2_x0r + s1_bf2_x1r;
wire signed [WIDTH:0] s1_bf2_ai = s1_bf2_x0i + s1_bf2_x1i;
wire signed [WIDTH:0] s1_bf2_sr = s1_bf2_x0r - s1_bf2_x1r;
wire signed [WIDTH:0] s1_bf2_si = s1_bf2_x0i - s1_bf2_x1i;
wire [WIDTH-1:0] s1_bf2_y0_re = (s1_bf2_ar + 1) >>> 1;
wire [WIDTH-1:0] s1_bf2_y0_im = (s1_bf2_ai + 1) >>> 1;
wire [WIDTH-1:0] s1_bf2_y1_re = (s1_bf2_sr + 1) >>> 1;
wire [WIDTH-1:0] s1_bf2_y1_im = (s1_bf2_si + 1) >>> 1;


wire [WIDTH-1:0] s1_db2_di_re = s1_bf2_bf ? s1_bf2_y1_re : s1_bf1_do_re;
wire [WIDTH-1:0] s1_db2_di_im = s1_bf2_bf ? s1_bf2_y1_im : s1_bf1_do_im;

integer s1_i2;
always @(posedge clock) begin
    if (effective_mode) begin
        for (s1_i2=31; s1_i2>0; s1_i2=s1_i2-1) begin
            s1_db2_re[s1_i2] <= s1_db2_re[s1_i2-1];
            s1_db2_im[s1_i2] <= s1_db2_im[s1_i2-1];
        end
        s1_db2_re[0] <= s1_db2_di_re;
        s1_db2_im[0] <= s1_db2_di_im;
    end else begin
        for (s1_i2=15; s1_i2>0; s1_i2=s1_i2-1) begin
            s1_db2_re[s1_i2] <= s1_db2_re[s1_i2-1];
            s1_db2_im[s1_i2] <= s1_db2_im[s1_i2-1];
        end
        s1_db2_re[0] <= s1_db2_di_re;
        s1_db2_im[0] <= s1_db2_di_im;
    end
end

wire [WIDTH-1:0] s1_bf2_sp_re = s1_bf2_bf ? s1_bf2_y0_re : s1_db2_do_re;
wire [WIDTH-1:0] s1_bf2_sp_im = s1_bf2_bf ? s1_bf2_y0_im : s1_db2_do_im;

reg s1_bf2_sp_en_1, s1_bf2_sp_en_0;
reg [6:0] s1_bf2_count_1;
reg [5:0] s1_bf2_count_0;
reg s1_bf2_start_1, s1_bf2_start_0;
wire s1_bf2_end_1 = (s1_bf2_count_1 == 127);
wire s1_bf2_end_0 = (s1_bf2_count_0 == 63);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s1_bf2_sp_en_1 <= 0; s1_bf2_count_1 <= 0;
        s1_bf2_sp_en_0 <= 0; s1_bf2_count_0 <= 0;
    end else begin
        if (effective_mode) begin
            s1_bf2_sp_en_1 <= s1_bf2_start_1 ? 1'b1 : s1_bf2_end_1 ? 1'b0 : s1_bf2_sp_en_1;
            s1_bf2_count_1 <= s1_bf2_sp_en_1 ? (s1_bf2_count_1 + 1'b1) : 0;
        end else begin
            s1_bf2_sp_en_0 <= s1_bf2_start_0 ? 1'b1 : s1_bf2_end_0 ? 1'b0 : s1_bf2_sp_en_0;
            s1_bf2_count_0 <= s1_bf2_sp_en_0 ? (s1_bf2_count_0 + 1'b1) : 0;
        end
    end
end

always @(posedge clock) begin
    s1_bf2_start_1 <= (s1_bf1_count_1 == 31) & s1_bf1_sp_en_1;
    s1_bf2_start_0 <= (s1_bf1_count_0 == 15) & s1_bf1_sp_en_0;
end

reg [WIDTH-1:0] s1_bf2_do_re, s1_bf2_do_im;
always @(posedge clock) begin
    s1_bf2_do_re <= s1_bf2_sp_re;
    s1_bf2_do_im <= s1_bf2_sp_im;
end

reg s1_bf2_do_en;
always @(posedge clock or posedge reset) begin
    if (reset) s1_bf2_do_en <= 0;
    else s1_bf2_do_en <= effective_mode ? s1_bf2_sp_en_1 : s1_bf2_sp_en_0;
end

// Twiddle
wire [1:0] s1_tw_sel_1 = {s1_bf2_count_1[5], s1_bf2_count_1[6]};
wire [4:0] s1_tw_num_1 = (s1_bf2_count_1 << 0);
wire [6:0] s1_tw_addr_1 = ({2'b0, s1_tw_num_1} * {5'b0, s1_tw_sel_1});

wire [1:0] s1_tw_sel_0 = {s1_bf2_count_0[4], s1_bf2_count_0[5]};
wire [3:0] s1_tw_num_0 = (s1_bf2_count_0 << 0);
wire [6:0] s1_tw_addr_0 = ({3'b0, s1_tw_num_0} * {5'b0, s1_tw_sel_0}) * 2;

wire [6:0] s1_tw_addr = effective_mode ? s1_tw_addr_1 : s1_tw_addr_0;


reg [WIDTH-1:0] s1_tw_re, s1_tw_im;
always @(posedge clock) begin
    case (s1_tw_addr)
            7'h00: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h01: begin s1_tw_re <= 16'h7FD9; s1_tw_im <= 16'hF9B8; end
            7'h02: begin s1_tw_re <= 16'h7F62; s1_tw_im <= 16'hF374; end
            7'h03: begin s1_tw_re <= 16'h7E9D; s1_tw_im <= 16'hED38; end
            7'h04: begin s1_tw_re <= 16'h7D8A; s1_tw_im <= 16'hE707; end
            7'h05: begin s1_tw_re <= 16'h7C2A; s1_tw_im <= 16'hE0E6; end
            7'h06: begin s1_tw_re <= 16'h7A7D; s1_tw_im <= 16'hDAD8; end
            7'h07: begin s1_tw_re <= 16'h7885; s1_tw_im <= 16'hD4E1; end
            7'h08: begin s1_tw_re <= 16'h7642; s1_tw_im <= 16'hCF04; end
            7'h09: begin s1_tw_re <= 16'h73B6; s1_tw_im <= 16'hC946; end
            7'h0A: begin s1_tw_re <= 16'h70E3; s1_tw_im <= 16'hC3A9; end
            7'h0B: begin s1_tw_re <= 16'h6DCA; s1_tw_im <= 16'hBE32; end
            7'h0C: begin s1_tw_re <= 16'h6A6E; s1_tw_im <= 16'hB8E3; end
            7'h0D: begin s1_tw_re <= 16'h66D0; s1_tw_im <= 16'hB3C0; end
            7'h0E: begin s1_tw_re <= 16'h62F2; s1_tw_im <= 16'hAECC; end
            7'h0F: begin s1_tw_re <= 16'h5ED7; s1_tw_im <= 16'hAA0A; end
            7'h10: begin s1_tw_re <= 16'h5A82; s1_tw_im <= 16'hA57E; end
            7'h11: begin s1_tw_re <= 16'h55F6; s1_tw_im <= 16'hA129; end
            7'h12: begin s1_tw_re <= 16'h5134; s1_tw_im <= 16'h9D0E; end
            7'h13: begin s1_tw_re <= 16'h4C40; s1_tw_im <= 16'h9930; end
            7'h14: begin s1_tw_re <= 16'h471D; s1_tw_im <= 16'h9592; end
            7'h15: begin s1_tw_re <= 16'h41CE; s1_tw_im <= 16'h9236; end
            7'h16: begin s1_tw_re <= 16'h3C57; s1_tw_im <= 16'h8F1D; end
            7'h17: begin s1_tw_re <= 16'h36BA; s1_tw_im <= 16'h8C4A; end
            7'h18: begin s1_tw_re <= 16'h30FC; s1_tw_im <= 16'h89BE; end
            7'h19: begin s1_tw_re <= 16'h2B1F; s1_tw_im <= 16'h877B; end
            7'h1A: begin s1_tw_re <= 16'h2528; s1_tw_im <= 16'h8583; end
            7'h1B: begin s1_tw_re <= 16'h1F1A; s1_tw_im <= 16'h83D6; end
            7'h1C: begin s1_tw_re <= 16'h18F9; s1_tw_im <= 16'h8276; end
            7'h1D: begin s1_tw_re <= 16'h12C8; s1_tw_im <= 16'h8163; end
            7'h1E: begin s1_tw_re <= 16'h0C8C; s1_tw_im <= 16'h809E; end
            7'h1F: begin s1_tw_re <= 16'h0648; s1_tw_im <= 16'h8027; end
            7'h20: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h8000; end
            7'h21: begin s1_tw_re <= 16'hF9B8; s1_tw_im <= 16'h8027; end
            7'h22: begin s1_tw_re <= 16'hF374; s1_tw_im <= 16'h809E; end
            7'h23: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h24: begin s1_tw_re <= 16'hE707; s1_tw_im <= 16'h8276; end
            7'h25: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h26: begin s1_tw_re <= 16'hDAD8; s1_tw_im <= 16'h8583; end
            7'h27: begin s1_tw_re <= 16'hD4E1; s1_tw_im <= 16'h877B; end
            7'h28: begin s1_tw_re <= 16'hCF04; s1_tw_im <= 16'h89BE; end
            7'h29: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h2A: begin s1_tw_re <= 16'hC3A9; s1_tw_im <= 16'h8F1D; end
            7'h2B: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h2C: begin s1_tw_re <= 16'hB8E3; s1_tw_im <= 16'h9592; end
            7'h2D: begin s1_tw_re <= 16'hB3C0; s1_tw_im <= 16'h9930; end
            7'h2E: begin s1_tw_re <= 16'hAECC; s1_tw_im <= 16'h9D0E; end
            7'h2F: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h30: begin s1_tw_re <= 16'hA57E; s1_tw_im <= 16'hA57E; end
            7'h31: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h32: begin s1_tw_re <= 16'h9D0E; s1_tw_im <= 16'hAECC; end
            7'h33: begin s1_tw_re <= 16'h9930; s1_tw_im <= 16'hB3C0; end
            7'h34: begin s1_tw_re <= 16'h9592; s1_tw_im <= 16'hB8E3; end
            7'h35: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h36: begin s1_tw_re <= 16'h8F1D; s1_tw_im <= 16'hC3A9; end
            7'h37: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h38: begin s1_tw_re <= 16'h89BE; s1_tw_im <= 16'hCF04; end
            7'h39: begin s1_tw_re <= 16'h877B; s1_tw_im <= 16'hD4E1; end
            7'h3A: begin s1_tw_re <= 16'h8583; s1_tw_im <= 16'hDAD8; end
            7'h3B: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h3C: begin s1_tw_re <= 16'h8276; s1_tw_im <= 16'hE707; end
            7'h3D: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h3E: begin s1_tw_re <= 16'h809E; s1_tw_im <= 16'hF374; end
            7'h3F: begin s1_tw_re <= 16'h8027; s1_tw_im <= 16'hF9B8; end
            7'h40: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h41: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h42: begin s1_tw_re <= 16'h809E; s1_tw_im <= 16'h0C8C; end
            7'h43: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h44: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h45: begin s1_tw_re <= 16'h83D6; s1_tw_im <= 16'h1F1A; end
            7'h46: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h47: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h48: begin s1_tw_re <= 16'h89BE; s1_tw_im <= 16'h30FC; end
            7'h49: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h4A: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h4B: begin s1_tw_re <= 16'h9236; s1_tw_im <= 16'h41CE; end
            7'h4C: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h4D: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h4E: begin s1_tw_re <= 16'h9D0E; s1_tw_im <= 16'h5134; end
            7'h4F: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h50: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h51: begin s1_tw_re <= 16'hAA0A; s1_tw_im <= 16'h5ED7; end
            7'h52: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h53: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h54: begin s1_tw_re <= 16'hB8E3; s1_tw_im <= 16'h6A6E; end
            7'h55: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h56: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h57: begin s1_tw_re <= 16'hC946; s1_tw_im <= 16'h73B6; end
            7'h58: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h59: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h5A: begin s1_tw_re <= 16'hDAD8; s1_tw_im <= 16'h7A7D; end
            7'h5B: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h5C: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h5D: begin s1_tw_re <= 16'hED38; s1_tw_im <= 16'h7E9D; end
            7'h5E: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h5F: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h60: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h61: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h62: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h63: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h64: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h65: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h66: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h67: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h68: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h69: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h6A: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h6B: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h6C: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h6D: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h6E: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h6F: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h70: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h71: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h72: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h73: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h74: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h75: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h76: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h77: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h78: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h79: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h7A: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h7B: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h7C: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h7D: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h7E: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
            7'h7F: begin s1_tw_re <= 16'h0000; s1_tw_im <= 16'h0000; end
        default: begin s1_tw_re <= 0; s1_tw_im <= 0; end
    endcase
end


reg s1_mu_en;
always @(posedge clock) begin
    if (effective_mode == 0 && 6 == 2) s1_mu_en <= 0;
    else s1_mu_en <= (s1_tw_addr != 0);
end

wire [WIDTH-1:0] s1_mu_a_re = s1_mu_en ? s1_bf2_do_re : 16'b0;
wire [WIDTH-1:0] s1_mu_a_im = s1_mu_en ? s1_bf2_do_im : 16'b0;

wire signed [WIDTH-1:0] s1_mu_ar = $signed(s1_mu_a_re);
wire signed [WIDTH-1:0] s1_mu_ai = $signed(s1_mu_a_im);
wire signed [WIDTH-1:0] s1_mu_br = $signed(s1_tw_re);
wire signed [WIDTH-1:0] s1_mu_bi = $signed(s1_tw_im);
wire signed [2*WIDTH-1:0] s1_mu_rr = s1_mu_ar * s1_mu_br;
wire signed [2*WIDTH-1:0] s1_mu_ri = s1_mu_ar * s1_mu_bi;
wire signed [2*WIDTH-1:0] s1_mu_ir = s1_mu_ai * s1_mu_br;
wire signed [2*WIDTH-1:0] s1_mu_ii = s1_mu_ai * s1_mu_bi;
wire [WIDTH-1:0] s1_mu_m_re = (s1_mu_rr >>> 15) - (s1_mu_ii >>> 15);
wire [WIDTH-1:0] s1_mu_m_im = (s1_mu_ri >>> 15) + (s1_mu_ir >>> 15);


reg [WIDTH-1:0] s1_mu_do_re, s1_mu_do_im;
always @(posedge clock) begin
    s1_mu_do_re <= s1_mu_en ? s1_mu_m_re : s1_bf2_do_re;
    s1_mu_do_im <= s1_mu_en ? s1_mu_m_im : s1_bf2_do_im;
end

reg s1_mu_do_en;
always @(posedge clock or posedge reset) begin
    if (reset) s1_mu_do_en <= 0;
    else s1_mu_do_en <= s1_bf2_do_en;
end

wire s1_do_en = (7==2 && mode_active) ? s1_bf2_do_en : (6==2 && !effective_mode) ? s1_bf2_do_en : s1_mu_do_en;
wire [WIDTH-1:0] s1_do_re = (7==2 && mode_active) ? s1_bf2_do_re : (6==2 && !effective_mode) ? s1_bf2_do_re : s1_mu_do_re;
wire [WIDTH-1:0] s1_do_im = (7==2 && mode_active) ? s1_bf2_do_im : (6==2 && !effective_mode) ? s1_bf2_do_im : s1_mu_do_im;


//----------------------------------------------------------------------
// Stage 2: 128=(N=128, M=32), 64=(N=64, M=16)
//----------------------------------------------------------------------
reg [6:0] s2_di_count_1;
reg [5:0] s2_di_count_0;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s2_di_count_1 <= 0;
        s2_di_count_0 <= 0;
    end else begin
        if (effective_mode)
            s2_di_count_1 <= s1_do_en ? (s2_di_count_1 + 1'b1) : 0;
        else
            s2_di_count_0 <= s1_do_en ? (s2_di_count_0 + 1'b1) : 0;
    end
end

wire s2_bf1_bf_1 = s2_di_count_1[4];
wire s2_bf1_bf_0 = s2_di_count_0[3];
wire s2_bf1_bf   = effective_mode ? s2_bf1_bf_1 : s2_bf1_bf_0;

wire [WIDTH-1:0] s2_db1_do_re_1, s2_db1_do_im_1;
wire [WIDTH-1:0] s2_db1_do_re_0, s2_db1_do_im_0;

reg [WIDTH-1:0] s2_db1_re [0:15];
reg [WIDTH-1:0] s2_db1_im [0:15];

assign s2_db1_do_re_1 = s2_db1_re[15];
assign s2_db1_do_im_1 = s2_db1_im[15];
assign s2_db1_do_re_0 = s2_db1_re[7];
assign s2_db1_do_im_0 = s2_db1_im[7];

wire [WIDTH-1:0] s2_db1_do_re = effective_mode ? s2_db1_do_re_1 : s2_db1_do_re_0;
wire [WIDTH-1:0] s2_db1_do_im = effective_mode ? s2_db1_do_im_1 : s2_db1_do_im_0;

wire [WIDTH-1:0] s2_bf1_x0_re = s2_bf1_bf ? s2_db1_do_re : 16'b0;
wire [WIDTH-1:0] s2_bf1_x0_im = s2_bf1_bf ? s2_db1_do_im : 16'b0;
wire [WIDTH-1:0] s2_bf1_x1_re = s2_bf1_bf ? s1_do_re : 16'b0;
wire [WIDTH-1:0] s2_bf1_x1_im = s2_bf1_bf ? s1_do_im : 16'b0;


wire signed [WIDTH-1:0] s2_bf1_x0r = $signed(s2_bf1_x0_re);
wire signed [WIDTH-1:0] s2_bf1_x0i = $signed(s2_bf1_x0_im);
wire signed [WIDTH-1:0] s2_bf1_x1r = $signed(s2_bf1_x1_re);
wire signed [WIDTH-1:0] s2_bf1_x1i = $signed(s2_bf1_x1_im);
wire signed [WIDTH:0] s2_bf1_ar = s2_bf1_x0r + s2_bf1_x1r;
wire signed [WIDTH:0] s2_bf1_ai = s2_bf1_x0i + s2_bf1_x1i;
wire signed [WIDTH:0] s2_bf1_sr = s2_bf1_x0r - s2_bf1_x1r;
wire signed [WIDTH:0] s2_bf1_si = s2_bf1_x0i - s2_bf1_x1i;
wire [WIDTH-1:0] s2_bf1_y0_re = (s2_bf1_ar + 0) >>> 1;
wire [WIDTH-1:0] s2_bf1_y0_im = (s2_bf1_ai + 0) >>> 1;
wire [WIDTH-1:0] s2_bf1_y1_re = (s2_bf1_sr + 0) >>> 1;
wire [WIDTH-1:0] s2_bf1_y1_im = (s2_bf1_si + 0) >>> 1;


wire [WIDTH-1:0] s2_db1_di_re = s2_bf1_bf ? s2_bf1_y1_re : s1_do_re;
wire [WIDTH-1:0] s2_db1_di_im = s2_bf1_bf ? s2_bf1_y1_im : s1_do_im;

integer s2_i1;
always @(posedge clock) begin
    if (effective_mode) begin
        for (s2_i1=15; s2_i1>0; s2_i1=s2_i1-1) begin
            s2_db1_re[s2_i1] <= s2_db1_re[s2_i1-1];
            s2_db1_im[s2_i1] <= s2_db1_im[s2_i1-1];
        end
        s2_db1_re[0] <= s2_db1_di_re;
        s2_db1_im[0] <= s2_db1_di_im;
    end else begin
        for (s2_i1=7; s2_i1>0; s2_i1=s2_i1-1) begin
            s2_db1_re[s2_i1] <= s2_db1_re[s2_i1-1];
            s2_db1_im[s2_i1] <= s2_db1_im[s2_i1-1];
        end
        s2_db1_re[0] <= s2_db1_di_re;
        s2_db1_im[0] <= s2_db1_di_im;
    end
end

wire s2_bf1_start_1 = (s2_di_count_1 == 15);
wire s2_bf1_start_0 = (s2_di_count_0 == 7);
wire s2_bf1_start   = effective_mode ? s2_bf1_start_1 : s2_bf1_start_0;

reg s2_bf1_sp_en_1, s2_bf1_sp_en_0;
reg [6:0] s2_bf1_count_1;
reg [5:0] s2_bf1_count_0;

wire s2_bf1_end_1 = (s2_bf1_count_1 == 127);
wire s2_bf1_end_0 = (s2_bf1_count_0 == 63);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s2_bf1_sp_en_1 <= 0;
        s2_bf1_count_1 <= 0;
        s2_bf1_sp_en_0 <= 0;
        s2_bf1_count_0 <= 0;
    end else begin
        if (effective_mode) begin
            s2_bf1_sp_en_1 <= s2_bf1_start_1 ? 1'b1 : s2_bf1_end_1 ? 1'b0 : s2_bf1_sp_en_1;
            s2_bf1_count_1 <= s2_bf1_sp_en_1 ? (s2_bf1_count_1 + 1'b1) : 0;
        end else begin
            s2_bf1_sp_en_0 <= s2_bf1_start_0 ? 1'b1 : s2_bf1_end_0 ? 1'b0 : s2_bf1_sp_en_0;
            s2_bf1_count_0 <= s2_bf1_sp_en_0 ? (s2_bf1_count_0 + 1'b1) : 0;
        end
    end
end

wire s2_bf1_mj_1 = (s2_bf1_count_1[4:3] == 2'd3);
wire s2_bf1_mj_0 = (s2_bf1_count_0[3:2] == 2'd3);
wire s2_bf1_mj   = effective_mode ? s2_bf1_mj_1 : s2_bf1_mj_0;

wire [WIDTH-1:0] s2_bf1_sp_re = s2_bf1_bf ? s2_bf1_y0_re : s2_bf1_mj ? s2_db1_do_im : s2_db1_do_re;
wire [WIDTH-1:0] s2_bf1_sp_im = s2_bf1_bf ? s2_bf1_y0_im : s2_bf1_mj ? (0 - s2_db1_do_re) : s2_db1_do_im;

reg [WIDTH-1:0] s2_bf1_do_re, s2_bf1_do_im;
always @(posedge clock) begin
    s2_bf1_do_re <= s2_bf1_sp_re;
    s2_bf1_do_im <= s2_bf1_sp_im;
end

// 2nd Butterfly
reg s2_bf2_bf_1, s2_bf2_bf_0, s2_bf2_bf;
always @(posedge clock) begin
    s2_bf2_bf_1 <= s2_bf1_count_1[3];
    s2_bf2_bf_0 <= s2_bf1_count_0[2];
    s2_bf2_bf   <= effective_mode ? s2_bf1_count_1[3] : s2_bf1_count_0[2];
end

wire [WIDTH-1:0] s2_db2_do_re_1, s2_db2_do_im_1;
wire [WIDTH-1:0] s2_db2_do_re_0, s2_db2_do_im_0;
reg [WIDTH-1:0] s2_db2_re [0:7];
reg [WIDTH-1:0] s2_db2_im [0:7];

assign s2_db2_do_re_1 = s2_db2_re[7];
assign s2_db2_do_im_1 = s2_db2_im[7];
assign s2_db2_do_re_0 = s2_db2_re[3];
assign s2_db2_do_im_0 = s2_db2_im[3];

wire [WIDTH-1:0] s2_db2_do_re = effective_mode ? s2_db2_do_re_1 : s2_db2_do_re_0;
wire [WIDTH-1:0] s2_db2_do_im = effective_mode ? s2_db2_do_im_1 : s2_db2_do_im_0;

wire [WIDTH-1:0] s2_bf2_x0_re = s2_bf2_bf ? s2_db2_do_re : 16'b0;
wire [WIDTH-1:0] s2_bf2_x0_im = s2_bf2_bf ? s2_db2_do_im : 16'b0;
wire [WIDTH-1:0] s2_bf2_x1_re = s2_bf2_bf ? s2_bf1_do_re : 16'b0;
wire [WIDTH-1:0] s2_bf2_x1_im = s2_bf2_bf ? s2_bf1_do_im : 16'b0;


wire signed [WIDTH-1:0] s2_bf2_x0r = $signed(s2_bf2_x0_re);
wire signed [WIDTH-1:0] s2_bf2_x0i = $signed(s2_bf2_x0_im);
wire signed [WIDTH-1:0] s2_bf2_x1r = $signed(s2_bf2_x1_re);
wire signed [WIDTH-1:0] s2_bf2_x1i = $signed(s2_bf2_x1_im);
wire signed [WIDTH:0] s2_bf2_ar = s2_bf2_x0r + s2_bf2_x1r;
wire signed [WIDTH:0] s2_bf2_ai = s2_bf2_x0i + s2_bf2_x1i;
wire signed [WIDTH:0] s2_bf2_sr = s2_bf2_x0r - s2_bf2_x1r;
wire signed [WIDTH:0] s2_bf2_si = s2_bf2_x0i - s2_bf2_x1i;
wire [WIDTH-1:0] s2_bf2_y0_re = (s2_bf2_ar + 1) >>> 1;
wire [WIDTH-1:0] s2_bf2_y0_im = (s2_bf2_ai + 1) >>> 1;
wire [WIDTH-1:0] s2_bf2_y1_re = (s2_bf2_sr + 1) >>> 1;
wire [WIDTH-1:0] s2_bf2_y1_im = (s2_bf2_si + 1) >>> 1;


wire [WIDTH-1:0] s2_db2_di_re = s2_bf2_bf ? s2_bf2_y1_re : s2_bf1_do_re;
wire [WIDTH-1:0] s2_db2_di_im = s2_bf2_bf ? s2_bf2_y1_im : s2_bf1_do_im;

integer s2_i2;
always @(posedge clock) begin
    if (effective_mode) begin
        for (s2_i2=7; s2_i2>0; s2_i2=s2_i2-1) begin
            s2_db2_re[s2_i2] <= s2_db2_re[s2_i2-1];
            s2_db2_im[s2_i2] <= s2_db2_im[s2_i2-1];
        end
        s2_db2_re[0] <= s2_db2_di_re;
        s2_db2_im[0] <= s2_db2_di_im;
    end else begin
        for (s2_i2=3; s2_i2>0; s2_i2=s2_i2-1) begin
            s2_db2_re[s2_i2] <= s2_db2_re[s2_i2-1];
            s2_db2_im[s2_i2] <= s2_db2_im[s2_i2-1];
        end
        s2_db2_re[0] <= s2_db2_di_re;
        s2_db2_im[0] <= s2_db2_di_im;
    end
end

wire [WIDTH-1:0] s2_bf2_sp_re = s2_bf2_bf ? s2_bf2_y0_re : s2_db2_do_re;
wire [WIDTH-1:0] s2_bf2_sp_im = s2_bf2_bf ? s2_bf2_y0_im : s2_db2_do_im;

reg s2_bf2_sp_en_1, s2_bf2_sp_en_0;
reg [6:0] s2_bf2_count_1;
reg [5:0] s2_bf2_count_0;
reg s2_bf2_start_1, s2_bf2_start_0;
wire s2_bf2_end_1 = (s2_bf2_count_1 == 127);
wire s2_bf2_end_0 = (s2_bf2_count_0 == 63);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s2_bf2_sp_en_1 <= 0; s2_bf2_count_1 <= 0;
        s2_bf2_sp_en_0 <= 0; s2_bf2_count_0 <= 0;
    end else begin
        if (effective_mode) begin
            s2_bf2_sp_en_1 <= s2_bf2_start_1 ? 1'b1 : s2_bf2_end_1 ? 1'b0 : s2_bf2_sp_en_1;
            s2_bf2_count_1 <= s2_bf2_sp_en_1 ? (s2_bf2_count_1 + 1'b1) : 0;
        end else begin
            s2_bf2_sp_en_0 <= s2_bf2_start_0 ? 1'b1 : s2_bf2_end_0 ? 1'b0 : s2_bf2_sp_en_0;
            s2_bf2_count_0 <= s2_bf2_sp_en_0 ? (s2_bf2_count_0 + 1'b1) : 0;
        end
    end
end

always @(posedge clock) begin
    s2_bf2_start_1 <= (s2_bf1_count_1 == 7) & s2_bf1_sp_en_1;
    s2_bf2_start_0 <= (s2_bf1_count_0 == 3) & s2_bf1_sp_en_0;
end

reg [WIDTH-1:0] s2_bf2_do_re, s2_bf2_do_im;
always @(posedge clock) begin
    s2_bf2_do_re <= s2_bf2_sp_re;
    s2_bf2_do_im <= s2_bf2_sp_im;
end

reg s2_bf2_do_en;
always @(posedge clock or posedge reset) begin
    if (reset) s2_bf2_do_en <= 0;
    else s2_bf2_do_en <= effective_mode ? s2_bf2_sp_en_1 : s2_bf2_sp_en_0;
end

// Twiddle
wire [1:0] s2_tw_sel_1 = {s2_bf2_count_1[3], s2_bf2_count_1[4]};
wire [4:0] s2_tw_num_1 = (s2_bf2_count_1 << 2);
wire [6:0] s2_tw_addr_1 = ({2'b0, s2_tw_num_1} * {5'b0, s2_tw_sel_1});

wire [1:0] s2_tw_sel_0 = {s2_bf2_count_0[2], s2_bf2_count_0[3]};
wire [3:0] s2_tw_num_0 = (s2_bf2_count_0 << 2);
wire [6:0] s2_tw_addr_0 = ({3'b0, s2_tw_num_0} * {5'b0, s2_tw_sel_0}) * 2;

wire [6:0] s2_tw_addr = effective_mode ? s2_tw_addr_1 : s2_tw_addr_0;


reg [WIDTH-1:0] s2_tw_re, s2_tw_im;
always @(posedge clock) begin
    case (s2_tw_addr)
            7'h00: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h01: begin s2_tw_re <= 16'h7FD9; s2_tw_im <= 16'hF9B8; end
            7'h02: begin s2_tw_re <= 16'h7F62; s2_tw_im <= 16'hF374; end
            7'h03: begin s2_tw_re <= 16'h7E9D; s2_tw_im <= 16'hED38; end
            7'h04: begin s2_tw_re <= 16'h7D8A; s2_tw_im <= 16'hE707; end
            7'h05: begin s2_tw_re <= 16'h7C2A; s2_tw_im <= 16'hE0E6; end
            7'h06: begin s2_tw_re <= 16'h7A7D; s2_tw_im <= 16'hDAD8; end
            7'h07: begin s2_tw_re <= 16'h7885; s2_tw_im <= 16'hD4E1; end
            7'h08: begin s2_tw_re <= 16'h7642; s2_tw_im <= 16'hCF04; end
            7'h09: begin s2_tw_re <= 16'h73B6; s2_tw_im <= 16'hC946; end
            7'h0A: begin s2_tw_re <= 16'h70E3; s2_tw_im <= 16'hC3A9; end
            7'h0B: begin s2_tw_re <= 16'h6DCA; s2_tw_im <= 16'hBE32; end
            7'h0C: begin s2_tw_re <= 16'h6A6E; s2_tw_im <= 16'hB8E3; end
            7'h0D: begin s2_tw_re <= 16'h66D0; s2_tw_im <= 16'hB3C0; end
            7'h0E: begin s2_tw_re <= 16'h62F2; s2_tw_im <= 16'hAECC; end
            7'h0F: begin s2_tw_re <= 16'h5ED7; s2_tw_im <= 16'hAA0A; end
            7'h10: begin s2_tw_re <= 16'h5A82; s2_tw_im <= 16'hA57E; end
            7'h11: begin s2_tw_re <= 16'h55F6; s2_tw_im <= 16'hA129; end
            7'h12: begin s2_tw_re <= 16'h5134; s2_tw_im <= 16'h9D0E; end
            7'h13: begin s2_tw_re <= 16'h4C40; s2_tw_im <= 16'h9930; end
            7'h14: begin s2_tw_re <= 16'h471D; s2_tw_im <= 16'h9592; end
            7'h15: begin s2_tw_re <= 16'h41CE; s2_tw_im <= 16'h9236; end
            7'h16: begin s2_tw_re <= 16'h3C57; s2_tw_im <= 16'h8F1D; end
            7'h17: begin s2_tw_re <= 16'h36BA; s2_tw_im <= 16'h8C4A; end
            7'h18: begin s2_tw_re <= 16'h30FC; s2_tw_im <= 16'h89BE; end
            7'h19: begin s2_tw_re <= 16'h2B1F; s2_tw_im <= 16'h877B; end
            7'h1A: begin s2_tw_re <= 16'h2528; s2_tw_im <= 16'h8583; end
            7'h1B: begin s2_tw_re <= 16'h1F1A; s2_tw_im <= 16'h83D6; end
            7'h1C: begin s2_tw_re <= 16'h18F9; s2_tw_im <= 16'h8276; end
            7'h1D: begin s2_tw_re <= 16'h12C8; s2_tw_im <= 16'h8163; end
            7'h1E: begin s2_tw_re <= 16'h0C8C; s2_tw_im <= 16'h809E; end
            7'h1F: begin s2_tw_re <= 16'h0648; s2_tw_im <= 16'h8027; end
            7'h20: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h8000; end
            7'h21: begin s2_tw_re <= 16'hF9B8; s2_tw_im <= 16'h8027; end
            7'h22: begin s2_tw_re <= 16'hF374; s2_tw_im <= 16'h809E; end
            7'h23: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h24: begin s2_tw_re <= 16'hE707; s2_tw_im <= 16'h8276; end
            7'h25: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h26: begin s2_tw_re <= 16'hDAD8; s2_tw_im <= 16'h8583; end
            7'h27: begin s2_tw_re <= 16'hD4E1; s2_tw_im <= 16'h877B; end
            7'h28: begin s2_tw_re <= 16'hCF04; s2_tw_im <= 16'h89BE; end
            7'h29: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h2A: begin s2_tw_re <= 16'hC3A9; s2_tw_im <= 16'h8F1D; end
            7'h2B: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h2C: begin s2_tw_re <= 16'hB8E3; s2_tw_im <= 16'h9592; end
            7'h2D: begin s2_tw_re <= 16'hB3C0; s2_tw_im <= 16'h9930; end
            7'h2E: begin s2_tw_re <= 16'hAECC; s2_tw_im <= 16'h9D0E; end
            7'h2F: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h30: begin s2_tw_re <= 16'hA57E; s2_tw_im <= 16'hA57E; end
            7'h31: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h32: begin s2_tw_re <= 16'h9D0E; s2_tw_im <= 16'hAECC; end
            7'h33: begin s2_tw_re <= 16'h9930; s2_tw_im <= 16'hB3C0; end
            7'h34: begin s2_tw_re <= 16'h9592; s2_tw_im <= 16'hB8E3; end
            7'h35: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h36: begin s2_tw_re <= 16'h8F1D; s2_tw_im <= 16'hC3A9; end
            7'h37: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h38: begin s2_tw_re <= 16'h89BE; s2_tw_im <= 16'hCF04; end
            7'h39: begin s2_tw_re <= 16'h877B; s2_tw_im <= 16'hD4E1; end
            7'h3A: begin s2_tw_re <= 16'h8583; s2_tw_im <= 16'hDAD8; end
            7'h3B: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h3C: begin s2_tw_re <= 16'h8276; s2_tw_im <= 16'hE707; end
            7'h3D: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h3E: begin s2_tw_re <= 16'h809E; s2_tw_im <= 16'hF374; end
            7'h3F: begin s2_tw_re <= 16'h8027; s2_tw_im <= 16'hF9B8; end
            7'h40: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h41: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h42: begin s2_tw_re <= 16'h809E; s2_tw_im <= 16'h0C8C; end
            7'h43: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h44: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h45: begin s2_tw_re <= 16'h83D6; s2_tw_im <= 16'h1F1A; end
            7'h46: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h47: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h48: begin s2_tw_re <= 16'h89BE; s2_tw_im <= 16'h30FC; end
            7'h49: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h4A: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h4B: begin s2_tw_re <= 16'h9236; s2_tw_im <= 16'h41CE; end
            7'h4C: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h4D: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h4E: begin s2_tw_re <= 16'h9D0E; s2_tw_im <= 16'h5134; end
            7'h4F: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h50: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h51: begin s2_tw_re <= 16'hAA0A; s2_tw_im <= 16'h5ED7; end
            7'h52: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h53: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h54: begin s2_tw_re <= 16'hB8E3; s2_tw_im <= 16'h6A6E; end
            7'h55: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h56: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h57: begin s2_tw_re <= 16'hC946; s2_tw_im <= 16'h73B6; end
            7'h58: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h59: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h5A: begin s2_tw_re <= 16'hDAD8; s2_tw_im <= 16'h7A7D; end
            7'h5B: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h5C: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h5D: begin s2_tw_re <= 16'hED38; s2_tw_im <= 16'h7E9D; end
            7'h5E: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h5F: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h60: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h61: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h62: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h63: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h64: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h65: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h66: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h67: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h68: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h69: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h6A: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h6B: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h6C: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h6D: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h6E: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h6F: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h70: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h71: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h72: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h73: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h74: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h75: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h76: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h77: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h78: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h79: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h7A: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h7B: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h7C: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h7D: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h7E: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
            7'h7F: begin s2_tw_re <= 16'h0000; s2_tw_im <= 16'h0000; end
        default: begin s2_tw_re <= 0; s2_tw_im <= 0; end
    endcase
end


reg s2_mu_en;
always @(posedge clock) begin
    if (effective_mode == 0 && 4 == 2) s2_mu_en <= 0;
    else s2_mu_en <= (s2_tw_addr != 0);
end

wire [WIDTH-1:0] s2_mu_a_re = s2_mu_en ? s2_bf2_do_re : 16'b0;
wire [WIDTH-1:0] s2_mu_a_im = s2_mu_en ? s2_bf2_do_im : 16'b0;

wire signed [WIDTH-1:0] s2_mu_ar = $signed(s2_mu_a_re);
wire signed [WIDTH-1:0] s2_mu_ai = $signed(s2_mu_a_im);
wire signed [WIDTH-1:0] s2_mu_br = $signed(s2_tw_re);
wire signed [WIDTH-1:0] s2_mu_bi = $signed(s2_tw_im);
wire signed [2*WIDTH-1:0] s2_mu_rr = s2_mu_ar * s2_mu_br;
wire signed [2*WIDTH-1:0] s2_mu_ri = s2_mu_ar * s2_mu_bi;
wire signed [2*WIDTH-1:0] s2_mu_ir = s2_mu_ai * s2_mu_br;
wire signed [2*WIDTH-1:0] s2_mu_ii = s2_mu_ai * s2_mu_bi;
wire [WIDTH-1:0] s2_mu_m_re = (s2_mu_rr >>> 15) - (s2_mu_ii >>> 15);
wire [WIDTH-1:0] s2_mu_m_im = (s2_mu_ri >>> 15) + (s2_mu_ir >>> 15);


reg [WIDTH-1:0] s2_mu_do_re, s2_mu_do_im;
always @(posedge clock) begin
    s2_mu_do_re <= s2_mu_en ? s2_mu_m_re : s2_bf2_do_re;
    s2_mu_do_im <= s2_mu_en ? s2_mu_m_im : s2_bf2_do_im;
end

reg s2_mu_do_en;
always @(posedge clock or posedge reset) begin
    if (reset) s2_mu_do_en <= 0;
    else s2_mu_do_en <= s2_bf2_do_en;
end

wire s2_do_en = (5==2 && mode_active) ? s2_bf2_do_en : (4==2 && !effective_mode) ? s2_bf2_do_en : s2_mu_do_en;
wire [WIDTH-1:0] s2_do_re = (5==2 && mode_active) ? s2_bf2_do_re : (4==2 && !effective_mode) ? s2_bf2_do_re : s2_mu_do_re;
wire [WIDTH-1:0] s2_do_im = (5==2 && mode_active) ? s2_bf2_do_im : (4==2 && !effective_mode) ? s2_bf2_do_im : s2_mu_do_im;


//----------------------------------------------------------------------
// Stage 3: 128=(N=128, M=8), 64=(N=64, M=4)
//----------------------------------------------------------------------
reg [6:0] s3_di_count_1;
reg [5:0] s3_di_count_0;
always @(posedge clock or posedge reset) begin
    if (reset) begin
        s3_di_count_1 <= 0;
        s3_di_count_0 <= 0;
    end else begin
        if (effective_mode)
            s3_di_count_1 <= s2_do_en ? (s3_di_count_1 + 1'b1) : 0;
        else
            s3_di_count_0 <= s2_do_en ? (s3_di_count_0 + 1'b1) : 0;
    end
end

wire s3_bf1_bf_1 = s3_di_count_1[2];
wire s3_bf1_bf_0 = s3_di_count_0[1];
wire s3_bf1_bf   = effective_mode ? s3_bf1_bf_1 : s3_bf1_bf_0;

wire [WIDTH-1:0] s3_db1_do_re_1, s3_db1_do_im_1;
wire [WIDTH-1:0] s3_db1_do_re_0, s3_db1_do_im_0;

reg [WIDTH-1:0] s3_db1_re [0:3];
reg [WIDTH-1:0] s3_db1_im [0:3];

assign s3_db1_do_re_1 = s3_db1_re[3];
assign s3_db1_do_im_1 = s3_db1_im[3];
assign s3_db1_do_re_0 = s3_db1_re[1];
assign s3_db1_do_im_0 = s3_db1_im[1];

wire [WIDTH-1:0] s3_db1_do_re = effective_mode ? s3_db1_do_re_1 : s3_db1_do_re_0;
wire [WIDTH-1:0] s3_db1_do_im = effective_mode ? s3_db1_do_im_1 : s3_db1_do_im_0;

wire [WIDTH-1:0] s3_bf1_x0_re = s3_bf1_bf ? s3_db1_do_re : 16'b0;
wire [WIDTH-1:0] s3_bf1_x0_im = s3_bf1_bf ? s3_db1_do_im : 16'b0;
wire [WIDTH-1:0] s3_bf1_x1_re = s3_bf1_bf ? s2_do_re : 16'b0;
wire [WIDTH-1:0] s3_bf1_x1_im = s3_bf1_bf ? s2_do_im : 16'b0;


wire signed [WIDTH-1:0] s3_bf1_x0r = $signed(s3_bf1_x0_re);
wire signed [WIDTH-1:0] s3_bf1_x0i = $signed(s3_bf1_x0_im);
wire signed [WIDTH-1:0] s3_bf1_x1r = $signed(s3_bf1_x1_re);
wire signed [WIDTH-1:0] s3_bf1_x1i = $signed(s3_bf1_x1_im);
wire signed [WIDTH:0] s3_bf1_ar = s3_bf1_x0r + s3_bf1_x1r;
wire signed [WIDTH:0] s3_bf1_ai = s3_bf1_x0i + s3_bf1_x1i;
wire signed [WIDTH:0] s3_bf1_sr = s3_bf1_x0r - s3_bf1_x1r;
wire signed [WIDTH:0] s3_bf1_si = s3_bf1_x0i - s3_bf1_x1i;
wire [WIDTH-1:0] s3_bf1_y0_re = (s3_bf1_ar + 0) >>> 1;
wire [WIDTH-1:0] s3_bf1_y0_im = (s3_bf1_ai + 0) >>> 1;
wire [WIDTH-1:0] s3_bf1_y1_re = (s3_bf1_sr + 0) >>> 1;
wire [WIDTH-1:0] s3_bf1_y1_im = (s3_bf1_si + 0) >>> 1;


wire [WIDTH-1:0] s3_db1_di_re = s3_bf1_bf ? s3_bf1_y1_re : s2_do_re;
wire [WIDTH-1:0] s3_db1_di_im = s3_bf1_bf ? s3_bf1_y1_im : s2_do_im;

integer s3_i1;
always @(posedge clock) begin
    if (effective_mode) begin
        for (s3_i1=3; s3_i1>0; s3_i1=s3_i1-1) begin
            s3_db1_re[s3_i1] <= s3_db1_re[s3_i1-1];
            s3_db1_im[s3_i1] <= s3_db1_im[s3_i1-1];
        end
        s3_db1_re[0] <= s3_db1_di_re;
        s3_db1_im[0] <= s3_db1_di_im;
    end else begin
        for (s3_i1=1; s3_i1>0; s3_i1=s3_i1-1) begin
            s3_db1_re[s3_i1] <= s3_db1_re[s3_i1-1];
            s3_db1_im[s3_i1] <= s3_db1_im[s3_i1-1];
        end
        s3_db1_re[0] <= s3_db1_di_re;
        s3_db1_im[0] <= s3_db1_di_im;
    end
end

wire s3_bf1_start_1 = (s3_di_count_1 == 3);
wire s3_bf1_start_0 = (s3_di_count_0 == 1);
wire s3_bf1_start   = effective_mode ? s3_bf1_start_1 : s3_bf1_start_0;

reg s3_bf1_sp_en_1, s3_bf1_sp_en_0;
reg [6:0] s3_bf1_count_1;
reg [5:0] s3_bf1_count_0;

wire s3_bf1_end_1 = (s3_bf1_count_1 == 127);
wire s3_bf1_end_0 = (s3_bf1_count_0 == 63);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s3_bf1_sp_en_1 <= 0;
        s3_bf1_count_1 <= 0;
        s3_bf1_sp_en_0 <= 0;
        s3_bf1_count_0 <= 0;
    end else begin
        if (effective_mode) begin
            s3_bf1_sp_en_1 <= s3_bf1_start_1 ? 1'b1 : s3_bf1_end_1 ? 1'b0 : s3_bf1_sp_en_1;
            s3_bf1_count_1 <= s3_bf1_sp_en_1 ? (s3_bf1_count_1 + 1'b1) : 0;
        end else begin
            s3_bf1_sp_en_0 <= s3_bf1_start_0 ? 1'b1 : s3_bf1_end_0 ? 1'b0 : s3_bf1_sp_en_0;
            s3_bf1_count_0 <= s3_bf1_sp_en_0 ? (s3_bf1_count_0 + 1'b1) : 0;
        end
    end
end

wire s3_bf1_mj_1 = (s3_bf1_count_1[2:1] == 2'd3);
wire s3_bf1_mj_0 = (s3_bf1_count_0[1:0] == 2'd3);
wire s3_bf1_mj   = effective_mode ? s3_bf1_mj_1 : s3_bf1_mj_0;

wire [WIDTH-1:0] s3_bf1_sp_re = s3_bf1_bf ? s3_bf1_y0_re : s3_bf1_mj ? s3_db1_do_im : s3_db1_do_re;
wire [WIDTH-1:0] s3_bf1_sp_im = s3_bf1_bf ? s3_bf1_y0_im : s3_bf1_mj ? (0 - s3_db1_do_re) : s3_db1_do_im;

reg [WIDTH-1:0] s3_bf1_do_re, s3_bf1_do_im;
always @(posedge clock) begin
    s3_bf1_do_re <= s3_bf1_sp_re;
    s3_bf1_do_im <= s3_bf1_sp_im;
end

// 2nd Butterfly
reg s3_bf2_bf_1, s3_bf2_bf_0, s3_bf2_bf;
always @(posedge clock) begin
    s3_bf2_bf_1 <= s3_bf1_count_1[1];
    s3_bf2_bf_0 <= s3_bf1_count_0[0];
    s3_bf2_bf   <= effective_mode ? s3_bf1_count_1[1] : s3_bf1_count_0[0];
end

wire [WIDTH-1:0] s3_db2_do_re_1, s3_db2_do_im_1;
wire [WIDTH-1:0] s3_db2_do_re_0, s3_db2_do_im_0;
reg [WIDTH-1:0] s3_db2_re [0:1];
reg [WIDTH-1:0] s3_db2_im [0:1];

assign s3_db2_do_re_1 = s3_db2_re[1];
assign s3_db2_do_im_1 = s3_db2_im[1];
assign s3_db2_do_re_0 = s3_db2_re[0];
assign s3_db2_do_im_0 = s3_db2_im[0];

wire [WIDTH-1:0] s3_db2_do_re = effective_mode ? s3_db2_do_re_1 : s3_db2_do_re_0;
wire [WIDTH-1:0] s3_db2_do_im = effective_mode ? s3_db2_do_im_1 : s3_db2_do_im_0;

wire [WIDTH-1:0] s3_bf2_x0_re = s3_bf2_bf ? s3_db2_do_re : 16'b0;
wire [WIDTH-1:0] s3_bf2_x0_im = s3_bf2_bf ? s3_db2_do_im : 16'b0;
wire [WIDTH-1:0] s3_bf2_x1_re = s3_bf2_bf ? s3_bf1_do_re : 16'b0;
wire [WIDTH-1:0] s3_bf2_x1_im = s3_bf2_bf ? s3_bf1_do_im : 16'b0;


wire signed [WIDTH-1:0] s3_bf2_x0r = $signed(s3_bf2_x0_re);
wire signed [WIDTH-1:0] s3_bf2_x0i = $signed(s3_bf2_x0_im);
wire signed [WIDTH-1:0] s3_bf2_x1r = $signed(s3_bf2_x1_re);
wire signed [WIDTH-1:0] s3_bf2_x1i = $signed(s3_bf2_x1_im);
wire signed [WIDTH:0] s3_bf2_ar = s3_bf2_x0r + s3_bf2_x1r;
wire signed [WIDTH:0] s3_bf2_ai = s3_bf2_x0i + s3_bf2_x1i;
wire signed [WIDTH:0] s3_bf2_sr = s3_bf2_x0r - s3_bf2_x1r;
wire signed [WIDTH:0] s3_bf2_si = s3_bf2_x0i - s3_bf2_x1i;
wire [WIDTH-1:0] s3_bf2_y0_re = (s3_bf2_ar + 1) >>> 1;
wire [WIDTH-1:0] s3_bf2_y0_im = (s3_bf2_ai + 1) >>> 1;
wire [WIDTH-1:0] s3_bf2_y1_re = (s3_bf2_sr + 1) >>> 1;
wire [WIDTH-1:0] s3_bf2_y1_im = (s3_bf2_si + 1) >>> 1;


wire [WIDTH-1:0] s3_db2_di_re = s3_bf2_bf ? s3_bf2_y1_re : s3_bf1_do_re;
wire [WIDTH-1:0] s3_db2_di_im = s3_bf2_bf ? s3_bf2_y1_im : s3_bf1_do_im;

integer s3_i2;
always @(posedge clock) begin
    if (effective_mode) begin
        for (s3_i2=1; s3_i2>0; s3_i2=s3_i2-1) begin
            s3_db2_re[s3_i2] <= s3_db2_re[s3_i2-1];
            s3_db2_im[s3_i2] <= s3_db2_im[s3_i2-1];
        end
        s3_db2_re[0] <= s3_db2_di_re;
        s3_db2_im[0] <= s3_db2_di_im;
    end else begin
        s3_db2_re[0] <= s3_db2_di_re;
        s3_db2_im[0] <= s3_db2_di_im;
    end
end

wire [WIDTH-1:0] s3_bf2_sp_re = s3_bf2_bf ? s3_bf2_y0_re : s3_db2_do_re;
wire [WIDTH-1:0] s3_bf2_sp_im = s3_bf2_bf ? s3_bf2_y0_im : s3_db2_do_im;

reg s3_bf2_sp_en_1, s3_bf2_sp_en_0;
reg [6:0] s3_bf2_count_1;
reg [5:0] s3_bf2_count_0;
reg s3_bf2_start_1, s3_bf2_start_0;
wire s3_bf2_end_1 = (s3_bf2_count_1 == 127);
wire s3_bf2_end_0 = (s3_bf2_count_0 == 63);

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s3_bf2_sp_en_1 <= 0; s3_bf2_count_1 <= 0;
        s3_bf2_sp_en_0 <= 0; s3_bf2_count_0 <= 0;
    end else begin
        if (effective_mode) begin
            s3_bf2_sp_en_1 <= s3_bf2_start_1 ? 1'b1 : s3_bf2_end_1 ? 1'b0 : s3_bf2_sp_en_1;
            s3_bf2_count_1 <= s3_bf2_sp_en_1 ? (s3_bf2_count_1 + 1'b1) : 0;
        end else begin
            s3_bf2_sp_en_0 <= s3_bf2_start_0 ? 1'b1 : s3_bf2_end_0 ? 1'b0 : s3_bf2_sp_en_0;
            s3_bf2_count_0 <= s3_bf2_sp_en_0 ? (s3_bf2_count_0 + 1'b1) : 0;
        end
    end
end

always @(posedge clock) begin
    s3_bf2_start_1 <= (s3_bf1_count_1 == 1) & s3_bf1_sp_en_1;
    s3_bf2_start_0 <= (s3_bf1_count_0 == 0) & s3_bf1_sp_en_0;
end

reg [WIDTH-1:0] s3_bf2_do_re, s3_bf2_do_im;
always @(posedge clock) begin
    s3_bf2_do_re <= s3_bf2_sp_re;
    s3_bf2_do_im <= s3_bf2_sp_im;
end

reg s3_bf2_do_en;
always @(posedge clock or posedge reset) begin
    if (reset) s3_bf2_do_en <= 0;
    else s3_bf2_do_en <= effective_mode ? s3_bf2_sp_en_1 : s3_bf2_sp_en_0;
end

// Twiddle
wire [1:0] s3_tw_sel_1 = {s3_bf2_count_1[1], s3_bf2_count_1[2]};
wire [4:0] s3_tw_num_1 = (s3_bf2_count_1 << 4);
wire [6:0] s3_tw_addr_1 = ({2'b0, s3_tw_num_1} * {5'b0, s3_tw_sel_1});

wire [1:0] s3_tw_sel_0 = {s3_bf2_count_0[0], s3_bf2_count_0[1]};
wire [3:0] s3_tw_num_0 = (s3_bf2_count_0 << 4);
wire [6:0] s3_tw_addr_0 = ({3'b0, s3_tw_num_0} * {5'b0, s3_tw_sel_0}) * 2;

wire [6:0] s3_tw_addr = effective_mode ? s3_tw_addr_1 : s3_tw_addr_0;


reg [WIDTH-1:0] s3_tw_re, s3_tw_im;
always @(posedge clock) begin
    case (s3_tw_addr)
            7'h00: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h01: begin s3_tw_re <= 16'h7FD9; s3_tw_im <= 16'hF9B8; end
            7'h02: begin s3_tw_re <= 16'h7F62; s3_tw_im <= 16'hF374; end
            7'h03: begin s3_tw_re <= 16'h7E9D; s3_tw_im <= 16'hED38; end
            7'h04: begin s3_tw_re <= 16'h7D8A; s3_tw_im <= 16'hE707; end
            7'h05: begin s3_tw_re <= 16'h7C2A; s3_tw_im <= 16'hE0E6; end
            7'h06: begin s3_tw_re <= 16'h7A7D; s3_tw_im <= 16'hDAD8; end
            7'h07: begin s3_tw_re <= 16'h7885; s3_tw_im <= 16'hD4E1; end
            7'h08: begin s3_tw_re <= 16'h7642; s3_tw_im <= 16'hCF04; end
            7'h09: begin s3_tw_re <= 16'h73B6; s3_tw_im <= 16'hC946; end
            7'h0A: begin s3_tw_re <= 16'h70E3; s3_tw_im <= 16'hC3A9; end
            7'h0B: begin s3_tw_re <= 16'h6DCA; s3_tw_im <= 16'hBE32; end
            7'h0C: begin s3_tw_re <= 16'h6A6E; s3_tw_im <= 16'hB8E3; end
            7'h0D: begin s3_tw_re <= 16'h66D0; s3_tw_im <= 16'hB3C0; end
            7'h0E: begin s3_tw_re <= 16'h62F2; s3_tw_im <= 16'hAECC; end
            7'h0F: begin s3_tw_re <= 16'h5ED7; s3_tw_im <= 16'hAA0A; end
            7'h10: begin s3_tw_re <= 16'h5A82; s3_tw_im <= 16'hA57E; end
            7'h11: begin s3_tw_re <= 16'h55F6; s3_tw_im <= 16'hA129; end
            7'h12: begin s3_tw_re <= 16'h5134; s3_tw_im <= 16'h9D0E; end
            7'h13: begin s3_tw_re <= 16'h4C40; s3_tw_im <= 16'h9930; end
            7'h14: begin s3_tw_re <= 16'h471D; s3_tw_im <= 16'h9592; end
            7'h15: begin s3_tw_re <= 16'h41CE; s3_tw_im <= 16'h9236; end
            7'h16: begin s3_tw_re <= 16'h3C57; s3_tw_im <= 16'h8F1D; end
            7'h17: begin s3_tw_re <= 16'h36BA; s3_tw_im <= 16'h8C4A; end
            7'h18: begin s3_tw_re <= 16'h30FC; s3_tw_im <= 16'h89BE; end
            7'h19: begin s3_tw_re <= 16'h2B1F; s3_tw_im <= 16'h877B; end
            7'h1A: begin s3_tw_re <= 16'h2528; s3_tw_im <= 16'h8583; end
            7'h1B: begin s3_tw_re <= 16'h1F1A; s3_tw_im <= 16'h83D6; end
            7'h1C: begin s3_tw_re <= 16'h18F9; s3_tw_im <= 16'h8276; end
            7'h1D: begin s3_tw_re <= 16'h12C8; s3_tw_im <= 16'h8163; end
            7'h1E: begin s3_tw_re <= 16'h0C8C; s3_tw_im <= 16'h809E; end
            7'h1F: begin s3_tw_re <= 16'h0648; s3_tw_im <= 16'h8027; end
            7'h20: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h8000; end
            7'h21: begin s3_tw_re <= 16'hF9B8; s3_tw_im <= 16'h8027; end
            7'h22: begin s3_tw_re <= 16'hF374; s3_tw_im <= 16'h809E; end
            7'h23: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h24: begin s3_tw_re <= 16'hE707; s3_tw_im <= 16'h8276; end
            7'h25: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h26: begin s3_tw_re <= 16'hDAD8; s3_tw_im <= 16'h8583; end
            7'h27: begin s3_tw_re <= 16'hD4E1; s3_tw_im <= 16'h877B; end
            7'h28: begin s3_tw_re <= 16'hCF04; s3_tw_im <= 16'h89BE; end
            7'h29: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h2A: begin s3_tw_re <= 16'hC3A9; s3_tw_im <= 16'h8F1D; end
            7'h2B: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h2C: begin s3_tw_re <= 16'hB8E3; s3_tw_im <= 16'h9592; end
            7'h2D: begin s3_tw_re <= 16'hB3C0; s3_tw_im <= 16'h9930; end
            7'h2E: begin s3_tw_re <= 16'hAECC; s3_tw_im <= 16'h9D0E; end
            7'h2F: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h30: begin s3_tw_re <= 16'hA57E; s3_tw_im <= 16'hA57E; end
            7'h31: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h32: begin s3_tw_re <= 16'h9D0E; s3_tw_im <= 16'hAECC; end
            7'h33: begin s3_tw_re <= 16'h9930; s3_tw_im <= 16'hB3C0; end
            7'h34: begin s3_tw_re <= 16'h9592; s3_tw_im <= 16'hB8E3; end
            7'h35: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h36: begin s3_tw_re <= 16'h8F1D; s3_tw_im <= 16'hC3A9; end
            7'h37: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h38: begin s3_tw_re <= 16'h89BE; s3_tw_im <= 16'hCF04; end
            7'h39: begin s3_tw_re <= 16'h877B; s3_tw_im <= 16'hD4E1; end
            7'h3A: begin s3_tw_re <= 16'h8583; s3_tw_im <= 16'hDAD8; end
            7'h3B: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h3C: begin s3_tw_re <= 16'h8276; s3_tw_im <= 16'hE707; end
            7'h3D: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h3E: begin s3_tw_re <= 16'h809E; s3_tw_im <= 16'hF374; end
            7'h3F: begin s3_tw_re <= 16'h8027; s3_tw_im <= 16'hF9B8; end
            7'h40: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h41: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h42: begin s3_tw_re <= 16'h809E; s3_tw_im <= 16'h0C8C; end
            7'h43: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h44: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h45: begin s3_tw_re <= 16'h83D6; s3_tw_im <= 16'h1F1A; end
            7'h46: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h47: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h48: begin s3_tw_re <= 16'h89BE; s3_tw_im <= 16'h30FC; end
            7'h49: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h4A: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h4B: begin s3_tw_re <= 16'h9236; s3_tw_im <= 16'h41CE; end
            7'h4C: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h4D: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h4E: begin s3_tw_re <= 16'h9D0E; s3_tw_im <= 16'h5134; end
            7'h4F: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h50: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h51: begin s3_tw_re <= 16'hAA0A; s3_tw_im <= 16'h5ED7; end
            7'h52: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h53: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h54: begin s3_tw_re <= 16'hB8E3; s3_tw_im <= 16'h6A6E; end
            7'h55: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h56: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h57: begin s3_tw_re <= 16'hC946; s3_tw_im <= 16'h73B6; end
            7'h58: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h59: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h5A: begin s3_tw_re <= 16'hDAD8; s3_tw_im <= 16'h7A7D; end
            7'h5B: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h5C: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h5D: begin s3_tw_re <= 16'hED38; s3_tw_im <= 16'h7E9D; end
            7'h5E: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h5F: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h60: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h61: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h62: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h63: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h64: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h65: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h66: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h67: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h68: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h69: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h6A: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h6B: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h6C: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h6D: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h6E: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h6F: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h70: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h71: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h72: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h73: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h74: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h75: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h76: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h77: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h78: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h79: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h7A: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h7B: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h7C: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h7D: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h7E: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
            7'h7F: begin s3_tw_re <= 16'h0000; s3_tw_im <= 16'h0000; end
        default: begin s3_tw_re <= 0; s3_tw_im <= 0; end
    endcase
end


reg s3_mu_en;
always @(posedge clock) begin
    if (effective_mode == 0 && 2 == 2) s3_mu_en <= 0;
    else s3_mu_en <= (s3_tw_addr != 0);
end

wire [WIDTH-1:0] s3_mu_a_re = s3_mu_en ? s3_bf2_do_re : 16'b0;
wire [WIDTH-1:0] s3_mu_a_im = s3_mu_en ? s3_bf2_do_im : 16'b0;

wire signed [WIDTH-1:0] s3_mu_ar = $signed(s3_mu_a_re);
wire signed [WIDTH-1:0] s3_mu_ai = $signed(s3_mu_a_im);
wire signed [WIDTH-1:0] s3_mu_br = $signed(s3_tw_re);
wire signed [WIDTH-1:0] s3_mu_bi = $signed(s3_tw_im);
wire signed [2*WIDTH-1:0] s3_mu_rr = s3_mu_ar * s3_mu_br;
wire signed [2*WIDTH-1:0] s3_mu_ri = s3_mu_ar * s3_mu_bi;
wire signed [2*WIDTH-1:0] s3_mu_ir = s3_mu_ai * s3_mu_br;
wire signed [2*WIDTH-1:0] s3_mu_ii = s3_mu_ai * s3_mu_bi;
wire [WIDTH-1:0] s3_mu_m_re = (s3_mu_rr >>> 15) - (s3_mu_ii >>> 15);
wire [WIDTH-1:0] s3_mu_m_im = (s3_mu_ri >>> 15) + (s3_mu_ir >>> 15);


reg [WIDTH-1:0] s3_mu_do_re, s3_mu_do_im;
always @(posedge clock) begin
    s3_mu_do_re <= s3_mu_en ? s3_mu_m_re : s3_bf2_do_re;
    s3_mu_do_im <= s3_mu_en ? s3_mu_m_im : s3_bf2_do_im;
end

reg s3_mu_do_en;
always @(posedge clock or posedge reset) begin
    if (reset) s3_mu_do_en <= 0;
    else s3_mu_do_en <= s3_bf2_do_en;
end

wire s3_do_en = (3==2 && mode_active) ? s3_bf2_do_en : (2==2 && !effective_mode) ? s3_bf2_do_en : s3_mu_do_en;
wire [WIDTH-1:0] s3_do_re = (3==2 && mode_active) ? s3_bf2_do_re : (2==2 && !effective_mode) ? s3_bf2_do_re : s3_mu_do_re;
wire [WIDTH-1:0] s3_do_im = (3==2 && mode_active) ? s3_bf2_do_im : (2==2 && !effective_mode) ? s3_bf2_do_im : s3_mu_do_im;


// Final radix-2 stage (SdfUnit2) for 128-mode only
reg s4_bf;
always @(posedge clock or posedge reset) begin
    if (reset) s4_bf <= 0;
    else s4_bf <= (effective_mode && s3_do_en) ? ~s4_bf : 0;
end

reg [WIDTH-1:0] s4_db_re, s4_db_im;
wire [WIDTH-1:0] s4_bf_x0_re = s4_bf ? s4_db_re : 16'b0;
wire [WIDTH-1:0] s4_bf_x0_im = s4_bf ? s4_db_im : 16'b0;
wire [WIDTH-1:0] s4_bf_x1_re = s4_bf ? s3_do_re : 16'b0;
wire [WIDTH-1:0] s4_bf_x1_im = s4_bf ? s3_do_im : 16'b0;


wire signed [WIDTH-1:0] s4_bf_x0r = $signed(s4_bf_x0_re);
wire signed [WIDTH-1:0] s4_bf_x0i = $signed(s4_bf_x0_im);
wire signed [WIDTH-1:0] s4_bf_x1r = $signed(s4_bf_x1_re);
wire signed [WIDTH-1:0] s4_bf_x1i = $signed(s4_bf_x1_im);
wire signed [WIDTH:0] s4_bf_ar = s4_bf_x0r + s4_bf_x1r;
wire signed [WIDTH:0] s4_bf_ai = s4_bf_x0i + s4_bf_x1i;
wire signed [WIDTH:0] s4_bf_sr = s4_bf_x0r - s4_bf_x1r;
wire signed [WIDTH:0] s4_bf_si = s4_bf_x0i - s4_bf_x1i;
wire [WIDTH-1:0] s4_bf_y0_re = (s4_bf_ar + 0) >>> 1;
wire [WIDTH-1:0] s4_bf_y0_im = (s4_bf_ai + 0) >>> 1;
wire [WIDTH-1:0] s4_bf_y1_re = (s4_bf_sr + 0) >>> 1;
wire [WIDTH-1:0] s4_bf_y1_im = (s4_bf_si + 0) >>> 1;


wire [WIDTH-1:0] s4_db_di_re = s4_bf ? s4_bf_y1_re : s3_do_re;
wire [WIDTH-1:0] s4_db_di_im = s4_bf ? s4_bf_y1_im : s3_do_im;

always @(posedge clock) begin
    if (effective_mode) begin
        s4_db_re <= s4_db_di_re;
        s4_db_im <= s4_db_di_im;
    end
end

wire [WIDTH-1:0] s4_sp_re = s4_bf ? s4_bf_y0_re : s4_db_re;
wire [WIDTH-1:0] s4_sp_im = s4_bf ? s4_bf_y0_im : s4_db_im;

reg s4_sp_en;
reg s4_do_en_reg;
reg [WIDTH-1:0] s4_do_re_reg, s4_do_im_reg;

always @(posedge clock or posedge reset) begin
    if (reset) begin
        s4_sp_en <= 0;
        s4_do_en_reg <= 0;
    end else if (effective_mode) begin
        s4_sp_en <= s3_do_en;
        s4_do_en_reg <= s4_sp_en;
    end else begin
        s4_sp_en <= 0;
        s4_do_en_reg <= 0;
    end
end

always @(posedge clock) begin
    if (effective_mode) begin
        s4_do_re_reg <= s4_sp_re;
        s4_do_im_reg <= s4_sp_im;
    end
end

assign do_en = effective_mode ? s4_do_en_reg : s3_do_en;
assign do_re = effective_mode ? s4_do_re_reg : s3_do_re;
assign do_im = effective_mode ? s4_do_im_reg : s3_do_im;

endmodule
