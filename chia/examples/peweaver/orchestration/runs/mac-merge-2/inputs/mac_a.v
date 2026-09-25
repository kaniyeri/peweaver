// PEWeaver MAC reference A: accumulating multiply-accumulate lane.
// Input design for the clean-room MAC merge experiment. This file is an
// INPUT to the framework, not a candidate.
module mac_a (
    input  wire        clock,
    input  wire        reset,
    input  wire        en,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    output reg  [15:0] y
);
    wire signed [15:0] product = $signed(a) * $signed(b);
    reg [15:0] acc;

    always @(posedge clock) begin
        if (reset) begin
            acc <= 16'd0;
            y   <= 16'd0;
        end else if (en) begin
            acc <= acc + product;
            y   <= acc + product;
        end
    end
endmodule
