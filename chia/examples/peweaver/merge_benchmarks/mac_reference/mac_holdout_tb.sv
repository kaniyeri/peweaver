// Hidden randomized holdout TB for the MAC merge experiment.
// Stimulus file: one line per clock edge, hex tokens "mode en a b".
// Captures y after every posedge (at the negedge) to +OUT, one hex word per
// line, cycle-aligned with the stimulus lines. The controller compares
// against the pure-python oracle.
`timescale 1ns/1ns

module mac_holdout_tb;
    logic clock = 0, reset = 0, mode = 0, en = 0;
    logic [7:0] a = 0, b = 0;
    wire [15:0] y;
    always #5 clock = ~clock;

    shared_mac dut (
        .clock(clock), .reset(reset), .mode(mode), .en(en),
        .a(a), .b(b), .y(y));

    reg [7:0] smem [0:8191];
    integer errors = 0, lines = 0, k;
    reg [4095:0] stim_path, out_path;
    integer out_fd;

    integer total = 2048;
    initial begin : stimulus
        if (!$value$plusargs("STIM=%s", stim_path)) stim_path = "stim.txt";
        if (!$value$plusargs("OUT=%s", out_path)) out_path = "cap.txt";
        if (!$value$plusargs("CYCLES=%d", total)) total = 2048;
        out_fd = $fopen(out_path, "w");
        if (out_fd == 0) begin
            $display("MAC_ERROR cannot open %0s", out_path);
            $finish;
        end
        $readmemh(stim_path, smem);
        for (k = 0; k < 4*total; k = k + 4) begin
            mode = smem[k][0];
            en   = smem[k][1];
            a    = smem[k+1];
            b    = smem[k+2];
            reset = smem[k+3][0];
            @(posedge clock);
            lines = lines + 1;
            @(negedge clock);
            $fwrite(out_fd, "%h\n", y);
        end
        $fclose(out_fd);
        if (errors == 0) $display("MAC_DONE lines=%0d", lines);
        else $display("MAC_ERROR total_errors=%0d", errors);
        $finish;
    end

    initial begin : watchdog
        repeat (40000) @(posedge clock);
        $display("MAC_ERROR watchdog timeout");
        $finish;
    end
endmodule
