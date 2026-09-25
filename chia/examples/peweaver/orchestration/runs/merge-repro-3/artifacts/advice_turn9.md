**Highest-value next instruction: fix top-level elaboration compatibility before changing any FFT logic.**

The candidate declares:

```verilog
module peweaver_shared_fft (
```

but the evaluator wrapper likely instantiates:

```verilog
peweaver_shared_fft #(.WIDTH(16)) u_core (...)
```

Verilator reports unknown parameters as `PINNOTFOUND`; the five-character marker strongly indicates `WIDTH`. Add a compatibility parameter:

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

Keep the nine contracted ports and fixed 16-bit datapath unchanged; `WIDTH` is only for wrapper elaboration compatibility.

Before proceeding:

1. Elaborate a direct instance using all nine named ports.
2. Elaborate the evaluator-style instance with `#(.WIDTH(16))`.
3. Require zero `PINNOTFOUND`, syntax, duplicate-module, and fatal width errors.
4. Run a reset smoke test: asynchronous `reset=1` must immediately force `do_en=0`; after release with `di_en=0`, `do_en` must remain low with no stale reassertion.

Do not debug butterflies, twiddles, or 71/137-cycle latency until this gate compiles and executes—the current failure occurs before architectural behavior is tested.