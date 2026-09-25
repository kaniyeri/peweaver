**Highest-value instruction: close timing in the registered complex-multiplier path without changing pipeline latency.**

Refactor each `P0/P1/P2` multiplier so the only combinational cone between the registered inputs and `mul_out_*` is four signed 16×16 multiplies followed by **16-bit** modular add/subtract:

- Inputs must already be aligned registers:
  - `tw_re_q`, `tw_im_q`
  - delayed `bf2_re_q`, `bf2_im_q`
  - `tw_nonzero_q` / bypass flag
- Declare all four products explicitly as signed `[31:0]`.
- Apply `>>> 15` to each product independently, then truncate each shifted result to signed `[15:0]` **before** complex addition/subtraction. Do not allow synthesis to infer 32-bit final adders.
- Register the final result in `mul_out_re_q/mul_out_im_q`.
- When `tw_nonzero_q==0`, that same register must capture the correspondingly delayed unmodified BF2 sample.
- Do not add a pipeline stage: `P0/P1/P2` and total latencies must remain 51/15/5 and 71 for mode 0, and 99/27/9 plus P3=2 and 137 for mode 1.

Before moving on, verify both:

1. **STA:** under the 10 ns constraint, inspect the worst paths into `mul_out_*`; require nonnegative setup slack and confirm no ROM decode or feedback-buffer mux has leaked into that cone.
2. **Cycle/bit equivalence:** compare multiplier outputs for all reachable twiddle addresses plus corner operands (`-32768`, `32767`, negative odd products, overflow). Confirm address-zero bypass is exact, `do_en` first rises at cycles 71/137, and exactly 64/128 consecutive outputs are produced.

This directly targets the failed timing gate while preserving the contract’s arithmetic truncation and fixed observable latency.