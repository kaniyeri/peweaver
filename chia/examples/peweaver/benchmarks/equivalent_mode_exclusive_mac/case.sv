// PEWeaver benchmark: equivalent mode-exclusive MAC sharing.
//
// Scheduling contract: mode is the one-bit selector for this transaction.
// Exactly one logical PE is active per cycle; the inactive PE's inputs and
// accumulator are don't-care from the system's point of view.  Under that
// contract, the candidate may multiplex operands into one multiplier.

module peweaver_equiv_baseline (
    input  logic signed [3:0]  a0,
    input  logic signed [3:0]  b0,
    input  logic signed [7:0]  acc0,
    input  logic signed [3:0]  a1,
    input  logic signed [3:0]  b1,
    input  logic signed [7:0]  acc1,
    input  logic               mode,
    output logic signed [7:0] y
);
    logic signed [7:0] product0;
    logic signed [7:0] product1;

    assign product0 = $signed(a0) * $signed(b0);
    assign product1 = $signed(a1) * $signed(b1);
    assign y = mode ? (product1 + acc1) : (product0 + acc0);
endmodule

module peweaver_equiv_shared_candidate (
    input  logic signed [3:0]  a0,
    input  logic signed [3:0]  b0,
    input  logic signed [7:0]  acc0,
    input  logic signed [3:0]  a1,
    input  logic signed [3:0]  b1,
    input  logic signed [7:0]  acc1,
    input  logic               mode,
    output logic signed [7:0] y
);
    logic signed [3:0]  a_selected;
    logic signed [3:0]  b_selected;
    logic signed [7:0] acc_selected;
    logic signed [7:0] shared_product;

    assign a_selected   = mode ? a1   : a0;
    assign b_selected   = mode ? b1   : b0;
    assign acc_selected = mode ? acc1 : acc0;
    // This is the sole multiplier in the candidate datapath.
    assign shared_product = $signed(a_selected) * $signed(b_selected);
    assign y = shared_product + acc_selected;
endmodule

module peweaver_equiv_miter (
    input  logic signed [3:0]  a0,
    input  logic signed [3:0]  b0,
    input  logic signed [7:0]  acc0,
    input  logic signed [3:0]  a1,
    input  logic signed [3:0]  b1,
    input  logic signed [7:0]  acc1,
    input  logic               mode,
    output logic               mismatch
);
    logic signed [7:0] baseline_y;
    logic signed [7:0] candidate_y;

    peweaver_equiv_baseline baseline (
        .a0(a0), .b0(b0), .acc0(acc0), .a1(a1), .b1(b1), .acc1(acc1),
        .mode(mode), .y(baseline_y)
    );
    peweaver_equiv_shared_candidate candidate (
        .a0(a0), .b0(b0), .acc0(acc0), .a1(a1), .b1(b1), .acc1(acc1),
        .mode(mode), .y(candidate_y)
    );

    assign mismatch = baseline_y != candidate_y;
endmodule
