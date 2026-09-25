# PEWeaver shared 64/128-point FFT architecture specification

Status: architecture specification for the next experiment (2026-08-30).
This document defines the comparison, contracts, and falsifiable candidates; it
does not implement RTL and does not claim a sharing result.

## 1. Research question and claim boundary

The experiment asks whether the 64-point and 128-point `r22sdf` streaming FFT
proxies can share a physical PE when the top-level workloads are mutually
exclusive, while preserving the exact fixed-point stream contract and meeting
the same throughput target. The intended claim is narrower than “an SDF FFT is
shareable”: a particular generated implementation passes the stated gates and
has a measured Pareto advantage under matched open-PDK workloads.

These are HALO-inspired proxies, not HALO RTL, a reproduction of a published
HALO process result, or a neural-decoding validation. The authoritative
references are:

- `third_party/r22sdf/FFT64.v` and `FFT128.v`, pinned at revision
  `f7dca6e548e1370b69a09382d30609ee14ba4a57`;
- `fft64_oracle.py` and `fft128_oracle.py`, independent arithmetic/dataflow
  models; and
- the directed fixtures and manifests under
  `benchmarks/halo_fft64_reference/` and
  `benchmarks/halo_fft128_reference/`.

The current `physical/rtl/peweaver_shared_fft.v` is retained as a negative
control. Its recorded RTL run (`physical/results/logs/verilator_rtl_shared_run.log`)
reports `0/64`, `0/64`, `0/128`, and `0/128` valid outputs for the four checked
frames. It must not be presented as a candidate result or repaired silently
into the headline comparison.

## 2. Evidence classification

| Item | Status | Meaning |
| --- | --- | --- |
| Pinned FFT64/FFT128 interfaces, stage structure, 16-bit literals, and source comments | Proven by source inspection | Reference facts, subject to the fixture regressions. |
| FFT64 independent oracle reproduces both frozen vector sets | Proven by the existing oracle/regression record | Numerical cross-check, not a formal proof. |
| FFT128 independent oracle and directed fixture | Proven as a reference fixture by its recorded regression | Full arithmetic is still not formally proved. |
| 71/137-cycle first-valid latency and N consecutive output-valid cycles | Proven for the pinned references by the directed contracts | Candidate must preserve these cycles for a like-for-like result. |
| Separate-core baseline is the fair physical comparison | Required by `PHYSICAL_PPA_PLAN.md` and this specification | A sum of standalone reports is only a sanity estimate; the combined top must be measured. |
| Dynamic max-depth/tap-mux SDF sharing is unsafe in its current form | Proven negative for the checked RTL: no valid outputs | This rejects the implementation, not every possible shared FFT. |
| Banked-state stage sharing can preserve SDF schedules | Inferred from the topology and mutual-exclusion contract | Requires a new RTL, formal control proof, and full differential simulation. |
| MDC/feed-forward and memory-iterative alternatives | Experimental | Their area, timing, and throughput are unknown until implemented and measured. |

## 3. Reference datapaths

The reference cores are single-clock, radix-2^2 single-path delay-feedback
streams. A stage has two radix-2 butterflies, delay feedback, a registered
twiddle lookup, and a registered complex-multiplier/bypass path.

| Mode | Stages | SDF parameters | Final stage | Frame | First `do_en` | Output stream |
| --- | --- | --- | --- | ---: | ---: | --- |
| 64 | 3 `SdfUnit` stages | `(N,M)=(64,64),(64,16),(64,4)` | none; last `SdfUnit` has `M=4` | 64 | 71 | 64 consecutive samples, bit-reversed emission order |
| 128 | 3 `SdfUnit` stages | `(128,128),(128,32),(128,8)` | `SdfUnit2`, radix-2, depth 1 | 128 | 137 | 128 consecutive samples, bit-reversed emission order |

Input sample `k` is presented for one clock edge, with `di_en=1`, in natural
order. The source fixtures use no `ready` or backpressure. A legal steady-state
stream has exactly N consecutive accepted samples per frame and can start the
next same-mode frame according to the reference streaming schedule. Output
sample `k` corresponds to natural bin `bitrev(log2(N), k)`.

The first output-valid cycle is counted from the edge that accepts input sample
zero: 71 for 64 and 137 for 128. `do_en` remains high for exactly N cycles and
then returns low. A candidate with an added or removed pipeline cycle is a
different contract and is not a like-for-like PPA winner unless a separately
registered latency experiment is declared before measurement.

## 4. Fixed-point and arithmetic contract

All ports and stored words are raw unsigned 16-bit two's-complement words whose
interpretation is signed Q1.15. The implementation must preserve the following
semantics for every 16-bit input word, including corner values; “normalized
input” is not an assumption that may be added to make a proof pass.

1. A butterfly computes signed 17-bit add/sub results and stores
   `(sum + RH) >>> 1`, where `>>>` is arithmetic right shift (floor for a
   negative value). The first butterfly in every `SdfUnit` uses `RH=0`; the
   second uses `RH=1`. `SdfUnit2` uses `RH=0`.
2. A complex multiply forms exact signed 16x16 products, arithmetic-shifts
   each product by 15 with no rounding bias, then performs the real
   subtraction and imaginary addition modulo 2^16. There is no saturation.
3. The `-j` path is `(re, im) -> (im, -re mod 2^16)`.
4. Twiddles are the literal Q1.15 values in the pinned tables, not freshly
   rounded floating-point values. A legal address zero bypasses multiplication
   as in `Multiply.v`; it is represented as a zero literal in the upstream
   table for waveform convenience. For 64 mode, the equivalent 128-table
   address is `2*k` for the selected legal twiddle index.
5. The upstream tables contain deliberate `16'hxxxx` entries at addresses that
   R2^2SDF never selects. The fixture runs with Verilator's documented two-state
   policy (`--x-assign 0 --x-initial 0`). A candidate must either implement all
   legal addresses with the exact literals and prove illegal addresses
   unreachable, or fail closed on an illegal address; it may not use an X or an
   arbitrary replacement to mask an addressing bug.

The total scaling is 1/N: six radix-2 halvings for 64 and seven for 128. No
extra normalization, saturation, rounding mode, or output reordering is
permitted at the shared wrapper boundary.

## 5. Fair combined no-sharing baseline

The baseline is one top-level wrapper containing both original reference cores:

```text
mode, di_en, di_re, di_im
          |
          +--> FFT64 reference replica --+
          |                               +--> output mux --> do_en/do_re/do_im
          +--> FFT128 reference replica -+
```

The top-level mode is mutually exclusive. The wrapper sends `di_en=0` to the
inactive replica and may clock-gate its sequential state. Both replicas,
clock-gating enables, reset synchronizer, mode/output mux, and I/O assumptions
are included in the synthesized baseline. Clock-gating or operand-isolation
logic added to make the inactive replica quiet must also be included in the
shared candidate's transition-control accounting. A physically ideal
“remove the inactive core” baseline is not fair and is reported only as a
sensitivity bound if useful.

The baseline must be synthesized and, where the physical tier is available,
placed/routed as this combined top with the same sky130A/sky130_fd_sc_hd flow,
10 ns clock, I/O constraints, reset convention, uncertainty, activity source,
and report schema used by the frozen FFT64 and FFT128 studies. Standalone
figures are useful checks: the current records report routed areas of
164,408 um2 (64) and 260,477 um2 (128), but their sum (424,885 um2) is not the
combined-baseline result because the top-level mux and constraints must be
measured once.

The baseline's mode protocol is intentionally identical to the candidate's:
mode is set before a frame, held through that frame, and a mode transition
requires reset and drain. This controls for wrapper latency and transition
energy rather than allowing the baseline a more permissive interface.

## 6. Candidate contract at the shared wrapper

The first full-rate candidate uses the reference-compatible ports:

```verilog
clock, reset, mode, di_en, di_re[15:0], di_im[15:0]
                    -> do_en, do_re[15:0], do_im[15:0]
```

There is no hidden `ready`, frame length, or client identity signal. The
following rules are part of the contract and must be checked at the boundary.

### Mode and acceptance

- `mode` is sampled/latches into `mode_active` only while the PE is idle. It
  must remain constant from the first accepted sample through the last valid
  output and drain. A change while busy is illegal and must not redirect any
  in-flight token.
- The first `di_en` after idle starts a frame. Exactly 64 or 128 consecutive
  `di_en` cycles, according to `mode_active`, are required. Data is ignored
  whenever `di_en=0` outside an accepted frame.
- There is no input stall. For a same-mode sustained stream, the candidate must
  accept one sample per cycle and sustain one frame every 64 or 128 input
  cycles, respectively. This is the headline throughput target.
- If `di_en` drops before the required N samples, the partial frame is
  aborted, no `do_en` may be emitted for it, and the PE remains unarmed until
  reset. The candidate may expose an internal diagnostic, but adding a new
  externally visible recovery protocol changes the benchmark contract.

### Reset, drain, and state isolation

- `reset` is active-high asynchronous assertion. It clears all control,
  validity, counters, mode ownership, and output-valid state immediately.
  The physical wrapper uses the established asynchronous-assertion,
  synchronous-deassertion two-flop synchronizer.
- No input is accepted while reset is asserted. Outputs are invalid and
  `do_en=0` throughout reset and until a new legal frame is accepted.
- A mode change requires: finish or explicitly abort the current frame; assert
  reset; hold reset long enough for the synchronized release; then provide the
  required idle drain before the next frame. The reference fixtures use 16
  reset cycles plus 96 idle cycles for 64 and 256 idle cycles for 128; the
  shared campaign uses the maximum 256-cycle drain for a mode transition.
- The shared PE must not expose a result from the previous mode after reset.
  Data memories need not be physically reset if valid bits/epoch tags prove
  that every read is initialized before use. A mode bank may not retain a
  frame merely because the design later returns to that mode.
- A legal same-mode back-to-back stream may avoid reset, but output-valid
  pulses must remain ordered, contiguous per frame, and attributable to the
  accepted input frame. The verification schedule must include both this case
  and reset-separated transitions.

### Latency and output

For input sample zero accepted at edge 1 after reset/drain:

- 64 mode: first `do_en` exactly at edge 71, high for edges 71–134;
- 128 mode: first `do_en` exactly at edge 137, high for edges 137–264.

The output words at those cycles must match the corresponding reference stream
bit-for-bit. `do_re` and `do_im` while `do_en=0` are don't-care at the interface,
but deterministic zero is preferred in wrappers and must not be used as a
validity indication.

## 7. Candidate architecture choices

### C0 — dynamic max-depth SDF with mode-muxed taps (negative control)

This is the shape attempted in `physical/rtl/peweaver_shared_fft.v`: maximum
delay arrays, run-time tap selection, mode-muxed counters and twiddle paths,
and a 128-only final stage. It is attractive on paper because it resembles
parameter sharing, but an SDF delay is feedback state, not merely a FIFO whose
read depth can change.

The checked instance produces no valid outputs in its recorded run and has
compile width/driver warnings. The key research conclusion is negative:
changing taps, modulo counter periods, `-j` phases, multiplier enable, and
valid pipelines at run time without a mode-latched schedule does not establish
equivalence. Keep it as an unsafe/rejected candidate and do not use its area
estimate as evidence.

### C1 — mode-latched banked-state shared stage shell (recommended first)

Use one physical stage shell for each corresponding pipeline position: three
shared R2^2 stages plus a dedicated fourth radix-2 shell required only by 128
mode. Each shell contains the arithmetic/register timing needed by both modes,
but its state is selected from a mode-specific bank under a static
`mode_active` for the entire transaction. The controller holds independent
stage descriptors/counters for 64 and 128 and selects one descriptor only at
idle; it does not mux a live counter's modulus or a live delay tap each cycle.

For each shared stage, the bank descriptor fixes the following active delay
depths and twiddle schedule (the two depths are the first and second radix-2
feedback buffers inside that stage):

| Shared stage | 64 mode: `(N,M)`, depths | 128 mode: `(N,M)`, depths | Twiddle |
| --- | --- | --- | --- |
| 1 | `(64,64)`, 32 and 16 | `(128,128)`, 64 and 32 | 64 legal address mapped to 128 literal at `2*k`; 128 legal address |
| 2 | `(64,16)`, 8 and 4 | `(128,32)`, 16 and 8 | 64 legal address mapped to 128 literal at `2*k`; 128 legal address |
| 3 | `(64,4)`, 2 and 1 | `(128,8)`, 4 and 2 | no 64 multiply; 128 legal address |

The final 128 radix-2 stage has depth 1 and no multiply. Physical implementation may use SRAM,
register files, or generated shift storage, but a read/write bank must have a
defined one-cycle timing matching the reference. The selected bank and
address schedule are static during a frame. The arithmetic shell is shared;
the memories, valid/epoch bits, and any state required to isolate a mode are
not assumed shareable merely because their maximum depth matches.

This is the smallest credible full-rate architecture because it preserves the
reference's pipeline occupancy and makes the hard part—state isolation—an
explicit design object. Expected benefits are fewer duplicated butterflies,
multiplier structures, and twiddle ROMs at the cost of bank muxing, mode
decode, and the unavoidable 128-only final stage. The area and timing outcome
is experimental.

### C2 — feed-forward/MDC shared pipeline

Replace feedback SDF storage with a feed-forward or multi-path delay-commutator
(MDC) pipeline. Shared radix-2^2 lanes and a common twiddle table perform both
transforms; a mode-latched route/commutator schedule inserts the 64- versus
128-point delays. This can make state ownership easier to reason about and can
map delay lines to compact memories, but switch networks and extra lanes may
erase the area benefit. It is a separate topology, not a cleanup of C0.

The first MDC prototype must use a cycle-accurate schedule table generated
from the reference oracle. Runtime route changes are forbidden while tokens
occupy the pipeline. Compare at the same one-sample-per-cycle throughput and
71/137-cycle external latency; a relaxed-latency MDC result is reported as a
different experiment.

### C3 — memory-based iterative FFT

Use one shared butterfly/complex multiplier and a mode-sized SRAM with an
iterative radix-2/4 controller. This maximizes arithmetic reuse and is useful
as a lower-bound/area study, but the natural operation count is
`N*log2(N)/2` butterflies plus twiddle work, so one arithmetic lane generally
cannot meet the reference's one-sample-per-cycle stream. A folded design may
be accepted only if it provisions enough lanes and schedule bandwidth to meet
the full-rate contract.

If a deliberately relaxed-throughput version is explored, publish its exact
frame latency, input buffering, output rate, SRAM ports, and duty-cycle model
and do not compare its area/power directly to the full-rate baseline.

### C4 — conservative mode-specific reuse

Retain mode-specific stateful datapaths but share only objects that cannot be
active concurrently: the twiddle literal store, reset/transition controller,
input/output shell, or a time-multiplexed arithmetic unit proven idle between
stage uses. This is expected to be safe but may deliver a small PPA delta. It
is an important control: a failed C1/C2 does not justify claiming that all
reuse is impossible, and a small safe win is preferable to an unsafe large
one.

## 8. Verification ladder

Every candidate is fail-closed. A timeout, unknown, missing trace, illegal
assumption, or tool error is rejection, not a pass.

1. **Contract model.** Validate mode schedule, N-consecutive input length,
   illegal-gap handling, reset/drain preconditions, output pulse shape, and
   exact first-valid cycles in a transaction-level reference model.
2. **Arithmetic unit differential.** Compare butterfly, `-j`, multiplier,
   twiddle address mapping, and modulo/floor behavior against the independent
   Python oracles on exhaustive small-width/corner cases and randomized 16-bit
   words.
3. **Reduced formal datapath.** Prove the mode controller, bank ownership,
   reset, abort, no-stale-output, and valid/latency properties on reduced
   parameter instances (for example N=8/16) with the same stage generator.
   Prove that illegal mode changes and simultaneous client requests cannot be
   accepted. This is a control/structure proof, not a full 128-point arithmetic
   proof.
4. **Full-size differential simulation.** Run the complete 64 and 128 cores
   against both independent oracles and frozen vectors. Include zero, impulse,
   alternating-sign, maximum/minimum, random, and multi-frame inputs; natural
   ordering; reset-separated and same-mode streaming; mid-frame abort; mode
   switch; and long idle drain.
5. **Transaction miter.** Compare candidate and the corresponding unmerged
   baseline independently in each mode with exact cycle alignment. Compare
   valid pulses as well as data, and assert no candidate output is attributed
   to the wrong mode or frame. No full-size formal-equivalence claim is made
   unless the proof actually completes.
6. **Physical gate check.** Synthesize both combined tops under identical
   constraints, run matched gate-level functional simulation, then timing and
   activity-based power. A timing failure or missing activity annotation
   rejects the PPA comparison even if RTL simulation passed.

The mandatory unsafe case is a schedule that requests concurrent use of one
shared stateful PE by two logical clients (or changes mode while an earlier
frame is in flight). The candidate must reject or block that schedule; a
counterexample showing overlap is not permission to add an unstated mutual
exclusion assumption.

## 9. Matched workloads and activity

Use the existing frozen clock and physical methodology: sky130A,
`sky130_fd_sc_hd`, the recorded tool revisions, 10 ns clock, identical I/O
delays/driving cells/loads, propagated-clock uncertainty, and the same reset
synchronizer pattern. Generate activity from the mapped netlist with the same
functional gate models and verify golden outputs in the gate-level run.

Use these pre-registered windows for both combined baseline and candidate:

- **64 window:** asynchronous reset assertion, 16 reset cycles, 96 idle/drain
  cycles, one input4 frame, 96 idle cycles, then a three-frame continuous
  burst (input4, input5, input4) with no gap inside the burst, and final idle;
- **128 window:** the corresponding 128-sample frames and 256-cycle drain;
- **transition window:** a 64 frame, complete output drain, reset, maximum
  drain, a 128 frame, complete drain, then the reverse transition. The mode
  switch energy and cycles are reported separately as well as included in the
  full scenario.

The comparison reports each mode separately, equal-mode weighting, and a
duty-cycle sweep `p64` from 0 to 1. For a mixture, report

```text
E_mix(p64) = p64 * E64 + (1-p64) * E128 + transition_energy_rate
```

with the transition rate and frame duty cycle stated. No single favorable
workload probability may be used as the sole result. Input/output vector
identity, trace hashes, frame counts, reset/drain cycles, and mode order are
part of the result record.

## 10. PPA acceptance criteria

Correctness, schedule, latency, throughput, and timing are hard gates before
PPA is considered. The candidate must have zero unsafe accepts, exact valid
pulses, exact reference outputs in both modes, 71/137 first-valid cycles,
one-sample-per-cycle input acceptance, and no worse than zero WNS under the
common 10 ns constraints. DRC and activity annotation must pass in the
physical tier.

Pre-register the following interpretation of a “winner” before looking at
candidate measurements:

- **Area winner:** at least 10% lower routed area than the combined baseline,
  with each mode's active energy no more than 10% above baseline and no
  transition/latency violation.
- **Energy winner:** at least 10% lower equal-weighted active energy than the
  combined baseline, with routed area no more than 5% higher and no timing or
  leakage-contract violation.
- **Pareto point:** passes all hard gates and improves one reported metric but
  misses both headline thresholds. Retain and report it; do not call it a
  headline PPA win.
- **Valid rejection:** functionally correct but larger, slower, more active,
  or unprofitable at the declared duty cycle. This is a useful result and is
  not repaired by changing the workload after measurement.

Report routed and synthesis area, WNS/TNS, leakage, internal/switching/total
power, energy per frame, mode-transition cycles/energy, and physical PE count.
The current standalone finite-window numbers—64 at 23.314 mW and 20.400 nJ
per FFT, 128 at 41.040 mW and 71.205 nJ per FFT—include pipeline fill/drain
over each three-frame transaction and are orientation only; the combined top
and candidate must be measured from matched traces.

## 11. Smallest viable implementation sequence

1. Freeze the combined dual-replica baseline wrapper and record its exact
   latency, pulse, reset, and mode-transition behavior. Do not use standalone
   core sums as the final baseline.
2. Build a parameterized stage specification (depths, counter periods,
   twiddle map, registered enables) and a cycle-level model for one reduced
   shared stage. Establish the C1 state-bank invariant: mode selection is
   static while busy, and every state read/write belongs to the active epoch.
3. Implement only the reduced C1 shell (N=8/16), with separate mode banks,
   static descriptors, and a shared butterfly/multiplier. Prove reset,
   abort, mode exclusion, no-stale-output, and transaction equivalence.
4. Scale the same shell to full 64/128 with three shared stages and the
   128-only final radix-2 stage. Preserve the reference register schedule;
   do not optimize latency during the first correctness milestone.
5. Run full-size oracle/directed/differential campaigns, including the
   mandatory concurrent-use negative. Reject on any data, valid, state, or
   latency discrepancy. This stage remains functional evidence, not a full
   arithmetic formal claim.
6. Synthesize the candidate and combined baseline with identical constraints,
   then run matched gate-level activity and physical measurement. Publish
   hard-gate status before PPA numbers and apply the pre-registered thresholds.
7. Only after C1 has a clean result, prototype C2 MDC or C3 iterative memory
   reuse as separately named experiments. If C1 is correct but unprofitable,
   retain that rejection and let other PEWeaver families carry any aggregate
   improvement.

The minimum credible result is therefore a safe, cycle-accurate C1 (or a
clearly labelled C4 fallback), a combined no-sharing measurement, and an
auditable rejection or Pareto decision. No architecture is accepted merely
because synthesis reports fewer cells; state isolation and matched workload
evidence are part of the design.
