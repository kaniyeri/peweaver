## Optimization objective

Preserve the accepted architecture’s state sequencing, pipeline registers, and output-valid timing. Recover power by preventing activity in logic whose results are either mode-exclusive or architecturally unobservable. Do **not** add/remove pipeline stages or retime arithmetic.

## 1. Locate the dominant switching cones

Use post-route SAIF/VCD activity for separate workloads:

- Continuous 64-point frames.
- Continuous 128-point frames.
- One frame followed by a long idle interval.
- Reset and mode-transition sequences.

Rank instances by internal and clock power. The likely priorities are:

1. **128-only final radix-2 stage**
   - The 128-point path has six radix-2 stages in the three `SdfUnit`s plus the final `SdfUnit2`.
   - The 64-point path ends after six stages and must not exercise the extra radix-2 stage.
   - In mode 64, clock/data activity in this stage is entirely wasted.

2. **Third shared stage’s multiplier**
   - In 64-point operation, the last `SdfUnit` has `M=4`; its twiddle address is effectively zero and multiplication is bypassed.
   - In 128-point operation, the corresponding `M=8` stage needs nonzero twiddles.
   - Any stage-3 multiplier, twiddle register, or multiplier-control activity observed during mode 64 is a high-value target.

3. **Complex multipliers in zero-twiddle slots**
   - Each complex multiplier contains four signed 16×16 multipliers.
   - When `tw_addr==0`, the architectural result uses the bypass path, but the multiplier cone can still toggle from changing data or unconstrained/X operands.

4. **Delay storage**
   - Literal `DelayBuffer` shift banks clock every word on every cycle. Their clock-pin and internal shifting power can dominate.
   - Check whether the parent already converted these to circular storage. If not, they are the largest structural opportunity.

5. **Unconditionally clocked datapath registers**
   - Butterfly result registers, multiplier result registers, twiddle output registers, and mode-mux branch registers may toggle while their valid is low.
   - Control counters are comparatively small and should not be the first clock-gating target.

## 2. Operand isolation

### A. Isolate mode-exclusive multiplier logic

For the shared third-stage multiplier, derive an activity condition from the **latched mode**, stage validity, and aligned twiddle decision:

```verilog
mul_active = mode_q && stage3_mul_valid && (tw_addr != 0);
```

When `mul_active==0`, drive stable constants into the combinational multiplier:

```verilog
mul_a_re = mul_active ? active_a_re : 16'sd0;
mul_a_im = mul_active ? active_a_im : 16'sd0;
mul_b_re = mul_active ? tw_re      : 16'sd0;
mul_b_im = mul_active ? tw_im      : 16'sd0;
```

The bypass/output selection must remain exactly as in the accepted design. This changes only an unselected cone and adds no register or latency.

Do not rely on the reference’s `{WIDTH{1'bx}}` assignments for isolation. Synthesis may treat them as don’t-cares and allow substantial physical toggling. Explicit stable values are preferable for power and deterministic gate-level behavior.

### B. Isolate all zero-address multiplication slots

For each active `SdfUnit`, clamp all four multiplier operands whenever the address-zero bypass is selected. Keep the existing registered bypass timing unchanged.

Important alignment rule: use the same delayed/address-aligned condition that currently selects the multiplier result. Do not recompute a condition from a counter at a different pipeline phase.

### C. Hold inactive branch registers

Where the merged implementation has separate mode-specific branch registers:

- Update the 64-specific bank only while a 64-point token is present.
- Update the 128-specific bank only while a 128-point token is present.
- Hold both banks during idle/drain phases in which their data cannot later be consumed.

Use `mode_q`, not the external `mode` input. Operand isolation must not allow an asynchronous mode-pin transition to disturb an active datapath.

### D. Suppress invalid-cycle arithmetic

Hold or clamp butterfly and `-j` path inputs only when the corresponding result is not needed for:

- Feedback-buffer writes,
- Future butterfly operands,
- Pipeline drain,
- A valid downstream sample.

Do not equate “not externally valid” with “inactive”; SDF stages continue internal feedback work before and after their external valid window.

## 3. Integrated clock gating

Use only characterized `sky130_fd_sc_hd__dlclkp_4` cells, preferably through a single wrapper with explicit `CLK`, `GATE`, and `GCLK` connections. Apply `dont_touch`/clock-gating preservation as required by the synthesis flow. Never create `clock & enable` logic.

### A. Gate the complete 128-only tail

Create one coarse gated clock for the final radix-2 stage:

```text
tail128_clock_enable = mode_q && tail128_live
```

Place on this gated clock:

- Tail delay register/buffer.
- Tail butterfly data registers.
- Tail datapath-valid pipeline registers if their reset behavior remains safe.

Keep the global output-valid/reset controller on the root clock initially. In mode 64, `tail128_clock_enable` must remain low for the entire run.

`tail128_live` must span the full period from before the first required tail clock edge through the edge that captures the last 128-point result. It should be derived from the accepted valid pipeline, not from a new independent latency counter.

### B. Gate mode-64-unused stage-3 twiddle/multiplier state

If the parent has distinct multiplier/twiddle registers for the mode-dependent last shared stage, clock them only when:

```text
mode_q && stage3_live
```

Use operand isolation for individual zero-address slots. Avoid toggling a large ICG on and off for every twiddle-zero cycle unless power analysis proves that it wins after accounting for gate overhead and clock-enable activity.

### C. Gate delay and datapath banks during true idle

For each stage, form a coarse `stage_live` token covering:

1. Initial delay-buffer filling.
2. Butterfly/feedback processing.
3. Pipeline drain.
4. Capture of the final stage output.

Gate large delay banks and datapath register bundles only when `stage_live==0`. During continuous same-mode streaming, the gate may correctly remain enabled; the primary streaming savings then come from mode-exclusive shutdown and multiplier operand isolation.

Do not gate a delay buffer using only its input `di_en`. A stage can still need clock edges after its input-valid interval to emit or drain buffered samples.

### D. Preserve gate-opening timing

`dlclkp_4` uses a level-sensitive latch internally. The gate enable must be stable early enough to pass the first required rising edge.

For internally generated enables:

- Generate or predecode the enable on the root clock at least one phase/cycle before the first gated edge, or
- Use an already-active upstream valid signal that is available during the preceding low phase.

Explicitly verify the first and last passed clock edges. An ICG is cycle-transparent only if its enable is timed correctly.

### E. Reset handling

- Keep asynchronous reset connected directly to every resettable control/valid flop, including flops behind an ICG.
- Do not depend on a gated clock edge to clear state.
- Do not OR asynchronous reset into a clock or construct a reset-dependent combinational clock gate.
- Nonreset datapath registers may retain stale values only if reset clears all valid/busy state and the data is overwritten before reuse.

After reset, `do_en` must remain low until the first new frame reaches the exact contractual latency.

## 4. Delay-buffer optimization

If the parent still implements long delays as full shift registers, consider a second, higher-risk optimization: replace each shift bank with circular storage and a pointer so only one complex word is written per active cycle.

Requirements:

- Preserve the exact delay of `DEPTH` clock edges.
- Preserve old-data/new-data behavior on wraparound.
- Advance the pointer on every cycle in which the original delay line would have shifted, including internal drain cycles.
- Retain 16-bit modular data unchanged.
- Infer or instantiate only storage structures supported reliably by the sky130 flow.

This can sharply reduce data and clock switching, but it requires full equivalence and mapped-netlist testing. Apply mode-exclusive gating and multiplier isolation first because they are lower risk.

## 5. Latency and arithmetic safeguards

The following must remain invariant:

- No new register in any active data, twiddle, bypass, or valid path.
- No removal of the registered bypass cycle around a multiplier.
- First `do_en` remains exactly cycle 71 or 137 from sample 0.
- Output-valid width remains exactly 64 or 128 cycles.
- Butterfly RH sequence remains `0,1` per `SdfUnit` and `0` for `SdfUnit2`.
- Signed shifts, 16-bit wraparound, `-j` negation, and twiddle literals remain unchanged.
- Mode gating uses the accepted idle-latched `mode_q`.
- Continuous frames must not experience a gate close/reopen bubble.

## 6. Recommended implementation order

1. Clamp multiplier operands during address-zero bypass.
2. Completely isolate the stage-3 multiplier/twiddle cone in mode 64.
3. Gate the 128-only tail with one `dlclkp_4`.
4. Hold invalid-cycle butterfly/multiplier output registers where feedback analysis proves them dead.
5. Add coarse stage-idle clock gates to large register/delay banks.
6. Consider circular delay storage only if shift-register power remains dominant.

After every step, run bit-exact RTL tests, mapped-netlist simulation, STA/clock-gating checks, DRC, and post-route power using identical activity. Compare 64- and 128-mode power separately so savings in the mode-exclusive cones are visible.