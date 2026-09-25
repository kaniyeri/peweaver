## Decision: repair the rejected attempt

Do **not** branch from the incumbent yet. The candidate passed all functional gates, so the timing failure is likely a localized implementation regression rather than an architectural defect. The next burst should fix timing before adding any further clock gating or delay-buffer optimization.

## Highest-value fix: remove late isolation muxes from the stage-3 multiplier path

The likely regression is the zero-clamping logic placed directly before the four 16×16 multipliers:

```verilog
mul_a_* = mul_active ? active_a_* : 0;
mul_b_* = mul_active ? tw_*       : 0;
```

That adds a control-dependent mux/AND level to the active 128-point arithmetic path.

Move this isolation to the **D inputs of the existing registered multiplier/twiddle operands**, without adding a register or changing latency. Use the already aligned condition:

```verilog
mul_active = mode_q &&
             stage3_mul_valid &&
             (tw_addr_aligned != 0);
```

Expected behavior at the existing operand-capture edge:

- `mul_active==1`: capture the original butterfly data and twiddle values bit-exactly.
- `mul_active==0`: capture zero into the otherwise-unused multiplier operand registers, or hold zero if already zero.
- The multiplier inputs must come directly from those registers—no new `mul_active` mux between register Q and the multiplier.
- Keep the existing registered bypass selection and multiplier-result selection unchanged.
- Do not register or recompute `mul_active`; use the same address-aligned condition currently controlling the bypass.
- If there is no existing data-operand register at this boundary, leave `active_a_re/im` direct and clamp only the existing registered `tw_re/im` to zero. A zero coefficient suppresses most multiplier-cone activity without burdening the critical data path.
- Do not add per-slot ICG gating in this burst.

Thus, in 64-point mode the stage-3 multiplier coefficient/state remains zero and the multiplier result is never selected; in 128-point nonzero-twiddle slots the active path is structurally the same as the incumbent.

## Verification before proceeding

1. **Timing-path inspection**
   - Confirm the candidate’s worst paths traverse `mul_active` operand isolation or its fanout.
   - After the change, verify no `mode_q`, `stage3_mul_valid`, or `tw_addr_aligned` logic lies between the operand-register Q pins and multiplier inputs.
   - Run the same post-route corner and constraints as the failed portfolio run; require setup and hold `WNS >= 0`, `TNS >= 0`, and no clock-gating violations.

2. **Cycle-level behavior**
   - For `mode_q=1 && stage3_mul_valid && tw_addr_aligned!=0`, multiplier operands and results must equal the rejected candidate/incumbent on the same cycles.
   - For `mode_q=0` or `tw_addr_aligned==0`, isolated registers must become/remain zero, while the original bypass value is selected.
   - Verify no stale isolated value can be consumed when `mul_active` returns high.

3. **Architectural contract**
   - First `do_en`: exactly cycle 71 for 64-point and 137 for 128-point frames.
   - `do_en` width: exactly 64 or 128 cycles.
   - Bit-exact outputs for impulse, corner-value, random, back-to-back, reset, and mode-transition tests.
   - No bubble between continuous same-mode frames.
   - `mode` changes must have no datapath effect until accepted into `mode_q`.

Only after timing closes should the burst proceed to tail clock gating or broader stage-idle gating.