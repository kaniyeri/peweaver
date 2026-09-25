### Highest-value instruction: implement and verify the control/valid skeleton first

The candidate currently ends immediately after the port declaration—there is no module body or `endmodule`. Do **not** begin twiddles or arithmetic yet. First make the RTL compile and establish the exact transaction, mode, reset, and latency behavior using placeholder/tagged data.

Implement:

- `mode_q`, captured on the first accepted sample while idle.
- `busy_q`, set on that edge and cleared only after the last output sample.
- Mode-dependent frame length: `64` when `mode_q=0`, `128` when `mode_q=1`.
- Valid/control state for `P0`, `P1`, `P2`, and `P3`, with the planned stage latencies:
  - 64 mode: `51 + 15 + 5 = 71`
  - 128 mode: `99 + 27 + 9 + 2 = 137`
- Final registered `do_en`, guaranteed to produce exactly 64 or 128 consecutive cycles.
- Active-high asynchronous reset clearing `do_en`, `busy_q`, all valid flags, counters, phase bits, and pointers.
- A syntactically complete module ending in `endmodule`.

Use tagged placeholder data so sample index \(k\) can be observed at output; do not claim arithmetic correctness yet. Verify before moving on:

1. Verilator compiles with no warnings promoted to errors.
2. With sample 0 accepted at cycle 0:
   - `mode=0`: first `do_en` at cycle 71, high for exactly 64 cycles.
   - `mode=1`: first `do_en` at cycle 137, high for exactly 128 cycles.
3. Three consecutive same-mode frames produce contiguous output windows with no missing or extra valid cycle.
4. Changing external `mode` while `busy_q=1` does not change `mode_q` or pipeline scheduling.
5. Assert `reset` during every pipeline phase: `do_en` must drop immediately and never reassert from pre-reset state.
6. After reset, the next accepted sample recaptures `mode_q`.

Only after these checks pass should the burst proceed to exact `SdfUnit` feedback/butterfly timing and arithmetic. This removes the current fatal gate failure and isolates the highest-ranked architectural risk—cycle alignment—before coefficient and numerical mismatches obscure it.