## Atomic hypothesis

**Clock-gate only the mode-128-only upper halves of the six shared delay banks using characterized `sky130_fd_sc_hd__dlclkp` cells.**

Do not gate the radix-2 tail or modify any other state in this candidate.

### Target

Single candidate file:

`/work/peweaver/runs/ps-fft-6/best/peweaver_shared_fft.v`

Relevant implementation:

- Six `SharedDelayBuffer` instances: approximately lines 203–214 and 275–286
- `SharedDelayBuffer`: approximately lines 403–436

## Rationale

Every delay bank has `DEPTH1 = 2*DEPTH0`. Mode 64 observes only `buf[DEPTH0-1]`, but the incumbent shifts the entire `DEPTH1` bank every cycle. Because shifting runs from low indices toward high indices, the upper half cannot influence the lower half.

The mode-128-only storage is:

| Bank | Mode-128-only words | Clocked bits |
|---|---:|---:|
| 64/32 | 32 complex | 1,024 |
| 32/16 | 16 complex | 512 |
| 16/8 | 8 complex | 256 |
| 8/4 | 4 complex | 128 |
| 4/2 | 2 complex | 64 |
| 2/1 | 1 complex | 32 |
| **Total** | **63 complex** | **2,016 bits** |

Thus this hypothesis removes mode-64 clock activity from approximately 2,016 flop clock pins. That directly attacks the dominant measured region: clock-root power is 19.66 mW, or 49.1% of total streaming power.

It is likely a materially larger opportunity than gating the roughly 67 bits of tail-stage state alone.

## Intended structural replacement

Split `SharedDelayBuffer` into:

1. An always-clocked lower array of `DEPTH0` complex words.
2. A gated upper array of `DEPTH1-DEPTH0` complex words.
3. One local characterized clock gate per buffer, enabled by the existing per-stage `mode` input—which is already driven by `active_mode`.

Equivalent behavior should be:

- Lower bank shifts on every original clock edge.
- Upper bank shifts only when mode 128 is active.
- On a mode-128 edge, upper word zero captures the **old** lower terminal word.
- Mode 64 output remains the lower terminal word.
- Mode 128 output becomes the upper terminal word.

Using separate nonblocking processes preserves the required old-value transfer across the lower/upper boundary. No additional staging register may be introduced.

## Correctness argument

### Mode 64

The upper half:

- Is never selected as output.
- Does not feed any lower-half register.
- Does not influence stage control, counters, valid timing, twiddles, or arithmetic.

Freezing it therefore cannot affect:

- FFT values
- 71-cycle latency
- `do_en`
- Frame boundaries
- Continuous-frame behavior

### Mode 128

`active_mode` is high before useful traffic under the reset-separated mode protocol. The integrated latch-based gate consequently supplies one gated rising edge for every source-clock rising edge. Both lower and upper shifts remain cycle-equivalent to the incumbent, preserving the 137-cycle latency and exact arithmetic stream.

### Mode transitions and reset

The delay-bank contents are not reset in the incumbent; control and valid state prevent stale data from becoming valid output. Retaining stale upper-bank contents during mode 64 is therefore acceptable. A subsequent mode-128 transaction is reset-separated and flushes the delay path before valid output.

Do not add reset logic to these arrays, and do not alter any incumbent reset sensitivity.

## Physical expectations

- Add six `sky130_fd_sc_hd__dlclkp_*` cells.
- Remove approximately 2,016 flop loads from the active mode-64 clock tree.
- Slightly increase mode-128 power from clock-gate internal capacitance.
- Negligible area increase relative to the approximately 52,938 µm² margin beneath the hard area ceiling of 339,908 µm².
- Potentially meaningful reductions in `p64` and `e64`; `p128` and `e128` must be checked for gate overhead.

Six local gates are preferable to one weak gate driving all 2,016 bits because they create manageable gated subtrees and reduce extreme clock fanout.

## Main implementation risk

The RTL regression apparently compiles the candidate without automatically including the PDK functional model. The replacement therefore needs a simulation-safe way to resolve the primitive while ensuring synthesis retains the real characterized `dlclkp` instance.

The important checks are:

- No behavioral `clock & enable`, ternary clock, or generic combinational clock gate reaches synthesis.
- No unresolved black box appears in RTL simulation.
- No duplicate primitive definition conflicts with PDK models during GLS.
- The mapped netlist contains exactly the intended characterized clock gates.
- CTS and propagated-clock STA recognize all gated-clock endpoints.

## Acceptance checks

1. Bit-exact directed and randomized tests in both modes.
2. Exact first-valid latency: 71 and 137 cycles.
3. Continuous three-frame streams.
4. Reset-separated 64→128 and 128→64 transitions.
5. Return to mode 128 after a long mode-64 run.
6. Mapped GLS with the real PDK clock-gate model.
7. Exactly six characterized clock-gate instances after mapping.
8. No generic logic driving clock pins.
9. TNS 0, DRC 0, and area below 339,908 µm².
10. Separate power measurements confirming mode-64 savings and quantifying mode-128 overhead.

No files were edited.