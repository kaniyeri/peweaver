//----------------------------------------------------------------------
// PEWeaver FFT64 PPA activity + golden testbench (Phase 3, v3).
//
// PEWeaver-owned. One testbench serves both activity modes:
//   * RTL mode  : compiles rtl/peweaver_ppa_fft64.v + reference fixture RTL
//   * GLS mode  : compiles the mapped netlist (top peweaver_ppa_fft64) with
//                 the sky130_fd_sc_hd cell models (unit-delay, self-powered
//                 supply1/supply0 variants; primitives.v provides UDPs)
// and verifies golden FFT outputs on the DUT it was compiled against.
//
// Workload (frozen per physical/README.md):
//   phase 0: asynchronous power-on reset (16 cycles) + 96-cycle idle drain
//   phase 1: reset-separated frame A (vectors/input4.txt); outputs drained;
//             an explicit idle separation before the burst is intentional
//   phase 2: TRUE CONTINUOUS STREAMING BURST: producer and collector run
//             concurrently (fork/join). The producer asserts di_en for
//             exactly 192 consecutive samples (frames input4, input5,
//             input4) with no reset and no gap inside the burst; the
//             collector captures exactly 192 consecutive do_en outputs
//             starting at the first do_en. Expected output windows:
//             output4, output5, output4.
//   phase 3: final idle drain
//
// Golden contract: captured emission sample j of window w must equal golden
// frame w at natural bin bitrev6(j) (bit-reversed emission order).
//
// VCD modes:
//   +VCD=<path>                 dump the full scenario
//   +VCD=<path> +STREAM_ONLY    dump only the streaming burst window (first
//                               streaming input through last burst output),
//                               used for the active-streaming power report
//
// Verdict markers: exactly one of
//   PEWEAVER_ACTIVITY_DONE              (all windows matched)
//   PEWEAVER_ACTIVITY_ERROR <reason>    (fail closed)
//----------------------------------------------------------------------
`timescale 1ns/1ns

module peweaver_fft64_activity_tb;

    localparam int FRAME = 64;
    localparam int DRAIN = 96;
    localparam int STREAM_FRAMES = 3;
    localparam int BURST_SAMPLES = STREAM_FRAMES * FRAME;
    localparam int BURST_CAP = BURST_SAMPLES + 128;  // burst outputs + latency margin

    logic clock = 1'b0;
    logic reset = 1'b0;
    logic di_en = 1'b0;
    logic [15:0] di_re = 16'h0000;
    logic [15:0] di_im = 16'h0000;
    wire        do_en;
    wire [15:0] do_re;
    wire [15:0] do_im;

    always #5 clock = ~clock;

    peweaver_ppa_fft64 dut (
        .clock (clock),
        .reset (reset),
        .di_en (di_en),
        .di_re (di_re),
        .di_im (di_im),
        .do_en (do_en),
        .do_re (do_re),
        .do_im (do_im)
    );

    logic [15:0] imem [0:2*FRAME-1];

    integer errors = 0;

    // Phase-1 window capture.
    int win_re  [0:FRAME-1];
    int win_im  [0:FRAME-1];

    // Flat burst capture: BURST_SAMPLES consecutive do_en outputs.
    int burst_re [0:BURST_SAMPLES-1];
    int burst_im [0:BURST_SAMPLES-1];
    int burst_len;
    int burst_gaps;

    function automatic int bitrev6(input int x);
        int r = 0;
        for (int b = 0; b < 6; b++)
            if (((x >> b) & 1) != 0) r = r | (1 << (5 - b));
        return r;
    endfunction

    task automatic load_inputs(input string in_path);
        $readmemh(in_path, imem);
    endtask

    task automatic async_reset(input int hold_cycles);
        begin
            #1 reset = 1'b1;
            repeat (hold_cycles) @(posedge clock);
            #2 reset = 1'b0;
        end
    endtask

    task automatic idle(input int cycles);
        begin
            repeat (cycles) @(posedge clock);
        end
    endtask

    // Stream one 64-sample frame of imem at frame_base; returns after the
    // frame's inputs are consumed (di_en deasserted).
    task automatic stream_frame_inputs(input int frame_base);
        int n_in;
        begin
            n_in = 0;
            @(negedge clock);
            di_en = 1'b1;
            di_re = imem[2*frame_base];
            di_im = imem[2*frame_base + 1];
            while (n_in < FRAME) begin
                @(posedge clock);
                @(negedge clock);
                n_in++;
                if (n_in < FRAME) begin
                    di_re = imem[2*(frame_base + n_in)];
                    di_im = imem[2*(frame_base + n_in) + 1];
                end else begin
                    di_en = 1'b0;
                    di_re = 16'h0000;
                    di_im = 16'h0000;
                end
            end
        end
    endtask

    // Capture the next window of FRAME consecutive do_en samples (waits
    // bounded for the first one).
    task automatic capture_next_window;
        int n_out, cyc;
        begin
            n_out = 0; cyc = 0;
            while (n_out == 0 && cyc < BURST_CAP) begin
                @(negedge clock);
                cyc++;
                if (do_en) begin
                    win_re[0] = do_re;
                    win_im[0] = do_im;
                    n_out = 1;
                end
            end
            while (n_out > 0 && n_out < FRAME && cyc < BURST_CAP) begin
                @(negedge clock);
                cyc++;
                if (do_en) begin
                    win_re[n_out] = do_re;
                    win_im[n_out] = do_im;
                    n_out++;
                end else begin
                    errors++;
                    $display("PEWEAVER_ACTIVITY_ERROR phase1: do_en gap at sample %0d", n_out);
                    return;
                end
            end
            if (n_out != FRAME) begin
                errors++;
                $display("PEWEAVER_ACTIVITY_ERROR phase1: captured %0d of %0d outputs", n_out, FRAME);
            end
        end
    endtask

    // Compare a captured phase-1 window against a golden file (emission
    // sample j is natural bin bitrev6(j)).
    task automatic compare_window(input string golden_path, input string label);
        logic [15:0] gmem [0:2*FRAME-1];
        int mismatches;
        begin
            $readmemh(golden_path, gmem);
            mismatches = 0;
            for (int n = 0; n < FRAME; n++) begin
                if (win_re[bitrev6(n)] !== gmem[2*n]
                    || win_im[bitrev6(n)] !== gmem[2*n + 1]) begin
                    mismatches++;
                    if (mismatches <= 4)
                        $display("[FAIL] %s bin %0d got (%h,%h) expected (%h,%h)",
                                 label, n, win_re[bitrev6(n)], win_im[bitrev6(n)],
                                 gmem[2*n], gmem[2*n + 1]);
                end
            end
            if (mismatches != 0) begin
                errors++;
                $display("PEWEAVER_ACTIVITY_ERROR %s: %0d/%0d samples mismatch golden",
                         label, mismatches, FRAME);
            end
        end
    endtask

    // Capture exactly `count` consecutive do_en samples into the flat burst
    // arrays, waiting (bounded) for the first one. Runs concurrently with
    // the producer via fork/join: burst outputs overlap burst inputs, so the
    // collector must start before/with di_en.
    task automatic capture_burst(input int count, input string label);
        int n_out, cyc;
        begin
            n_out = 0; cyc = 0;
            while (n_out == 0 && cyc < BURST_CAP) begin
                @(negedge clock);
                cyc++;
                if (do_en) begin
                    burst_re[0] = do_re;
                    burst_im[0] = do_im;
                    n_out = 1;
                end
            end
            while (n_out > 0 && n_out < count && cyc < 2*BURST_CAP) begin
                @(negedge clock);
                cyc++;
                if (do_en) begin
                    burst_re[n_out] = do_re;
                    burst_im[n_out] = do_im;
                    n_out++;
                end else begin
                    errors++;
                    $display("PEWEAVER_ACTIVITY_ERROR %s: do_en gap at burst sample %0d", label, n_out);
                    disable fork;
                end
            end
            burst_len = n_out;
            if (n_out != count) begin
                errors++;
                $display("PEWEAVER_ACTIVITY_ERROR %s: captured %0d of %0d burst outputs",
                         label, n_out, count);
            end
        end
    endtask

    reg [4095:0] vcd_path;
    reg stream_only;

    initial begin : stimulus
        stream_only = $test$plusargs("STREAM_ONLY");
        if ($value$plusargs("VCD=%s", vcd_path) && !stream_only) begin
            // Full-scenario mode: dump from t=0 (includes reset/idle; power is
            // reported separately from the streaming-only VCD)
            $dumpfile(vcd_path);
            $dumpvars(0, peweaver_fft64_activity_tb);
        end
        // In STREAM_ONLY mode, dumpfile/dumpvars are called just before the
        // burst (see below) so the VCD contains no silent-prefix clock edges.

        // ---- phase 0: power-on reset + idle drain ----
        load_inputs("vectors/input4.txt");
        async_reset(16);
        idle(DRAIN);

        // ---- phase 1: reset-separated frame A + golden check ----
        stream_frame_inputs(0);
        capture_next_window;
        compare_window("vectors/output4.txt", "phase1_frameA");
        idle(DRAIN);

        // ---- phase 2: true continuous streaming burst (producer+collector) --
        if (stream_only && $value$plusargs("VCD=%s", vcd_path)) begin
            // Streaming-only VCD: start recording at the burst
            $dumpfile(vcd_path);
            $dumpvars(0, peweaver_fft64_activity_tb);
        end
        load_inputs("vectors/input4.txt");   // burst frame 1: input4
        burst_gaps = 0;
        burst_len = 0;
        fork
            begin : producer
                int k;
                @(negedge clock);
                di_en = 1'b1;
                for (k = 0; k < BURST_SAMPLES; k++) begin
                    if (k == FRAME)   load_inputs("vectors/input5.txt");
                    if (k == 2*FRAME) load_inputs("vectors/input4.txt");
                    di_re = imem[2*(k % FRAME)];
                    di_im = imem[2*(k % FRAME) + 1];
                    @(posedge clock);
                    @(negedge clock);
                end
                di_en = 1'b0;
                di_re = 16'h0000;
                di_im = 16'h0000;
            end
            begin : collector
                capture_burst(BURST_SAMPLES, "burst");
            end
        join
        if (stream_only) $dumpoff;

        // ---- split the flat burst into windows and compare ----
        begin : burst_compare
            logic [15:0] gmem [0:2*FRAME-1];
            int mismatches;
            string gnames [0:STREAM_FRAMES-1];
            gnames[0] = "vectors/output4.txt";
            gnames[1] = "vectors/output5.txt";
            gnames[2] = "vectors/output4.txt";
            for (int w = 0; w < STREAM_FRAMES; w++) begin
                $readmemh(gnames[w], gmem);
                mismatches = 0;
                for (int n = 0; n < FRAME; n++) begin
                    if (burst_re[w*FRAME + bitrev6(n)] !== gmem[2*n]
                        || burst_im[w*FRAME + bitrev6(n)] !== gmem[2*n + 1]) begin
                        mismatches++;
                        if (mismatches <= 4)
                            $display("[FAIL] burst w%0d bin %0d got (%h,%h) expected (%h,%h)",
                                     w, n, burst_re[w*FRAME + bitrev6(n)], burst_im[w*FRAME + bitrev6(n)],
                                     gmem[2*n], gmem[2*n + 1]);
                    end
                end
                if (mismatches != 0) begin
                    errors++;
                    $display("PEWEAVER_ACTIVITY_ERROR burst w%0d: %0d/%0d samples mismatch golden",
                             w, mismatches, FRAME);
                end
            end
        end

        // ---- phase 3: final idle drain ----
        idle(50);

        if (errors != 0) begin
            $display("PEWEAVER_ACTIVITY_ERROR total_errors=%0d burst_gaps=%0d burst_len=%0d",
                     errors, burst_gaps, burst_len);
        end else begin
            $display("PEWEAVER_ACTIVITY_DONE");
        end
        $finish;
    end

    initial begin : watchdog
        repeat (10000) @(posedge clock);
        $display("PEWEAVER_ACTIVITY_ERROR watchdog timeout");
        $finish;
    end

endmodule
