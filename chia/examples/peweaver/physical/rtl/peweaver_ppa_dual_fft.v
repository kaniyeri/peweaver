// PEWeaver ungated dual-core FFT reference (variant A, plan workstream 4).
// No hardware sharing: the two frozen standalone cores are instantiated side
// by side on one die. The inactive core receives di_en=0; both core clocks
// run continuously. Mode follows the frozen shared-design protocol: mode
// changes only through the reset-separated transition (select_and_reset).
// Input data fans out to both cores; the output mux selects the active core.
// The wrapper's I/O contract is identical to peweaver_ppa_shared_fft so the
// same SDC, activity schedule, and power accounting apply.

module peweaver_ppa_dual_fft (
    input  wire        clock,
    input  wire        reset,
    input  wire        mode,       // 0 = 64-point core, 1 = 128-point core
    input  wire        di_en,
    input  wire [15:0] di_re,
    input  wire [15:0] di_im,
    output wire        do_en,
    output wire [15:0] do_re,
    output wire [15:0] do_im
);
    // route the enable only to the selected core; both clocks always run
    wire en64  = di_en & ~mode;
    wire en128 = di_en & mode;

    wire        do_en64, do_en128;
    wire [15:0] do_re64, do_im64;
    wire [15:0] do_re128, do_im128;

    peweaver_ppa_fft64 u_fft64 (
        .clock  (clock),
        .reset  (reset),
        .di_en  (en64),
        .di_re  (di_re),
        .di_im  (di_im),
        .do_en  (do_en64),
        .do_re  (do_re64),
        .do_im  (do_im64)
    );

    peweaver_ppa_fft128 u_fft128 (
        .clock  (clock),
        .reset  (reset),
        .di_en  (en128),
        .di_re  (di_re),
        .di_im  (di_im),
        .do_en  (do_en128),
        .do_re  (do_re128),
        .do_im  (do_im128)
    );

    assign do_en = mode ? do_en128 : do_en64;
    assign do_re = mode ? do_re128 : do_re64;
    assign do_im = mode ? do_im128 : do_im64;
endmodule
