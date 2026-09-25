// PEWeaver benchmark: unsafe sharing when two MAC outputs are simultaneous.
//
// Scheduling contract: there is no mode/exclusivity assumption here.  Both
// logical PEs must produce their outputs in the same cycle.  A one-multiplier
// candidate that services only one selected lane cannot satisfy this contract.

module peweaver_unsafe_baseline (
    input  logic signed [3:0]  a0,
    input  logic signed [3:0]  b0,
    input  logic signed [7:0]  acc0,
    input  logic signed [3:0]  a1,
    input  logic signed [3:0]  b1,
    input  logic signed [7:0]  acc1,
    output logic signed [7:0] y0,
    output logic signed [7:0] y1
);
    logic signed [7:0] product0;
    logic signed [7:0] product1;

    assign product0 = $signed(a0) * $signed(b0);
    assign product1 = $signed(a1) * $signed(b1);
    assign y0 = product0 + acc0;
    assign y1 = product1 + acc1;
endmodule

module peweaver_unsafe_shared_candidate (
    input  logic signed [3:0]  a0,
    input  logic signed [3:0]  b0,
    input  logic signed [7:0]  acc0,
    input  logic signed [3:0]  a1,
    input  logic signed [3:0]  b1,
    input  logic signed [7:0]  acc1,
    input  logic               mode,
    output logic signed [7:0] y0,
    output logic signed [7:0] y1
);
    logic signed [3:0]  a_selected;
    logic signed [3:0]  b_selected;
    logic signed [7:0] acc_selected;
    logic signed [7:0] shared_product;

    assign a_selected   = mode ? a1   : a0;
    assign b_selected   = mode ? b1   : b0;
    assign acc_selected = mode ? acc1 : acc0;
    // One multiplier can calculate one lane, but cannot produce both
    // independent same-cycle products required by the baseline contract.
    assign shared_product = $signed(a_selected) * $signed(b_selected);
    assign y0 = mode ? 8'sd0 : (shared_product + acc_selected);
    assign y1 = mode ? (shared_product + acc_selected) : 8'sd0;
endmodule

module peweaver_unsafe_miter (
    input  logic signed [3:0]  a0,
    input  logic signed [3:0]  b0,
    input  logic signed [7:0]  acc0,
    input  logic signed [3:0]  a1,
    input  logic signed [3:0]  b1,
    input  logic signed [7:0]  acc1,
    input  logic               mode,
    output logic               mismatch
);
    logic signed [7:0] baseline_y0;
    logic signed [7:0] baseline_y1;
    logic signed [7:0] candidate_y0;
    logic signed [7:0] candidate_y1;

    peweaver_unsafe_baseline baseline (
        .a0(a0), .b0(b0), .acc0(acc0), .a1(a1), .b1(b1), .acc1(acc1),
        .y0(baseline_y0), .y1(baseline_y1)
    );
    peweaver_unsafe_shared_candidate candidate (
        .a0(a0), .b0(b0), .acc0(acc0), .a1(a1), .b1(b1), .acc1(acc1),
        .mode(mode), .y0(candidate_y0), .y1(candidate_y1)
    );

    assign mismatch = (baseline_y0 != candidate_y0) ||
                      (baseline_y1 != candidate_y1);
endmodule
