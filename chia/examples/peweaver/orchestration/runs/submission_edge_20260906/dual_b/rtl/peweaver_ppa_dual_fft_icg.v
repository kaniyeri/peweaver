// PEWeaver power-managed dual-core FFT reference (variant B, plan workstream 4).
// No arithmetic sharing: the two frozen standalone cores are instantiated side
// by side on one die, but each core's clock is gated using characterized
// Sky130 integrated clock gating (ICG) cells (sky130_fd_sc_hd__dlclkp_4).
// When mode = 0 (64-point active), the 128-point core clock is gated off.
// When mode = 1 (128-point active), the 64-point core clock is gated off.
// Both cores are clocked during reset so asynchronous/synchronous initializations
// occur cleanly prior to burst execution.

`timescale 1ns/1ps
`default_nettype wire

module peweaver_ppa_dual_fft_icg (
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
    // Clock gating control signals:
    // Core 64 is clocked when mode == 0 OR when reset is asserted.
    // Core 128 is clocked when mode == 1 OR when reset is asserted.
    wire gate_core64  = (~mode) | reset;
    wire gate_core128 = mode | reset;

    wire clock_64;
    wire clock_128;

    (* keep *)
    sky130_fd_sc_hd__dlclkp_4 u_icg_core64 (
        .CLK  (clock),
        .GATE (gate_core64),
        .GCLK (clock_64)
    );

    (* keep *)
    sky130_fd_sc_hd__dlclkp_4 u_icg_core128 (
        .CLK  (clock),
        .GATE (gate_core128),
        .GCLK (clock_128)
    );

    // Route data enable only to the selected core
    wire en64  = di_en & ~mode;
    wire en128 = di_en & mode;

    wire        do_en64, do_en128;
    wire [15:0] do_re64, do_im64;
    wire [15:0] do_re128, do_im128;

    peweaver_ppa_fft64 u_fft64 (
        .clock  (clock_64),
        .reset  (reset),
        .di_en  (en64),
        .di_re  (di_re),
        .di_im  (di_im),
        .do_en  (do_en64),
        .do_re  (do_re64),
        .do_im  (do_im64)
    );

    peweaver_ppa_fft128 u_fft128 (
        .clock  (clock_128),
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
