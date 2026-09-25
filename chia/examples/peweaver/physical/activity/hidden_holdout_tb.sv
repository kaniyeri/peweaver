// Hidden randomized holdout testbench for the shared 64/128 FFT candidate.
// Parameterized by plusargs; asserts EXACT first-valid latency and exact
// output pulse width; captures raw outputs for controller-side comparison
// against the independent Python oracles. Controller-owned, model-free.
`timescale 1ns/1ns

module hidden_holdout_tb;
    logic clock = 0, reset = 0, mode = 0, di_en = 0;
    logic [15:0] di_re = 0, di_im = 0;
    wire do_en; wire [15:0] do_re, do_im;
    always #5 clock = ~clock;

    peweaver_ppa_shared_fft dut (
        .clock(clock), .reset(reset), .mode(mode), .di_en(di_en),
        .di_re(di_re), .di_im(di_im),
        .do_en(do_en), .do_re(do_re), .do_im(do_im));

    logic [15:0] imem [0:255];
    integer errors = 0;
    integer n, expect_lat;
    reg [4095:0] vec_dir, f0, f1, f2, out_path;
    integer out_fd;

    task automatic do_reset;
        begin
            di_en = 0; di_re = 0; di_im = 0;
            #1 reset = 1;
            repeat (16) @(posedge clock);
            #2 reset = 0;
            repeat (16) @(posedge clock);
        end
    endtask

    // Drive one full frame (di_en=1 for n cycles), then wait for exactly n
    // consecutive do_en outputs. Latency is measured from the posedge that
    // accepts sample zero (counted as edge 1) and asserted against
    // expect_lat. Captured pairs are appended to out_fd in emission order.
    task automatic drive_capture_frame(input int frame_n);
        int k, c, got, post;
        begin
            got = 0; c = 0; post = 0;
            @(negedge clock); di_en = 1;
            for (k = 0; k < frame_n; k++) begin
                di_re = imem[2*k]; di_im = imem[2*k + 1];
                @(posedge clock);
                c = c + 1;
                @(negedge clock);
                if (do_en && got == 0) begin
                    if (c !== expect_lat) begin
                        errors = errors + 1;
                        $display("HIDDEN_ERROR latency got=%0d expect=%0d", c, expect_lat);
                    end
                end
            end
            di_en = 0; di_re = 0; di_im = 0;
            while (got < frame_n && post < 1024) begin
                @(posedge clock);
                c = c + 1;
                @(negedge clock);
                if (do_en) begin
                    if (got == 0 && c !== expect_lat) begin
                        errors = errors + 1;
                        $display("HIDDEN_ERROR latency got=%0d expect=%0d", c, expect_lat);
                    end
                    $fwrite(out_fd, "%h %h\n", do_re, do_im);
                    got = got + 1;
                end else if (got > 0) begin
                    errors = errors + 1;
                    $display("HIDDEN_ERROR output gap at %0d", got);
                    got = frame_n;
                end
                post = post + 1;
            end
            if (got != frame_n) begin
                errors = errors + 1;
                $display("HIDDEN_ERROR captured %0d/%0d", got, frame_n);
            end else begin
                @(posedge clock); @(negedge clock);
                if (do_en) begin
                    errors = errors + 1;
                    $display("HIDDEN_ERROR do_en wider than frame");
                end
            end
        end
    endtask

    // Continuous 3-frame burst: di_en high for 3*n cycles with per-frame
    // data files; captures 3n consecutive outputs; asserts frame-0 latency.
    task automatic run_burst(input int frame_n);
        int k, c, got, post;
        logic [15:0] bmem [0:255];
        begin
            got = 0; c = 0; post = 0;
            $readmemh({vec_dir, "/", f0}, imem);
            @(negedge clock); di_en = 1;
            for (k = 0; k < 3*frame_n; k++) begin
                if (k == frame_n) $readmemh({vec_dir, "/", f1}, imem);
                if (k == 2*frame_n) $readmemh({vec_dir, "/", f2}, imem);
                di_re = imem[2*(k % frame_n)]; di_im = imem[2*(k % frame_n) + 1];
                @(posedge clock);
                c = c + 1;
                @(negedge clock);
                if (do_en) begin
                    if (got == 0 && c !== expect_lat) begin
                        errors = errors + 1;
                        $display("HIDDEN_ERROR burst latency got=%0d expect=%0d", c, expect_lat);
                    end
                    $fwrite(out_fd, "%h %h\n", do_re, do_im);
                    got = got + 1;
                end else if (got > 0) begin
                    errors = errors + 1;
                    $display("HIDDEN_ERROR burst gap at %0d", got);
                end
            end
            di_en = 0; di_re = 0; di_im = 0;
            while (got < 3*frame_n && post < 1024) begin
                @(posedge clock);
                c = c + 1;
                @(negedge clock);
                if (do_en) begin
                    $fwrite(out_fd, "%h %h\n", do_re, do_im);
                    got = got + 1;
                end else if (got > 0) begin
                    errors = errors + 1;
                    $display("HIDDEN_ERROR burst tail gap at %0d", got);
                end
                post = post + 1;
            end
            if (got != 3*frame_n) begin
                errors = errors + 1;
                $display("HIDDEN_ERROR burst captured %0d/%0d", got, 3*frame_n);
            end
        end
    endtask

    initial begin : stimulus
        string casename;
        int k;
        if (!$value$plusargs("N=%d", n)) n = 64;
        if (!$value$plusargs("EXPECT_LAT=%d", expect_lat)) expect_lat = 71;
        if (!$value$plusargs("MODE=%d", mode)) mode = 0;
        if (!$value$plusargs("DIR=%s", vec_dir)) vec_dir = ".";
        if (!$value$plusargs("F0=%s", f0)) f0 = "in.txt";
        if (!$value$plusargs("F1=%s", f1)) f1 = f0;
        if (!$value$plusargs("F2=%s", f2)) f2 = f0;
        if (!$value$plusargs("OUT=%s", out_path)) out_path = "captured.txt";
        if (!$value$plusargs("CASE=%s", casename)) casename = "single";
        out_fd = $fopen(out_path, "w");
        if (out_fd == 0) begin
            $display("HIDDEN_ERROR cannot open %0s", out_path);
            $finish;
        end

        if (casename == "single") begin
            $readmemh({vec_dir, "/", f0}, imem);
            do_reset;
            drive_capture_frame(n);
        end else if (casename == "burst") begin
            do_reset;
            run_burst(n);
        end else if (casename == "abort_then_frame") begin
            $readmemh({vec_dir, "/", f0}, imem);
            do_reset;
            @(negedge clock); di_en = 1;
            for (k = 0; k < n/2; k++) begin
                di_re = imem[2*k]; di_im = imem[2*k + 1];
                @(posedge clock); @(negedge clock);
            end
            di_en = 0; di_re = 0; di_im = 0;
            k = 0;
            repeat (n + 256) begin
                @(posedge clock); @(negedge clock);
                if (do_en) begin
                    k = k + 1;
                end
            end
            $display("HIDDEN_ABORT_PULSE %0d", k);
            do_reset;
            drive_capture_frame(n);
        end else if (casename == "midreset_then_frame") begin
            $readmemh({vec_dir, "/", f0}, imem);
            do_reset;
            @(negedge clock); di_en = 1;
            for (k = 0; k < n/3; k++) begin
                di_re = imem[2*k]; di_im = imem[2*k + 1];
                @(posedge clock); @(negedge clock);
            end
            do_reset;
            drive_capture_frame(n);
        end else if (casename == "switch_then_frame") begin
            $readmemh({vec_dir, "/", f0}, imem);
            do_reset;
            drive_capture_frame(n);
            mode = ~mode;
            n = mode ? 128 : 64;
            expect_lat = mode ? 137 : 71;
            $readmemh({vec_dir, "/", f1}, imem);
            do_reset;
            drive_capture_frame(n);
        end else begin
            $display("HIDDEN_ERROR unknown CASE=%0s", casename);
            errors = errors + 1;
        end

        $fclose(out_fd);
        if (errors == 0) $display("HIDDEN_DONE");
        else $display("HIDDEN_ERROR total_errors=%0d", errors);
        $finish;
    end

    initial begin : watchdog
        repeat (40000) @(posedge clock);
        $display("HIDDEN_ERROR watchdog timeout");
        $finish;
    end
endmodule
