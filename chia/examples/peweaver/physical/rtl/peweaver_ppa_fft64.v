//----------------------------------------------------------------------
// PEWeaver PPA integration top for the FFT64 baseline (Phase 3).
//
// PEWeaver-owned physical-integration wrapper. The imported reference
// (peweaver_halo_fft64_reference) remains byte-identical; this wrapper adds
// only the physically required reset contract:
//
//   * asynchronous assertion (propagates immediately, as upstream assumes),
//   * synchronous deassertion via a standard two-flop reset synchronizer,
//     so reset RELEASE is never evaluated against an unsynchronized
//     asynchronous removal check (the open-PDK flow's recovery/removal
//     analysis is therefore meaningful).
//
// The same integration contract (this wrapper pattern) applies to FFT128
// and the future shared candidate. Data inputs are NOT reset-gated here;
// the core ignores them while its reset is asserted.
//----------------------------------------------------------------------

module peweaver_ppa_reset_sync (
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

module peweaver_ppa_fft64 (
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

    peweaver_ppa_reset_sync u_reset_sync (
        .clock          (clock),
        .reset_async_in (reset),
        .reset_sync_out (core_reset)
    );

    peweaver_halo_fft64_reference u_fft64 (
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
