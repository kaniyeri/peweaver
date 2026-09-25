### Highest-value instruction: fix top-level elaboration before any FFT logic

The functional gate is not reaching simulation. `peweaver_ppa_shared_fft.v` instantiates:

```verilog
peweaver_shared_fft #(.WIDTH(16)) u_core (...)
```

but the candidate currently declares `peweaver_shared_fft` without a `WIDTH` parameter. Verilator reports this parameter mismatch as `PINNOTFOUND`.

Restore wrapper compatibility with:

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

Keep the nine contracted ports and their names exactly as shown. `WIDTH` is an integration parameter, not an additional port; the implementation may remain fixed at 16-bit data.

Before changing SDF scheduling or arithmetic, verify:

1. Direct core elaboration using all nine named ports.
2. Wrapper elaboration through `peweaver_ppa_shared_fft` with `#(.WIDTH(16))`.
3. Zero `PINNOTFOUND`, unknown-parameter, duplicate-module, syntax, or fatal width errors.
4. A reset smoke test:
   - asynchronous `reset=1` immediately makes `do_en=0`;
   - after reset deassertion with `di_en=0`, `do_en` remains low;
   - no stale pre-reset transaction later raises `do_en`.

Only after both elaboration paths pass should work proceed to the 71/137-cycle valid timing.