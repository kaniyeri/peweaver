**Highest-value next instruction: restore a clean compile by fixing the malformed canonical twiddle literal before debugging functionality.**

At `peweaver_shared_fft.v:724`, change the invalid token conceptually from:

```verilog
wn_re[90] = 16'DAD8
```

to the exact reference value:

```verilog
wn_re[90] = 16'hDAD8
```

Keep:

```verilog
wn_im[90] = 16'h7A7D
```

This must match `third_party/r22sdf/Twiddle128.v` entry 90 exactly. Also scan every `wn_re[]`/`wn_im[]` assignment for malformed numeric syntax, without replacing intentional unreachable `16'hxxxx` entries.

Before changing any datapath or control logic, run the prescribed full regression. Acceptance criteria:

1. Verilator reports **zero syntax/elaboration errors**.
2. All four mode/vector tests execute rather than stopping during compilation.
3. Record the first functional mismatch separately for each mode, including cycle/bin and `do_en` behavior.

Do not investigate butterfly timing until this compile gate is clean; currently no architectural behavior is being evaluated at all.