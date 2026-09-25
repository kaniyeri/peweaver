### Highest-value instruction: fix and prove the configurable delay-store primitive first

The current `DEPTH` error at line 405 is an elaboration blocker and likely exposes an incorrect distinction between **physical maximum depth** and **mode-selected runtime depth**.

- Declare `buf_re` and `buf_im` using an elaboration-time parameter such as `MAX_DEPTH`:
  ```verilog
  reg [WIDTH-1:0] buf_re [0:MAX_DEPTH-1];
  reg [WIDTH-1:0] buf_im [0:MAX_DEPTH-1];
  ```
- Use the mode-selected depth only for pointer wrap, e.g. `wr_ptr == selected_depth-1`.
- On every `clock`, including when `di_en==0`:
  1. Present the old contents of `buf_*[wr_ptr]` as the delayed output.
  2. Write the current input into `buf_*[wr_ptr]`.
  3. Advance or wrap `wr_ptr`.

This must implement read-before-write behavior. In particular, selected depth 1 must return the input from exactly the preceding edge. Do not qualify delay writes or pointer movement with `di_en`, and do not make a runtime signal such as selected depth an unpacked-array bound.

Before reconnecting arithmetic, use a unit test with a unique `(re, im)` value on **every clock** and check:

```text
delay_out[t] == delay_in[t-selected_depth]
```

for every selectable configuration:

- `64/32`, `32/16`, `16/8`, `8/4`, `4/2`, `2/1`
- final fixed depth `1`

Include clocks where `di_en=0` to prove that delay time is measured in clocks rather than accepted samples. Explicitly test pointer wrap and depth 1. Then lint/elaborate `peweaver_shared_fft` with both `mode=0` and `mode=1` configurations and require zero undefined parameters, out-of-range indices, or width warnings.

Do not proceed to twiddle or arithmetic debugging until this primitive passes: an incorrect delay or one-cycle read/write error invalidates every butterfly pairing and both 71-/137-cycle latency paths.