module peweaver_unsafe_sim_tb;
    logic signed [3:0] a0, b0, a1, b1;
    logic signed [7:0] acc0, acc1;
    logic mode;
    logic mismatch;

    peweaver_unsafe_miter dut (.*);

    initial begin
        // Both baseline results are required. A one-multiplier selected-lane
        // candidate necessarily drops one of these distinct products.
        a0 = 4'sd1; b0 = 4'sd1; acc0 = 8'sd0;
        a1 = 4'sd2; b1 = 4'sd1; acc1 = 8'sd0;
        mode = 1'b0;
        #1;
        if (!mismatch) $fatal(1, "unsafe simultaneous MAC did not expose a mismatch");
        $display("PEWEAVER_SIM_PASS unsafe_simultaneous_mac");
        $finish;
    end
endmodule
