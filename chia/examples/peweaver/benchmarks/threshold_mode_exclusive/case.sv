// PEWeaver benchmark: HALO-inspired mode-exclusive threshold sharing.
//
// Two logical threshold variants from the HALO-inspired BCI threshold family
// ("movement" above-threshold detection and "seizure" below-threshold
// detection) compare one signed 8-bit sample against a signed 8-bit threshold.
//
// Scheduling contract: mode is the one-bit selector for this transaction.
// Exactly one threshold variant is active per cycle; the inactive variant's
// threshold is don't-care from the system's point of view. Under that
// contract, the candidate may multiplex the threshold operand and the
// comparison relation into one signed comparator.

module peweaver_threshold_baseline (
    input  logic signed [7:0] x,
    input  logic signed [7:0] t0,
    input  logic signed [7:0] t1,
    input  logic              mode,
    output logic              y
);
    // Variant "movement": above-threshold detection (x >= t0).
    logic movement_hit;
    // Variant "seizure": below-threshold detection (x < t1).
    logic seizure_hit;

    assign movement_hit = ($signed(x) >= $signed(t0));
    assign seizure_hit  = ($signed(x) <  $signed(t1));
    assign y = mode ? seizure_hit : movement_hit;
endmodule

module peweaver_threshold_shared_candidate (
    input  logic signed [7:0] x,
    input  logic signed [7:0] t0,
    input  logic signed [7:0] t1,
    input  logic              mode,
    output logic              y
);
    logic signed [7:0] t_selected;
    logic              invert_relation;

    // Select operands/configuration: the threshold operand and the comparison
    // relation both follow mode.
    assign t_selected      = mode ? t1 : t0;
    assign invert_relation = mode;
    // This is the sole signed comparator in the candidate datapath.
    assign y = ($signed(x) >= $signed(t_selected)) ^ invert_relation;
endmodule

module peweaver_threshold_miter (
    input  logic signed [7:0] x,
    input  logic signed [7:0] t0,
    input  logic signed [7:0] t1,
    input  logic              mode,
    output logic              mismatch
);
    logic baseline_y;
    logic candidate_y;

    peweaver_threshold_baseline baseline (
        .x(x), .t0(t0), .t1(t1), .mode(mode), .y(baseline_y)
    );
    peweaver_threshold_shared_candidate candidate (
        .x(x), .t0(t0), .t1(t1), .mode(mode), .y(candidate_y)
    );

    assign mismatch = baseline_y != candidate_y;
endmodule