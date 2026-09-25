### Highest-value instruction: fix and verify the configurable delay-store elaboration and semantics first

The current attempt cannot elaborate because `buf_im[0:DEPTH-1]` references undeclared `DEPTH` at line 405. Fix this before changing FFT control or arithmetic.

Use a **compile-time maximum-depth parameter** (for example, `MAX_DEPTH`) for both storage arrays:

- `buf_re[0:MAX_DEPTH-1]`
- `buf_im[0:MAX_DEPTH-1]`

Use the runtime/configured depth only to control the circular address rollover; never use it as an unpacked-array dimension. Ensure the delay logic has these behaviors:

- `buf_re` and `buf_im` are written on **every `clock`**, independent of `di_en` or stage valid.
- The output on edge \(t\) is the input from exactly \(t-D\), where `D` is the selected depth.
- At pointer wrap, the old `buf_*[wr_ptr]` value is observed before the new input replaces it. Nonblocking assignments should preserve this read-before-write behavior.
- Reset clears `wr_ptr` and output-valid/control state; clearing memory contents is unnecessary.
- The selected depth remains fixed until reset/idle mode transition.
- Depth 1 must work explicitly: every edge returns the immediately preceding sample.

Before moving on, verify in this order:

1. Run Verilator lint/elaboration on the complete RTL and require **zero errors**, especially no remaining `DEPTH` references.
2. Unit-test each selectable delay:
   - `64/32`, `32/16`, `16/8`, `8/4`, `4/2`, `2/1`, and final depth `1`.
   - Drive a unique cycle-number pattern into `di_re/di_im`.
   - Check every clock that `dout(t) == din(t-D)`.
3. Include pointer-wrap tests and clocks where `di_en=0`; outputs must still advance by clock, proving this is not a valid-qualified FIFO.
4. Repeat after asynchronous reset and after changing depth only across reset.

Do not debug FFT latency or twiddle behavior until this delay primitive both elaborates and passes these exact-delay checks.