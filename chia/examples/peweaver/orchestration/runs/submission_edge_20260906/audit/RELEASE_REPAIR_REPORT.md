# Release Repair Report

**Release:** `submission_edge_20260906`  
**Repair date:** 2026-09-09  
**Scope:** read-only release hardening; no model campaign, physical rerun, VM operation, or RTL optimization.

## Result

The release outputs are regenerated from the archived evidence and pass the
fail-closed semantic verifier. Canonical S0/S1/A/B measurements remain
unchanged. S1 timing and router-DRC detail remain explicitly unknown.

The replay corpus contains 31 records: 22 defects and 9 legal records. Three
legal records have complete local evidence: S0, MAC M2, and MAC M3. The 22
defect records are not evidence-complete for a fresh nested replay statistic;
detection rates are withheld. The represented legal checks falsely reject
`0/3`.

## Checks

- Candidate and declared RTL dependency hashes are bound for S0, A, and B.
- Frozen corner, positive activity, finite PPA values, energy-duration
  consistency, and exact metric types are validated for direct physical results.
- S0 repeat evidence validates all 24 declared artifact hashes and sizes, the
  published and archived repeat result identity, direct primary/repeat metric
  agreement, timing/DRC/activity constraints, and GLS completion markers.
- S0 holdout evidence is bound to the current candidate path and 36-case report;
  the report's failed-case list must be empty for a passing holdout gate.
- MAC M2/M3 evidence validates candidate manifests, second-seed reports,
  required stimulus/capture files, seed `0x7EEDBEEF`, and candidate paths.
- Workload JSON/CSV/control tables and plotted Figure 1 data are independently
  recalculated and compared.
- The artifact inventory contains 558 records, 557 unique checked files, and
  one intentional duplicate path with identical expectations.
- Canonical, replay, workload, and figure regeneration is deterministic.
- All five SVGs parse as XML, contain one closing tag, and reject non-finite
  text; Figure 1 additionally passes plotted-point and axis checks. No SVG rasterizer is
  installed in this environment, so rendered visual inspection remains an
  explicit open limitation rather than a claimed review.
- The guard suite has one pytest test, 13 negative assertions covering malformed
  statuses, source/dependency/path corruption, fabricated summaries, duplicate
  workload points, stale manifests, missing evidence, and non-finite figure
  input, plus an unmodified-package positive assertion. `compileall` passes.
- A second complete generator pass produced byte-identical canonical, replay,
  workload, and five-figure outputs.

## Claim Boundary

This package does not claim independent streamed-layout DRC/LVS signoff,
multi-corner signoff, IR/EM, thermal silicon measurement, clinical validity,
or a sustained-stream energy result beyond the measured finite three-frame
windows. Variant B has no idle-only VCD and is excluded from sparse-duty
extrapolation.

## Validation Commands

```text
python3 -B audit/verify_release_consistency.py
python3 -B audit/test_release_guards.py
python3 -B audit/verify_artifact_index.py --root /home/peweaver-user/Documents/chialoop --manifest audit/artifact_index.json
```

All three commands pass for the current release tree.
