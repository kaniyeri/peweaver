## Recommended atomic hypothesis

**Clock-gate only the complete mode-128 radix-2 tail (`SU_TAIL`) in mode 64 with one characterized `sky130_fd_sc_hd__dlclkp_1`.**

Do not modify shared delay banks, arithmetic, operands, counters, reset behavior, or valid generation in this candidate.

### Why this is the appropriate next experiment

The prior upper-delay-bank attempt failed timing and substantially increased implementation cost:

- Area: `282,963 → 311,415 µm²`
- `p128`: `40.4448 → 42.07478 mW`
- WNS: approximately `-0.092 ns`
- TNS: approximately `-0.150 ns`

Regardless of whether that result used true ICGs or enable-flop substitution, it shows that a six-bank/2,016-bit transformation is presently too disruptive. Tail-only gating is a much smaller physical experiment:

- One ICG rather than six.
- Approximately 67 tail-state bits stop receiving mode-64 clock edges:
  - 32-bit one-word complex delay
  - 32-bit output data registers
  - `bf_en`, `bf_sp_en`, and `do_en`
- No mux or enable is added to a functional data path.
- Mode-128 sees only one gate’s clock insertion and internal-power overhead.

This still directly targets the dominant measured mechanism: clock-related power is 19.6566 mW, or 49.1% of total mode-64 streaming power.

### Required structure

Generate a dedicated tail clock through exactly one characterized gate:

- Source clock: top-level `clock`
- Gate enable: transaction-stable `active_mode`
- Gated-clock load: every sequential process inside `SU_TAIL`, including its depth-one `DelayBuffer`
- Keep asynchronous reset behavior exactly as in the incumbent
- Keep `tail_di_en`, output selection, and all tail arithmetic unchanged

The synthesis-visible implementation must contain the real `sky130_fd_sc_hd__dlclkp_1`; no AND, ternary, mux, or generic logic may drive the tail clock. Any RTL-simulation accommodation must be excluded from synthesis and must not conflict with the PDK model during GLS.

### Correctness argument

- **Mode 64:** `do_*` selects `s2_do_*`, so no tail state or output is architecturally observable. Freezing the entire tail cannot affect the 64-point values, 71-cycle latency, or valid window.
- **Mode 128:** `active_mode` remains high for the transaction, so every source-clock edge reaches the tail. Its behavior and 137-cycle latency remain cycle-equivalent to the incumbent.
- **Reset-separated transitions:** Tail control registers retain their existing reset behavior. The unreset depth-one data word is flushed before valid tail output, as in the incumbent.
- **Continuous frames:** The gate remains continuously enabled throughout all mode-128 fill, processing, drain, and back-to-back-frame intervals.

### Physical expectations and checks

The likely mode-64 saving is modest—roughly on the order of `0.1–0.3 mW`, not the theoretical benefit of gating 2,016 delay-bank bits—but implementation risk and mode-128 overhead should be much lower.

Verify:

1. Exactly one `sky130_fd_sc_hd__dlclkp_1` survives synthesis.
2. All tail sequential cells are clocked from its `GCLK`.
3. No generic logic drives a clock pin.
4. Bit-exact 64/128 directed, randomized, and three-frame tests pass.
5. First-valid latency remains exactly 71/137 cycles.
6. Mapped GLS passes.
7. Clock-gating setup/hold and ordinary setup/hold pass with TNS 0.
8. DRC remains zero and area remains below `339,908 µm²`.
9. Measure both modes; reject if the mode-128 gate overhead outweighs the mode-64 reduction.

No files were edited.