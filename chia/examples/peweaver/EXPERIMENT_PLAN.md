# PEWeaver experiment plan

Status: pre-launch execution plan (2026-08-29). This plan turns the submitted
proposal into a reproducible first experiment; it does not claim that the
agent can discover arbitrary hardware reuse.

## Research claim and scope

**Claim.** Given two workloads and an explicit scheduling/interface contract,
an agent can identify safe cross-workload sharing opportunities and produce a
shared PE whose functional correctness is preserved and whose measured PPA is
better than keeping both PEs, when deterministic tools are allowed to reject
or repair proposals.

The contract must state clock/reset behavior, operand/result widths, latency,
valid/ready or mutually-exclusive-use assumptions, mode transition rules,
throughput requirements, and any state-isolation requirement. A text-only
similarity score is not evidence of shareability. A merge is accepted only if
the contract and all gates below pass.

This is a hardware-reuse experiment, not a neural-decoding study. Allen
Neuropixels traces may provide representative activity/switching stimuli, but
they do not validate movement-intent, seizure-prediction, or any other task
accuracy. Thermal modeling (for example HotSpot) is secondary evidence; the
primary physical results are synthesized/post-layout area, timing, and power.

## Benchmark tiers

Every case is a versioned manifest containing workload RTL, contract, oracle
label (`shareable`, `unsafe`, or `reference`), test vectors, and expected
metrics. Keep easy cases separate from the headline result.

1. **Easy positive.** Small combinational or pipelined blocks with obvious
   compatible structure (for example parameterized add/compare variants).
   Purpose: validate plumbing, candidate ranking, and a known true merge.
2. **Unsafe negatives.** Similar-looking pairs that must not merge: differing
   signedness/overflow, reset/state semantics, latency, or overlapping use
   under the stated schedule. Include at least one near-miss that a structural
   matcher will propose and formal equivalence will reject.
3. **HALO reproduction.** Separate short-FFT and long-FFT blocks, then a
   configurable shared FFT PE matching the submitted proposal's controlled
   target. Preserve each workload's interface/latency contract and make the
   schedule explicit (mutual exclusion or legal mode transitions).
4. **Stress/holdout.** Additional width, stage, and parameter variants held
   out of prompt/examples until evaluation. Use these to detect overfitting;
   do not count hand-tuned cases as generalization.

## Systems compared

Run every tier with the same RTL, constraints, seeds, tool versions, and
machine budget.

- **Two-PE baseline:** original blocks retained independently.
- **Yosys alone:** deterministic synthesis/equivalence flow with no agent
  candidate generation; records what automated synthesis can achieve by
  itself.
- **Structural matcher:** syntax/netlist similarity proposes merges, then
  deterministic gates decide; no language-model reasoning or repair loop.
- **Single-shot agent:** one candidate and one verification attempt, no repair
  or iterative measurement.
- **Closed loop (PEWeaver):** inspect -> propose -> generate -> simulate/formal
  check -> synthesize/measure -> repair or reject, with a bounded budget.

## Metrics and reporting

Report per case and aggregate by tier, with confidence intervals where repeats
are feasible:

- proposal precision, recall, and F1 against the manifest oracle labels;
- behavioral regression and formal-equivalence pass rates (including false
  accept and false reject counts);
- repair iterations, rejected candidates, and accepted-candidate yield;
- deterministic tool calls, wall-clock runtime, and token cost (agent runs);
- area, worst negative slack/critical delay, and matched-activity power;
- optional thermal estimate, clearly labeled secondary and not substituted for
  power or correctness;
- final PE count and delta versus the two-PE baseline.

Never average away an unsafe acceptance: report it as a release-blocking
failure even if aggregate PPA improves.

## Deterministic acceptance gates

An accepted merge must pass all gates in order; failures are logged and the
candidate is rejected or sent to the bounded repair loop.

1. Manifest/schema and contract validation; reproducible tool/container
   versions and a recorded random seed.
2. RTL lint/parse and interface/parameter checks.
3. Directed plus randomized Verilator regressions for both workloads, including
   reset, back-to-back operations, mode changes, corner widths, and illegal
   schedule probes.
4. Formal miter/equivalence proof for each workload under the explicit
   assumptions; unknown, timeout, or tool error is **fail closed**.
5. Scheduling/latency contract check: no overlap or state leakage beyond what
   the manifest permits.
6. Yosys synthesis and timing checks; OpenROAD placement/routing when the case
   is in the physical tier. Reject timing regressions outside the contract.
7. Matched-input/activity power measurement against the two-PE baseline;
   retain only if the declared objective improves without violating gates.

The unsafe-negative suite is a mandatory guardrail: zero false accepts is the
first release criterion. If physical tools are unavailable, label the result
functional-only and do not claim PPA improvement.

## Artifact and log schema

Use one run directory per `{case, system, seed}`. Store immutable inputs plus
machine-readable records:

```text
manifest.json       case id, tier, oracle label, contract, tool versions
candidate.json       parent ids, rationale, parameters, source hashes
verification.json    sim/formal commands, status, assumptions, diagnostics
synthesis.json       area, timing, constraints, tool status
power.json            vectors/activity source, power, baseline, delta
run.json              seed, timestamps, token/tool counts, outcome, failures
artifacts/            RTL, logs, proofs, netlists, reports, layout snapshots
```

Hashes must identify RTL, vectors, constraints, prompts/configuration, and
tool images. A top-level `results.jsonl` should contain one summary per run;
human-readable reports may be generated from it, never used as the source of
truth.

## Milestones (Aug 29–Sep 20, 2026)

Each date ends with a demonstrable artifact and a pass/fail review.

- **Aug 29–30 — harness baseline.** Freeze schema, contracts, tool versions,
  and two-PE baseline. Demo: one command produces a JSON result and a passing
  formal miter from `examples/peweaver/`.
- **Aug 31–Sep 2 — benchmark pack.** Add easy positives, unsafe negatives,
  and golden vectors with oracle labels. Demo: regression table has no
  unexplained labels and catches the planted near-miss.
- **Sep 3–5 — deterministic baselines.** Implement Yosys-alone and structural
  matcher runs with shared reporting. Demo: side-by-side precision/recall and
  gate outcomes on the benchmark pack.
- **Sep 6–9 — candidate loop.** Add single-shot and bounded closed-loop agent
  adapters, repair trace, token/tool accounting, and fail-closed behavior.
  Demo: one accepted positive and one rejected unsafe negative with complete
  logs.
- **Sep 10–13 — HALO RTL.** Import/minimize short- and long-FFT references,
  specify the mode schedule, and establish independent golden behavior. Demo:
  reproducible proofs/regressions for both reference FFTs.
- **Sep 14–16 — HALO sharing.** Generate or encode the configurable shared FFT
  and run equivalence, timing, and synthesis. Demo: shared RTL plus proof log
  and first area/timing comparison.
- **Sep 17–18 — physical/power tier.** Run OpenROAD and matched-activity power;
  optionally run HotSpot as secondary thermal context. Demo: baseline/shared
  reports and layout artifacts, or an explicit blocked-tools record.
- **Sep 19 — holdout and ablations.** Run stress cases and compare all systems;
  freeze seeds/configuration before viewing outcomes. Demo: complete JSONL
  results and ablation table.
- **Sep 20 — release package.** Audit provenance, rerun from a clean checkout,
  and write limitations. Demo: one-command reproduction bundle with plots,
  logs, RTL, proofs, and a claim table separating correctness, PPA, and thermal
  evidence.

## Decision rule

The project is a success only if closed-loop PEWeaver has zero unsafe accepts,
passes the HALO proofs and schedule checks, and shows a reproducible matched
activity PPA advantage over the two-PE baseline on at least the controlled
HALO case. Otherwise report the negative result precisely and retain all
rejected candidates and logs.
