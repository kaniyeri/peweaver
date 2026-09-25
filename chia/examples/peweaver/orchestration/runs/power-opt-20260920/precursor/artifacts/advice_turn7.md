**Fix the configurable delay-store elaboration and semantics before touching FFT arithmetic or control.** The undefined `DEPTH` at line 405 is the immediate gate blocker and likely indicates confusion between compile-time capacity and runtime-selected delay.

Implement each circular store with:

- A compile-time parameter such as `MAX_DEPTH` for array declarations:
  - `buf_re[0:MAX_DEPTH-1]`
  - `buf_im[0:MAX_DEPTH-1]`
- A runtime selected depth signal, fixed during operation, for pointer wrap:
  - wrap when `wr_ptr == selected_depth - 1`
- A resettable `wr_ptr`; memory contents and the data output register need not reset.
- An unconditional write on **every** `clock`, regardless of `di_en`.
- Read-before-write behavior:
  - `delay_re <= buf_re[wr_ptr]`
  - `delay_im <= buf_im[wr_ptr]`
  - then write `di_re/di_im` to that same location using nonblocking assignments.
- Correct depth-1 handling: every edge returns the value written on the immediately preceding edge.

Do not merely define `DEPTH` as one fixed value if the same store must select different depths by mode.

Before proceeding, require both:

1. Verilator elaborates/lints the complete `peweaver_shared_fft.v` with zero errors.
2. A focused delay testbench checks every used depth `1, 2, 4, 8, 16, 32, 64` with a unique value every clock, including clocks where `di_en=0`, and asserts after priming that:
   - `delay_re[t] == input_re[t-selected_depth]`
   - `delay_im[t] == input_im[t-selected_depth]`

Also reset mid-stream and confirm `wr_ptr` restarts at zero while no stale data is treated as valid externally. This isolates the exact-delay primitive on which every butterfly pairing and both 71/137-cycle latency contracts depend.