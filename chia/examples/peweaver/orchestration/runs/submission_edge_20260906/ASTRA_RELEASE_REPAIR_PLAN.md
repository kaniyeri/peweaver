# Astra Release Repair Plan

Date: 2026-09-09
Status: implementation handoff, not release approval
Audience: Luna and the operator

## 1. Goal and Boundaries

Repair the submission-edge release so that its generated tables, figures,
identity bindings, evidence ledger, and verification tools agree with archived
primary evidence. A successful checksum inventory is necessary but is not a
scientific validation or a complete reproducibility check.

Do not launch model optimization, change candidate RTL, change frozen physical
constraints, modify the frozen physical/tool-lock.json, or rerun physical design
as part of this repair. Local analysis and model-free tests come first. Starting
the existing VM is only a separately recorded step when a specific missing
artifact cannot be recovered locally.

Read the workspace AGENTS.md and the authoritative campaign plan before work:

- /home/peweaver-user/Documents/chialoop/AGENTS.md
- chia/examples/peweaver/orchestration/runs/merge_clean_1/FINAL_CAMPAIGN_PLAN.md

Preserve existing unrelated changes. The chia repository currently has unrelated
model/provider edits, and examples/peweaver is untracked in the observed git
status. Do not commit, discard, or stage the entire tree.

## 2. Paths and Command Roots

Use these exact roots. Confusing them caused repeated false missing-file errors
in the preceding session.

- Workspace root W: /home/peweaver-user/Documents/chialoop
- Git repository R: /home/peweaver-user/Documents/chialoop/chia
- PEWeaver root P: /home/peweaver-user/Documents/chialoop/chia/examples/peweaver
- Release root E: /home/peweaver-user/Documents/chialoop/chia/examples/peweaver/orchestration/runs/submission_edge_20260906
- Runs root: /home/peweaver-user/Documents/chialoop/chia/examples/peweaver/orchestration/runs

Paths below are relative to E unless prefixed with W, R, or P. The artifact index
currently stores paths beginning with chia/examples, so its --root must be W,
not R. Use explicit tool working directories; do not guess the current directory.

Known verification command, executable from any directory:

```sh
python3 -B /home/peweaver-user/Documents/chialoop/chia/examples/peweaver/orchestration/runs/submission_edge_20260906/audit/verify_artifact_index.py --manifest /home/peweaver-user/Documents/chialoop/chia/examples/peweaver/orchestration/runs/submission_edge_20260906/audit/artifact_index.json --root /home/peweaver-user/Documents/chialoop
```

## 3. Current State Is Not Approval

The existing guards pass ordinary inputs but have demonstrated semantic bypasses.
An in-memory test changed S0 canonical power to 999999 mW and changed replay
statistics to 22 evaluated defects with 100% detection; verify_release_consistency
still returned ok=true. No primary artifact was changed by that review test.

The current replay generator calls three legal records VERIFIED, but some
required passes and provenance are still declarations rather than verified
report-derived observations. Do not preserve a 3/9 or 0/3 headline by assumption.

The current archive contains 78 copied repeat-result files. All 24 artifacts
declared by s0_physical_repeat_sky130.json were checked against their hashes and
sizes after path rebasing. This does not establish that every required source,
tool input, or historical flow version has been archived.

The VM was last observed TERMINATED after artifact transfer. No further VM work
is necessary until local evidence discovery identifies a precise missing input.

## 4. Work Order

Execute A through H in order. Do not refresh the artifact index to hide a failing
semantic test. Do not mark the overall release complete merely because these
scripts return zero.

### A. Record Baseline and Reproduce Review Findings

Files:

- audit/verify_release_consistency.py
- audit/test_release_guards.py
- manifest/build_canonical_comparison.py
- replay/build_replay_corpus.py
- figures/generate_figures.py

Actions:

1. Inspect git status in R; leave unrelated edits alone.
2. Record existing hashes of files that will be edited and of primary source JSONs.
3. Run the existing guard tests, semantic verifier, and index verifier separately.
4. Add regression tests that reproduce the reviewed bypasses using in-memory
   objects or temporary directories. Never mutate the real primary artifacts.
5. Capture expected failing tests before fixing implementation.

Minimum initial regressions:

- Changed canonical S0 power must fail source-consistency validation.
- Invented 100% replay rates must fail recomputed-summary validation.
- A VERIFIED row with a missing or arbitrary verdict must fail validation.
- A missing candidate RTL or mismatched report identity must prevent VERIFIED.
- Duplicate workload points replacing missing combinations must fail.
- Figure 1 must contain every plotted point inside its plot bounds.
- Figure 2 overall denominator must be 22 for the present source summary.

Acceptance: the test failures reproduce the defects, without changing release
evidence or starting tools on the VM.

### B. Bind Canonical Measurements to Real Source Identities

Primary implementation: manifest/build_canonical_comparison.py
Verifier integration: audit/verify_release_consistency.py

Source files:

- manifest/phase_manifest.json
- P/orchestration/runs/merge_clean_1/shared_mergerun1_sky130.json
- P/orchestration/runs/merge_clean_1/peweaver_shared_fft.mergerun1.v
- P/orchestration/runs/ps_fft_campaign/artifacts/final_repeat.json
- P/orchestration/runs/ps_fft_campaign/artifacts/physical_turn4.json
- P/orchestration/runs/ps_fft_campaign/best/peweaver_shared_fft.v
- P/physical/results/dual_baseline_sky130.json
- P/physical/rtl/peweaver_ppa_dual_fft.v
- dual_b/results/physical_attempt2/dual_b_sky130.json
- dual_b/rtl/peweaver_ppa_dual_fft_icg.v

Actions:

1. Inspect the actual schemas, including physical source-hash maps and S1 best_hash.
2. For each S0/S1/A/B row, require agreement between the phase identity, SHA-256
   of actual archived RTL, and the corresponding identity in the measurement
   evidence. Do not treat candidate_hash=true alone as that agreement.
3. Validate SHA-256 as 64 lowercase hexadecimal characters, not just length.
4. Check the B rtl_path in the phase manifest. It currently names a physical/rtl
   path while the archive index names dual_b/rtl; use the actual matching source
   and disclose any path correction. Do not silently pick another file.
5. For wrapper-based controls, distinguish wrapper identity from complete design
   identity. Validate the declared dependent source hashes or disclose the narrower
   binding. One wrapper hash is not a hash of all underlying logic.
6. Reject strings/Booleans for numeric measurements, NaN, infinity, negative area,
   negative power/energy, and invalid integer DRC values. Require positive area.
   Validate timing as an actual Boolean when present, with missing detail explicit.
7. Recompute every comparison from validated source metrics. Derive or verify the
   standalone sum using the frozen FFT64/FFT128 baseline result files in
   P/physical/results, rather than trusting an unexplained constant.
8. Do not label a minimal metric record complete_physical_result. Define exactly
   what evidence was checked, or use a narrower source-record label.
9. Preserve S1 unknown timing/DRC detail until an actual linked detailed report
   is found. Search locally first. An aggregate successful final verification is
   evidence of that verification, not a numeric slack or a directly parsed DRC
   count. Do not invent detail or erase the historical acceptance record.

Implementation shape: expose a side-effect-free comparison builder returning
the expected object. Keep main responsible for writing JSON/CSV. The verifier
should compare released output to independently loaded/validated source data,
not only to another field copied from the same manifest.

Tests: wrong manifest hash, wrong source RTL, mismatched report hash, missing
dependency, duplicate design rows, extra/missing design, altered metric, altered
derived percentage, malformed types, nonfinite values, and changed CSV cells.

Acceptance: each mutation fails with a specific diagnostic; unmodified supported
measurements retain their values. Unknown fields remain unknown.

### C. Make Replay Evidence and Denominators Defensible

Primary implementation: replay/build_replay_corpus.py
Outputs: replay/corpus_manifest.json, replay/candidate_by_gate_matrix.json,
replay/candidate_by_gate_matrix.md, replay/detection_summary.json

Evidence starting points:

- P/orchestration/runs/merge_clean_1/check_turn32.json
- P/orchestration/runs/merge_clean_1/hidden_holdout_report.json
- replay/final_s0_hidden_holdout/hidden_holdout_report.json
- replay/s0_physical_repeat_20260909/s0_physical_repeat_sky130.json
- replay/s0_physical_repeat_20260909/physical_artifacts/results/logs/
- P/orchestration/runs/mac-merge-2/artifacts/check_turn1.json
- P/orchestration/runs/mac-merge-3/artifacts/check_turn1.json
- P/orchestration/runs/mac-merge-2/best/shared_mac.v
- P/orchestration/runs/mac-merge-3/best/shared_mac.v
- mac_hidden_judge/m2_fixed/hidden_judge_report.json
- mac_hidden_judge/m3_fixed/hidden_judge_report.json
- P/orchestration/runs/mac-mutants-1/mutation_report.json
- P/orchestration/runs/ps_fft_campaign/artifacts/check_turn*.json
- P/orchestration/runs/ps_fft_campaign/artifacts/physical_turn*.json

Actions:

1. Inventory what each report actually observes. Separate archived observations,
   source-code guard descriptions, and fresh executions. A report's existence is
   not proof it passed or belongs to the candidate.
2. Derive each evaluated gate status from a linked report. Remove hardcoded GLS,
   provenance, exact-latency, and other passes from evaluated evidence.
3. Bind report identities to candidate RTL hashes. Validate every evidence path
   required for a VERIFIED row, including MAC candidate files.
4. Read mapped GLS evidence explicitly for FFT; do not infer it solely from
   timing_met, activity count, or an aggregate ACCEPT verdict.
5. Extract exact latency from the relevant RTL holdout observations. Distinguish
   that contract from the mapped testbench's sampling/reset conventions.
6. Define required gates per domain. MAC/FIR do not acquire physical GLS or P&R
   evidence merely because a shared column is named Config 2 or Config 3.
7. Treat missing/invalid/unknown evidence as unevaluated or blocked, not a detected
   semantic defect. Infrastructure failure is not a successful defect rejection.
8. Keep evidence completeness separate from acceptance: a genuine failed gate can
   be fully evidenced. Conversely, an accepted candidate can have a partial local
   archive. Do not define VERIFIED to mean verdict==ACCEPT.
9. State denominator policy explicitly. For an ordered ladder, an observed failure
   with all required preceding gates documented can establish that ladder's rejection
   without running later gates. A counterfactual configuration is not observed just
   because another configuration rejected. Never require an unnecessary expensive
   rerun to improve a headline statistic.
10. If the current policy remains complete evidence for all nested configurations,
    disclose that narrow policy. Do not interpret excluded defect rows as missing
    all useful failure evidence or as evidence that the evaluator did not work.
11. Recompute per-stratum and overall counts, rates, and false rejections from the
    validated row verdicts. Count semantic REJECT separately from BLOCKED. Use null
    rates when denominators are zero. Do not count NOT_EVALUATED as caught.
12. Enforce unique IDs, recognized domains, expected labels, gate statuses, evidence
    statuses, and verdicts. Invalid objects/lists must not produce a passing result.

Tests: missing GLS report, failed GLS with physical success, missing RTL, wrong
hash, partial evidence with declared PASS, fake VERIFIED status, missing verdict,
unknown domain/status, contradictory ACCEPT and failed gate, changed denominator,
changed caught count, duplicate ID, and zero-denominator handling.

Acceptance: the published counts follow the actual evidence, even if fewer than
three legal rows qualify. Do not promise a numerical outcome in advance.

### D. Repair Workload Accounting, Coverage, and Labels

Implementation: workloads/workload_matrix.py
Outputs: workloads/workload_metrics.json, workloads/workload_metrics.csv,
workloads/breakeven_analysis.md, workloads/measured_control_comparison.csv

Actions:

1. Retain matching energy and duration windows: measured three-frame windows
   2.94 us and 5.52 us, or 0.98 us and 1.84 us per completed transform. Confirm these
   values against the primary records before treating them as authoritative.
2. Source full-precision energy/power values from validated canonical evidence
   rather than independently rounded constants. Preserve output rounding only
   at presentation boundaries.
3. Define alpha as duty fraction of the declared finite active windows. Define
   beta as transform-count occupancy. At alpha=1, call this back-to-back finite
   windows or zero additional modeled idle time, not an unlimited steady-state
   streaming energy measurement. Do not imply modeled schedules were simulated.
4. Validate finite alpha in (0,1], beta in [0,1], and recognized idle models.
5. Emit exactly 54 unique combinations: 3 idle models x 6 duty fractions x 3
   occupancies. Check the full expected tuple set, not global sets alone.
6. Recompute every energy/power row in the verifier and compare JSON and CSV.
7. Keep idle values explicitly sensitivity assumptions. A clock-network estimate
   is not automatically a proven lower bound for a different idle activity state;
   use assumption labels unless a bound is supported by relevant measurements.
8. Keep B out of sparse-duty extrapolation because its idle-only VCD is absent.
9. Recompute narrative savings ranges and the nominal 10% example from new rows;
   remove stale 35-40% or 39.9% literals where they do not match the stated scope.

Tests: all pure modes reproduce the declared finite-window ratios; mixed cases
use count-weighted energies and durations; alpha=1 adds zero idle energy; duplicate
points, missing points, malformed inputs, and altered CSV/JSON metrics are rejected.

Acceptance: 54 unique validated points, consistent labels, no unmeasured B idle
claim, and no mismatch between finite energy and the power denominator.

### E. Repair and Inspect Figures

Implementation: figures/generate_figures.py
Outputs: figures/fig1_workload_breakeven.svg, figures/fig2_evaluator_replay.svg
Other SVGs: validate without changing physical/thermal evidence unnecessarily.

Actions:

1. Figure 1: derive y-axis range from plotted values. The present nominal A value
   at 5% duty is 957.777 nJ; a 700 nJ axis sends it to y=-25.75 outside the viewport.
2. Sort points by duty fraction. Plot the explicitly selected idle model and label
   it. Derive savings annotations from that same selection.
3. Figure 2: use overall.total_defects for the overall denominator, not defects.
   The current code renders 0/0 under Overall (22).
4. Derive all labels, corpus totals, denominators, and footers from validated data.
   If retaining an evidence-coverage chart, label it as coverage, not detection.
5. Fail nonzero on missing required inputs rather than leaving stale figures in
   place after a silent return.
6. Validate XML and one closing SVG tag, then render/open SVGs and inspect bounds,
   clipped curves, label overlap, legends, and misleading zero-versus-unavailable
   representations. Valid XML alone is not acceptance.

Tests: original 957.777 nJ point fits the chart; modified fixture maxima rescale
correctly; a nonzero evaluated-defect fixture updates coverage/footers; empty or
malformed data fails; no NaN or infinity enters SVG coordinates.

Acceptance: every point is in bounds, denominators match JSON, and visual review
is recorded. Do not claim rendered review if only XML parsing was performed.

### F. Strengthen Release Consistency Verification

Implementation: audit/verify_release_consistency.py
Tests: audit/test_release_guards.py or small adjacent unittest modules

Required checks:

- Exact design row count and unique IDs before dictionary conversion.
- Canonical-to-primary identity and numeric consistency, including comparisons.
- CSV contents agree with JSON, not merely that CSV files exist.
- Corpus, matrix, and summary agree by recomputation, not fixed headline counts.
- Valid enums and exact types; malformed schemas produce a clear nonzero result.
- Evidence paths resolve within their declared roots and required references exist.
- Full workload tuple coverage and every modeled numeric result.
- Required generated figures exist and parse, plus testable plot-bounds checks.
- Repeated artifact hashes match original recorded hashes after explicit rebasing.

Avoid making the verifier enforce today's missing evidence forever. For example,
do not permanently require S1 timing_met is None; require it matches the evidence
available under the declared source contract. Likewise, do not hardcode current
0/22 coverage or the number of qualifying legal rows as the definition of validity.

Make tests discoverable by the repository's chosen test runner. The present script
only uses assertions in main and does not test the semantic verifier. Cover both
normal inputs and the mutations above. Prefer isolated fixtures and standard
unittest if no project-specific test setup is needed.

Acceptance: a normal generated package passes, every targeted corruption fails,
and no test rewrites the real package or silently blesses changed expectations.

### G. Reconcile Documentation and Remaining Provenance

Files:

- README.md
- PAPER_NARRATIVE_OUTLINE.md
- manifest/phase_manifest.json
- manifest/discrepancy_log.md
- replay/contract_to_evidence_index.json
- replay/s0_physical_repeat_20260909/s0_physical_repeat_audit.json
- replay/s0_physical_repeat_20260909/physical_artifacts/ARCHIVE_NOTE.md
- finalization/gds_roundtrip_audit.json
- finalization/layout_verification_status.json

Actions:

1. Correct README S0 setup/hold from primary timing fields; the previously
   identified values were +0.108688/+0.130449 ns, not fallback +0.13/+0.16.
2. Check S1 detail against recovered evidence; distinguish historical acceptance
   from locally available detailed measurements. Do not manufacture slacks.
3. Remove unsupported replay percentages and false-rejection denominators after
   C determines the supported rows. Do not replace one unsupported headline with
   a new fixed 0/3 headline.
4. Correct the contract index's exact-latency and independent layout-verification
   wording. It currently mixes RTL holdout latency with mapped GLS and historically
   said independent layout DRC had been checked. Preserve pending DRC/LVS status.
5. Keep phase_manifest explicitly post-outcome. Updating a date or version does
   not make the manifest a pre-outcome freeze or preregistration.
6. Reconcile GDS bounding boxes against actual die dimensions used for thermal
   calculations. A full-layout bounding box may include geometry outside DIEAREA;
   identify which geometry each number describes rather than forcing equality.
7. Record the repeat flow-script difference: primary S0 uses hash
   3d8e08b0463e4787bc98c5d1d93d156860dc6466628dc52f897a87f6a6b5e47d;
   repeat uses cf833c5866b326cccaf71362c0c534b6c5d1d4ff19951e084ef1cc506c6f7f83.
   Do not call these identical-flow runs. If historical script content is absent,
   say semantic equivalence of scripts has not been established.
8. Check all source inputs and tool/provenance files referenced by the repeat.
   The copied results directory does not itself contain the complete source tree.
   Preserve original result JSONs; add a local path-rebasing manifest rather than
   editing primary evidence to pretend it originally used local paths.
9. Fix README path typos such as matrix.json when the actual file is
   replay/candidate_by_gate_matrix.json. Distinguish paths relative to E versus P.
10. Search prose and figure generators for stale hardcoded claims after regeneration.

Acceptance: every headline has a source and a scope; unresolved items are listed
as open, not marked COMPLETE. The archive is described only as complete for the
specific files actually validated.

### H. Regenerate, Inventory, and Run the Final Audit

Regenerate in dependency order from E:

```sh
python3 -B manifest/build_canonical_comparison.py
python3 -B replay/build_replay_corpus.py
python3 -B workloads/workload_matrix.py
python3 -B figures/generate_figures.py
```

Run each command with failure propagation. Fix generator-owned contract prose
in the generator or its source, not only in output that regeneration will erase.

Inventory rules:

1. Preserve a before/after record of inventory changes. Do not blanket rehash
   primary evidence and treat a changed source as newly trusted.
2. Refresh hashes only for deliberately changed derived outputs, edited code,
   documentation, and newly archived files. Unexpected primary artifact changes
   are failures requiring investigation, not candidates for automatic refresh.
3. Include new tests, this plan, and any new provenance manifest in the release
   inventory if they are release deliverables. Do not add secrets, caches, or
   unrelated local files. Do not attempt to hash an index inside itself.
4. Keep exactly one size field per entry. The previous refresh accidentally
   added size_bytes alongside bytes and failed schema validation.
5. Preserve declared duplicate-path policy. The observed duplicate is B's wrapper
   listed both as a design and as a phase artifact; expectations must agree.
6. Report current counts from verification output, not the previous 547/546 count.

Final required checks:

- Guard regression suite passes, including semantic corruption tests.
- Canonical output matches validated sources and CSV serialization.
- Replay outputs and summaries match validated evidence and denominator policy.
- Workload matrix has the exact grid and matching calculations.
- SVG/XML checks and rendered visual review pass.
- Repeat declared artifacts validate against original hashes and sizes.
- Artifact index validates with --root W.
- A second generator run produces byte-identical derived outputs.
- No unrelated changes were reverted; no candidate RTL or frozen tool lock changed.

Run generators before the final inventory refresh. A successful final audit must
not be followed by an unrecorded edit or regeneration that invalidates its hashes.

Write a final report at audit/RELEASE_REPAIR_REPORT.md containing commands,
test counts, expected rejection cases, changed claims, inventory counts, remaining
gaps, and VM status if touched. Distinguish local consistency success from full
evaluator validity and from reproducibility-qualified acceptance.

## 5. VM Recovery Only If Necessary

Do not restart the VM merely to inspect files already in the local archive.
First list the exact missing relative paths, expected hashes, and why each is
needed. Check local archives and historical repository objects before recovery.

Allowed existing resource only:

- Project: peweaver-gcp-project
- Zone: peweaver-zone
- VM: peweaver-vm
- Repeat sandbox: /work/peweaver/runs/s0-independent-repeat-20260909
- Source checkout: /work/peweaver/source/chia

Lifecycle helper from R:

```sh
bash examples/peweaver/cloud_gcp/gcp-lifecycle.sh status
bash examples/peweaver/cloud_gcp/gcp-lifecycle.sh start
bash examples/peweaver/cloud_gcp/gcp-lifecycle.sh verify
```

Follow AGENTS.md for model-free preflight/local-smoke after starting, use IAP and
OS Login only, copy only required non-secret artifacts, verify transferred hashes,
stop Ray if running, stop the VM, and verify TERMINATED status. Do not run new
physical or model jobs to fill an archive hole without an explicit separate plan.

## 6. Stopping Rules and Honest Final Status

If primary identity cannot be bound, mark that row unverified and state the missing
binding. If historical report detail cannot be recovered, preserve the measured
values supported by available sources and label the missing detail. Do not guess.

If a verifier passes after a deliberate semantic mutation, its work package is
not complete. If generated output contradicts source data, do not repair only the
output. If the artifact index fails because the root is wrong, correct the command
root; do not rewrite all recorded paths.

The following remain separate scientific limitations even after local repair:

- Independent streamed-layout DRC/LVS is pending after KLayout startup failures.
- Dual B has no idle-only VCD and no recorded independent model-free repeat.
- S0 repeat is post-audit and non-preregistered, with a different flow-script hash.
- MAC formal evidence is bounded BMC depth 12; MAC/FIR counts are generic cells,
  not physical mapped-area results.
- No silicon, multi-corner signoff, IR/EM, clinical, or biological thermal claim.

Desired final outcome: a reproducible, evidence-scoped local package with tested
guards and explicit remaining gaps, not a stronger claim obtained by renaming
unknown statuses or refreshing hashes.
