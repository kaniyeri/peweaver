# PEWeaver FFT-to-physical-PPA plan

Status: agreed execution plan, 2026-08-29.

This plan supersedes any implication that a shared/configurable FFT or a CHIA
loop should be built before the project can produce one reproducible physical
implementation and power estimate from unmerged RTL.

## Objective

Establish a reproducible, auditable path from fixed-point streaming FFT RTL to
an open-PDK implementation estimate.  First measure unmerged reference cores;
only then build a shared/configurable candidate and compare it under identical
conditions.

This produces an implementation estimate, not sign-off silicon power, a HALO
reproduction, or a clinical claim.

## Scope and order

```text
FFT64 reference + independent arithmetic oracle
    -> FFT128 reference + independent arithmetic oracle
    -> physical-flow bring-up
    -> FFT64 baseline physical PPA study
    -> FFT128 baseline physical PPA study
    -> shared/configurable short/long candidate
    -> matched baseline-versus-candidate PPA study
    -> CHIA candidate discovery and autonomous orchestration
```

No CHIA integration, automated merge generation, Allen-data download, or
physical comparison claim belongs before the FFT64 baseline physical study has
completed.

## Phase 1: FFT64 independent arithmetic oracle

### Deliverable

A dependency-free Python model that consumes FFT64 input vectors and computes
the fixture-compatible 16-bit complex outputs without consulting output golden
files during computation.

### Required behavior

- signed Q1.15 conversion and exact 16-bit wrap behavior;
- the selected FFT64 fixed-point multiply, rounding, and per-stage scaling
  rules, derived from the pinned curated RTL and documented explicitly;
- 64-sample transaction input, output ordering, and output formatting;
- bit-exact agreement with both pinned upstream input4/output4 and
  input5/output5 vectors.

### Acceptance gate

- unit tests cover conversion, arithmetic edge cases, ordering, and both full
  vector sets;
- no external numerical package is required;
- the model does not read output golden files as an input to calculation;
- existing RTL regression and corpus gates remain passing.

If exact behavior cannot be specified from the RTL, stop and document the
missing semantics rather than shipping a floating-point approximation labelled
as bit-accurate.

## Phase 2: FFT128 reference and oracle

### Deliverable

A curated FFT128 reference fixture with the same provenance and claim
discipline as FFT64, plus a matching independent arithmetic model.

### Required controls

- pin the upstream revision, license, file hashes, and vector hashes;
- preserve curated third-party source byte-for-byte;
- use a PEWeaver-owned name-isolation wrapper only;
- provide directed checks for reset, transaction length, latency, valid-output
  continuity, ordering, post-reset quietness, back-to-back transactions, and
  abort/state isolation;
- keep the fixture outside the formal-equivalence and synthesis-proxy corpus
  until it has an explicit, valid candidate/comparison contract.

### Acceptance gate

- independent model reproduces the frozen FFT128 vectors bit-exactly;
- directed RTL regression passes deterministically;
- all existing FFT64 and corpus gates remain passing.

## Phase 3: physical-flow bring-up

### Objective

Prove that the local environment can implement an RTL top using one pinned open
PDK and produce a power estimate driven by measured switching activity.

### Setup decisions to freeze before installation

- one open PDK and matching standard-cell library, with exact revision;
- synthesis, place-and-route, STA, and power-analysis tool versions;
- a top-level wrapper, clock port, reset convention, and explicit I/O
  constraints;
- a target clock period;
- an activity window that includes reset, idle, one or more FFT transactions,
  output drain, and representative duty cycle;
- versioned VCD or SAIF trace generation and a machine-readable result schema.

Do not mix PDK/library revisions, clocks, or activity schedules between designs
being compared.

### FFT64 baseline study

The initial end-to-end proof case is the unmerged FFT64 core.  The study must
produce:

- source and fixture hashes;
- tool and PDK/library revisions;
- constraints and achieved timing/slack;
- synthesis and routed area;
- leakage, dynamic, and total estimated power;
- identity of the activity trace and exact workload/duty-cycle description;
- complete logs/artifact locations and a concise limitations statement.

### Acceptance gate

- all flow stages succeed without hand-editing generated netlists or reports;
- timing status is explicit (met or not met); a failing-timing design may not
  be presented as an equivalent comparison point;
- the power report is trace-based or clearly labelled as vectorless if that is
  the only temporarily available measurement;
- repeating the flow from the recorded inputs yields materially identical
  results;
- the report makes no sign-off, HALO-node, or silicon-power claim.

### FFT128 baseline study

Reuse the identical flow and reporting schema for the unmerged FFT128 core.
This is not required to establish the first physical-flow proof, but it is
required before comparing a short/long merged candidate.

## Phase 4: shared/configurable candidate (later)

Only after both baseline implementations are measurable, implement a
PEWeaver-owned short/long candidate.  Its contract must declare mode selection,
transition preconditions, reset/drain/abort behavior, state isolation, latency,
and throughput.

Prove the wrapper/control protocol on a reduced instance and retain independent
model plus directed regression for the full datapaths.  Do not claim full
arithmetic formal proof unless it is actually obtained.

## Phase 5: matched comparison

Compare the separate-core baseline against the shared/configurable candidate
using the same PDK, library, constraints, clock, workload traces, duty cycles,
and reporting scripts.  Report area, timing, leakage, dynamic power, total
estimated power, transition overhead, and all compatibility assumptions.

A correct candidate that is larger, slower, fails timing, or is not
power-beneficial is a valid rejection outcome.

## Phase 6: CHIA integration (last)

Once the deterministic implementation and measurement flow is proven, CHIA may
orchestrate bounded candidate discovery, generation, verification, PPA runs,
and audit reporting.  It must not weaken contracts or accept a candidate after
a tool error, timeout, unknown proof result, missing activity data, or failing
timing status.

