//----------------------------------------------------------------------
// PEWeaver directed regression testbench for the curated r22sdf 64-point
// FFT reference (HALO-inspired stateful FFT proxy, Phase A).
//
// Interface/control validation of the stateful reference:
//   1. asynchronous active-high reset (asserted away from clock edges);
//   2. exactly 64 consecutive valid input samples per frame;
//   3. no output valid before the documented pipeline latency;
//   4. exactly 64 consecutive output-valid samples per frame;
//   5. reset between transactions clears/drains state (no stale output);
//   6. a second transaction after reset does not leak stale output;
//   7. back-to-back streaming frames (upstream usage pattern);
//   8. mid-frame asynchronous abort leaves no output and no stale data.
//
// Vectors: upstream r22sdf sim/fft_64 input4/input5/output4/output5
// (ModelSim goldens at pinned revision f7dca6e548e1370b69a09382d30609ee14ba4a57).
// output*.txt line n (natural bin order n) is compared against captured
// sample bitrev6(n) because the reference emits bit-reversed order.
//
// Two-state policy: upstream Twiddle64.v and SdfUnit*.v contain deliberate
// 1'bx assignments ("Set unknown value x for verification") for paths that
// are never selected. Verilator resolves x to 0 (--x-assign 0 --x-initial 0);
// the testbench also drives defined zero on idle inputs so delay-line
// contents are deterministic. This regression validates interface/control
// behavior and reproduces the upstream goldens; it is NOT an independent
// numerical FFT oracle.
//----------------------------------------------------------------------
`timescale 1ns/1ns

module peweaver_fft64_directed_tb;

    // Documented pipeline latency of FFT64 (upstream header comment: 71
    // clock cycles). Measured convention: sample 0 is driven at a negedge
    // and consumed at the first following posedge (cycle 1); FIRST_OUT is
    // the cycle index whose negedge first observes do_en high.
    localparam int FIRST_OUT = 71;

    localparam int FRAME = 64;
    localparam int DRAIN = 96;   // > longest DelayBuffer depth (32) plus margin

    logic clock = 1'b0;
    logic reset = 1'b0;
    logic di_en = 1'b0;
    logic [15:0] di_re = 16'h0000;
    logic [15:0] di_im = 16'h0000;
    wire        do_en;
    wire [15:0] do_re;
    wire [15:0] do_im;

    always #5 clock = ~clock;

    peweaver_halo_fft64_reference dut (
        .clock (clock),
        .reset (reset),
        .di_en (di_en),
        .di_re (di_re),
        .di_im (di_im),
        .do_en (do_en),
        .do_re (do_re),
        .do_im (do_im)
    );

    logic [15:0] imem [0:2*FRAME-1];   // interleave (re, im) per sample
    logic [15:0] gmem [0:2*FRAME-1];   // golden outputs in natural bin order

    integer errors = 0;

    function automatic int bitrev6(input int x);
        int r = 0;
        for (int b = 0; b < 6; b++)
            if (((x >> b) & 1) != 0) r = r | (1 << (5 - b));
        return r;
    endfunction

    task automatic check(input bit ok, input string label);
        if (!ok) begin
            errors++;
            $display("[FAIL] %s", label);
        end
    endtask

    task automatic load_input4;
        begin
            $readmemh("vectors/input4.txt", imem);
            $readmemh("vectors/output4.txt", gmem);
        end
    endtask

    task automatic load_input5;
        begin
            $readmemh("vectors/input5.txt", imem);
            $readmemh("vectors/output5.txt", gmem);
        end
    endtask

    // Assert reset asynchronously between edges, hold, deassert between edges.
    task automatic async_reset(input int hold_cycles);
        begin
            #1 reset = 1'b1;                       // away from any clock edge
            repeat (hold_cycles) @(posedge clock);
            #2 reset = 1'b0;                       // away from any clock edge
        end
    endtask

    // Idle window: di_en low, defined zero data, do_en must stay low.
    task automatic idle_no_output(input int cycles, input string label);
        int seen;
        begin
            seen = 0;
            for (int k = 0; k < cycles; k++) begin
                @(posedge clock);
                @(negedge clock);
                if (do_en) seen++;
            end
            check(seen == 0, $sformatf("%s: %0d unexpected output-valid cycles during idle", label, seen));
            if (seen == 0) $display("[ ok ] %s: no output during %0d idle cycles", label, cycles);
        end
    endtask

    // Drive exactly FRAME consecutive samples and check the full output
    // contract of one transaction. Returns after FRAME+8 idle-checked cycles.
    task automatic checked_frame(input string label);
        int cyc, n_in, n_out, first_out, last_out, extra, mismatches;
        int got_re [0:FRAME-1];
        int got_im [0:FRAME-1];
        begin
            $display("[ run ] %s", label);
            cyc = 0; n_in = 0; n_out = 0; first_out = -1; last_out = -1; extra = 0; mismatches = 0;
            @(negedge clock);
            di_en = 1'b1;
            di_re = imem[0];
            di_im = imem[1];
            while (n_out < FRAME && cyc < FRAME + FIRST_OUT + 32) begin
                @(posedge clock);   // sample n_in is consumed by the DUT here
                @(negedge clock);
                cyc++;
                if (n_in < FRAME) begin
                    n_in++;
                    if (n_in < FRAME) begin
                        di_re = imem[2*n_in];
                        di_im = imem[2*n_in + 1];
                    end else begin
                        di_en = 1'b0;   // exactly FRAME consecutive valid samples
                        di_re = 16'h0000;
                        di_im = 16'h0000;
                    end
                end
                if (do_en) begin
                    if (first_out < 0) first_out = cyc;
                    if (last_out >= 0 && last_out != cyc - 1) begin
                        errors++;
                        $display("[FAIL] %s: do_en gap before cycle %0d", label, cyc);
                    end
                    last_out = cyc;
                    if (n_out < FRAME) begin
                        got_re[n_out] = do_re;
                        got_im[n_out] = do_im;
                    end
                    n_out++;
                end
            end
            for (int k = 0; k < 8; k++) begin
                @(posedge clock);
                @(negedge clock);
                if (do_en) extra++;
            end
            check(n_in == FRAME, $sformatf("%s: drove %0d input samples (expected %0d)", label, n_in, FRAME));
            check(n_out == FRAME, $sformatf("%s: captured %0d output-valid samples (expected %0d)", label, n_out, FRAME));
            check(extra == 0, $sformatf("%s: %0d extra output-valid cycles after frame", label, extra));
            if (first_out != FIRST_OUT)
                $display("[FAIL] %s: first output-valid at cycle %0d (expected %0d)", label, first_out, FIRST_OUT);
            check(first_out == FIRST_OUT, $sformatf("%s: latency mismatch (measured %0d, expected %0d)", label, first_out, FIRST_OUT));
            if (n_out == FRAME) begin
                for (int n = 0; n < FRAME; n++) begin
                    if (got_re[bitrev6(n)] !== gmem[2*n] || got_im[bitrev6(n)] !== gmem[2*n + 1]) begin
                        mismatches++;
                        if (mismatches <= 4)
                            $display("[FAIL] %s: bin %0d got (%h,%h) expected (%h,%h)",
                                     label, n, got_re[bitrev6(n)], got_im[bitrev6(n)], gmem[2*n], gmem[2*n + 1]);
                    end
                end
            end
            check(mismatches == 0, $sformatf("%s: %0d/%0d output samples mismatch golden", label, mismatches, FRAME));
            if (errors == 0) $display("[ ok ] %s: latency=%0d, 64 consecutive outputs match golden", label, first_out);
        end
    endtask

    // Aborted-frame state-isolation probe: start a frame, reset
    // asynchronously mid-stream, verify no output ever appears and the next
    // transaction still matches golden.
    task automatic abort_frame_probe;
        int done;
        begin
            $display("[ run ] abort_frame_probe");
            done = 0;
            fork
                begin : drive_aborted
                    @(negedge clock);
                    di_en = 1'b1;
                    di_re = imem[0];
                    di_im = imem[1];
                    for (int n = 1; n < FRAME && !done; n++) begin
                        @(posedge clock);
                        @(negedge clock);
                        di_re = imem[2*n];
                        di_im = imem[2*n + 1];
                    end
                    if (!done) begin
                        di_en = 1'b0;
                        di_re = 16'h0000;
                        di_im = 16'h0000;
                    end
                end
                begin : aborter
                    repeat (20) @(posedge clock);
                    #1 reset = 1'b1;           // asynchronous mid-frame abort
                    done = 1;
                    di_en = 1'b0;
                    di_re = 16'h0000;
                    di_im = 16'h0000;
                    repeat (8) @(posedge clock);
                    #2 reset = 1'b0;
                end
            join
            idle_no_output(DRAIN, "abort_frame_probe/post_abort");
        end
    endtask

    initial begin : stimulus
        // Phase 0: power-on asynchronous reset, then quiet bus.
        load_input4();
        check(imem[0] === 16'h7FFD, "vectors/input4.txt did not load expected first word 7FFD");
        async_reset(16);
        idle_no_output(DRAIN, "phase0/post_reset");

        // Phase 1: first transaction (input4 -> output4 golden).
        checked_frame("phase1/frameA_input4");

        // Phase 2: reset between transactions, then prove the bus is quiet
        // (reset cleared control state; no stale output leaks).
        async_reset(16);
        idle_no_output(DRAIN, "phase2/post_reset");

        // Phase 3: second transaction after reset (input5 -> output5 golden).
        load_input5();
        check(imem[0] === 16'h7FFD, "vectors/input5.txt did not load expected first word 7FFD");
        checked_frame("phase3/frameB_input5");

        // Phase 4: back-to-back transaction without reset (upstream streaming
        // usage; input4 again -> output4 golden).
        load_input4();
        checked_frame("phase4/frameC_input4_noreset");

        // Phase 5: mid-frame asynchronous abort leaves no output and the
        // following transaction is still golden.
        load_input4();
        abort_frame_probe();
        load_input5();
        checked_frame("phase5/frameD_input5_after_abort");

        // Exactly one verdict marker is printed; $finish is the last
        // statement (Verilator --timing may execute statements after
        // $finish within the same block).
        if (errors != 0) begin
            $display("PEWEAVER_SIM_FAIL halo_fft64_reference errors=%0d", errors);
        end else begin
            $display("PEWEAVER_SIM_PASS halo_fft64_reference");
        end
        $finish;
    end

    // Fail-closed watchdog: any hang terminates the regression with failure.
    initial begin : watchdog
        repeat (60000) @(posedge clock);
        $display("PEWEAVER_SIM_FAIL halo_fft64_reference watchdog timeout");
        $finish;
    end

endmodule
