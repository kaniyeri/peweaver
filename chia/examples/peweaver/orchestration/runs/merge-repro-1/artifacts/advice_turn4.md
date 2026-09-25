### Highest-value instruction: close the twiddle-to-multiplier timing path without changing latency

Make each `CSDF` twiddle port a **physically local, registered, balanced ROM/decoder**. The likely timing failure is a large coefficient-selection cone—potentially including `mode_q`, address remapping, and a wide case mux—feeding the complex multiplier in the same cycle.

For each stage:

- Compute `tw_addr_raw` from `bf2_count`.
- Form the canonical address:
  ```verilog
  tw_addr_128 = mode_q ? tw_addr_raw : {tw_addr_raw_64, 1'b0};
  ```
- On that same edge, register:
  - `tw_re_q`, `tw_im_q`
  - `tw_zero_q = (tw_addr_128 == 0)`
  - the corresponding BF2 sample into `mu_di_re_q`, `mu_di_im_q`
  - `mu_en_q`
- In the following cycle, feed only these registered signals to the multiplier/bypass selection. Address zero must select the aligned BF2 data; it must not introduce a combinational bypass around pipeline registers.
- Replicate the coefficient decoder near each multiplier if sharing one physical decoder creates high-fanout or routing delay. Share the literal definition in source, not necessarily the synthesized mux hardware.
- Do **not** add another architectural pipeline stage: the existing stage latencies must remain 51/99 for CSDF0, 15/27 for CSDF1, and 5/9 for CSDF2.

Before moving on, verify:

1. Cycle-by-cycle against the reference `SdfUnit`:
   - `tw_addr_128`
   - `tw_re_q`, `tw_im_q`
   - `tw_zero_q`
   - `mu_en_q`
   - aligned multiplier input and result
   - stage `do_en`, `do_re`, and `do_im`

2. Exhaustively check every reachable coefficient:
   ```text
   Twiddle64[a] == Twiddle128[2*a]
   ```
   and confirm unreachable addresses return deterministic zero.

3. Re-run continuous 64- and 128-point frames and require unchanged top-level timing:
   - 64 mode: `do_en` cycles 71–134
   - 128 mode: `do_en` cycles 137–264

4. Synthesize immediately and inspect the worst path. Acceptance is **TNS = 0 at 10 ns**, with no path spanning coefficient decode plus multiplier arithmetic. If the remaining critical path is elsewhere, optimize that reported path rather than introducing speculative pipeline stages.