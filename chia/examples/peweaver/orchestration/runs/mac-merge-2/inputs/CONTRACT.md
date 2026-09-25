INTERFACE
- One top module named shared_mac with exactly these ports:
  input clock, reset (synchronous, active-high), mode (0 = accumulating
  lane, 1 = product lane), en, a[7:0], b[7:0]; output y[15:0].
  No other external signals.

BEHAVIORAL CONTRACT
- All words are two's complement: a and b are signed 8-bit, y is signed
  16-bit (raw 16-bit wrapping).
- On a clock edge with reset=1: internal accumulator and y are cleared.
- On a clock edge with reset=0 and en=1:
  mode=0: y <= (accumulator + a*b) mod 2^16 and the accumulator takes the
          same value (running sum of all mode-0 products since reset).
  mode=1: y <= (a*b) mod 2^16; the accumulator is unchanged.
- On a clock edge with en=0: y and the accumulator hold.
- The product is the exact signed 8x8 product; no rounding or saturation.
- mode may change only while en=0 (mutually exclusive lanes); the design
  must hold state across mode changes and never mix lanes within a cycle.

SHARING OBJECTIVE
- Exactly ONE 8x8 multiplier structure in the design (the two input designs
  each contain one; a merged design with two is rejected).
- Synthesized area strictly below the sum of the two input designs.

FORBIDDEN: $readmem*, $fopen/system tasks, initial/final blocks, delays,
DPI/PLI, testbench constructs.