### Highest-value instruction: close the reported critical path without changing pipeline latency

Target the **registered twiddle-to-multiplier-output path** in each shared R2² stage—typically from `tw_re_q`/`tw_im_q` and delayed `bf2` data through the four 16×16 products, shifts, and complex add/sub into the multiplier output register.

Implement/confirm this exact one-cycle structure:

- Inputs are registered: `bf2_re_q`, `bf2_im_q`, `tw_re_q`, `tw_im_q`, and `tw_nonzero_q`.
- Compute four signed 16×16 products **in parallel**.
- Apply signed `>>> 15` independently to each 32-bit product.
- Perform only the final 16-bit modular complex add/sub after truncation.
- Register the selected result:
  - `tw_nonzero_q=1`: multiplier result.
  - `tw_nonzero_q=0`: the correspondingly delayed unmodified BF2 sample.
- Do not place ROM decoding, twiddle-address multiplication, mode selection, or feedback-memory reads in this cone. Those must terminate at the existing coefficient/data registers.
- Do **not** add a pipeline stage; that would violate the fixed 71/137-cycle contract.

Use the timing report to confirm the actual worst path and ensure it now begins and ends at these intended registers rather than crossing multiple architectural boundaries.

Before moving on, verify:

1. STA meets the 10 ns requirement for all three multiplier instances and both modes.
2. Cycle-by-cycle equivalence is unchanged at `do_en`, `do_re`, and `do_im`.
3. First `do_en` remains cycle **71** for mode 0 and **137** for mode 1.
4. Multiplication matches the required expression exactly, especially for negative odd products and `16'h8000`.
5. `tw_nonzero_q=0` selects the correctly delayed BF2 sample with no one-cycle skew.
6. Reset during any multiplier cycle immediately suppresses `do_en` and never allows stale validity to reappear.

This is the best burst because functionality already passed three gates; changing scheduling or storage now creates high regression risk, while isolating and simplifying the known arithmetic critical cone directly addresses the only reported failure.