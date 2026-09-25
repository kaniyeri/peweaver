module peweaver_threshold_sim_tb;
    logic signed [7:0] x, t0, t1;
    logic mode;
    logic mismatch;

    peweaver_threshold_miter dut (.*);

    task automatic check_case(
        input logic signed [7:0] next_x,
        input logic signed [7:0] next_t0,
        input logic signed [7:0] next_t1,
        input logic next_mode
    );
        begin
            x = next_x; t0 = next_t0; t1 = next_t1; mode = next_mode;
            #1;
            if (mismatch) $fatal(1, "threshold mismatch, mode=%0d", mode);
        end
    endtask

    initial begin
        check_case(8'sd0, 8'sd0, 8'sd0, 1'b0);
        check_case(-8'sd128, -8'sd128, 8'sd127, 1'b0);
        check_case(8'sd127, -8'sd128, 8'sd127, 1'b1);
        check_case(-8'sd1, 8'sd0, -8'sd1, 1'b1);
        check_case(8'sd42, 8'sd43, 8'sd41, 1'b0);
        $display("PEWEAVER_SIM_PASS threshold_mode_exclusive");
        $finish;
    end
endmodule
