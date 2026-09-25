module shared_mac(input wire clock, input wire reset, input wire mode, input wire en, input wire [7:0] a, input wire [7:0] b, output reg [15:0] y);
  wire signed [15:0] pa_full = $signed(a) * $signed(b);
  wire signed [15:0] pa = {4'b0000, pa_full[15:4]};
  reg [15:0] acc;
  always @(posedge clock) begin
    if (reset) begin acc <= 0; y <= 0; end
    else if (en && !mode) begin acc <= acc + pa; y <= acc + pa; end
    else if (en && mode) y <= pa;
  end
endmodule
