## Highest-value burst: restore top-level `WIDTH` parameter compatibility

The failure is an elaboration blocker, not an FFT datapath failure. The immutable wrapper instantiates:

```verilog
peweaver_shared_fft #(.WIDTH(16)) u_core (...)
```

The five-character `^~~~~` in `PINNOTFOUND` points to `WIDTH`. Keep the nine contract ports unchanged, but declare the compatibility parameter:

```verilog
module peweaver_shared_fft #(
    parameter integer WIDTH = 16
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

`WIDTH` is a parameter, not an extra port, so this preserves the external interface. Keep `di_re`, `di_im`, `do_re`, and `do_im` fixed at 16 bits. Do not modify CSDF control, twiddles, arithmetic, or latency in this burst—the earlier implementation already passed functional and physical gates.

### Verification before moving on

1. Run the evaluator’s exact elaboration path containing `peweaver_ppa_shared_fft`.
2. Require no `PINNOTFOUND` for `WIDTH` or the nine named ports.
3. Confirm simulation actually starts.
4. Re-run functional checks and require:
   - asynchronous `reset` forces `do_en=0`;
   - with no post-reset `di_en`, `do_en` remains low;
   - mode 0 first asserts `do_en` exactly 71 cycles after sample 0 and stays high for 64 clocks;
   - mode 1 first asserts it at cycle 137 and stays high for 128 clocks;
   - `do_re/do_im` remain bit-exact against both reference cores.

Do not optimize timing until this exact wrapper-compatible declaration is preserved and functional regression is back to passing.