### Highest-value instruction: fix and prove the configurable delay primitive first

The immediate blocker is the undeclared `DEPTH` used in the memory declaration near line 405. Do not merely define `DEPTH` as a runtime signal: unpacked array bounds must be elaboration-time constants.

Implement the delay primitive with:

- An elaboration-time `MAX_DEPTH` parameter used by `buf_re` and `buf_im`.
- A runtime selected depth, such as `depth_i`, set from `mode_q`.
- A circular pointer `wr_ptr` that wraps at `depth_i - 1`.
- Read-before-write behavior on every `clock`:
  - `delay_re_q <= buf_re[wr_ptr]`
  - `delay_im_q <= buf_im[wr_ptr]`
  - Then write current input into that same location via nonblocking assignments.
- No `di_en` write qualification. The stores must advance and write every clock, including gaps.
- A pointer width of at least one bit so `MAX_DEPTH=1` is legal; avoid a zero-width `$clog2(1)` result.

Instantiate/prove these selected depths:

| Maximum depth | 64 mode | 128 mode |
|---:|---:|---:|
| 64 | 32 | 64 |
| 32 | 16 | 32 |
| 16 | 8 | 16 |
| 8 | 4 | 8 |
| 4 | 2 | 4 |
| 2 | 1 | 2 |
| 1 | bypassed | 1 |

Before touching FFT arithmetic, verify:

1. **Compile/lint:** Verilator elaborates `peweaver_shared_fft.v` with no undefined symbols or invalid array widths.
2. **Standalone delay test:** Drive a unique signed complex ramp every clock and, for every depth above, check that the delay output after edge `k` equals the input presented at edge `k-depth`.
3. **Wrap boundary:** Run at least three full pointer rotations and explicitly check the cycles immediately before and after wrap.
4. **Invalid-clock behavior:** Toggle `di_en` randomly while continuing to change `di_re/di_im`; confirm the delay still advances every clock.
5. **Depth-one behavior:** Confirm that a value written at edge `k` appears at the output at edge `k+1`, not at edge `k`.
6. **Reset:** Reset the pointer/control asynchronously, but do not require memory clearing; suppress comparisons until the selected depth has refilled.

Do not proceed to twiddle or butterfly debugging until this primitive both compiles and matches the exact-clock-delay model. Every butterfly pairing and both 71/137-cycle latency contracts depend on it.