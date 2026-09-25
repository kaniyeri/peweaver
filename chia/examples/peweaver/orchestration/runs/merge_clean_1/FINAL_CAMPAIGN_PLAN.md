# PEWeaver final campaign plan

Status: proposed implementation plan for operator approval  
Campaign window: 2026-09-05 through 2026-09-19  
Submission deadline: 2026-09-20 AoE  
Primary source of current state: `SOL_BRIEFING.md`  
Project rules and claim boundary: repository-root `AGENTS.md`

## 1. Campaign objective

Turn the current verified ChiaMerge result into one coherent, toolchain-centered
hackathon project:

> **PEWeaver: toolchain-verified hardware sharing and power recovery with
> CHIA.** ChiaMerge generates a safe shared implementation from reference PEs;
> ChiaPowerSave consumes an accepted implementation and uses measured power
> feedback to propose bounded optimizations. CHIA schedules the work, but
> deterministic simulation, formal, synthesis, gate-level, physical-design,
> DRC, LVS, and power tools alone decide what survives.

The intended top-level composition is:

```text
reference RTL + behavioral contract
    |
    v
ChiaMerge
    |  deterministic functional/formal/physical acceptance
    v
accepted shared RTL
    |
    v
ChiaPowerSave
    |  fixed workloads + immutable constraints + Pareto gates
    v
accepted Pareto RTL or measured no-improvement result
    |
    v
model-free physical finalization
    -> mapped GLS
    -> place and route
    -> extracted timing and activity power
    -> GDS stream-out
    -> independent DRC and LVS
    -> comparative thermal sensitivity
```

This campaign must strengthen the CHIA/toolchain contribution rather than add
more model-centric machinery. Model routing, provider comparisons, generic
budget dashboards, N-way merging, and corpus-level PE classification are not
headline work for this campaign.

## 2. Current evidence to preserve

Do not overwrite or silently replace any of the following records.

### Frozen standalone and prior shared baselines

- FFT64 placed cell area: 164,408 um^2.
- FFT128 placed cell area: 260,477 um^2.
- Standalone placed-area sum: 424,885 um^2. This is a sum, not a placed
  combined dual-core result.
- FFT64 streaming power: 23.314 mW; finite three-frame energy: 20.40 nJ/FFT.
- FFT128 streaming power: 41.040 mW; finite three-frame energy: 71.20 nJ/FFT.
- Frozen fallback shared RTL SHA-256:
  `6a56b8326993d091cd989fc45a68ac341e5a25a33aaace47e81fa42a1ab78499`.
- Frozen fallback result:
  `physical/results/shared_baseline_sky130.json`.
- Frozen fallback result SHA-256:
  `b9d3fc0a98a160972a6ff2de0c54979c5b5c721992d3cc7b232cb3f2a063a73e`.

### ChiaMerge discovery and reproduction results

- Discovery candidate RTL SHA-256:
  `ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e`.
- Discovery candidate: 286,970 um^2, 32.46% below the standalone sum,
  39.81859/40.44372 mW in mode 64/128, timing met, DRC 0.
- Discovery holdout: 36/36, exact 71/137-cycle first-valid latency, exact
  valid-pulse width, and four applied corruptions caught.
- Preregistered clean reproduction: 3/3 accepted at turns 10/2/13, each with a
  different candidate and 32-33% placed-area reduction.
- Reproduction power ranges: 40.02-40.45 mW in mode 64 and 40.63-41.08 mW in
  mode 128.
- Current ChiaMerge primitive/unit suite: 96 passing tests as recorded in
  `SOL_BRIEFING.md`.

These are immutable inputs to the next campaign. New results go in fresh,
design- and campaign-scoped directories. A new result may supersede a headline
only after all required gates and an independent model-free repeat.

## 3. Non-negotiable scientific rules

1. Models propose; they never accept, score their own correctness, alter the
   evaluator, choose post-hoc workloads, or declare a physical result valid.
2. Functional and cycle-level correctness precede PPA. Exact latency,
   throughput, valid windows, frame count, reset, gaps, continuous frames, and
   mode transitions are immutable gates.
3. Use lexicographic gates and Pareto archives. Do not use a weighted score that
   trades correctness, timing, DRC, or the accepted area result for power.
4. Evaluate one atomic power hypothesis per candidate. A candidate may not
   combine several unrelated optimizations and then claim causal attribution.
5. The shared FFT must retain at least 20% placed-area reduction against the
   newly measured combined dual-core reference unless the operator explicitly
   approves a different Pareto experiment before it runs.
6. Do not dilute average power by changing latency, inserting idle cycles,
   shortening the measured window, dropping transforms, changing the clock, or
   weakening I/O, uncertainty, utilization, activity, or routing constraints.
7. Use characterized integrated clock-gating cells only. Never create a clock
   with `clock & enable`, a ternary clock assignment, or an uncharacterized
   combinational gate.
8. Always rebuild mapped GLS. For sky130 sequential GLS use Icarus with
   `FUNCTIONAL` and `UNIT_DELAY=#1`, not Verilator.
9. Preserve the validated simple mapping requirement for the shared design.
   Do not replace it with an `abc` path that can exploit X don't-cares.
10. Full OpenROAD runs are serial. Cheap generation, lint, simulation, formal,
    and synthesis proxies may run in parallel in isolated workspaces.
11. Preserve failed candidates, false merges, tool failures, model failures,
    and no-improvement outcomes. Never report only successful turns.
12. Do not claim HALO reproduction, clinical accuracy, implant safety, thermal
    safety, silicon measurement, tapeout readiness, or multi-corner signoff.
13. GDS is a generated layout artifact, not a fabricated chip.
14. HotSpot results are comparative sensitivity under declared assumptions,
    not brain-tissue validation.
15. No model process may remain alive during hidden evaluation or final
    physical reproduction.

## 4. What is and is not a CHIA primitive

The implementation must make the relationship to CHIA explicit.

### Existing CHIA machinery used by this project

- `@ChiaFunction` for resource-aware remote execution.
- `chia_remote()` and CHIA `get()` for dispatch and result collection.
- `OpenCodeLLM`, which is itself a CHIA model adapter.
- Ray resource scheduling and task isolation.
- CHIA profiling/cost metadata where enabled.
- CHIA process cancellation and process-group cleanup.

### Current integration state

- FFT lint, functional evaluation, and physical evaluation are
  `@ChiaFunction(resources={"yosys": 1})` nodes and are invoked with
  `.chia_remote()` by `peweaver_chia_graph.py`.
- The FFT physical node executes the validated model-free
  `run-physical.sh` flow: Yosys -> Icarus mapped GLS -> OpenROAD -> OpenSTA.
- `ChiaIterate` and `ChiaCheckCondition` are local Python orchestration, which
  is consistent with CHIA's loops-as-Python design.
- ChiaMerge's adviser and implementer use the CHIA `OpenCodeLLM` adapter but
  currently call it locally rather than scheduling it as a remote task.
- MAC gates currently invoke Verilator and Yosys locally and are not yet
  first-class CHIA nodes.
- The hidden holdout is model-free post-generation evaluation outside the main
  graph.

### Required positioning

Do not claim that CHIA lacked iteration or search. The narrower contribution is:

> `ChiaIterate` supplies crash-safe transactional repair over mutable
> engineering artifacts: isolated attempts, an ordered fail-closed gate ladder,
> deterministic promotion or rollback, and resumable best-state recovery.

`ChiaMerge` remains the resource-sharing specialization. `ChiaPowerSave` will
be a second specialization over the same transactional control semantics.

## 5. Target repository organization

Use the smallest organization that exposes reusable boundaries without
rewriting validated tools.

```text
examples/peweaver/orchestration/
    chia_merge.py                 existing transactional primitives
    peweaver_chia_graph.py        FFT ChiaMerge driver
    mac_merge_driver.py           MAC ChiaMerge driver
    chia_power_save.py            new domain-neutral PowerSave composition
    power_save_fft_driver.py      shared and dual-core FFT driver
    power_save_fir_driver.py      second PowerSave-domain driver
    evaluator_nodes.py            thin @ChiaFunction wrappers, if useful
    formal/                       model-free proof drivers and properties
    campaigns/                    preregistration manifests

examples/peweaver/physical/
    rtl/                          accepted/frozen physical wrappers only
    activity/                     fixed matched activity testbenches
    synth/                        design-scoped Yosys scripts
    constraints/                  design-scoped immutable SDCs
    openroad/                     validated P&R and report scripts
    gds/                          stream-out, DRC, LVS scripts/config
    thermal/                      power-map and HotSpot scripts/config
    results/<campaign>/<design>/  fresh artifacts and JSON

examples/peweaver/merge_benchmarks/
    mac_reference/                existing MAC references
    fir_reference/                new FIR PowerSave benchmark
```

This layout is advisory. Do not move working files only to satisfy it. Prefer
thin additions and preserve compatibility with existing frozen commands.

## 6. Workstream 0: artifact synchronization and campaign freeze

Complete this before any new model-driven campaign.

### Tasks

1. Copy the preregistration manifest and complete `merge-repro-1/2/3` records
   from `/work/peweaver/runs` into the local/open-source artifact tree.
2. Include each accepted RTL, state JSON, check JSON, model transcript or
   provider record, physical JSON, holdout report, mutation report, and hashes.
3. Remove reliance on inaccessible absolute `/work/...` paths in the release
   index. Preserve original absolute paths as provenance fields if useful, but
   add relocatable artifact paths.
4. Verify all candidate and result hashes against the VM records.
5. Create a campaign preregistration manifest before new outcomes are viewed.
   Record source commit/tree hash, exact inputs, prompts, models, candidate
   budgets, full-physical budgets, workloads, gates, new tool locks, and stop
   conditions.
6. Fix prose and gate notes that call 424,885 um^2 a "combined baseline." Until
   the wrapper is physically measured, it is the standalone placed-area sum.
7. Create a read-only frozen snapshot of the discovery candidate and all three
   reproduction candidates.
8. Establish separate model-worker and evaluator checkouts/containers or Unix
   identities before any new model campaign. The evaluator, hidden vectors,
   toolchain, provider credentials, and result directory must not be writable by
   the model worker. Give the evaluator a clean snapshot plus exactly one
   controller-hashed candidate file.
9. Add a controller action that terminates the model worker's process group or
   container before hidden, formal, physical, GDS, or thermal evaluation.

### Acceptance

- One model-free audit command validates every listed artifact hash.
- The campaign refuses to start if an immutable input is missing or changed.
- The release tree contains complete evidence for all three preregistered runs.
- A deliberate worker-side attempt to read or modify hidden/evaluator inputs is
  denied, recorded, and cannot affect a subsequent evaluation.

## 7. Workstream 1: strengthen CHIA-native tool execution

The purpose is to make deterministic tool execution visibly first-class without
duplicating the tools or changing the frozen flow's semantics.

### Tasks

1. Keep `run-physical.sh` authoritative for the validated FFT physical flow.
2. Add or consolidate thin `@ChiaFunction` nodes for these operations where
   they are reused by more than one driver:
   - RTL lint/interface/anti-cheat.
   - Functional differential judge.
   - Formal judge.
   - Yosys synthesis proxy.
   - Mapped Icarus GLS.
   - Full physical flow.
   - GDS stream-out and independent DRC/LVS.
   - HotSpot run, if thermal work reaches that gate.
3. Use the existing `yosys` Ray resource for deterministic evaluator tasks on
   the current VM. Do not invent new GCP resources or credentials.
4. Convert the MAC deterministic gates to `@ChiaFunction` dispatches or route
   them through shared evaluator nodes.
5. Keep gate output structured and bounded: status, failure class, note, metric
   fields, artifact paths, and hashes.
6. Add tests proving that the FFT and MAC drivers dispatch evaluator nodes via
   `.chia_remote()` and that infrastructure errors become `RETRY`, not semantic
   rejection or acceptance.
7. Enable CHIA profiling for at least one representative run and archive its
   execution graph. The paper should show tool/model node composition and
   elapsed tool time, not center model cost.
8. Do not force the model calls to Ray merely for appearance. Worker/evaluator
   identity separation and deterministic evaluation matter more than remote
   model scheduling.

### Acceptance

- Existing ChiaMerge tests remain green.
- FFT directed and hidden judges remain unchanged and pass the frozen
  candidates.
- MAC gates run through CHIA scheduling and retain the same self-test outcomes.
- The physical node still invokes the exact validated shell flow.
- A CHIA profile graph visibly contains model proposal and deterministic
  evaluator stages, with the evaluator stages authoritative.

## 8. Workstream 2: complete the MAC ChiaMerge experiment

The MAC experiment is the second-domain demonstration of ChiaMerge, not a
headline physical-power benchmark.

### Contract

Preserve the existing contract in `mac_merge_driver.py`:

- Signed 8x8 multiply.
- Mode 0 accumulates modulo 2^16.
- Mode 1 returns a product and preserves the accumulator.
- `en=0` holds all state and output.
- Mode changes only while `en=0`.
- Exactly one multiplier structure.
- Area below the two-reference synthesis sum.

### Required deterministic gates

1. Interface, syntax, and anti-cheat lint.
2. Existing 1,200-cycle randomized oracle test with reset, enable gaps, and
   legal mode changes.
3. Directed signed corners: 0, 1, -1, +127, -128, overflow/wrap, repeated
   accumulation, mode-1 interruption, and reset.
4. Yosys structural check for exactly one multiplier after the declared
   normalization pass.
5. Formal proof or exhaustive sequential proof of:
   - Mode-0 equivalence to `mac_a`.
   - Mode-1 equivalence to `mac_b`.
   - Accumulator hold in mode 1 and while disabled.
   - Reset and output hold behavior.
   - The declared legal mode-transition assumption.
6. Synthesis area below the two-reference sum.

### Negative controls

- The existing two/three-multiplier reference-mux implementation must fail the
  structural gate.
- A deliberately unsafe implementation that loses accumulator state across a
  mode-1 interval must fail functional/formal evaluation.
- A simultaneous-lane contract that cannot legally use one multiplier must not
  be "solved" by silently adding mutual exclusion.

### Run protocol

- Freeze model IDs, prompts, sources, gates, and turn budget before launch.
- Run at least three clean starts if time permits; report `k/n`, turns, and all
  failures. One accepted run is enough for the second-domain artifact, but not
  for a reliability claim.
- Run final formal and randomized evaluation with no model process alive.

### Acceptance

- At least one clean ChiaMerge run passes all deterministic and formal gates.
- Every negative control is rejected for the intended reason.
- Complete run history and accepted RTL are included in the release.

## 9. Workstream 3: hierarchical and temporal power attribution

Do not begin broad RTL power edits without this evidence.

### Designs to attribute

- Standalone FFT64.
- Standalone FFT128.
- Discovery shared candidate `ce64c715...`.
- The three preregistered ChiaMerge candidates.
- Later, ungated and clock-gated combined dual-core references.

### Required windows

- Reset assertion and synchronized release.
- Idle before input.
- Pipeline fill.
- Three-frame continuous active streaming.
- Drain after the final input.
- Idle after complete drain.
- 64-to-128 and 128-to-64 reset-separated transitions.

Do not infer finite energy from a window with a different number of transforms.
Each report records duration, accepted samples, emitted samples, valid cycles,
and transform count.

### Attribution outputs

- Total, internal, switching, and leakage power.
- Sequential, combinational, clock, macro, and pad groups.
- Clock sink count and clock-tree power.
- Per-stage or per-logical-block power where the tool can support it.
- Delay-bank clocked-bit count and toggle count.
- Twiddle, multiplier, butterfly, counter/control, reset wrapper, and 128-only
  tail attribution where available.
- A spatial power map for later thermal analysis.

The frozen synthesis uses `synth -flatten`. If hierarchy is insufficient for
attribution, create a clearly labelled attribution-only synthesis that preserves
hierarchy or source names. Do not compare its PPA numbers against the frozen
physical result. Final measured totals still come from the frozen mapping and
physical flow.

Every attribution decomposition must reconcile to the authoritative total
within 1%. If the tool cannot produce defensible per-instance power, report
stage-level toggle/capacitance proxies separately and do not label them measured
power.

### Acceptance

- A machine-readable attribution JSON exists for every starting design.
- The mode-64 shared-power excess can be assigned to at least clocked storage,
  clock tree, combinational logic, and unexplained residual categories.
- The report identifies the first atomic hypotheses from evidence rather than
  model intuition alone.

## 10. Workstream 4: combined dual-core FFT references

Build two physically measured no-sharing controls.

### Variant A: ungated dual core

- Instantiate the frozen FFT64 and FFT128 references.
- Send `di_en=0` to the inactive core.
- Keep both core clocks running.
- Include reset synchronization, mode handling, input fanout, and output mux.

### Variant B: power-managed dual core

- Use characterized sky130 integrated clock-gating cells to stop the inactive
  core.
- Mode/gating enables must be stable under the declared transition protocol.
- Include gating cells, control, CTS, reset synchronization, and output mux in
  area, timing, power, and GDS.
- Validate generated clocks, gating checks, reset assertion/deassertion,
  setup/hold, GLS, and DRC.

### Matched schedules

Use the same schedules for dual-core and shared designs:

- Mode-64 single frame and three-frame continuous burst.
- Mode-128 single frame and three-frame continuous burst.
- Reset-separated 64 -> 128 and 128 -> 64 transitions.
- Idle/fill/drain windows.
- Duty-cycle mixtures with `p64` from 0 to 1. Report endpoints, equal weighting,
  and at least one intermediate point; do not select one favorable mixture.

### Physical controls

- Same sky130A/`sky130_fd_sc_hd` corner.
- Same 10 ns clock and uncertainty.
- Same I/O delays, drive cells, loads, reset convention, routing layers, and
  activity generation.
- Same utilization policy for ordinary PPA comparison.
- For thermal comparison, report both actual floorprints and a fixed-package-
  footprint sensitivity so area and heat-spreading effects are distinguishable.

### Acceptance

- RTL and mapped GLS are bit-exact in each mode with exact latency and pulses.
- Both variants complete P&R with timing met, TNS 0, DRC 0, no STA-1452, and
  valid activity annotation.
- New baseline JSONs contain area, timing, per-mode power, finite energy,
  transition energy, artifacts, and hashes.
- All prose replaces the standalone-area sum with the physically measured
  combined area when making a combined-chip comparison.

## 11. Workstream 5: ChiaPowerSave composition

### Purpose

`ChiaPowerSave` is a domain-neutral composition for bounded,
correctness-preserving power optimization of an already accepted engineering
artifact. It must compose CHIA functions and deterministic evaluator callbacks;
it must not contain FFT, FIR, sky130, or Verilog-specific policy.

### Inputs

- Frozen incumbent workspace and manifest.
- Candidate filename or artifact adapter.
- Immutable functional, cycle, formal, synthesis, GLS, and physical gates.
- Fixed activity scenarios and transform/transaction accounting.
- Hard constraints and protected-file manifest.
- Adviser/proposer and implementer callbacks.
- Candidate-generation budget.
- Full-physical-run budget.
- Pareto/promotion policy.
- Stop conditions.

### State

- Turn and candidate IDs.
- Parent hash and candidate hash.
- Atomic hypothesis ID and rationale.
- Gate level and exact failing feedback.
- Proxy metrics and physical metrics.
- Tool/model failure class.
- Candidate, tool, and wall-clock cost.
- Pareto archive rather than only one scalar best.
- Complete history and final accepted set.

### Evaluation cascade

1. Protected-input and anti-cheat validation.
2. Parse/lint/interface check.
3. Public directed and controller-generated randomized correctness.
4. Exact cycle, latency, throughput, valid, reset, and transition checks.
5. Targeted formal properties where available.
6. Yosys synthesis area/cell/clocked-state proxy.
7. Mapped Icarus GLS.
8. Full OpenROAD timing, DRC, extraction, and power for selected survivors.
9. Independent model-free repeat for a final winner.

### Selection semantics

Correctness, timing, DRC, activity validity, and area floor are hard gates.
After those gates, maintain a Pareto archive over:

- Placed cell area.
- Mode-64 streaming power.
- Mode-128 streaming power.
- Mode-64 finite energy per FFT.
- Mode-128 finite energy per FFT.
- Transition energy.
- Optional idle energy.

Do not collapse these into a weighted score. A candidate may be labelled:

- `INVALID`: any correctness/security/tool-integrity gate fails.
- `REGRESSION`: valid but violates timing, DRC, activity, or area floor.
- `DOMINATED`: valid physical point dominated by an archived point.
- `PARETO`: valid and improves at least one declared objective without being
  dominated.
- `TARGET`: meets all strict per-mode target thresholds.

Require at least a 1% preliminary improvement in a measured target before
spending an independent full repeat, unless the result is needed to establish a
boundary. Report exact deterministic repeats; do not invent statistical
confidence from identical tool reruns.

### Portfolio execution

- The adviser ranks evidence-backed atomic hypotheses.
- Generate several isolated candidates in parallel, one hypothesis each.
- Run cheap gates in parallel.
- Select at most the top one or two candidates per round for serial full P&R.
- Never let workers edit the accepted RTL concurrently.
- Copy an accepted candidate into evaluation only by controller-verified hash.

### Security

- Worker and evaluator use different checkouts/containers or Unix identities.
- The worker can read only pinned references, contract, incumbent candidate,
  public feedback, and its own output directory.
- Hidden vectors, evaluator scripts, toolchain, result directory, and protected
  hashes are not writable by the worker.
- Reject unexpected files and hash all transitive compile inputs before and
  after every gate.
- Kill the worker process group/container before hidden and physical evaluation.

### Tests

- Unit-test all verdict and Pareto semantics.
- Test crash during candidate promotion and archive update.
- Test resume with altered input, workload, objective, and constraint hashes.
- Test semantic rejection versus infrastructure retry.
- Test same-level candidate comparison, which existing milestone-only
  `ChiaIterate` does not support.
- Test full-physical budget exhaustion.
- Keep domain-neutrality guards for the primitive module.

## 12. Workstream 6: FFT ChiaPowerSave campaign

### Starting points

Use the discovery candidate as the default shared incumbent because it has the
lowest recorded per-mode power among the four new accepted candidates while
retaining 32.46% area reduction. Confirm its hash and rerun before use.

Run matched PowerSave campaigns on:

- The shared incumbent.
- The power-managed combined dual-core reference.

Give both campaigns the same maximum model candidate count and full-physical-
run count. This prevents an optimized shared design from being compared against
an intentionally unoptimized reference.

### Shared-design atomic hypotheses

Evaluate in evidence-driven order:

1. Stop the 128-only tail stage clock in mode 64.
2. Split max-depth delay banks into lower/upper segments and gate only the upper
   segment in mode 64.
3. Hold stage-3 twiddle and multiplier registers in mode 64.
4. Stop invalid-cycle pipeline-register movement while preserving fill/drain.
5. Stop idle delay-bank movement only after the final valid output drains.
6. Merge duplicated mode-specific counter/control state one block at a time.
7. Replace shifting storage with addressed/circular storage as a separately
   named architecture experiment.
8. Consider SRAM-backed storage only after the register-based hypotheses and
   only if macro timing, simulation, LEF, Liberty, GDS, and power views can be
   validated.

### Dual-core atomic hypotheses

1. Gate the inactive core with characterized ICG cells.
2. Gate both cores only during provably idle post-drain windows.
3. Hold inactive input and output mux operands where clock gating is not legal.
4. Minimize transition-control state without changing mode/reset protocol.

### Clock-gating gates

Every clock-gated candidate additionally requires:

- No combinationally generated clocks outside characterized cells.
- Gating enable stable during active clock edges.
- Defined generated clocks in STA.
- Gating-check report with no violation.
- Reset assertion and synchronized release validated at RTL and GLS.
- CTS reaches all gated domains.
- Setup/hold/recovery/removal timing met.
- Mode transition and post-reset holdouts pass.
- Gate-level VCD clock period and activity coverage validated per domain.

### Targets

Preserve the strict targets from `AGENTS.md`:

- Mode-64 power <= 23.314 mW and E/FFT <= 20.40 nJ.
- Mode-128 power <= 41.040 mW and E/FFT <= 71.20 nJ.
- At least 20% placed-area reduction unless a different preregistered Pareto
  tradeoff is approved.

Missing the strict targets is not failure of the experiment. Preserve and report
the measured Pareto frontier and the best valid reduction.

### Initial budget

- Up to 16 generated shared candidates.
- Up to 16 generated dual-core candidates.
- No more than 5 full physical shared evaluations before a review checkpoint.
- No more than 5 full physical dual-core evaluations before a review checkpoint.
- One independent model-free repeat of each final comparison point.

The operator may extend a budget only after reviewing exact measured progress.

## 13. Workstream 7: second ChiaPowerSave domain

Use a symmetric streaming FIR as the second domain. Do not use the tiny MAC as
the main physical-power demonstration.

### Benchmark definition

- A straightforward fixed-coefficient, signed, streaming FIR reference with a
  meaningful but tractable tap count, initially 32 taps.
- Symmetric Q-format coefficients pinned by literal and hash.
- Exact arithmetic contract: input width, coefficient width, product width,
  accumulator width, wrap/saturation policy, rounding, truncation, latency,
  valid behavior, reset, continuous input, and gaps.
- A direct-form unoptimized reference that is reasonable engineering, not an
  intentionally pathological strawman.
- An independent Python oracle.
- Directed corners, random streams, continuous bursts, valid gaps, reset, and
  coefficient-symmetry checks.

The benchmark represents a generic streaming filter and BCI-relevant DSP
context. It does not establish neural filtering quality or clinical accuracy.

### Expected hypothesis families

- Exploit coefficient symmetry with pre-addition while preserving exact signed
  width and modulo behavior.
- Hold the delay line and arithmetic pipeline on invalid cycles.
- Isolate constant-multiplier operands when a tap group is inactive.
- Reduce redundant sign extension and duplicated control.
- Gate provably idle register banks with characterized ICG cells if warranted.

These are examples, not answers embedded in the generic PowerSave prompt. The
driver may expose measured attribution and contract facts; the model must derive
the concrete patch.

### Gates

1. Interface/anti-cheat/lint.
2. Independent bit-exact directed and randomized oracle.
3. Exact valid/latency/reset/gap behavior.
4. Formal or bounded equivalence where tractable.
5. Mapped GLS.
6. P&R timing and DRC.
7. Matched continuous and gapped-activity power.
8. Final independent repeat.

### Acceptance

- The same domain-neutral `ChiaPowerSave` implementation runs unchanged.
- At least one valid candidate is evaluated physically, whether or not it
  improves power.
- A positive result reports before/after power and area under identical
  workloads; a negative result preserves the attempted mechanisms and failures.

### Initial budget

- Up to 16 generated candidates.
- Up to 4 full physical candidate evaluations.
- One independent model-free repeat of the best valid point.

## 14. Workstream 8: GDS stream-out, independent DRC, and LVS

GDS completion is a required campaign objective, but it is not part of every
candidate turn. Run it only on frozen final points.

### Why it is absent now

The validated backend ends at detailed routing, extracted SPEF, STA/power,
router DRC, and `write_def`. It does not invoke OpenROAD/KLayout/Magic GDS
stream-out, an independent foundry-deck DRC, extraction, or Netgen LVS.

### Tool setup

1. Inventory KLayout, Magic, Netgen, and compatible sky130A decks on the VM.
2. If a required tool is absent, install it only in the approved persistent
   toolchain area after operator approval. Do not alter system/GCP
   infrastructure or credentials.
3. Pin versions, binaries, PDK cells, technology files, layer maps, DRC decks,
   extraction setup, and scripts in a separate signoff/finalization tool lock.
4. Do not silently modify the frozen `physical/tool-lock.json`; extend it with a
   versioned schema or add a clearly linked finalization lock.

### Stream-out

- Convert the final routed DEF/OpenDB design plus sky130 standard-cell GDS into
  a top-level GDS using a pinned KLayout or Magic flow.
- Include standard-cell geometry, routing, vias, tap/tie cells, clock tree, and
  PDN.
- Record top-cell name, die bounding box, layer inventory, instance count, file
  size, and SHA-256.
- Render a layout image for human inspection, but do not use the image as a
  correctness result.

### Independent DRC

- Run the available sky130A Magic or KLayout DRC deck on the streamed GDS.
- Distinguish detailed-router DRC from independent streamed-layout DRC.
- Parse marker count and categories into JSON.
- A missing deck, crash, unknown marker format, or partial run is not DRC clean.

### LVS

- Produce the reference schematic/CDL/SPICE netlist from the accepted mapped or
  post-route design with power/ground and filler conventions documented.
- Extract or convert the GDS netlist with the pinned sky130 setup.
- Run Netgen LVS or the validated equivalent.
- Require top-level ports, device/cell counts, connectivity, and final match.
- Do not waive mismatches merely because mapped GLS passed.

### Additional checks

- `design_is_routed` or equivalent must confirm no unrouted signal nets.
- Record antenna, density/fill, seal-ring, pad, and packaging status.
- If antenna or density fill is absent, state that explicitly. Do not call the
  layout tapeout ready.

### Designs

Required:

- Final selected shared FFT.
- Final power-managed combined dual-core FFT.

If time permits:

- FIR baseline and best PowerSave point.

### Acceptance

- GDS exists, is nonempty, has the correct top and dimensions, and is hash
  pinned.
- Independent DRC reports zero violations for a `DRC-clean` claim.
- LVS reports a complete match for an `LVS-clean` claim.
- Any blocked stage produces a machine-readable blocked result and removes the
  corresponding claim.

## 15. Workstream 9: comparative HotSpot thermal sensitivity

Thermal work starts in parallel with GDS setup but may use routed DEF/OpenDB;
HotSpot does not require GDS polygons.

### Required inputs

- Actual die and core dimensions from DEF/OpenDB.
- Spatial locations of placed cells or logical blocks.
- Measured activity-based power reconciled to the authoritative OpenSTA total.
- Time-resolved workload schedule.
- Pinned HotSpot version and configuration.
- Explicit material, package, boundary, ambient, resistance, and capacitance
  assumptions with citations.

### Power map

Preferred method:

- Obtain per-instance power from the timing/power engine and combine it with
  OpenDB instance coordinates.
- Bin power onto a fixed grid, initially 32x32 or another preregistered
  resolution.
- Include clock-tree cells and distribute non-cell residual power by a declared
  method.
- Reconcile every grid total to OpenSTA within 1%.

Fallback:

- Use measured stage/block power and declared block regions.
- If only total uniform power is available, label the run a uniform-block
  sensitivity sanity check, not a hotspot result.

### Comparisons

- Standalone FFT64 and FFT128 orientation points.
- Ungated combined dual core.
- Power-managed combined dual core.
- Unoptimized shared candidate.
- Power-optimized shared candidate.

Run two floorplan interpretations:

- Actual implementation footprint, which includes area and heat-spreading
  consequences.
- Fixed package footprint, which better isolates spatial concentration and
  total-power effects.

### Workloads

- Continuous mode 64.
- Continuous mode 128.
- Equal-weight alternating modes with declared reset/drain transitions.
- Duty-cycle sweep over mode occupancy and active/idle fraction.
- A repeated trace long enough to reach meaningful thermal time scales; do not
  interpret a microsecond VCD window itself as tissue thermal equilibrium.

### Thermal model

- Ambient may be set to 37 C only as a declared boundary assumption.
- Sweep uncertain package/interface thermal resistance and capacitance rather
  than selecting one favorable point.
- A conventional HotSpot package configuration is a tool smoke test, not an
  implant model.
- If an implant-like layer stack is attempted, list silicon, BEOL/package,
  encapsulation, and tissue-equivalent parameters and report a sensitivity
  envelope. Do not call it calibrated without external measurement.

### Outputs

- Peak and average temperature rise above ambient.
- Spatial peak location and power density.
- Steady-state and transient response.
- Time above selected illustrative delta-temperature thresholds.
- Break-even maps showing when sharing lowers total energy but raises local
  temperature because of concentration.
- Full parameter sensitivity rather than one absolute temperature.

### Claim boundary

Allowed:

> Under the stated HotSpot floorplan, package, workload, and boundary
> assumptions, design A has lower/higher modeled peak on-die temperature rise
> than design B.

Not allowed:

> The design is safe for implantation, avoids tissue damage, meets a clinical
> thermal standard, or holds brain temperature below 1 C rise.

### Acceptance

- Power maps reconcile to measured totals.
- Shared and baseline designs use identical thermal assumptions.
- Results include a parameter sweep and are reproducible from pinned inputs.
- The report clearly separates on-die comparative modeling from tissue or
  clinical inference.

## 16. Experiment matrix

The release should distinguish compositions, deterministic evidence, and
claims.

| Experiment | Agentic composition | Required deterministic evidence | Intended claim |
|---|---|---|---|
| FFT merge discovery | ChiaMerge | RTL judge, mapped GLS, P&R, holdout | Shared RTL can be discovered and accepted |
| FFT merge reproduction | ChiaMerge | 3 clean runs, holdout, P&R | `k/n = 3/3` for frozen composition |
| MAC merge | ChiaMerge | oracle, formal, structure, synthesis | Second-domain ChiaMerge evidence |
| Unsafe MAC controls | none/model candidate | oracle, formal, structure | Evaluator rejects invalid sharing |
| Dual-core FFT | none | matched GLS/P&R/power | Fair no-sharing reference |
| Shared FFT power recovery | ChiaPowerSave | all hard gates + physical power | Verified power optimization/Pareto result |
| Dual-core power recovery | ChiaPowerSave | same budget and gates | Fair optimized reference |
| FIR power recovery | ChiaPowerSave | oracle/formal/GLS/P&R/power | Second-domain PowerSave evidence |
| GDS finalization | model-free | GDS validation, independent DRC/LVS | Layout artifact and exact closure status |
| Thermal sensitivity | model-free | reconciled power map + HotSpot sweep | Comparative modeled thermal context |

## 17. Verification of the verifier

Keep this bounded and tool-centered.

### Required

- Preserve existing FFT mutation tests.
- Generalize mutation application enough that each final FFT architecture has
  applicable counter/latency, arithmetic, and constant corruptions.
- Add MAC mutants for signedness, accumulator hold, reset, enable, and
  multiplier duplication.
- Add FIR mutants for coefficient, sign extension, rounding/truncation, valid
  delay, and delay-line hold.
- Require every applicable deliberate corruption to fail at least one intended
  gate.
- Add one deliberately corrupted GDS/DEF/netlist or mismatch fixture to prove
  DRC/LVS result parsing fails closed.

### Optional

Do not build an agentic red-team loop unless all primary work is complete. A
deterministic structural mutation library and formal checks provide better value
for this deadline.

## 18. Campaign execution and parallelism

### Isolation

- Model workers write complete candidates into isolated attempt directories.
- Evaluator checkout, hidden tests, toolchain, and result directories are not
  writable by model workers.
- No two workers edit the same incumbent.
- The controller alone promotes by hash.

### Parallel workstreams

These may proceed concurrently because they do not edit the same accepted RTL:

- Artifact synchronization and manifest audit.
- MAC CHIA-node conversion and formal harness.
- Combined dual-core wrapper and activity tests.
- GDS tool inventory and deterministic stream-out prototype.
- FIR benchmark/oracle creation.
- Power attribution report development.

These must be serialized or explicitly coordinated:

- Changes to `run-physical.sh` and common OpenROAD scripts.
- Full OpenROAD runs on the current VM.
- Promotion of the shared PowerSave incumbent.
- Final GDS/DRC/LVS and independent reproduction.

### Model roles

- Use a strong reasoning model for architecture ranking, power-report
  interpretation, difficult clock/reset reasoning, and final integration review.
- Use bounded worker models for one-file candidates, mechanical node wrappers,
  test generation, and failure triage.
- Each worker receives exact editable files, one atomic hypothesis, immutable
  constraints, gate feedback, and a stop condition.
- A lead reviews candidate intent before the controller spends a full physical
  run, but human preference cannot override a failed gate.

### GCP boundary

- Use only `peweaver-vm` in project `peweaver-gcp-project`, zone
  `peweaver-zone`.
- Use the credential-free lifecycle helper and existing IAP/OS Login setup.
- Do not create/delete resources, change IAM/firewall, attach a service account,
  enable direct SSH, or expose provider credentials.
- Run model-free `runner.py preflight --json` and `local-smoke --json` after each
  start and before model work.
- Stop Ray and then stop the VM after campaign batches.

## 19. Proposed 14-day sequence

The dates are execution targets, not permission to skip a failed prerequisite.

### Sep 5-6: freeze and toolchain graph

- Synchronize and hash all reproduction artifacts.
- Freeze the new campaign manifest.
- Correct "combined baseline" labels.
- Convert MAC gates to CHIA nodes.
- Prototype formal MAC harness.
- Inventory GDS/DRC/LVS and HotSpot tools.
- Start power attribution reports.

Exit: complete artifact audit, green existing tests, MAC self-test through CHIA,
and a documented GDS tool path.

### Sep 7-8: MAC and combined references

- Launch preregistered MAC ChiaMerge runs.
- Complete model-free MAC formal and negative controls.
- Implement and functionally verify ungated and gated dual-core FFT wrappers.
- Add matched activity windows.

Exit: at least one MAC accepted result or a complete negative run record; both
dual-core wrappers pass RTL functional tests.

### Sep 9-10: physical controls and PowerSave foundation

- Physically measure both dual-core variants.
- Finish attribution for standalone/shared/dual designs.
- Implement and unit-test domain-neutral ChiaPowerSave verdict, Pareto, archive,
  resume, and budget behavior.
- Freeze FFT PowerSave campaign inputs.

Exit: authoritative combined baseline JSONs and evidence-backed first
hypotheses.

### Sep 11-13: FFT power campaign

- Run parallel cheap candidate rounds and serial full physical evaluations.
- Apply one hypothesis per candidate.
- Run equal-budget shared and dual-core campaigns.
- Independently repeat any provisional best.
- Begin GDS stream-out on already frozen baseline layouts.

Exit: measured Pareto archive, exact failures, and at least one independently
repeated final FFT comparison point.

### Sep 11-14 in parallel: FIR PowerSave domain

- Freeze FIR contract, reference RTL, oracle, tests, and baseline physical
  result.
- Run deterministic corruptions.
- Launch bounded ChiaPowerSave campaign.
- Physically evaluate and independently repeat the best valid point.

Exit: one complete second-domain PowerSave result, positive or negative.

### Sep 14-16: GDS closure

- Stream final selected shared and dual-core GDS.
- Run independent DRC and LVS.
- Repair only genuine flow/layout issues; never weaken decks or waive unknowns.
- If time permits, finalize FIR GDS.

Exit: hash-pinned GDS plus exact DRC/LVS status and limitation record.

### Sep 15-17: thermal sensitivity

- Generate reconciled spatial power maps.
- Run HotSpot smoke, actual-footprint, fixed-footprint, transient, and parameter
  sensitivity cases.
- Produce comparative plots and machine-readable results.

Exit: reproducible comparative thermal result or a clearly documented blocked
reason. Thermal cannot block the core submission.

### Sep 17-18: independent release reproduction

- Kill all model workers.
- Re-run final functional/formal/GLS/physical/GDS gates from a clean evaluator
  snapshot.
- Verify hashes and result freshness.
- Generate final tables and figures only from machine-readable records.

Exit: release candidate and claim matrix.

### Sep 19: audit and buffer

- No new architecture campaign unless required to fix a release-blocking defect.
- Complete README, one-command reproduction paths, artifact index, failure log,
  and limitations.
- Audit the four-page paper against machine-readable results.

### Sep 20: submission

- Submit the paper and open-source artifact.
- Preserve an immutable submitted snapshot and hash manifest.

## 20. Priority and fallback ladder

### P0: required for the intended submission

- Complete reproduction artifact packaging.
- CHIA-native deterministic gates for FFT and MAC.
- MAC ChiaMerge run plus formal/negative controls.
- Physically measured ungated and gated combined dual-core FFT references.
- ChiaPowerSave implementation and at least the FFT campaign.
- GDS stream-out with exact independent DRC/LVS status.
- Final model-free reproduction and claim audit.

### P1: high-value

- FIR ChiaPowerSave result.
- Shared and dual-core equal-budget power optimization.
- Spatial HotSpot sensitivity.
- GDS/DRC/LVS for FIR.

### P2: stretch only

- Representative Neuropixels activity traces.
- OpenROAD PDNSim IR-drop sensitivity.
- Implant-like multilayer thermal model.
- Additional ChiaMerge or PowerSave repeats beyond preregistered budgets.
- Architecture-adaptive model-generated mutations.

If the schedule slips, drop P2 first, then FIR GDS, then advanced thermal
modeling. Do not drop matched power controls, correctness gates, independent
DRC/LVS status, artifact audit, or paper time.

## 21. Stop conditions

Stop a candidate immediately when:

- A protected hash changes.
- An unexpected helper file appears.
- Interface, anti-cheat, correctness, exact-cycle, formal, or GLS gates fail.
- A tool returns unknown, stale, incomplete, or unparseable output.
- Timing fails, TNS is nonzero, DRC is nonzero, STA-1452 appears, or activity
  coverage is invalid.
- A shared candidate falls below the preregistered area floor.
- A power result changes the workload, transform count, clock, constraints, or
  measurement window.
- Clock gating lacks characterized cells, generated-clock analysis, or clean
  gating checks.
- The full-physical budget is exhausted.

Stop a campaign for review when:

- Three consecutive full physical candidates are dominated for the same
  hypothesis family.
- Two independent attempts expose the same evaluator or infrastructure defect.
- A proposed optimization requires changing immutable behavior or constraints.
- Remaining time threatens final independent reproduction or paper completion.

Stop thermal claims when:

- Power cannot be spatially reconciled.
- Baseline and candidate require different undeclared package assumptions.
- Results depend on one unsupported tissue/package parameter choice.

## 22. Machine-readable artifacts

Every new experiment directory must contain, as applicable:

```text
preregistration.json
input_hashes.json
candidate_manifest.json
state.json
history.jsonl
gate_results.json
formal_result.json
synthesis_result.json
gls_result.json
physical_result.json
power_attribution.json
pareto_archive.json
gds_result.json
thermal_result.json
tool_lock.json
artifact_hashes.json
logs/
rtl/
netlists/
def/
spef/
gds/
reports/
activity/
plots/
```

Required provenance fields include:

- Source and candidate hashes.
- Prompt and model identifiers.
- Evaluator and hidden-test hashes.
- Tool and PDK versions.
- Constraint, testbench, VCD, netlist, DEF, SPEF, GDS, DRC deck, and LVS deck
  hashes.
- Freshness timestamps and run ID.
- Exact command and environment allowlist, with secrets redacted.
- Gate status and first failure.
- Accepted sample/transaction count and measurement duration.
- Model tokens/cost where available and physical wall time.

Human-readable prose and plots are generated from these records. They are never
the authoritative result.

## 23. Release claims by evidence level

### Already supportable after artifact synchronization

- The frozen ChiaMerge composition achieved `k/n = 3/3` clean-run acceptance on
  the 64/128 FFT merge.
- All accepted FFT candidates are bit-exact on the recorded holdout, meet exact
  71/137-cycle latency, close timing with DRC 0 in the current OpenROAD flow,
  and reduce placed cell area by 32-33% against the standalone placed-area sum.

### Supportable only after this campaign succeeds

- ChiaMerge works in a second MAC domain with randomized and formal evidence.
- ChiaPowerSave is reusable across FFT and FIR drivers.
- Shared versus dual-core chip area/power under a matched schedule.
- Verified amount of power recovered from the accepted shared architecture.
- GDS stream-out and exact independent DRC/LVS closure status.
- Comparative HotSpot temperature-rise sensitivity under declared assumptions.

### Forbidden without new evidence outside this plan

- HALO reproduction or HALO-equivalent workload behavior.
- Clinical task accuracy or benefit.
- Implant safety or compliance with thermal standards.
- Calibrated brain-tissue temperature.
- Silicon power, silicon timing, or measured thermal behavior.
- Tapeout-ready, signoff-complete, or multi-corner closure.
- A universal ChiaMerge or ChiaPowerSave success rate.

## 24. Definition of campaign success

### Minimum credible result

- Existing FFT ChiaMerge evidence is fully packaged.
- MAC ChiaMerge has one accepted formally checked result and unsafe controls are
  rejected.
- The combined dual-core FFT is physically measured.
- ChiaPowerSave evaluates at least one valid shared FFT power candidate under
  matched fixed workloads.
- Final FFT shared and dual-core layouts are streamed to GDS with exact DRC/LVS
  status.
- All claims and failures are reproducible from machine-readable artifacts.

### Strong result

- ChiaPowerSave independently reproduces a meaningful mode-64 and/or mode-128
  power/energy reduction while preserving at least 20% shared-area reduction.
- The power-managed shared and dual-core designs are compared under equal
  optimization budgets.
- The FIR driver runs unchanged through the same PowerSave primitive and
  produces a physically measured result.
- Final shared and dual-core GDS are independently DRC and LVS clean.
- Spatial thermal sensitivity explains the interaction among power, footprint,
  and local concentration.

### Stretch result

- Shared FFT meets both strict standalone per-mode power and finite-energy
  targets.
- FIR also yields a verified Pareto improvement.
- Representative neural activity and PDNSim are added as carefully bounded
  secondary analyses.

The campaign is scientifically successful even if strict power targets are not
met, provided the matched baseline, equal-budget optimization, Pareto frontier,
and negative result are complete and honestly reported.

## 25. Final paper narrative

The four-page paper should allocate attention in this order:

1. Problem: agents can propose hardware, but model statements cannot establish
   correctness or physical value.
2. Method: CHIA tool nodes plus transactional `ChiaIterate`, specialized as
   ChiaMerge and ChiaPowerSave.
3. FFT result: 3/3 preregistered merge reproduction and 32-33% area reduction.
4. Generality: MAC ChiaMerge formal result and FIR PowerSave result.
5. Physical result: matched dual-core baseline, power Pareto frontier, and
   GDS/DRC/LVS status.
6. Secondary context: comparative thermal sensitivity, if valid.
7. Limitations: clean-room isolation, one PDK/corner, power model, abort
   behavior, formal scope, thermal assumptions, and no silicon/clinical claim.

Suggested figures:

- CHIA composition graph showing model proposal nodes and deterministic tool
  gates.
- Transactional candidate promotion/rollback diagram.
- FFT and MAC acceptance/rejection table.
- Shared versus dual-core area/power Pareto plot before and after PowerSave.
- GDS image with exact DRC/LVS status.
- Optional thermal power-density/temperature sensitivity map.

Do not center token routing, model brands, or the number of prompts. Center the
composable loop, deterministic evidence, physical outcomes, and what failed.
