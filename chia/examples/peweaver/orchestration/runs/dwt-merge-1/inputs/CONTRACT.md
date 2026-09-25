INTERFACE
- One top module named dwt_shared, exactly these ports:
  input clock, reset (synchronous, active-high), ctx, en;
  input signed x[15:0];
  output signed a_l1_lo[39:0], a_l1_hi[39:0], output a_l1_valid;
  output signed b_l1_lo[39:0], b_l1_hi[39:0], output b_l1_valid;
  output signed b_l2_lo[39:0], b_l2_hi[39:0], output b_l2_valid.
- No other external signals. Valid outputs are single-cycle strobes; data
  outputs hold when not producing. reset=1 clears all state of both contexts.

CONTEXTS (mutually exclusive, independent state)
- ctx=0: Context A, ONE db2 decomposition level.
- ctx=1: Context B, TWO db2 decomposition levels.
- Only the active context accepts x on an enabled edge; the inactive context
  holds all history, phase, pending work, and data outputs.
- ctx may change only on an edge with reset=1 or en=0.

ARITHMETIC (identical for both contexts)
- Accepted samples are indexed from zero per context; samples with negative
  index are zero. The level-1 window is latest-first [x[n], x[n-1], x[n-2],
  x[n-3]]. Products are exact signed 16x16; the 40-bit result is the
  mathematical signed sum reduced modulo 2^40 (no rounding, no saturation).
- Pinned signed Q15 coefficients (literal constants; do not rescale):
  LOW  H = [ 15826,  27411,   7345,  -4240]
  HIGH G = [ -4240,  -7345,  27411, -15826]
- Level-1 output updates on accepted-sample index n odd, with l1_valid=1.
- Level-2 input is q(v) = signed16(v[30:15]) of the freshly computed B
  level-1 low result; it is pushed into B's latest-first level-2 window on
  every B level-1 pair. A level-2 job is created on B pair indices 1, 3, 5,
  ... and is consumed on the next B enabled sample with no level-1 output due
  (level-1 output updates are on odd accepted-sample indices). On that edge,
  l2_valid=1 and the level-2 result updates from the level-2 window as of
  that edge.
- Pending level-2 work and both contexts' phases survive en=0 and suspension.

SHARING OBJECTIVE
- The two references each instantiate a db2 analysis bank per level
  (one bank for A, two banks for B). A correct shared design may time-share
  arithmetic across A level 1, B level 1, and B level 2 while preserving every
  exact cycle of the contract above.
- Structural gate: at most 8 normalized multiplication operators after the
  frozen normalization pass.
- Generic-cell gate: strictly below 60% of the independently synthesized
  two-reference generic Yosys cell count (unweighted generic cell count, NOT
  mapped area).

FORBIDDEN: $readmem*, $system, $fopen and file I/O, initial/final blocks,
delays, force/release, DPI/PLI, testbench or hierarchical references outside
the candidate file.