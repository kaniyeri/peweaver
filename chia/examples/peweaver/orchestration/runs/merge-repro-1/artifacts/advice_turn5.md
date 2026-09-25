**Highest-value instruction:** fix the **registered twiddle-lookup/multiplier timing cone** before changing any other datapath logic.

Implement each `CSDFk` as a physically independent registered twiddle port. Compute `tw_addr` from `bf2_count`, capture it at the existing ROM register boundary, and decode the canonical `Twiddle128` literals with a balanced mux/case structure local to that stage. Do not share a combinational coefficient mux between stages, and do not add a pipeline cycle. Align these signals explicitly:

- `tw_addr_q`
- `tw_re_q`, `tw_im_q`
- delayed BF2 data entering the multiplier
- `mu_en_q`
- address-zero multiplier-bypass select

On every multiplier-active cycle, `tw_re_q/tw_im_q` must correspond to the same BF2 sample as the multiplier input. In 64 mode, lookup address must be `{tw_addr_64,1'b0}`. In CSDF2 64 mode, the multiplier remains bypassed with its five-cycle stage latency unchanged.

Before integration, perform a cycle-by-cycle comparison against the reference stages for:

- `bf2_do_en`
- `bf2_count`
- logical and canonical `tw_addr`
- `tw_re_q/tw_im_q`
- `mu_en_q`
- multiplier inputs and registered outputs
- stage `do_en/do_re/do_im`

Required first-output stage latencies remain:

- CSDF0: 51 / 99 clocks for 64 / 128 mode
- CSDF1: 15 / 27 clocks
- CSDF2: 5 / 9 clocks

Then synthesize this isolated change at 10 ns and inspect the worst paths. Proceed only if the twiddle/multiplier cone no longer dominates and full-design STA reports **TNS 0**, while end-to-end first `do_en` remains cycle 71 or 137 and all samples remain bit-exact. This targets the failed timing gate without risking the already-passing functional gates.