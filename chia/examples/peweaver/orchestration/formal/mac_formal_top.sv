// MAC sequential-contract formal harness (controller-owned; derived from the
// driver CONTRACT). The candidate under proof is read as shared_mac.v by the
// generated .sby script.
//
// Evidence class: BOUNDED model checking (BMC depth 12 clock cycles). This is NOT an unbounded sequential-contract proof; the report
// labels it accordingly. The randomized bit-exact oracle judge (pure-Python
// oracle, independent of this mirror) covers arithmetic beyond the bound.
//
// Proven with fully symbolic operands (a, b, mode, en, reset), under the
// declared protocol assumptions (initial reset, mode changes only while
// en=0):
//   - external equivalence to the contract mirror at every cycle, whose
//     next-state relations are exactly those of mac_a (mode 0) and mac_b
//     (mode 1) expressed through the candidate's own signed product, and
//   - mirror-level hold properties (disabled hold, mode-1 accumulator hold).
// Limitation (Sol review): mirror hold properties verify the mirror's own
// update code; DUT internal-state corruption is observable only through
// external equivalence within the bound.

module mac_formal_top (
    input wire reset, input wire mode, input wire en,
    input wire [7:0] a, input wire [7:0] b);

  // formal clock: undriven wire; yosys-smtbmc steps the single implicit
  // clock domain once per BMC step (standard synchronous formal pattern)
  wire clock;

  wire [15:0] y;
  shared_mac dut (.clock(clock), .reset(reset), .mode(mode), .en(en),
                  .a(a), .b(b), .y(y));

  // ---- protocol assumptions (declared contract) ----
  reg past_valid = 0;
  always @(posedge clock) past_valid <= 1;

  // initial reset: the first two cycles must assert reset (power-up state
  // of the DUT is otherwise unconstrained and would false-fail equivalence)
  integer cyc = 0;
  always @(posedge clock) begin
    cyc <= cyc + 1;
    if (cyc < 2)
      assume_reset: assume (reset);
    // mode may change only while en=0 on the edge where the new mode appears
    if (past_valid && !reset && en)
      assume_mode_legal: assume (mode == $past(mode));
  end

  // ---- contract mirror ----
  reg [15:0] m_acc = 0, m_y = 0;
  wire signed [15:0] mp = $signed(a) * $signed(b);
  wire [15:0] prod = mp[15:0];

  always @(posedge clock) begin
    if (reset) begin
      m_acc <= 0;
      m_y <= 0;
    end else if (en) begin
      if (!mode) begin
        m_acc <= m_acc + prod;
        m_y <= m_acc + prod;
      end else begin
        m_y <= prod;
      end
    end
  end

  // Hold properties are guarded with $past(en)/$past(reset): the mirror
  // register updates on the edge according to the PREVIOUS tick's inputs.
  always @(posedge clock) begin
    if (past_valid) begin
      contract_equiv: assert (y == m_y);
      if (!$past(en) && !$past(reset))
        mirror_disabled_hold: assert (m_acc == $past(m_acc));
      if ($past(en) && $past(mode) && !$past(reset))
        mirror_m1_acc_hold: assert (m_acc == $past(m_acc));
    end
  end

  // coverage: both modes exercised after reset
  reg [1:0] cov = 0;
  always @(posedge clock) begin
    if (reset) cov <= 0;
    else if (en && !mode) cov <= cov | 2'b01;
    else if (en && mode) cov <= cov | 2'b10;
    both_modes_seen: cover (cov == 2'b11);
  end
endmodule
