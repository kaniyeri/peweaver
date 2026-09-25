**Highest-value next instruction: fix elaboration by restoring the `WIDTH` parameter expected by the integration wrapper.**

The module currently declares:

```verilog
module peweaver_shared_fft (
```

but `peweaver_ppa_shared_fft.v` instantiates it as:

```verilog
peweaver_shared_fft #(.WIDTH(16)) u_core (...)
```

The five-character `^~~~~` in the `PINNOTFOUND` diagnostic is therefore almost certainly pointing at `WIDTH`, not a missing data port. Declare the top as:

```verilog
module peweaver_shared_fft #(
    parameter WIDTH = 16
) (
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

Keep the nine contracted ports unchanged and fixed at 16 bits; the parameter is needed for wrapper compatibility but should remain 16 for this design.

Before touching SDF timing or arithmetic, verify both elaboration paths:

1. Instantiate the core directly using all nine named ports.
2. Compile it through `peweaver_ppa_shared_fft`, including `#(.WIDTH(16))`.
3. Require zero `PINNOTFOUND`, parameter, duplicate-module, syntax, and width-fatal errors.
4. Run a reset smoke test:
   - asynchronous `reset=1` forces `do_en=0`;
   - after reset release with `di_en=0`, `do_en` stays low;
   - no stale transaction can later raise `do_en`.

Only after this passes should the burst move to cycle-accurate stage-valid timing and the required first-output cycles 71/137.