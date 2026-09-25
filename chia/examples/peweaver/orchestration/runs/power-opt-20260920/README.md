# Supplemental Parent Optimization Trace

## Status And Scope

`power-opt-20260920` is a supplemental `ParentOptimization` experiment. It is
not a clean-room `MergeDiscovery` run, not a `ChiaPowerSave` Pareto campaign,
and not a replacement for the frozen S0/S1/A/B comparison in the reviewer
guide.

The parent RTL came from turn 12 of the infrastructure-failed
`merge-clean-20260919-newarch` run. That discovery run did not accept a
candidate. Its controller artifacts, controller log, and turn-12 candidate are
archived under [`precursor/`](precursor/); complete per-turn physical bundles
are not. The recovered RTL was therefore admitted only after an explicit
model-independent parent attestation through the full four-gate ladder.

## Lineage

| Stage | RTL SHA-256 | Workspace SHA-256 | Verdict | Physical summary |
|---|---|---|---|---|
| Recovered parent / turn 0 | `23d4bfc118031b399aaabd8765737ada164e9cd385fd40b32f33dd38eb0ce1f1` | `6dd02d11b2e2702aac60def113a6e517959a2fe4480e5ebe44be6c4f61d7e7b6` | `ACCEPT`, level 4 | 288,084 um^2; setup/hold +0.234613/+0.188090 ns; TNS 0; DRC 0; 40.20143/40.88026 mW |
| Optimization turn 1 | `ddb3b0c12e1a3e162910df12c1f022838260611da5c74898f8a4b47776db9793` | `a773e03da1a458e3882cf994b7dc4042d3a0aebf9d6da1fe02de8e01f8b34265` | `REJECT`, level 3 | 316,256 um^2; setup -0.628614 ns; TNS -2.670632 ns; DRC 0; 39.93130/42.14808 mW |
| Optimization turn 2 | `be7448b949f5054391fe86a419506e3192f8296d4fdeb216949d44116dbd7a9b` | `045997605d55b845d843d9c9b5bc9502feaa1fc85b2cd3b3499e30398cee576c` | `ACCEPT`, level 4 | 287,829 um^2; setup/hold +0.209636/+0.140547 ns; TNS 0; DRC 0; 40.28173/41.00391 mW |

Turn 1 demonstrates fail-closed physical feedback: it passed lint, functional,
and physical execution but the portfolio gate rejected its negative setup
slack. Turn 2 restored timing and reduced parent area by 255 um^2 (0.09%). Its
mode-64 and mode-128 streaming-power estimates are respectively 0.08030 mW and
0.12365 mW higher than the parent, so this experiment establishes no
parent-relative power reduction.

The turn-2 area is 32.26% below the 424,885 um^2 sum of the two standalone
placed baselines. That denominator is a sum, not a placed dual-core chip. The
physically measured Dual A control remains the appropriate combined-chip
comparison. Turn 2 is also worse than frozen S0 in both area and per-mode
power, so it is not promoted into the canonical result table.

## Hash Semantics

The `state.json` history and `best_snapshot.json` `hash` fields are hashes of
the complete attempt workspace manifest. The `candidate_sha256` fields in the
check files are hashes of the candidate RTL file. They are deliberately
different identities.

## Evidence Index

| Evidence | Path |
|---|---|
| Controller checkpoint and chronology | [`artifacts/state.json`](artifacts/state.json) |
| SQLite attempt lineage | [`artifacts/lineage.sqlite3`](artifacts/lineage.sqlite3) |
| Parent attestation | [`artifacts/check_parent.json`](artifacts/check_parent.json) |
| Timing-rejected turn 1 | [`artifacts/check_turn1.json`](artifacts/check_turn1.json) |
| Accepted turn 2 | [`artifacts/check_turn2.json`](artifacts/check_turn2.json) |
| Adviser analyses | [`artifacts/advice_turn1.md`](artifacts/advice_turn1.md), [`artifacts/advice_turn2.md`](artifacts/advice_turn2.md) |
| Candidate manifests | [`artifacts/manifest_turn1.json`](artifacts/manifest_turn1.json), [`artifacts/manifest_turn2.json`](artifacts/manifest_turn2.json) |
| Recovered parent RTL | [`candidates/recovered_parent_23d4bfc1.v`](candidates/recovered_parent_23d4bfc1.v) |
| Timing-rejected turn-1 RTL | [`candidates/rejected_turn1_ddb3b0c1.v`](candidates/rejected_turn1_ddb3b0c1.v) |
| Accepted turn-2 RTL | [`best_peweaver_shared_fft.v`](best_peweaver_shared_fft.v) |
| Failed discovery precursor | [`precursor/artifacts/state.json`](precursor/artifacts/state.json), [`precursor/artifacts/check_turn12.json`](precursor/artifacts/check_turn12.json), [`precursor/controller.log`](precursor/controller.log) |
| Hash/size inventory | [`primary_artifact_index.json`](primary_artifact_index.json) |
| Concise controller log | [`power-opt-20260920.log`](power-opt-20260920.log) |

The archived SQLite file predates the subsequent lineage-schema hardening that
adds explicit per-attempt base-workspace, candidate-RTL, and checkpoint
columns. The same identities remain recoverable here from `state.json`, the
candidate manifests, and the three check files; the historical database is
not rewritten after the fact.

## Evidence Gaps And Claim Boundary

- The precursor controller evidence is archived and proves that discovery
  ended `accepted=false` after repeated physical infrastructure retries. It
  still cannot establish a successful clean-room discovery.
- Full per-turn synthesis, OpenROAD, OpenSTA, GLS, VCD, DEF, and SPEF bundles
  were retained on the campaign VM but were not copied into this checkout.
  The check files contain the controller-consumed summaries and RTL hashes.
- A 36-case exact-latency hidden holdout and five-mutant sensitivity check were
  rerun on turn 2 during post-run review, but their raw trace is not archived
  here. They are not used as primary release evidence for this supplemental run.
- The measurements are single-run, nominal-corner, open-source estimates.
  Router DRC is not independent streamed-layout DRC/LVS. There is no
  multi-corner signoff, IR/EM, thermal, silicon, HALO, or clinical claim.
- No independent model-free repeat of turn 2 is archived. Acceptance means the
  configured four-gate ladder passed, not reproducibility-qualified promotion.
