module shared_mac (
    input  wire        clock,
    input  wire        reset,
    input  wire        mode,
    input  wire        en,
    input  wire [7:0]  a,
    input  wire [7:0]  b,
    output reg  [15:0] y
);
    wire signed [15:0] product = $signed(a) * $signed(b);
    reg  [15:0]        acc;
    wire [15:0]        sum = acc + product;

    always @(posedge clock) begin
        if (reset) begin
            acc <= 16'd0;
            y   <= 16'd0;
        end else if (en) begin
            if (!mode) begin
                acc <= sum;
                y   <= sum;
            end else begin
                y   <= product;
            end
        end
    end
endmodule
