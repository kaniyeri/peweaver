//----------------------------------------------------------------------
// PEWeaver-owned wrapper for the curated r22sdf 64-point FFT reference.
//
// Upstream FFT64.v (module FFT, revision
// f7dca6e548e1370b69a09382d30609ee14ba4a57, MIT license) is used
// byte-identical; this file only gives the reference a PEWeaver-prefixed
// top-module name. No upstream logic, port, or parameter behavior is
// changed here: the wrapper is a pure name-isolation pass-through with
// WIDTH fixed to the selected 16-bit reference configuration.
//----------------------------------------------------------------------
module peweaver_halo_fft64_reference #(
    parameter WIDTH = 16
)(
    input               clock,   // Master Clock
    input               reset,   // Active High Asynchronous Reset
    input               di_en,   // Input Data Enable
    input   [WIDTH-1:0] di_re,   // Input Data (Real)
    input   [WIDTH-1:0] di_im,   // Input Data (Imag)
    output              do_en,   // Output Data Enable
    output  [WIDTH-1:0] do_re,   // Output Data (Real)
    output  [WIDTH-1:0] do_im    // Output Data (Imag)
);

    FFT #(.WIDTH(WIDTH)) core (
        .clock  (clock),
        .reset  (reset),
        .di_en  (di_en),
        .di_re  (di_re),
        .di_im  (di_im),
        .do_en  (do_en),
        .do_re  (do_re),
        .do_im  (do_im)
    );

endmodule
