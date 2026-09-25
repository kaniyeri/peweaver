**Highest-value instruction: fix and prove the configurable delay-store primitive before touching FFT control or arithmetic.**

The current `DEPTH` compile failure at `buf_im[0:DEPTH-1]` blocks all functional evaluation and likely indicates that runtime-selected depth was incorrectly used as a compile-time array bound. Replace that conceptually with:

- A compile-time `MAX_DEPTH` parameter for `buf_re`/`buf_im` allocation.
- A mode-selected effective depth, fixed during operation.
- A circular pointer reset to zero.
- An unconditional write and pointer advance on **every clock**, independent of `di_en`.
- Read-before-write behavior:
  - On edge `k`, the delay output receives the old `buf[ptr]`.
  - The current input is then written to `buf[ptr]`.
  - `ptr` wraps when it equals `selected_depth - 1`.

For every selected depth `D`, after filling, the observable result must be:

```text
delay_out[k] == delay_in[k-D]
```

Use the physical maxima for allocation—64, 32, 16, 8, 4, 2, and 1—and select the mode-specific depths from the architecture table. Do not reset the memory contents; reset only the pointer and relevant valid/control state.

**Verification before moving on:**

1. Run full Verilator lint/compile and require zero undefined identifiers or illegal array bounds.
2. Unit-test the delay primitive independently for every reachable `D`:
   `1, 2, 4, 8, 16, 32, 64`.
3. Drive a unique complex sample every clock while randomly toggling `di_en`. Compare against a software queue that advances every clock—not only valid clocks.
4. Explicitly test pointer wrap and depth-1 read-before-write behavior.
5. Assert that `selected_depth` remains stable outside reset/idle mode capture.
6. Then run a valid-only top-level check confirming first-output timing remains exactly 71 clocks in 64 mode and 137 clocks in 128 mode.

Do not proceed to twiddle or arithmetic debugging until this primitive compiles and passes the exact-clock-delay scoreboard.