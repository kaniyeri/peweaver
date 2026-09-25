// PEWeaver shared 64/128 FFT activity and golden testbench.
// The previous testbench waited for outputs but never asserted di_en.
// +STREAM_MODE=64/128 selects the workload for a +STREAM_ONLY power trace.
`timescale 1ns/1ns

module peweaver_shared_activity_tb;
    localparam int MAX_FRAME = 128;
    localparam int STREAM_FRAMES = 3;
    localparam int MAX_BURST = STREAM_FRAMES * MAX_FRAME;
    localparam int WAIT_CAP = 1024;

    logic clock = 0, reset = 0, mode = 0, di_en = 0;
    logic [15:0] di_re = 0, di_im = 0;
    wire do_en; wire [15:0] do_re, do_im;
    always #5 clock = ~clock;

    peweaver_ppa_shared_fft dut (
        .clock(clock), .reset(reset), .mode(mode), .di_en(di_en),
        .di_re(di_re), .di_im(di_im),
        .do_en(do_en), .do_re(do_re), .do_im(do_im));

    logic [15:0] imem [0:2*MAX_FRAME-1];
    int win_re [0:MAX_FRAME-1];
    int win_im [0:MAX_FRAME-1];
    int burst_re [0:MAX_BURST-1];
    int burst_im [0:MAX_BURST-1];
    integer errors = 0, burst_len = 0, stream_mode;
    reg [4095:0] vcd_path;
    reg stream_only;

    function automatic int bitrev(input int x, input int bits);
        int r = 0;
        for (int b = 0; b < bits; b++)
            if (((x >> b) & 1) != 0) r |= (1 << (bits - 1 - b));
        return r;
    endfunction

    task automatic async_reset;
        begin
            di_en = 0; di_re = 0; di_im = 0;
            #1 reset = 1;
            repeat (16) @(posedge clock);
            #2 reset = 0;
            repeat (16) @(posedge clock);
        end
    endtask

    task automatic load_inputs(input string dir, input string file_name);
        $readmemh({dir, "/vectors/", file_name}, imem);
    endtask

    task automatic drive_frame(input int n);
        begin
            @(negedge clock); di_en = 1;
            for (int k = 0; k < n; k++) begin
                di_re = imem[2*k]; di_im = imem[2*k + 1];
                @(posedge clock); @(negedge clock);
            end
            di_en = 0; di_re = 0; di_im = 0;
        end
    endtask

    task automatic capture_frame(input int n, input string label);
        int got, cycles;
        begin
            got = 0; cycles = 0;
            while (got == 0 && cycles < WAIT_CAP) begin
                @(negedge clock); cycles++;
                if (do_en) begin
                    win_re[0] = do_re; win_im[0] = do_im; got = 1;
                end
            end
            while (got > 0 && got < n && cycles < WAIT_CAP) begin
                @(negedge clock); cycles++;
                if (do_en) begin
                    win_re[got] = do_re; win_im[got] = do_im; got++;
                end else begin
                    errors++;
                    $display("PEWEAVER_ACTIVITY_ERROR %s: do_en gap at %0d", label, got);
                    return;
                end
            end
            if (got != n) begin
                errors++;
                $display("PEWEAVER_ACTIVITY_ERROR %s: captured %0d/%0d", label, got, n);
            end
        end
    endtask

    task automatic compare_frame(input int n, input int bits, input string dir,
                                 input string golden_name, input string label);
        logic [15:0] golden [0:2*MAX_FRAME-1];
        int mismatches, emission;
        begin
            $readmemh({dir, "/vectors/", golden_name}, golden);
            mismatches = 0;
            for (int bin = 0; bin < n; bin++) begin
                emission = bitrev(bin, bits);
                if (win_re[emission] !== golden[2*bin]
                    || win_im[emission] !== golden[2*bin + 1]) begin
                    mismatches++;
                    if (mismatches <= 4)
                        $display("[FAIL] %s bin%0d got(%h,%h) expected(%h,%h)",
                                 label, bin, win_re[emission], win_im[emission],
                                 golden[2*bin], golden[2*bin + 1]);
                end
            end
            if (mismatches != 0) begin
                errors++;
                $display("PEWEAVER_ACTIVITY_ERROR %s: %0d/%0d mismatches", label, mismatches, n);
            end else $display("[PASS] %s", label);
        end
    endtask

    task automatic capture_burst(input int count, input string label);
        int got, cycles;
        begin
            got = 0; cycles = 0;
            while (got == 0 && cycles < WAIT_CAP) begin
                @(negedge clock); cycles++;
                if (do_en) begin
                    burst_re[0] = do_re; burst_im[0] = do_im; got = 1;
                end
            end
            while (got > 0 && got < count && cycles < 2*WAIT_CAP) begin
                @(negedge clock); cycles++;
                if (do_en) begin
                    burst_re[got] = do_re; burst_im[got] = do_im; got++;
                end else begin
                    errors++;
                    $display("PEWEAVER_ACTIVITY_ERROR %s: do_en gap at %0d", label, got);
                    return;
                end
            end
            burst_len = got;
            if (got != count) begin
                errors++;
                $display("PEWEAVER_ACTIVITY_ERROR %s: captured %0d/%0d", label, got, count);
            end
        end
    endtask

    task automatic compare_burst(input int n, input int bits, input string dir,
                                 input string label);
        logic [15:0] golden [0:2*MAX_FRAME-1];
        string golden_name;
        int mismatches, emission;
        begin
            for (int frame = 0; frame < STREAM_FRAMES; frame++) begin
                golden_name = (frame == 1) ? "output5.txt" : "output4.txt";
                $readmemh({dir, "/vectors/", golden_name}, golden);
                mismatches = 0;
                for (int bin = 0; bin < n; bin++) begin
                    emission = frame*n + bitrev(bin, bits);
                    if (burst_re[emission] !== golden[2*bin]
                        || burst_im[emission] !== golden[2*bin + 1]) begin
                        mismatches++;
                        if (mismatches <= 4)
                            $display("[FAIL] %s frame%0d bin%0d got(%h,%h) expected(%h,%h)",
                                     label, frame, bin, burst_re[emission], burst_im[emission],
                                     golden[2*bin], golden[2*bin + 1]);
                    end
                end
                if (mismatches != 0) begin
                    errors++;
                    $display("PEWEAVER_ACTIVITY_ERROR %s frame%0d: %0d/%0d mismatches",
                             label, frame, mismatches, n);
                end
            end
        end
    endtask

    task automatic run_one(input int n, input int bits, input string dir,
                           input string label);
        begin
            load_inputs(dir, "input4.txt");
            fork
                drive_frame(n);
                capture_frame(n, {label, "_single"});
            join
            compare_frame(n, bits, dir, "output4.txt", {label, "_single"});
            repeat (32) @(posedge clock);
        end
    endtask

    task automatic run_burst(input int n, input int bits, input string dir,
                             input string label);
        int count;
        begin
            count = STREAM_FRAMES*n;
            load_inputs(dir, "input4.txt"); burst_len = 0;
            fork
                begin : producer
                    @(negedge clock); di_en = 1;
                    for (int k = 0; k < count; k++) begin
                        if (k == n) load_inputs(dir, "input5.txt");
                        if (k == 2*n) load_inputs(dir, "input4.txt");
                        di_re = imem[2*(k % n)]; di_im = imem[2*(k % n) + 1];
                        @(posedge clock); @(negedge clock);
                    end
                    di_en = 0; di_re = 0; di_im = 0;
                end
                capture_burst(count, {label, "_burst"});
            join
            compare_burst(n, bits, dir, {label, "_burst"});
            repeat (32) @(posedge clock);
        end
    endtask

    task automatic select_and_reset(input int selected_mode);
        begin mode = (selected_mode == 128); async_reset; end
    endtask

    initial begin : stimulus
        stream_only = $test$plusargs("STREAM_ONLY");
        stream_mode = 64;
        if ($value$plusargs("STREAM_MODE=%d", stream_mode)) begin end
        if (stream_mode != 64 && stream_mode != 128) begin
            $display("PEWEAVER_ACTIVITY_ERROR invalid STREAM_MODE=%0d", stream_mode);
            $finish;
        end
        if ($value$plusargs("VCD=%s", vcd_path) && !stream_only) begin
            $dumpfile(vcd_path); $dumpvars(0, peweaver_shared_activity_tb);
        end

        if (!stream_only) begin
            select_and_reset(64);
            run_one(64, 6, "../../benchmarks/halo_fft64_reference", "mode64");
            run_burst(64, 6, "../../benchmarks/halo_fft64_reference", "mode64");
            select_and_reset(128);
            run_one(128, 7, "../../benchmarks/halo_fft128_reference", "mode128");
            run_burst(128, 7, "../../benchmarks/halo_fft128_reference", "mode128");
        end else begin
            select_and_reset(stream_mode);
            if ($value$plusargs("VCD=%s", vcd_path)) begin
                $dumpfile(vcd_path); $dumpvars(0, peweaver_shared_activity_tb);
            end
            if (stream_mode == 64)
                run_burst(64, 6, "../../benchmarks/halo_fft64_reference", "mode64");
            else
                run_burst(128, 7, "../../benchmarks/halo_fft128_reference", "mode128");
            $dumpoff;
        end

        if (errors == 0) $display("PEWEAVER_ACTIVITY_DONE");
        else $display("PEWEAVER_ACTIVITY_ERROR total_errors=%0d burst_len=%0d", errors, burst_len);
        $finish;
    end

    initial begin : watchdog
        repeat (30000) @(posedge clock);
        $display("PEWEAVER_ACTIVITY_ERROR watchdog timeout");
        $finish;
    end
endmodule
