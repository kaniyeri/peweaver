//----------------------------------------------------------------------
// PEWeaver PPA integration top for the Shared FFT candidate (Phase 4).
//
// Same integration contract as the FFT64/FFT128 PPA tops: the shared
// configurable core wrapped with async-assert/sync-deassert reset.
// Mode input is a top-level port (held per frame set).
//----------------------------------------------------------------------

module peweaver_ppa_reset_sync_shared (
    input  wire clock,
    input  wire reset_async_in,
    output wire reset_sync_out
);
    reg [1:0] sync_ff;
    always @(posedge clock or posedge reset_async_in) begin
        if (reset_async_in) sync_ff <= 2'b11;
        else sync_ff <= {sync_ff[0], 1'b0};
    end
    assign reset_sync_out = sync_ff[1];
endmodule

module peweaver_ppa_shared_fft (
    input  wire        clock,
    input  wire        reset,
    input  wire        mode,       // 0 = 64-point, 1 = 128-point
    input  wire        di_en,
    input  wire [15:0] di_re,
    input  wire [15:0] di_im,
    output wire        do_en,
    output wire [15:0] do_re,
    output wire [15:0] do_im
);
    wire core_reset;
    peweaver_ppa_reset_sync_shared u_reset_sync (
        .clock(clock), .reset_async_in(reset), .reset_sync_out(core_reset));
    peweaver_shared_fft #(.WIDTH(16)) u_core (
        .clock(clock), .reset(core_reset), .mode(mode),
        .di_en(di_en), .di_re(di_re), .di_im(di_im),
        .do_en(do_en), .do_re(do_re), .do_im(do_im)
    );
endmodule
