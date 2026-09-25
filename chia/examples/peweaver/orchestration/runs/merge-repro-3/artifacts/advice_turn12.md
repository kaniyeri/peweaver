### Highest-value instruction: tighten the existing registered twiddle/multiplier boundary without changing latency

Refactor each shared R2² stage so the critical arithmetic path contains **only four 16×16 multiplies, independent `>>> 15` truncations, one add/sub layer, and the existing multiplier-output register**. Ensure coefficient lookup, address generation, bypass control, and sample alignment are not accidentally combinationally included in that path.

Concretely:

- Register together:
  - `bf2_do_re/im`
  - `tw_re/im`
  - `tw_addr_nonzero`
  - corresponding valid
- Feed only those registered signals into the complex multiplier.
- Replace general `tw_num * tw_sel` logic with the equivalent shift/select construction because `tw_sel` is only 0–3; coefficient decoding must terminate at `tw_*_q`.
- Compute:
  - `rr = ($signed(data_re_q) * $signed(tw_re_q)) >>> 15`
  - `ii = ($signed(data_im_q) * $signed(tw_im_q)) >>> 15`
  - `ri = ($signed(data_re_q) * $signed(tw_im_q)) >>> 15`
  - `ir = ($signed(data_im_q) * $signed(tw_re_q)) >>> 15`
- Perform the 16-bit modular complex add/sub only after those four independent shifts, then capture directly in the existing multiplier-output register.
- When delayed `tw_addr_nonzero_q==0`, that same output register must capture the correspondingly delayed unmodified BF2 sample.
- Do **not** add a pipeline stage; total first-output cycles must remain 71 and 137.

Before moving on, verify:

1. Timing reports show no counter/address/ROM-decode logic between `tw_*_q` and the multiplier-output registers, and the 10 ns constraint is met.
2. Cycle-by-cycle compare multiplier inputs, `tw_addr_nonzero_q`, and outputs against the current bit-exact implementation for all reachable coefficients.
3. Explicitly test negative odd products, `-32768`, overflow wrapping, and address-zero bypass.
4. Reconfirm exactly 64/128 consecutive outputs, first `do_en` at cycles 71/137, continuous-frame abutment, and no stale `do_en` after asynchronous reset.

This targets the likely timing-critical boundary while preserving the already successful functional gates and exact external contract.