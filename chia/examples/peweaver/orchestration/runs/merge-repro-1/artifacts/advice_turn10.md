### Highest-value burst: remove asynchronous reset from the registered twiddle data

The routed design misses setup by only **60 ps**, and the sole violating path is:

```text
CSDF0.MU.b_im[5]
  -> 16x16 product/reduction
  -> real subtraction
  -> address-zero bypass mux
  -> CSDF0.do_re[15]
```

The launch register for `MU.b_re/b_im` is currently an asynchronously reset flop. Change `TwiddleRom.tw_re` and `TwiddleRom.tw_im` to ordinary `posedge clock` registers with **no reset**, matching the reference `Twiddle128.v`. Apply this to all three CSDF twiddle ports, but keep reset on `mu_en`, `mu_do_en`, stage-valid state, counters, pointers, and `outstanding`.

Conceptually:

```verilog
always @(posedge clock) begin
    tw_re <= lut_re;
    tw_im <= lut_im;
end
```

Do **not** add a multiplier pipeline stage or alter the four-product arithmetic; either would risk violating latency or bit-exact truncation.

#### Required cycle behavior

For every CSDF stage:

- At edge `t`, `tw_re/tw_im`, `bf2_do_re/im`, and `mu_en <= (rom_addr != 0)` capture aligned values.
- During `t` to `t+1`, the multiplier computes the four independently shifted products.
- At edge `t+1`, `mu_do_re/im` capture either the multiplier result or the address-zero bypass data.
- `su0_do_en`, `su1_do_en`, `su2_do_en`, and final `do_en` must not shift.
- Mode 0 must still first assert `do_en` at cycle 71 for 64 cycles.
- Mode 1 must still first assert `do_en` at cycle 137 for 128 cycles.

Unreset twiddle data may be stale or unknown after reset, which is safe because reset clears all valid and multiplier-enable state; it must never reach an asserted `do_en`.

#### Verification before moving on

1. Run the full RTL regression for both modes, continuous frames, immediate input after reset, and reset during fill/output. Require bit-exact outputs and unchanged `do_en` timing.
2. Synthesize and confirm the flops driving:
   ```text
   CSDF0.MU.b_re[*]
   CSDF0.MU.b_im[*]
   ```
   map to ordinary non-resettable flops rather than `dfrtp` resettable cells.
3. Run mapped simulation and place-and-route.
4. Require:
   - setup **WNS ≥ 0**
   - setup **TNS = 0**
   - hold slack ≥ 0
   - DRC 0
   - placed area below 424,885 µm²
   - mapped outputs still bit-exact in both modes

This is the most direct, lowest-risk correction because it attacks the measured critical-path launch delay without changing architecture, arithmetic, or externally visible timing.