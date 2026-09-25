//----------------------------------------------------------------------
// PEWeaver PPA integration top for the FFT128 baseline (Phase 2).
//
// PEWeaver-owned physical-integration wrapper — the same integration
// contract as the FFT64 PPA top: the pinned, untouched reference
// (peweaver_halo_fft128_reference) wrapped with an async-assert /
// sync-deassert reset synchronizer so recovery/removal analysis is
// meaningful under the frozen physical flow.
//----------------------------------------------------------------------

module peweaver_ppa_reset_sync_128 (
    input  wire clock,
    input  wire reset_async_in,
    output wire reset_sync_out
);
    reg [1:0] sync_ff;

    always @(posedge clock or posedge reset_async_in) begin
        if (reset_async_in) begin
            sync_ff <= 2'b11;              // asynchronous assertion
        end else begin
            sync_ff <= {sync_ff[0], 1'b0}; // synchronized release
        end
    end

    assign reset_sync_out = sync_ff[1];
endmodule

module peweaver_ppa_fft128 (
    input  wire        clock,
    input  wire        reset,
    input  wire        di_en,
    input  wire [15:0] di_re,
    input  wire [15:0] di_im,
    output wire        do_en,
    output wire [15:0] do_re,
    output wire [15:0] do_im
);
    wire core_reset;

    peweaver_ppa_reset_sync_128 u_reset_sync (
        .clock          (clock),
        .reset_async_in (reset),
        .reset_sync_out (core_reset)
    );

    peweaver_halo_fft128_reference u_fft128 (
        .clock  (clock),
        .reset  (core_reset),
        .di_en  (di_en),
        .di_re  (di_re),
        .di_im  (di_im),
        .do_en  (do_en),
        .do_re  (do_re),
        .do_im  (do_im)
    );
endmodule
