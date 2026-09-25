# PEWeaver / ChiaMerge — state briefing for Sol (2026-09-04, evening)

Purpose: complete, self-contained context for a next-steps discussion. All claims
below are backed by artifacts on disk; hash-pinned where it matters.

## 1. What exists now

### Framework (chialoops-native, domain-neutral)
- `orchestration/chia_merge.py` (~700 lines): the primitive layer.
  - `ChiaAdvise` — read-only advisor (opencode permissions: edit/bash/webfetch denied).
  - `ChiaImplement` — reply-mode generator: model returns the complete file in one
    fenced block; controller writes it into the sandbox. Stateless, at-most-once.
  - `ChiaCheckCondition` — ordered gate ladder -> {ACCEPT, IMPROVE, REJECT, RETRY}
    with milestone levels; partial progress beyond best_level promotes (with the
    failing gate's note as feedback); RETRY = infra, does not consume the best.
  - `ChiaIterate` — transactional loop: fresh sandbox per turn (copied from best,
    blank on turn 1), promote-on-milestone-advance, discard otherwise, crash-safe
    promotion (state persisted before `best.prev` removal; `_recover_best` vouches
    from state), flock run lock with dead-owner takeover, atomic resumable state,
    per-turn advice threaded to the implementer.
  - `ChiaMerge` — thin composition: ONE architecture advise + ONE iterate.
  - Domain neutrality enforced by a unit test (zero benchmark vocabulary; prompts
    fully generic; per-domain knowledge lives only in drivers).
- `chia/models/opencode.py` hardening: process-group kill on timeout
  (start_new_session + killpg), export retry that NEVER re-runs the agent
  (ExportError; at-least-once mutation guard), explicit failure_reason metadata,
  session-id forensics, defensive export parsing.
- Tests: 96 passing (33 primitive/transaction tests incl. crash-recovery, lock
  takeover, resume, verdict semantics; opencode adapter suite; domain-neutrality guard).

### FFT experiment (complete, verified)
- Clean-room composition: inputs = pinned r22sdf references (FFT64/FFT128 + deps)
  + behavioral contract; NO candidate/seed/architecture doc visible to workers.
- Deterministic gate ladder: lint (anti-cheat + interface) -> bit-exact functional
  judge both modes (directed, from immutable script) -> full physical flow
  (Yosys -> Icarus GLS -> OpenROAD -> OpenSTA, sky130A, 10 ns) -> portfolio
  (timing met, DRC 0, area < 424,885 um^2 two-core sum).
- Discovery run `merge-clean-1`: accepted turn 32, area 286,970 um^2 (32.5% below
  baseline), power 39.82/40.44 mW (64/128), candidate sha `ce64c715...`,
  26.9 KB hierarchical design (8 modules). Model-free physical re-run: exact match.
- Hidden randomized holdout (`orchestration/hidden_holdout.py` +
  `physical/activity/hidden_holdout_tb.sv`): 36/36 bit-exact vs INDEPENDENT
  oracles (random frames, corners incl. +/-full-scale/impulse, 3-frame bursts
  with distinct frames, mid-frame reset recovery, abort+recovery, 64<->128
  switches), EXACT first-valid latency 71/137 asserted and met (a check the
  directed judge never made), exact N-wide pulses.
  Judge sensitivity: 4 deliberate corruptions caught (twiddle LSB x2, scale
  shift, counter off-by-one); two semantically-neutral mutation targets were
  discovered and replaced en route (documented).
- Documented deviation: garbage output pulse (N cycles) after an aborted partial
  frame — identical to the pinned reference behavior; spec clause never met by
  any design here; post-reset recovery bit-exact.

### Preregistered reproduction campaign (complete)
- Manifest BEFORE runs: `orchestration/runs/merge_repro_preregistration.json`
  (hashes of prompts/inputs/contract/gates/TB; models fixed: adviser
  `openrouter/openai/gpt-5.6-sol`, implementer `openrouter/google/gemini-3.8-flash`;
  budgets turns=32, advise 1500 s, implement 1200 s; acceptance = level 4;
  no-resume, fresh dirs).
- Results — **3/3 accepted**, each a DIFFERENT valid architecture:
  | run | accepted | area um^2 | vs baseline | inst | power 64/128 mW | sha prefix |
  |---|---|---|---|---|---|---|
  | merge-repro-1 | turn 10 | 283,464 | 33.3% below | 38,962 | 40.29/40.84 | `589585de` |
  | merge-repro-2 | turn 2 | 286,736 | 32.5% below | 39,826 | 40.02/40.63 | `e5f104b8` |
  | merge-repro-3 | turn 13 | 288,658 | 32.1% below | 39,928 | 40.45/41.08 | `150d5b25` |
  Holdout 36/36 on all three; mutation sensitivity: 4/5, 5/5-applied-caught, and
  3/5-applied-caught respectively (structure-specific mutation targets do not
  match every architecture's text; recorded honestly, not silently skipped).
  Turn variance: 10 / 2 / 13 (discovery run's 32 included framework debugging).
  Failure transparency: repro-3 spent turns 4-12 rejected/stalled; full histories
  in each run's artifacts.
- Prior human/model-iterated incumbent (`6a56b832...`, 315,359 um^2, 62.1 KB
  monolith) is dominated by all four candidates on area, power, and instances.
  It remains the frozen fallback until hidden-holdout claims are externalized.

### Second-domain MAC demo (assets + gates validated, run NOT started)
- `orchestration/mac_merge_driver.py` + `merge_benchmarks/mac_reference/`
  (answer-free references mac_a: accumulate lane, mac_b: product lane).
- Gates: lint -> functional (1200 randomized cycles vs pure-python oracle,
  incl. resets, en gaps, mode switches) -> structure (exactly ONE 8x8
  multiplier via yosys stat) -> area (synthesized gate count < two-reference sum).
- Selftest both directions: a correct shared one-multiplier design PASSES all
  four (44% below baseline gate count); the reference-mux control is REJECTED
  (3 multipliers). No-false-accept and no-false-reject demonstrated.
- Negative control planned per Sol's earlier advice: unsafe simultaneous-lane
  sharing must be rejected (contract forbids simultaneous use).

## 2. Claim boundary (what we may and may not say)
- Supported: "the preregistered composition achieved k/n = 3/3 clean-run
  acceptance on the FFT merge, with distinct valid architectures, all
  bit-exact (incl. exact-latency randomized holdouts), 32-33% below the
  two-core placed-area sum."
- Supported with caveat: per-mode power vs the STANDALONE FFT64 core (23.3 mW)
  is still worse in 64-mode; the shared-vs-two-core-CHIP power claim requires
  the combined dual-core baseline under a matched schedule (not yet built).
- NOT yet supported: second-domain generality (MAC run not executed);
  ablation attribution (which ingredient matters: adviser / reply-mode /
  inline sources / gate ladder); formal equivalence; GDS (we stop at placed
  STA + activity power); any thermal/clinical/silicon claim (out of scope).

## 3. Known weaknesses / risks
1. Clean-room is prompt+permission-based, not container-based: the adviser can
   technically read the run tree (which contains a copy of the prior accepted
   RTL under source/). Structural analysis exonerates current outputs (5.7%
   text similarity, disjoint modules, all candidates DIFFERENT from the
   incumbent), but a hostile reviewer can note the channel. True fix: separate
   checkout/container identity for the model worker (AGENTS.md wishlist).
2. Mutation targets are partly structure-specific; a second architecture may
   have fewer applicable mutations (recorded, but adaptive mutation generation
   would strengthen the holdout).
3. The abort clause of the spec is unmet by every design incl. the reference;
   holdout records it as a deviation rather than a failure.
4. Evaluator independence is procedural (controller-owned scripts), not
   two-identity; hidden vectors derive from the same oracles the fixtures use.
5. Single PDK/corner (sky130A tt_025C_1v80), single tool lock; area claims are
   placed-cell-area based; power is activity-based STA at the frozen corner.
6. Model/provider dependence: gemini-3.8-flash (implementer) and
   gpt-5.6-sol (adviser) via opencode/openrouter; glm-5.3-flash is unusable
   for long generations (route-specific drops, diagnosed via sibling probes).

## 4. Candidate next steps (pre-priced, in rough order of value)
A. **MAC merge run** — second-domain empirical generality. Assets done; one
   ChiaMerge call; expected hours. Produces "two domains, both accepted" or
   an honest failure report.
B. **Combined dual-core FFT baseline** (the two references muxed, same
   schedule/clock/IO) — enables the shared-vs-two-core-chip POWER claim and
   closes the biggest claim gap in the headline result. Physical flow exists;
   needs a wrapper + one physical run + a baseline JSON.
C. **Ablations** (one-variable-at-a-time on the frozen composition):
   no-adviser, agentic-implementer vs reply-mode, sources-not-inlined,
   no-feedback (feedback stripped) — quantifies which primitive carries the
   result. ~4 short runs + full gates each.
D. **Mutation-target generalization** — make holdout mutations
   architecture-adaptive (parse the candidate's table/counter idioms), so
   sensitivity is uniform across outputs.
E. **Formal equivalence** for the MAC domain (Yosys SAT miter vs references;
   small state space) — strongest possible second-domain evidence.
F. **Evaluator hardening**: separate worker/evaluator identities or
   containers; randomize hidden vectors controller-side per run.
G. **Writeup**: PE-reuse method section + reproducibility appendix (hashes,
   preregistration, per-run diversity, deviation log).

## 5. Questions for this discussion
1. Priority order among A-G given a hackathon deadline — which single result
   most strengthens the submission: second domain (A), the power claim (B),
   or attribution (C)?
2. For B: is a mux-of-references dual-core baseline with clock-gating of the
   inactive lane the right control, or do we owe a duty-cycle sweep?
3. For A: should the MAC demo also run the negative control (unsafe
   simultaneous sharing must be REJECTED by gates) as part of the headline,
   or is the gate-selftest sufficient evidence?
4. Do we freeze now (hash the current composition and write the method text)
   or after A/B? What minimum evidence do we owe the "frozen" adjective?
5. Any red flags in the deviation/leakage sections above that must be fixed
   BEFORE more model runs (vs documented and deferred)?

---

## Addendum 2026-09-05: final-campaign batch results (in progress)

Executed per `FINAL_CAMPAIGN_PLAN.md` with the preregistration frozen before
any outcome was viewed. Sol review of the new code was run BEFORE the batch
and all CRITICAL/HIGH findings were fixed first.

New verified results (VM, frozen composition):

1. MAC second-domain ChiaMerge, 6-gate ladder: clean starts 2 and 3 both
   ACCEPTED on turn 1 with distinct candidates; the pilot run-1 candidate
   separately re-evaluated 6/6. Negative controls and the six-mutation
   suite behave exactly as expected. Two domains now have accepted merges;
   MAC carries randomized + directed + bounded-formal evidence.
2. ChiaPowerSave implemented and unit-tested (19 tests) as the second
   specialization over the same transactional semantics; not yet run on a
   physical campaign.
3. Ungated dual-core FFT reference physically measuring (backend DRT in
   progress at the time of writing); result JSON pending.
4. Evidence archives: preregistration + 19 frozen inputs, VM evidence
   pulled and hash-pinned (13 artifacts), audit command passes.

Claim-status changes: "ChiaMerge works in a second domain" is now
supported (with bounded-formal caveat); "k/n for the frozen 6-gate MAC
composition" is supported as 2/2 clean starts (+1/1 separate re-eval of the
pilot). Do not claim unbounded formal proof. MAC 'area' claim is generic
cell-count reduction, not mapped area.

Remaining for the campaign: dual physical result + independent repeat,
ChiaPowerSave FFT campaign, GDS/DRC/LVS closure, FIR second PowerSave
domain, thermal sensitivity (P1/P2 per plan).

---

## Addendum 2026-09-06: campaign status — all P0 experiments executed

Complete campaign state after the Sep 5-6 batch:

| Experiment | Status | Result |
|---|---|---|
| FFT merge discovery + 3/3 preregistered repro | DONE | 32-33% placed-area reduction each, physical |
| MAC merge (2/2 clean starts + pilot re-eval, 6-gate ladder) | DONE | 44% generic-cell reduction, bounded formal |
| FIR third-domain merge (stateful two-context) | DONE | accepted turn 1, 8 mults, 11.6% below |
| Ungated dual-core control (variant A) | DONE + REPEATED | 429,130 um^2, 61.5/61.4 mW — exact deterministic repeat |
| Synthesis-only sharing control | DONE | plain yosys does NOT share (967 vs 531 cells) |
| Power attribution (fallback F, mode-64) | DONE | 49.1% sequential cells, 40.0% clock network; not 49% clock tree alone |
| ChiaPowerSave FFT campaign | DONE | PARETO area gain (−1.4%), small raw single-run power deltas, targets not met; 3/5 candidates timing-rejected |
| ChiaPowerSave implementation + tests | DONE | domain-neutral, 19 tests, verify_final passed |
| Framework hardening (astra review) | DONE | reject-preserve, eval retry, permissions, fingerprints |

Combined-chip claim now fully supported: shared vs ungated dual-core
(matched schedule, both physically measured, control exactly repeated):
area 286,970 vs 429,130 (33.1% below), p64 39.82 vs 61.52 (35.3% below),
p128 40.44 vs 61.45 (34.2% below).

Variant B is now complete as the first valid power-managed dual control after
two attempts: 429,655 um^2, 23.387/41.712 mW, 22.919/76.750 nJ, timing met,
TNS 0, DRC 0. It is not an area win (+0.12% vs Dual A), has no idle-only VCD,
and has no independent model-free repeat. GDS stream-out plus S0/A round-trip
audits are complete; independent streamed-layout DRC/LVS remains pending after
pinned KLayout startup failures. Remaining paper work includes the no-feedback
ablation decision, second-seed FIR judge, final model-free reproduction sweep,
and 4-page paper. The power story is negative-and-honest for model-driven S1,
while B supplies a measured continuous-streaming power control.
