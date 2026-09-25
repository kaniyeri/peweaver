## Highest-value next burst: fix the top-level interface and compile/lint boundary

The evaluator never reached architectural verification: it could not find `peweaver_shared_fft` or any required ports. First create or correct the synthesis-visible top module with the **exact** contract:

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

Do not rename ports, add parameters, wrap this under another top, or use unpacked/interface types. Ensure the file containing it is included by the evaluator’s source-file discovery or manifest, and that there is exactly one unambiguous definition.

For this burst, wire the existing candidate datapath beneath this module. At the boundary:

- Capture configuration into `mode_q` on the first accepted idle sample:
  ```verilog
  if (idle && di_en)
      mode_q <= mode;
  ```
- Use `mode` directly for all decisions made on that same first acceptance edge; use `mode_q` thereafter.
- Drive `do_en`, `do_re`, and `do_im` from the selected merged pipeline output.
- Asynchronously clear `do_en` and all valid/control state on `reset`; stale delay RAM must never make `do_en` assert.
- In 64 mode, bypass `R2_FINAL` without an added register.
- In 128 mode, select its registered output and valid.

### Verification before any further optimization

Run the evaluator’s exact lint/elaboration command and require:

1. `peweaver_shared_fft` is selected successfully as top.
2. All nine ports exist with the exact names, directions, and widths above.
3. No implicit nets, undriven outputs, duplicate modules, or unresolved instances.
4. A minimal smoke test confirms:
   - While `reset=1`, `do_en=0`.
   - After reset with no `di_en`, `do_en` remains 0.
   - With sample 0 accepted immediately after reset, `mode=0` produces the first `do_en` at cycle 71.
   - The same test with `mode=1` produces the first `do_en` at cycle 137.
   - The first acceptance edge uses the current `mode`, not reset’s old `mode_q`.
   - Reset asserted during fill or output clears `do_en` immediately and prevents any stale post-reset valid pulse.

Do not proceed to twiddle, arithmetic, or physical optimization until this exact top-level elaborates and these boundary timing checks pass.