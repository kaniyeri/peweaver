INTERFACE
- One top module named peweaver_shared_fft with exactly these ports:
  input clock, reset (active-high asynchronous assertion), mode
  (0 = 64-point, 1 = 128-point), di_en, di_re[15:0], di_im[15:0];
  output do_en, do_re[15:0], do_im[15:0]. No other external signals.

STREAMING CONTRACT
- One sample per clock accepted when di_en=1; no backpressure. Exactly N
  consecutive di_en samples form one frame (N=64 when mode=0, N=128 when
  mode=1), natural order.
- First do_en at exactly cycle 71 (64-point) or 137 (128-point), counted from
  the clock edge that accepts input sample 0; do_en stays high for exactly N
  cycles, then returns low.
- Sustained same-mode streaming: one frame accepted every N input cycles
  (one-output-per-cycle throughput during emission).
- mode may only be latched while idle; mode transitions require reset and an
  idle drain; after reset no output from a previous mode/frame may appear.

ARITHMETIC CONTRACT (16-bit two's-complement words interpreted as Q1.15)
- Butterfly: signed 17-bit add/sub; store (sum + RH) >>> 1 with arithmetic
  right shift (floor). First butterfly of every SdfUnit has RH=0, the second
  RH=1; SdfUnit2 has RH=0.
- Complex multiply: exact signed 16x16 products, each >>> 15 with no rounding
  bias, then real = pr - pi_shifted and imaginary = pr_shifted + pi
  (mod 2^16, no saturation).
- -j path: (re, im) -> (im, -re mod 2^16).
- Twiddles: the literal Q1.15 values of the reference tables; address zero
  bypasses the multiplier (as in Multiply.v).
- Total scaling 1/N. Input natural order, output bit-reversed emission order.

ACCEPTANCE GATES (checked by a deterministic judge after each attempt)
- Bit-exact match against both reference cores: single frames, continuous
  multi-frame bursts, and reset/mode-transition schedules, in both modes.
- Then synthesis, mapped-netlist gate-level simulation, place & route on
  sky130A at 10 ns: timing met with TNS 0, DRC 0, and placed cell area
  strictly below 424,885 um^2 (the combined two-core baseline).

FORBIDDEN: $readmem*, $fopen/system tasks, initial/final blocks, delays,
DPI/PLI, testbench constructs.