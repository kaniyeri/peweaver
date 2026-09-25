**Highest-value next instruction: fix the top-level elaboration contract before touching FFT control or arithmetic.**

The functional gate is not running because `peweaver_ppa_shared_fft` instantiates:

```verilog
peweaver_shared_fft #(.WIDTH(16)) u_core (...)
```

but the candidate declares no `WIDTH` parameter. Add a compatibility parameter to the module declaration:

```verilog
module peweaver_shared_fft #(parameter WIDTH = 16) (
```

Keep the required ports unchanged: `clock`, `reset`, `mode`, `di_en`, 16-bit `di_re/di_im`, and `do_en`, 16-bit `do_re/do_im`. Do not change stage logic in this burst; `WIDTH` should resolve to 16 and introduce no timing or behavioral change.

Verify by elaborating the candidate together with `physical/rtl/peweaver_ppa_shared_fft.v`, then run the shared FFT regression. Success criteria for this burst:

1. No `PINNOTFOUND` or hierarchy/elaboration error.
2. The functional tests actually simulate rather than abort during compilation.
3. With `reset=1`, `do_en` is immediately zero.
4. The regression reports substantive 64/128 timing or bin comparisons, even if arithmetic still fails.

Only after this interface blocker is cleared should the next burst address cycle-exact valid/control behavior.