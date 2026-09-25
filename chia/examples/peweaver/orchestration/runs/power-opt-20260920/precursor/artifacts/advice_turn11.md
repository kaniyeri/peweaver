### Highest-value instruction: fix and prove the configurable delay store

The current priority is the elaboration failure at line 405. The design cannot reach functional testing while `buf_im[0:DEPTH-1]` references an undefined `DEPTH`.

Use the delay module’s **compile-time maximum capacity**—for example `MAX_DEPTH`—for both storage arrays:

- `buf_re[0:MAX_DEPTH-1]`
- `buf_im[0:MAX_DEPTH-1]`

Do not make the unpacked-array bound depend on a runtime-selected depth. The runtime depth input should only control pointer wrap:

- Write on **every** `clock`, regardless of `di_en`.
- Return the word written exactly `selected_depth` prior edges.
- Preserve read-before-write behavior, especially when `selected_depth == 1`.
- Wrap the pointer when `wr_ptr == selected_depth - 1`.
- Reset control/pointer state asynchronously; memory contents need not reset.
- Keep `selected_depth` fixed while samples are outstanding.

If the module was instead intended to have a compile-time `DEPTH` parameter, declare and connect that parameter explicitly—but do not merely add an arbitrary `DEPTH` declaration if the intended architecture uses `MAX_DEPTH` plus a runtime depth selector.

### Verification required before proceeding

1. Run Verilator lint/compile and require **zero undefined identifiers or elaboration errors**.
2. Unit-test the delay independently for every used depth:
   - `1, 2, 4, 8, 16, 32, 64`
3. Drive a unique `(re, im)` value every clock while toggling `di_en`; verify `di_en` has no effect on writes.
4. For each depth `D`, check after initialization that:
   - `delay_re[t] == input_re[t-D]`
   - `delay_im[t] == input_im[t-D]`
5. Explicitly test depth 1 to prove that the output is the previous clock’s input, not the value being written on the current edge.
6. Then run a top-level valid-only smoke test confirming first `do_en` at exactly:
   - 71 clocks after sample 0 in 64-point mode
   - 137 clocks after sample 0 in 128-point mode

Do not move on to twiddle or arithmetic debugging until compilation passes and all selectable delay depths satisfy this exact-clock contract.