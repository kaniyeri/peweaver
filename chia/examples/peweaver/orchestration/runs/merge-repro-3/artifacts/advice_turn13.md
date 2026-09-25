### Highest-value instruction: optimize the registered complex-multiplier cone without adding latency

The only failing gate is timing, and the most likely critical combinational path is a signed `16×16` product followed by an accidentally widened add/sub. Keep the existing multiplier-output register and exact cycle schedule, but make the truncation and modular arithmetic widths explicit:

```text
rr_full = $signed(data_re) * $signed(tw_re)
ii_full = $signed(data_im) * $signed(tw_im)
ri_full = $signed(data_re) * $signed(tw_im)
ir_full = $signed(data_im) * $signed(tw_re)

rr_q15 = rr_full[30:15]
ii_q15 = ii_full[30:15]
ri_q15 = ri_full[30:15]
ir_q15 = ir_full[30:15]

mul_re_q <= rr_q15 - ii_q15   // 16-bit modular result
mul_im_q <= ri_q15 + ir_q15   // 16-bit modular result
```

Declare each `*_full` as signed 32-bit and each `*_q15` as signed 16-bit. Ensure the final operations are only 16 bits, discarding carry/borrow. Do **not** write a single expression such as `(rr_full >>> 15) - (ii_full >>> 15)`, because width propagation can infer a 32-bit adder after the multipliers. Do not replace the four products with a three-multiply identity; independent truncation makes that potentially non-equivalent.

Preserve these alignment rules:

- `tw_re_q`, `tw_im_q`, `tw_nonzero_q`, and the corresponding delayed sample must refer to the same `bf2_count`.
- If `tw_nonzero_q==0`, `mul_re_q/mul_im_q` select the delayed unmodified sample.
- In 64-point `P2`, multiplication is always bypassed.
- No register may be added or removed: first `do_en` must remain cycle 71 or 137.

Before moving on, verify:

1. Cycle-by-cycle multiplier results against a software model that separately shifts each 32-bit product by 15 and then performs 16-bit modular add/sub.
2. Directed operands including `16'h8000`, `16'hffff`, odd negative products, and overflowing final sums.
3. Full-frame output equality and unchanged `do_en` windows for both modes, including three continuous frames and asynchronous reset during multiplication.
4. Resynthesis with the timing report showing the multiplier endpoint now uses 16-bit final adders and meets the 10 ns constraint. If the reported worst path is not in this cone, do not speculate further—apply the same width/retiming discipline to the actual reported startpoint and endpoint while preserving the fixed register boundaries.