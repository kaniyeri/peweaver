**Highest-value instruction: fix elaboration compatibility before touching FFT logic.**

The functional harness instantiates:

```verilog
peweaver_shared_fft #(.WIDTH(16)) u_core (...)
```

but the candidate module has no `WIDTH` parameter. The five-character `^~~~~` in the `PINNOTFOUND` error is therefore almost certainly pointing at `WIDTH`.

Change only the module declaration to accept the compatibility parameter while retaining the exact nine-port interface:

```verilog
module peweaver_shared_fft #(
    parameter integer WIDTH = 16
) (
    input              clock,
    input              reset,
    input              mode,
    input              di_en,
    input       [15:0] di_re,
    input       [15:0] di_im,
    output              do_en,
    output      [15:0] do_re,
    output      [15:0] do_im
);
```

Keep the external data widths fixed at 16 bits because that is the contract; `WIDTH` only satisfies the immutable wrapper’s parameter override. Do not alter counters, stage timing, twiddle logic, or valid generation in this burst.

Verify before moving on:

1. Run the exact immutable regression compile path and require `compile_returncode == 0`; specifically, there must be no `PINNOTFOUND` for `.WIDTH(16)` or any of `clock`, `reset`, `mode`, `di_en`, `di_re`, `di_im`, `do_en`, `do_re`, and `do_im`.
2. Confirm the simulation binary starts, proving elaboration reached execution rather than stopping at compilation.
3. Record the first runtime failure with full mismatch/latency details. Only then choose the next datapath repair.
4. As an interface/reset smoke check, asynchronously assert `reset` and confirm `do_en` becomes and remains `0`; after deassertion with no `di_en`, it must stay low.

This removes the current hard blocker and exposes the first genuine functional defect for the next burst.