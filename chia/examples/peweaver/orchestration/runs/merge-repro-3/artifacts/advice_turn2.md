**Highest-value burst: fix top-level interface/elaboration before implementing more FFT logic.**

The functional gate is not reaching simulation; Verilator reports `PINNOTFOUND` at `peweaver_shared_fft`. Make the module’s port list match the contract **exactly**, with no renamed or omitted signals:

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

Use the full Verilator diagnostic to identify the named pin immediately before the caret—likely a mismatch such as `clk` versus `clock`, `rst` versus `reset`, or a missing `mode`. Do not modify the testbench or add a second wrapper interface.

Before proceeding:

1. Run the evaluator’s exact Verilator compile/elaboration command and require **zero errors**.
2. Instantiate the DUT once in a minimal smoke harness using all nine named ports.
3. Assert `reset` asynchronously and confirm:
   - `do_en` becomes `0` immediately.
   - `do_re/do_im` may be unspecified while `do_en=0`.
4. After reset, accept sample 0 with `di_en=1` and confirm the selected `mode` is captured into `mode_q`.

Only after this interface gate passes should the next burst implement the tagged-data valid pipeline and verify first-output cycles **71** and **137**. Arithmetic changes have no value while the DUT cannot elaborate.