**Highest-value next instruction: fix the top-level interface/elaboration failure before implementing more FFT logic.**

Make `peweaver_shared_fft` expose **exactly** these named ports:

```verilog
module peweaver_shared_fft (
    input         clock,
    input         reset,
    input         mode,
    input         di_en,
    input  [15:0] di_re,
    input  [15:0] di_im,
    output        do_en,
    output [15:0] do_re,
    output [15:0] do_im
);
```

The Verilator `PINNOTFOUND` error means the evaluator instantiates a named pin absent from the compiled module—commonly a `clk`/`clock`, reset, or output-name mismatch. Check the actual compiled top module, not only an unused duplicate declaration, and ensure no conditional compilation or wrapper changes its ports.

Before any datapath work, verify with the evaluator’s exact Verilator elaboration command, or an equivalent minimal named-port instantiation connecting all nine signals. Require:

1. Zero `PINNOTFOUND`, duplicate-module, or width errors.
2. With asynchronous `reset=1`, `do_en` immediately becomes `0`.
3. After reset release and with `di_en=0`, `do_en` remains `0`.
4. Outputs are driven to known values whenever observed—no undriven/X top-level signals.

Do not proceed to latency or arithmetic debugging until this compile/elaboration smoke test passes; currently none of the architecture can be functionally evaluated.