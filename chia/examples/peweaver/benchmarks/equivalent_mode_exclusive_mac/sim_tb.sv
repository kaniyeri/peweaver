module peweaver_equiv_sim_tb;
    logic signed [3:0] a0, b0, a1, b1;
    logic signed [7:0] acc0, acc1;
    logic mode;
    logic mismatch;

    peweaver_equiv_miter dut (.*);

    task automatic check_case(
        input logic signed [3:0] next_a0,
        input logic signed [3:0] next_b0,
        input logic signed [7:0] next_acc0,
        input logic signed [3:0] next_a1,
        input logic signed [3:0] next_b1,
        input logic signed [7:0] next_acc1,
        input logic next_mode
    );
        begin
            a0 = next_a0; b0 = next_b0; acc0 = next_acc0;
            a1 = next_a1; b1 = next_b1; acc1 = next_acc1; mode = next_mode;
            #1;
            if (mismatch) $fatal(1, "equivalent MAC mismatch, mode=%0d", mode);
        end
    endtask

    initial begin
        check_case(4'sd0, 4'sd0, 8'sd0, 4'sd0, 4'sd0, 8'sd0, 1'b0);
        check_case(4'sd7, -4'sd8, 8'sd127, -4'sd8, 4'sd7, -8'sd128, 1'b0);
        check_case(-4'sd8, -4'sd8, -8'sd128, 4'sd7, 4'sd7, 8'sd127, 1'b1);
        check_case(4'sd3, -4'sd5, -8'sd17, -4'sd4, 4'sd6, 8'sd23, 1'b1);
        $display("PEWEAVER_SIM_PASS equivalent_mode_exclusive_mac");
        $finish;
    end
endmodule
