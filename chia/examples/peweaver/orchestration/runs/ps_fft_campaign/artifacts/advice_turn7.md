## Failure interpretation

The previous run is **not a valid power candidate result**:

- Placement, routing, activity annotation, and power reporting completed.
- `read_power_activities` deprecation messages are warnings, not the cause of failure.
- Result assembly failed because both reset timing reports contain only `No paths found.`, while the assembler requires asynchronous recovery/removal path groups.
- The staged physical RTL also appears to have changed reset processes and twiddle-address logic, while containing no surviving `dlclkp` instance. Therefore it did not cleanly test the intended tail-gating hypothesis.
- The reported `288,442 µm²` must not enter the Pareto archive without a complete result JSON and all hard gates.

## One atomic hypothesis

**Clock-gate only the complete mode-128 radix-2 tail stage (`SU_TAIL`) during mode 64 using exactly one characterized `sky130_fd_sc_hd__dlclkp_1`.**

No other RTL transformation should accompany it: preserve reset style, twiddle-address generation, shared delay buffers, counters, arithmetic, valid logic, and output selection exactly.

### Required structure

- Instantiate one real `sky130_fd_sc_hd__dlclkp_1`.
- Source its `CLK` from top-level `clock`.
- Drive its gate enable from transaction-stable `active_mode`.
- If synchronous reset requires a clock edge to clear tail state, force the gate open during reset with `active_mode | reset`; this affects only the gate-enable input, never the clock net itself.
- Connect `GCLK` to the `SU_TAIL.clock` input.
- This must clock every tail register, including the depth-one `DelayBuffer`.
- Keep `tail_di_en`, tail inputs, and top-level output muxes unchanged.
- Never model the synthesized clock as `clock & enable`, a ternary clock, or a generic mux.

## Correctness basis

- **Mode 64:** Tail outputs are unselected, so freezing all tail sequential state cannot affect FFT data, `do_en`, or the exact 71-cycle latency.
- **Mode 128:** `active_mode` remains asserted for the transaction, passing every source-clock edge and preserving the 137-cycle pipeline exactly.
- **Reset:** The existing reset semantics must remain intact. If reset is synchronous, opening the gate during reset ensures all resettable tail state receives the required edge.
- **Continuous frames:** The gate remains enabled throughout mode-128 input, fill, output, drain, and back-to-back frames.
- **Arithmetic:** No arithmetic path is modified.

## Expected value

The tail contains roughly 67 clocked bits, so the likely mode-64 reduction is modest, approximately `0.1–0.3 mW`. Nevertheless, it has a plausible chance of beating the low-power archive point’s `p64 = 39.81859 mW` while adding little area and only one gate’s mode-128 overhead. It is substantially less disruptive than the six-bank experiment that reached `311,415 µm²`, increased `p128` to `42.07478 mW`, and failed timing.

## Mandatory validation

1. Exactly one `sky130_fd_sc_hd__dlclkp_1` survives synthesis.
2. All tail sequential clock pins descend from its `GCLK`.
3. No combinational logic directly drives a clock pin.
4. Directed, randomized, transition, and continuous-frame tests remain bit-exact.
5. First-valid latency remains exactly 71/137 cycles.
6. Mapped GLS passes.
7. Setup, hold, clock-gating, and applicable reset checks all pass with TNS 0.
8. DRC remains zero and area remains below `339,908 µm²`.
9. Result assembly produces authoritative JSON before any Pareto decision.
10. Measure both modes; reject if mode-128 overhead outweighs the mode-64 benefit.

No files were edited.