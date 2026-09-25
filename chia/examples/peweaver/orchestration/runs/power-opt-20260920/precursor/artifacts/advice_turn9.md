**Highest-value instruction: fix and prove the configurable delay-store primitive before touching FFT arithmetic or scheduling.**

The functional gate currently cannot elaborate because `buf_im[0:DEPTH-1]` uses an undefined—and potentially runtime—`DEPTH`. Array bounds must use a compile-time constant. Define each delay instance with a compile-time `MAX_DEPTH` (64, 32, 16, 8, 4, 2, or 1), while using a runtime `depth_sel` chosen from `mode_q` only for pointer wrap:

- Declare `buf_re[0:MAX_DEPTH-1]` and `buf_im[0:MAX_DEPTH-1]`.
- On **every** `clock` edge, regardless of `di_en` or stage valid:
  - Read `buf_*[wr_ptr]` into the delay output.
  - Write the current input into `buf_*[wr_ptr]`.
  - Wrap `wr_ptr` when `wr_ptr == depth_sel-1`.
- Preserve read-before-write behavior through nonblocking assignments. In particular, `depth_sel=1` must return the previous clock’s input, not the current input.
- Reset control/pointers asynchronously, but do not add a reset loop for the memories.
- Ensure `depth_sel` is never zero and remains fixed while `outstanding != 0`.

Verify this in two steps before proceeding:

1. **Elaboration gate:** rerun Verilator/lint and require zero errors for `peweaver_shared_fft.v`; specifically, no storage declaration may depend on an undeclared or runtime `DEPTH`.
2. **Isolated delay test:** drive unique `{re,im}` tags every clock—including clocks where `di_en=0`—and assert  
   `delay_out[n] == delay_in[n-depth_sel]`  
   for every supported selection:
   - `stage0.db1`: 32/64
   - `stage0.db2`: 16/32
   - `stage1.db1`: 8/16
   - `stage1.db2`: 4/8
   - `stage2.db1`: 2/4
   - `stage2.db2`: 1/2
   - `stage3_r2.db`: 1

Also test pointer wrap for at least two full periods and explicitly test depth 1. Do not move on to end-to-end latency or arithmetic until this primitive both compiles and matches exact clock-delay semantics.