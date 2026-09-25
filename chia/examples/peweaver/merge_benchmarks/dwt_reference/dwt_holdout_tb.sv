// Holdout testbench for the DWT two-context merge benchmark.
// Stimulus file ($readmemh, THREE bytes per line):
//   byte0: bit0 = ctx, bit1 = en, bit2 = reset
//   byte1: x[15:8], byte2: x[7:0]  (explicit x travels with the stimulus)
// Captures after every posedge (at the negedge) nine fields:
//   a_l1_lo a_l1_hi a_l1_valid b_l1_lo b_l1_hi b_l1_valid b_l2_lo b_l2_hi
//   b_l2_valid
// Data words are ten-digit hex; valid strobes are decimal. The controller
// compares against the pure-Python oracle.
`timescale 1ns/1ns

module dwt_holdout_tb;
    logic clock = 0, reset = 0, ctx = 0, en = 0;
    logic signed [15:0] x = 0;
    wire signed [39:0] a_l1_lo, a_l1_hi, b_l1_lo, b_l1_hi, b_l2_lo, b_l2_hi;
    wire a_l1_valid, b_l1_valid, b_l2_valid;
    always #5 clock = ~clock;

    dwt_shared dut (
        .clock(clock), .reset(reset), .ctx(ctx), .en(en), .x(x),
        .a_l1_lo(a_l1_lo), .a_l1_hi(a_l1_hi), .a_l1_valid(a_l1_valid),
        .b_l1_lo(b_l1_lo), .b_l1_hi(b_l1_hi), .b_l1_valid(b_l1_valid),
        .b_l2_lo(b_l2_lo), .b_l2_hi(b_l2_hi), .b_l2_valid(b_l2_valid));

    reg [7:0] smem [0:8191];
    integer lines = 0, k;
    reg [4095:0] stim_path, out_path;
    integer out_fd;
    integer total = 2048;

    initial begin : stimulus
        if (!$value$plusargs("STIM=%s", stim_path)) stim_path = "stim.txt";
        if (!$value$plusargs("OUT=%s", out_path)) out_path = "cap.txt";
        if (!$value$plusargs("CYCLES=%d", total)) total = 2048;
        out_fd = $fopen(out_path, "w");
        if (out_fd == 0) begin
            $display("DWT_ERROR cannot open %0s", out_path);
            $finish;
        end
        $readmemh(stim_path, smem);
        for (k = 0; k < total; k = k + 1) begin
            ctx   = smem[3*k][0];
            en    = smem[3*k][1];
            reset = smem[3*k][2];
            x     = {smem[3*k+1], smem[3*k+2]};
            @(posedge clock);
            lines = lines + 1;
            @(negedge clock);
            $fwrite(out_fd, "%010h %010h %0d %010h %010h %0d %010h %010h %0d\n",
                    a_l1_lo, a_l1_hi, a_l1_valid,
                    b_l1_lo, b_l1_hi, b_l1_valid,
                    b_l2_lo, b_l2_hi, b_l2_valid);
        end
        $fclose(out_fd);
        $display("DWT_DONE lines=%0d", lines);
        $finish;
    end

    initial begin : watchdog
        repeat (60000) @(posedge clock);
        $display("DWT_ERROR watchdog timeout");
        $finish;
    end
endmodule
