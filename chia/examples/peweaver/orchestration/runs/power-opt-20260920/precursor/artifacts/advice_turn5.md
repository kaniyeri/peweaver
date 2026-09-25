**Highest-value instruction: fix and prove the configurable delay-store implementation before any further FFT work.**

The current attempt cannot elaborate because `DEPTH` is undeclared at line 405. The buffer array dimensions must use a **compile-time maximum-depth parameter**, not the runtime-selected depth. Specifically, make `buf_im` use the same bound as `buf_re`—likely `MAX_DEPTH`:

```verilog
reg [WIDTH-1:0] buf_re [0:MAX_DEPTH-1];
reg [WIDTH-1:0] buf_im [0:MAX_DEPTH-1];
```

Use the selected depth only for pointer wrap and read-address calculation. Do not use a mode-dependent value in an unpacked-array declaration.

The store must satisfy, for selected depth `D`:

- Write `{di_re, di_im}` on **every** rising edge, regardless of `di_en`.
- After warm-up, output the value written exactly `D` clock edges earlier.
- Preserve read-before-write behavior.
- For `D=1`, the value visible after an edge must be the previous edge’s input, never the just-written input.
- Reset control/pointers as needed, but memory contents need not be reset.
- Keep `D` unchanged while a frame is active or draining.

Before moving on, perform two checks:

1. **Elaboration gate:** Run Verilator lint/compile on `peweaver_shared_fft` and require zero errors, especially no remaining references to undeclared `DEPTH`.
2. **Delay-only scoreboard:** Drive a unique complex ramp every clock while independently toggling `di_en`. Compare each delay output against a clock-indexed history queue for every required configuration:
   - `64→32/64`
   - `32→16/32`
   - `16→8/16`
   - `8→4/8`
   - `4→2/4`
   - `2→1/2`
   - `1→1`

Explicitly test pointer wrap and at least two full maximum-depth cycles. Do not proceed to twiddle or arithmetic debugging until every delay produces `out[k] == in[k-D]`; an off-by-one here invalidates all butterfly pairings and both latency targets.