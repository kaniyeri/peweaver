### Highest-value instruction: fix the top-level interface and compile/lint discovery first

The current blocker is structural, not arithmetic: the evaluator cannot find `peweaver_shared_fft` or any required ports. Before implementing or debugging pipeline behavior, create or correct the evaluator-visible top-level module so it matches the contract **exactly**:

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

Do not rename ports, add required wrapper parameters, use an alternate top name, or expose extra protocol signals. Ensure the source containing this module is included by the evaluator’s file list/glob and that there is exactly one unambiguous definition.

For this burst, wire the existing best datapath implementation behind this interface. If its ports differ, adapt them in the wrapper—for example, map `clock/reset`, pass `mode`, `di_en`, `di_re`, and `di_im`, and drive `do_en/do_re/do_im` from the implementation outputs. Do **not** silently tie `mode` to a constant; it must select 64- versus 128-point operation.

### Verification before moving on

Run the same lint/elaboration flow with `peweaver_shared_fft` explicitly selected as top and confirm:

1. The top module is found.
2. All nine ports exist with the exact names and directions above.
3. `di_re`, `di_im`, `do_re`, and `do_im` are exactly 16 bits.
4. There are no undriven or multiply driven outputs.
5. Both `mode=0` and `mode=1` elaborate through real datapath/control logic.
6. Asynchronous reset immediately forces `do_en=0`:
   ```verilog
   always @(posedge clock or posedge reset)
   ```
   or equivalent reset behavior.
7. A minimal smoke simulation accepts sample 0 immediately after reset deassertion in each mode and observes:
   - `mode=0`: first `do_en` at acceptance edge + 71, then 64 consecutive cycles.
   - `mode=1`: first `do_en` at acceptance edge + 137, then 128 consecutive cycles.
   - No `do_en` occurs before those offsets or survives reset.

Do not spend this burst optimizing twiddles, delays, or physical resources. Until the exact top-level ABI is discoverable and lint-clean, none of those improvements can be evaluated.