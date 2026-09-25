**Highest-value next instruction: close timing on the per-stage twiddle lookup→multiplier path without changing pipeline latency.**

Implement each `CSDFk` with its own **registered, balanced Twiddle128 lookup port**. Do not share a combinational ROM output or coefficient mux across stages. On the same edge, register:

- `tw_re_q[k]`, `tw_im_q[k]` from `tw_addr[k]`
- `tw_zero_q[k] <= (tw_addr[k] == 0)`
- the corresponding BF2 data
- `mu_en_q[k]`

Then feed only these local registers into that stage’s complex multiplier/bypass selection. Replicate or buffer high-fanout `mode_q` decoding locally if synthesis reports it on the critical path. Preserve the four-product multiplier and all existing multiplier output registers; do **not** add a pipeline stage.

Before moving on, verify:

1. **Timing:** post-place analysis at 10 ns reports setup TNS = 0 and WNS ≥ 0; inspect the prior worst path to confirm it no longer crosses a large coefficient decoder or shared high-fanout mux.
2. **Coefficient alignment:** whenever `mu_en_q[k]` is asserted, `tw_*_q[k]` equals `Twiddle128[mode_q ? tw_addr_128 : 2*tw_addr_64]` for the BF2 sample registered on that same edge.
3. **Zero-address bypass:** `tw_zero_q[k]` selects the aligned BF2 sample, bit-for-bit, with no extra cycle.
4. **Cycle contract remains unchanged:** first `do_en` is cycle 71/137, spans exactly 64/128 clocks, and continuous frames remain gapless.
5. **Bit equivalence:** compare every `do_re/do_im` while `do_en` is high against the currently passing RTL for long continuous 64- and 128-point bursts, including reset and signed-overflow cases.

This targets the most likely synthesis bottleneck while protecting the three already-passing functional gates.