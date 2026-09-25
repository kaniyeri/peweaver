# PEWeaver DWT ChiaMerge campaign specification

Status: DRAFT FOR INDEPENDENT REVIEW -- NOT PREREGISTERED

This document defines the proposed DWT campaign before benchmark RTL, hidden
stimulus, or model outcomes are frozen. No model-driven campaign may start
until the launch checklist in Section 13 is complete and a machine-readable
preregistration binds the final source and evaluator hashes.

## 1. Purpose and claim boundary

The experiment asks whether the unchanged domain-neutral `ChiaMerge`
composition can produce one cycle-exact, independently stateful implementation
of two mutually exclusive multirate DWT contexts while reducing a frozen
synthesis proxy relative to two explicitly unfolded references.

This is a controlled 1-D streaming Q15 db2 benchmark. It is not a novel DWT
algorithm, signal-quality study, JPEG-2000 implementation, mapped-area result,
physical-PPA result, exhaustive proof, clinical result, or comparison against a
best-known hand-optimized DWT architecture.

The allowed result language is limited to tested RTL and synthesized-netlist
agreement, normalized arithmetic structure, and unweighted generic Yosys cell
count. Generic cell count must never be called area.

## 2. Benchmark shape

The shared top module is `dwt_shared` with exactly these fixed-width ports:

```verilog
module dwt_shared (
    input  wire               clock,
    input  wire               reset,
    input  wire               ctx,
    input  wire               en,
    input  wire signed [15:0] x,
    output reg  signed [39:0] a_l1_lo,
    output reg  signed [39:0] a_l1_hi,
    output reg                a_l1_valid,
    output reg  signed [39:0] b_l1_lo,
    output reg  signed [39:0] b_l1_hi,
    output reg                b_l1_valid,
    output reg  signed [39:0] b_l2_lo,
    output reg  signed [39:0] b_l2_hi,
    output reg                b_l2_valid
);
```

- Context A (`ctx=0`) implements one db2 decomposition level.
- Context B (`ctx=1`) implements two db2 decomposition levels.
- Contexts have independent histories, phases, output registers, and valid
  state. Context B additionally has independent level-2 history, phase, and
  pending-work state.
- Only the active context accepts an input sample on an enabled edge. The
  inactive context holds all non-valid state.

## 3. Frozen arithmetic

The latest sample is tap zero. The pinned signed Q15 analysis coefficients are:

```text
LOW  H[0:3] = [ 15826,  27411,   7345,  -4240]
HIGH G[0:3] = [ -4240,  -7345,  27411, -15826]
```

For a latest-first signed 16-bit window `w[0:3]`, define:

```text
low40(w)  = modulo_2^40(sum(k=0..3, signed16(H[k]) * signed16(w[k])))
high40(w) = modulo_2^40(sum(k=0..3, signed16(G[k]) * signed16(w[k])))
```

Each multiplication is exact signed 16-by-16 to signed 32 bits. Each product is
sign-extended to 40 bits. The mathematical signed sum is reduced modulo 2^40;
there is no saturation or rounding. Addition order therefore cannot change the
defined 40-bit result.

Level 2 consumes a signed 16-bit truncation of a Context-B level-1 low result:

```text
q(v) = signed16(v[30:15])
```

This is a literal two's-complement bit slice equivalent to taking the low 16
bits after an arithmetic right shift by 15. It has no rounding or saturation;
discarded high bits do not affect the result.

## 4. Edge and sample semantics

All state changes occur on the rising edge of `clock`. Reset is synchronous and
active high.

At every rising edge:

1. If `reset=1`, all histories, sample counters/phases, pending work, output
   data registers, and valid registers for both contexts are set to zero.
2. Otherwise, all three valid outputs default to zero for the new cycle.
3. If `en=0`, no sample is accepted and all history, phase, pending-work, and
   output-data state holds. Valid outputs are strobes and remain zero; they are
   the only state that does not hold on a non-reset disabled edge.
4. If `en=1`, exactly one sample is accepted by the context selected by `ctx`.
   Every state element belonging to the inactive context holds, apart from its
   valid output being zero.

For each context separately, accepted samples are indexed from zero. Let
`x_c[n]` be the nth enabled sample accepted by context `c`; samples with a
negative index are zero. A legal context switch is one for which `ctx` changes
only on a rising edge with `reset=1` or `en=0`. Therefore, at every non-reset
rising edge with `en=1`, `ctx` must equal the value sampled at the immediately
preceding rising edge.

### 4.1 Context A level 1

After accepting `x_A[n]`, the latest-first level-1 window is:

```text
[x_A[n], x_A[n-1], x_A[n-2], x_A[n-3]]
```

If `n` is odd, `a_l1_lo` and `a_l1_hi` update on that edge from this window and
`a_l1_valid=1` for the following cycle. If `n` is even, the output data holds
and `a_l1_valid=0`. Thus the first valid pair follows acceptance of sample 1.

### 4.2 Context B level 1

Context B has the same latest-first level-1 rule and zero prehistory. If its
accepted-sample index `n` is odd, `b_l1_lo` and `b_l1_hi` update on that edge,
`b_l1_valid=1`, and `q(b_l1_lo_new)` is pushed into Context B's latest-first
level-2 history. The newly computed low value, not the prior output register,
is pushed.

Context-B level-1 pairs are indexed from zero as `m`. Pair `m` is produced at
accepted-sample index `n = 2m+1`. When `m` is odd (pairs 1, 3, 5, ...), one
level-2 job becomes pending. Pending state survives `en=0` and suspension in
Context A.

### 4.3 Context B level 2 and the folding schedule

A pending level-2 job is consumed on the next rising edge at which Context B
accepts a sample and no level-1 output is due. Under the legal cadence this is
the immediately following even-indexed Context-B sample. On that edge:

- the newly accepted input sample still enters Context B's level-1 history;
- the shared arithmetic slot evaluates the latest-first level-2 history, which
  at that point contains all previously pushed low values, the newest of which
  was pushed on the preceding odd-indexed edge;
- `b_l2_lo` and `b_l2_hi` update, `b_l2_valid=1`, and pending state clears;
- no Context-B level-1 output updates on that edge.

The first level-2 job is created at pair `m=1` (accepted-sample index 3) and is
consumed at index 4. Write `q0 = q(b_l1_lo produced at index 1)` and
`q1 = q(b_l1_lo produced at index 3)`. The first level-2 output uses the
latest-first window `[q1, q0, 0, 0]`: the two generated low values followed by
two zeros of prehistory. Subsequent level-2 results follow accepted-sample
indices 8, 12, and so on if Context B runs continuously. Enable gaps and
Context-A intervals suspend, but do not alter, these context-local indices or
pending work.

## 5. Frozen references and controls

The two independent reference tops are:

- `dwt_a`: one spatial db2 analysis bank implementing Context A.
- `dwt_b`: two spatial db2 analysis banks implementing Context B. Its second
  bank is scheduled to expose exactly the level-2 latency in Section 4.3 even
  though spatial hardware could calculate earlier.

The acceptance baseline is the sum of the references synthesized independently
with the frozen command and tool version. This is explicitly an **unfolded
spatial baseline**, not a best-known DWT implementation.

Three model-free controls must be frozen and evaluated before launch:

1. A naive wrapper instantiating both references must pass functional gates and
   fail the structural and generic-cell gates.
2. A model-free one-bank folded positive control must pass all gates with
   documented margin. Its result is a calibration/control, not a model outcome.
3. A shared-history cheater must pass syntax and fail the directed
   context-preservation test.

The release must report the independent-reference sum, operational naive
wrapper, model-free folded control, and every model candidate. The folded
control must be compared with an accepted candidate; beating the unfolded sum
alone is not evidence of superiority over an optimized implementation.
`control_results.json` must include the folded control's generic-cell reduction
margin as a percentage, not only pass/fail.

Pilot controls used to choose thresholds must be disclosed and excluded from
campaign outcomes. Positive-control RTL and hidden vectors must not be included
in model prompts or a model-writable checkout.

## 6. Six-gate acceptance ladder

All gates are ordered and fail closed. Infrastructure failure yields RETRY, not
semantic acceptance or rejection.

### Gate 1: integrity and lint

- Candidate file is exactly `dwt_shared.v` and contains `dwt_shared` with the
  exact interface in Section 2.
- Reject unexpected files and any protected-input hash change.
- Reject file/system I/O, `$readmem*`, DPI/PLI, testbench access, initial/final
  blocks, delays, force/release, and hierarchical references outside candidate
  helper modules.
- Elaborate the candidate with the frozen Yosys version.

### Gate 2: public randomized RTL oracle

- 1,502 cycles generated by a pure-Python oracle with seed `0xD17A5EED`.
- Include fixed and randomized resets, enable gaps, long context suspensions,
  phase-boundary switches, pending-level-2 suspension, and signed full-range
  samples.
- Compare all six 40-bit data outputs and all three valid outputs every cycle.
- Full first-mismatch feedback may be returned to the model.

### Gate 3: directed corners

Cover at least:

- exact low/high impulse responses and coefficient order for Context A and
  Context B level 1;
- Context B level-2 fill, steady cadence, drain, and exact first-valid cycle;
- zero, one, minus one, `16'h7fff`, and `16'h8000` samples;
- positive and negative 40-bit wrapping cases;
- reset at each decimation phase and with a level-2 job pending;
- `en=0` at each phase, including pending work;
- context switches with deliberately different A and B histories;
- long suspension and exact restoration of both contexts;
- data-hold and valid-strobe behavior on every non-producing edge;
- one Context-B stimulus forcing a level-1 low result whose bit 31 differs from
  bit 15, so the specified `[30:15]` truncation and the mutant `[31:16]`
  truncation provably differ, and comparing `b_l2_lo` for that case.

### Gate 4: normalized arithmetic structure

Use one frozen normalization sequence and parse machine-readable statistics:

```text
read_verilog -sv dwt_shared.v
hierarchy -check -top dwt_shared
proc
flatten
opt_expr
opt_clean
stat -json
```

The flattened candidate may contain at most eight normalized multiplication
operators. Count `$mul`, `$macc`, and any tool-version-specific multiply/MAC
cell representation; record operand widths and signedness. Shift/add constant
implementations are legal and count as zero multiplication operators. The gate
is a cap, not by itself proof of a particular architecture.

### Gate 5: unweighted generic Yosys cell count

Synthesize candidate and references with the same frozen Yosys binary and:

```text
read_verilog -sv <one design's sources>
synth -top <top> -flatten
stat -json
```

The candidate generic cell count must be strictly below 60% of the frozen sum
of independently synthesized `dwt_a` and `dwt_b`. The ratio was chosen after
disclosed model-free pilot calibration to distinguish a one-bank fold from the
observed naive and partial-share controls.

Record complete cell histograms, register bits, mux cells, normalized
multiplication operators, source hashes, command text, and Yosys version.
Define exactly one named `stat -json` histogram field as the **generic cell
count** used by this gate, and compute the 60% ratio from that number alone.
Report this only as **unweighted generic Yosys cell count**, never area.

### Gate 6: controller-only synthesized-netlist holdout

- In a fresh controller-owned directory, synthesize the candidate and emit a
  simulation-safe generic netlist with a frozen, hash-recorded command.
- Emit both the candidate and positive-control netlists with Yosys
  `write_verilog` from the same `synth` run, and simulate them with Icarus
  against the Yosys-provided `simcells.v`/`simlib.v` libraries. Those library
  files and the exact command text are hash-frozen in `input_manifest.json`.
- Always rebuild this netlist from the controller-hashed candidate.
- Run 1,202 independently generated cycles with seed `0x7D17BEEF` against the
  pure-Python oracle, comparing all data and valid outputs.
- Hidden vectors, generator details beyond the committed contract, netlist,
  and result files are not model-readable or writable.
- On failure return only `controller-only synthesized-netlist holdout failed`;
  do not expose vectors or mismatch details to a later turn.
- If a simulation-safe generic-netlist path cannot pass the positive control
  before preregistration, the campaign does not launch. It must not silently
  degrade to a second RTL-only seed.

Passing Gate 6 establishes agreement on tested cases after synthesis. It is not
mapped gate-level simulation or exhaustive equivalence.

## 7. Verification of the verifier

Before launch, deterministic mutations of the folded positive control must
each fail at least one named intended gate:

1. Change one coefficient sign.
2. Swap two coefficient positions.
3. Emit on the opposite decimation parity.
4. Change level-2 truncation from `[30:15]` to `[31:16]`.
5. Drop a pending level-2 job on `en=0`.
6. Drop a pending level-2 job on a context switch.
7. Reset only the active context.
8. Advance history or phase while `en=0`.
9. Share Context A and Context B level-1 history.
10. Hold a valid signal high or assert it one cycle early/late.

The mutation report records candidate/mutant hashes, intended violation,
gate-by-gate outcomes, and whether detection matched expectation.

## 8. Model composition and budget

- Composition: unchanged domain-neutral `ChiaMerge`.
- Adviser: `openai/gpt-5.6-sol` through the approved OpenCode adapter.
- Implementer: `gemini/gemini-3.8-flash` through `DirectGeminiLLM` reply mode.
- Candidate file: one complete `dwt_shared.v`.
- Maximum turns: 16.
- Clean starts: one primary preregistered run. Additional runs require a
  separately recorded extension and may not threaten paper finalization.
- Full physical runs: zero.
- Model prompts contain only frozen references, the public contract, and public
  gate feedback. They do not contain positive controls, mutations, hidden
  vectors, or hidden evaluator implementation.

The model process must be terminated before Gate 6. The controller alone copies
the candidate into the hidden evaluation directory by verified hash.

## 9. Artifact requirements

The campaign archive must contain, as applicable:

```text
preregistration.json
input_manifest.json
tool_lock.json
state.json
history.jsonl
gate_results.json
control_results.json
mutation_results.json
hidden_holdout.json
artifact_hashes.json
inputs/
attempts/
best/
logs/
```

The preregistration binds source, contract, public evaluator, hidden evaluator,
generator, testbench, tool, command, control, threshold, model, turn-budget, and
stop-condition hashes before the first model call.

## 10. Stop conditions

Stop a candidate on the first failed semantic gate. Stop or retry fail closed
on missing, stale, malformed, unknown, or infrastructure-invalid evidence.
Stop the campaign when:

- 16 turns are exhausted;
- any protected hash or config fingerprint changes;
- hidden assets are exposed to a model process;
- the model/evaluator identity boundary is not in force;
- the positive control or any required mutation no longer behaves as frozen;
- remaining time threatens final submission audit or packaging.

## 11. Result interpretation

If accepted, the intended statement is:

> On a frozen streaming Q15 db2 benchmark containing mutually exclusive,
> independently stateful one- and two-level decomposition contexts, ChiaMerge
> produced a candidate that passed directed and randomized bit-exact RTL
> checks, a controller-only synthesized-netlist holdout, and frozen structural
> gates. The candidate used no more than eight normalized multiplication
> operators and synthesized to X unweighted generic Yosys cells, Y% fewer than
> the sum of two explicitly unfolded references. This is controlled evidence
> of correct multirate resource folding under the tested contract. It is not
> an exhaustive proof, mapped-area or physical-PPA result, comparison with a
> best-known DWT implementation, or evidence of signal-processing quality.

If no candidate is accepted, preserve every attempt and report the frozen
composition's `0/1` result, deepest passed gate, and failure classes. Do not
relax gates within the run.

## 12. Paper positioning

An accepted result may be described as an additional wavelet/multirate
benchmark. It must not be used to claim four wholly unrelated hardware domains.
It supplements, but cannot replace, the physically verified FFT result, MAC's
bounded formal evidence, or FIR's independent-history evidence.

## 13. Launch checklist

No model call is allowed until all items pass:

- [ ] Reference RTL and independent Python oracle agree on directed and random
      tests.
- [ ] Exact public interface and contract are hash frozen.
- [ ] Positive, naive, and shared-history controls have intended outcomes.
- [ ] All ten required mutations are detected by intended gates.
- [ ] Generic synthesized-netlist simulation passes the positive control.
- [ ] Final reference/control cell counts replace pilot values and reproduce.
- [ ] Yosys, Verilator/Icarus, Python, and source versions are locked.
- [ ] Worker and evaluator isolation per the frozen composition: the
      implementer is a stateless reply-mode text call with no filesystem or
      tool access; the adviser runs with write tools denied and all sources
      inlined; hidden vectors, positive controls, evaluator code, toolchain,
      result archive, and provider credentials live only in controller-owned
      paths; prompts contain only frozen references, the contract, and public
      gate feedback; the controller kills any model process before Gate 6.
- [ ] Controller process-group kill is verified before hidden evaluation.
- [ ] Preregistration and transitive input manifest hashes verify.
- [ ] VM preflight and local smoke pass if the VM is used.
- [ ] The operator confirms that this run cannot delay final submission audit.

## Appendix A: frozen local calibration (2026-09-17)

Measured by the model-free `--selftest` path of `dwt_merge_driver.py` with
Yosys 0.68+136, Verilator 5.051, and Icarus from the local oss-cad-suite
toolchain, before any model call. Generic cell counts use the Gate 5 field
(`modules.<top>.num_cells`); normalized multiplication operators use the Gate 4
field. These final values replace the earlier pilot numbers; full evidence is
in `selftest_local_20260917.json` and `calibration.json`.

| Design | Generic cells | Normalized multipliers |
|---|---:|---:|
| `dwt_a` reference | 6,179 | 8 |
| `dwt_b` reference | 12,391 | 16 |
| two-reference sum (frozen baseline) | 18,570 | 24 |
| naive reference wrapper (negative) | 16,968 | 24 |
| model-free folded control (positive) | 6,521 | 8 |
| shared-history cheater (negative) | 6,417 | 8 |

Gate 5 threshold: candidate cells < 0.60 x 18,570 = 11,142. The folded
control passes at 6,521 (64.9% below the sum); the naive wrapper fails at
16,968 (24 multipliers) and the partial-share shape fails by construction.

Local selftest outcome: the folded control passes all six gates including the
controller-only synthesized-netlist holdout; the naive wrapper passes
functional and corners and fails structure and area; the cheater fails
functional, corners, and the holdout; all ten mutations are detected by their
intended gates.
