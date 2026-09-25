// PEWeaver MAC reference B: pass-through product lane.
// Input design for the clean-room MAC merge experiment. This file is an
// INPUT to the framework, not a candidate.
module mac_b (
    input  wire        clock,
    input  wire        reset,
    input  wire        en,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    output reg  [15:0] y
);
    wire signed [15:0] product = $signed(a) * $signed(b);

    always @(posedge clock) begin
        if (reset) begin
            y <= 16'd0;
        end else if (en) begin
            y <= product;
        end
    end
endmodule
