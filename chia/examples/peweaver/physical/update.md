# PEWeaver Session Status — 2026-08-31 / 09-01

> Historical experiment chronology. The VM and `cloud_gcp/` commands below
> refer to operator material removed from the public release and are not
> runnable from this repository.

## RESTART HANDOFF (written 2026-09-01 evening, VM stopped)

### Where things stand

1. **The native CHIA loop is live and proven.** `orchestration/peweaver_chia_graph.py`
   was rebuilt on chialoops machinery: `OpenCodeLLM` (CHIA's own adapter,
   already a `@ChiaFunction` node with `opencode_creds` resource) for model
   turns, `@ChiaFunction(resources={"yosys": 1})` nodes for lint/functional/
   physical gates, driver = the loop file, submitted against a Ray head.
   End-to-end probe passed on the VM (`PROBE_OK` via openrouter glm-5.3-flash).
2. **Run `chia-native-1`** (state preserved under `/work/peweaver/runs/chia-native-1/`):
   - Plan turn: openrouter `gpt-5.6-sol` returned an EXCELLENT 3-cause plan
     (`artifacts/lead_plan.txt`): s1_cnt wraps at 127 not 63 in 64-mode;
     s1/s2 twnum shift errors; s3_muen multiplies on unity twiddles + ROM
     placeholder entries. Delay taps confirmed correct.
   - Operate turn 1: openrouter `glm-5.3-flash` burned ~45 min (timeout) but
     left real edits — staged candidate grew 49,644 → 50,693 bytes.
   - Attempt 2 (fresh session, same prompt) was re-deriving from scratch —
     killed; driver state paused before judging attempt-1's edits.
3. **Diagnosis (user-confirmed)**: the loop unit was too big. One turn = one
   giant blind session (45 min, no judge signal). Judge feedback must arrive
   between SHORT bursts.

### Run-2 redesign (already edited locally in peweaver_chia_graph.py — NOT yet synced to VM)

- `--worker-timeout 900` (default now), `retries=1` (no blind identical retry)
- `--turns 10`; one-hypothesis-per-turn prompts cycling the lead plan's items
  (falls back to a known-defects list)
- Judge feedback (lint errors / bit-exact mismatch signature / physical tail)
  attaches to the NEXT turn's prompt
- `--resume` flag: keep the existing staged candidate (50,693-byte GLM work)
  instead of reseeding

### Restart procedure (when the operator says go)

```sh
bash chia/examples/peweaver/cloud_gcp/gcp-lifecycle.sh start
gcloud --project=peweaver-gcp-project compute ssh peweaver-vm \
  --zone=peweaver-zone --tunnel-through-iap
# on VM:
source /work/peweaver/toolchains/miniforge3/etc/profile.d/conda.sh && conda activate chia_env
export PATH=/home/peweaver-user/.opencode/bin:/work/peweaver/toolchains/oss-cad-suite/bin:$PATH
ray start --head --port=6379 --resources='{"yosys": 1, "opencode_creds": 1}'
# sync the updated local orchestration/ first (tar-over-ssh as before), then:
cd /work/peweaver/source/chia/examples/peweaver_deployed
export PYTHONPATH=/work/peweaver/source/chia
nohup python3 orchestration/peweaver_chia_graph.py --run-id chia-native-2 \
  --turns 10 --plan --resume > /work/peweaver/runs/chia_native_2.log 2>&1 &
# NOTE: --resume only helps if reusing chia-native-1's stage; for a fresh run
# id use a fresh stage (no --resume) and consider --worker-timeout 900.
```

Stop Ray + stop the VM via `gcp-lifecycle.sh stop` when done. Never delete
the VM or disks.

### Campaign model config (final, operator-set)

- plan: `openrouter/openai/gpt-5.6-sol` via opencode (their $25; Sol sub capped)
- operate: `openrouter/z-ai/glm-5.3-flash` via opencode ($0.075/M — agentic
  editing through the opencode harness; fallbacks `opencode-go/glm-5.3-flash`
  on their $10 sub, `opencode-go/deepseek-v4-flash` proven editor)
- All provider logins live in the VM user's opencode auth; no keys in the
  repo; Ray advertises `{"yosys": 1, "opencode_creds": 1}`.

### Earlier verified state (unchanged)

Accepted shared candidate (Luna-compacted, SHA-256 `6a56b832…`): 315,359 µm²
placed (25.78% reduction), bit-exact both modes, GLS pass, timing MET, DRC 0.
Frozen records: `physical/results/shared_baseline_sky130.json`. The retired
44% estimate and the 414,157 µm² simple_map run remain historical.

---

## Executive Summary (updated 2026-09-01)

Two frozen matched baselines (FFT64 and FFT128) delivered through a real
open-PDK physical/power pipeline. **Shared configurable FFT candidate is now
BIT-EXACT in both modes** (Sol/GPT via opencode fixed the RTL). A Sep 1 Luna
optimization compacted the six paired mode-specific delay banks and
**completed the defined frozen-corner physical flow**: 315,359 µm² placed, timing MET,
0 DRC, GLS golden PASS on the mapped netlist, result JSON frozen
(`shared_baseline_sky130.json`, schema peweaver-physical-result-2).

### The honest shared-candidate result (Sep 1)

| Metric | FFT64 | FFT128 | Shared 64-mode | Shared 128-mode |
|---|---|---|---|---|
| Placed cell area | 164,408 µm² | 260,477 µm² | 315,359 µm² | (same die) |
| Streaming power | 23.314 mW | 41.040 mW | 40.013 mW | 42.162 mW |
| E/FFT (3-frame burst) | 20.40 nJ | 71.20 nJ | 39.21 nJ | 77.58 nJ |

- Area reduction vs standalone sum (424,885 µm²): **25.78% placed / 24.73%
  synth**. This is a real bit-exact saving, but still below the retired 44%
  broken-RTL estimate.
- Energy per transform is now **1.92x the FFT64 baseline / 1.09x the FFT128
  baseline**. Delay-bank compaction cut shared power by 27.4% in 64 mode and
  26.4% in 128 mode versus the first correct shared implementation; remaining
  overhead includes mode muxing/control and ungated active state.
- The hard part (bit-exact mode-muxed r2²SDF plus the defined synth → GLS →
  OpenROAD timing/DRC/power flow at the frozen sky130 corner) is DONE. Two
  complete no-model runs reproduced the pre-compaction implementation. The
  compacted result has one complete fail-closed run and still needs an
  independent second run for reproducibility parity. This remains a
  provisional feasibility result, not multi-corner signoff or silicon power.

### Sep 1 optimization-loop result

- The hardened CHIA/Direct-Gemini controller correctly reused the validated
  initial physical result, handed the measured objective miss to Gemini, and
  protected every judge/flow input. One 30-minute generation was externally
  interrupted after the adapter's timeout defect was discovered; a bounded
  retry hit its 8K output ceiling. Neither of those first two calls changed
  the RTL or protected inputs. A third low-thinking attempt did edit the RTL,
  but applied the requested stage-3 assignment too broadly; the immutable
  judge rejected it, no physical run was launched, and the accepted Luna
  candidate was restored. The rejected edit did not enter the frozen result.
- The adapter now passes its timeout into the Gemini SDK, records interrupts,
  supports low/medium/high thinking control, and has bounded model-token,
  retry, and tool-iteration arguments. Offline adapter suite: 42 passed, 11
  live tests skipped after the final low-thinking patch.
- The controller now restores the last functionally passing RTL immediately
  after a rejected edit, restores changed protected inputs, and safely handles
  missing, symlink, FIFO, or directory replacement without following the
  model-created path. The orchestration safety suite passes all 14 tests.
- A Luna subagent then performed the exact controller-planned six-bank
  compaction. The immutable judge, mapped-netlist GLS, P&R, timing, DRC, VCD
  normalization/activity, and power stages all passed on the cloud VM.

### Key engineering findings from the Sep 1 no-model validation

1. **abc vs simple_map (root cause found)**: the shared RTL uses `x` as
   don't-cares for the inactive mode. `abc -liberty` exploits them for
   optimization; `setundef -zero` then pins them to 0 → netlist NOT
   equivalent under the x→0 two-state policy (GLS fails with 11/64 + 11/128
   mismatches — identical signature to the old broken-RTL runs).
   `synth/sky130_simple_map.v` (one-for-one generic→sky130 gate mapping,
   no abc) preserves RTL semantics and is **correct and required**.
   The abc netlist synthesizes only 2.4% smaller (348,091 vs 356,628 µm²)
   and is functionally wrong — not a real saving.
2. **Leakage record is design-independent**: results/leakage_check/
   nand2_leakage_check.json (made locally with ngspice) is required by
   assemble_results.py for every design. Copied to the VM; stage 4 then
   completed standalone with the env exports from run-physical.sh lines
   260–281 (no full-flow rerun needed).
3. **tmux `echo $?` after a pipeline gives tee's exit code** — capture the
   script exit separately (`cmd; echo EXIT_$?` without the pipe).

---

## SUCCESSES

### 1. FFT64 baseline — FROZEN ✓
- Synthesis: 16,037 cells / 141,236 µm²
- Routed: 21,791 instances / 164,408 µm² / 47% util
- Timing: MET, setup +0.867 ns, min +0.099 ns, TNS 0 (propagated clocks)
- Power: 23.314 mW streaming (VCD-normalized, no silent-prefix dilution)
- E/FFT: 20.40 nJ (finite 3-frame burst, fill+drain included)
- DRC: 0 violations
- GLS golden: PASS (bit-exact on mapped netlist, 53,086 pins annotated)
- Reproducibility: 2+ runs identical (clean1 = clean2, all metrics)
- STA-1452: absent (VCD normalizer fixed the clock period inference)
- Reset: recovery +8.94 ns, removal +0.33 ns (sync-deassert wrapper)

### 2. FFT128 baseline — FROZEN (1 complete run, 2nd was interrupted)
- Synthesis: 22,617 cells / 218,887 µm²
- Routed: 31,658 instances / 260,477 µm² / 48% util
- Timing: MET, setup +0.122 ns, min +0.201 ns, TNS 0 (propagated clocks)
- Power: 41.040 mW streaming (VCD-normalized)
- E/FFT: 71.20 nJ (finite 3-frame burst, fill+drain included)
- DRC: 0 violations
- GLS golden: PASS (74,985 pins annotated)
- STA-1452: absent

### 3. FFT128 reference + oracle (Phase 2) ✓
- `fft128_oracle.py`: bit-exact vs both goldens, no file I/O, 296 lines
- `fft128_regression.py`: directed Verilator regression, PASS
- `test_fft128_oracle.py`: 20 tests (latency 137, twiddle coverage, streaming)
- `test_fft128_regression.py`: 10 tests
- Third-party provenance: FFT128.v + Twiddle128.v hashed and curated
- Twiddle128 table: 128 entries extracted, 64 xxxx → 0 (never selected)
- Twiddle identity verified: 31/31 defined W64 entries match W128 even entries

### 4. Infrastructure built ✓
- `vcd_normalize.py`: shifts VCD timestamps to #0, validates clock period,
  fail-closed, integrated into run-physical.sh
- Icarus GLS always-rebuild (no stale cache)
- STA-1452 fail-closed check in run-physical.sh
- `insert_tiecells sky130_fd_sc_hd__conb_1/LO` (constant nets)
- `filter_liberty.py`: excludes probe/lpflow cells (36 removed)
- Post-global-route `repair_timing -setup` iteration
- `assemble_results.py --design fft64|fft128` (parameterized)
- Design-scoped artifacts: fft64 and fft128 never clobber each other
- Absolute paths throughout (no cwd-dependent failures)
- `ACTIVITY_SOURCES` array per design (correct sources for each)

### 5. Corrected energy accounting ✓
- RETIRED: 14.92 nJ (fft64) and 52.53 nJ (fft128) — these used
  `Pavg × frame_cycles` which is wrong (the VCD window includes fill/drain)
- CORRECTED: 20.40 nJ (fft64) and 71.20 nJ (fft128) — computed as
  `Pavg × VCD_window_duration / 3_frames`
- Definition: "finite 3-frame window energy per transform" — includes
  pipeline fill and drain; NOT sustained steady-state
- VCD window: fft64 = 262 cycles (2.62 µs), fft128 = 520 cycles (5.20 µs)

### 6. Methodology corrections ✓
- External async reset: treated as intentional asynchronous boundary,
  NOT timed with the 1.5 ns input delay
- Synchronized reset release: recovery/removal reported separately
- Placed cell area vs die/core footprint distinguished
- Leakage: Liberty-vs-SPICE discrepancy described honestly (NOT calibration)
- 0 STA-1452 warnings in both backend logs

### 7. Shared candidate design derivation ✓
- Full per-stage parameter map (all mode-muxed signals documented)
- Twiddle identity verified: 31/31 defined W64 entries match W128 even entries
- W64 xxxx entries map to 128-pt entries that are xxxx or unused
- Complete twiddle ROM bodies generated (64-entry + 128-entry)

### 8. Gemini loop prompt hardened ✓
- Reference-first approach (agent studies SdfUnit.v, NOT handed answers)
- Edit scope restricted to peweaver_shared_fft.v only
- Protected file list enforced (shared_activity_tb.sv, regression script, etc.)
- Judge tampering detection working (blocked Gemini when it tried to edit TB)

---

## FAILURES

### 1. Historical shared FFT RTL mismatch ✗ → FIXED
- 64-point mode: 32/64 mismatches (first frame), do_en gap at frame boundary
- 128-point mode: 53/128 mismatches
- The mode-muxed delay-buffer read tap approach does NOT correctly
  replicate the r2²SDF feedback timing for the 64-point case
- Root cause: butterfly x0 uses fixed `buf[63]` instead of mode-muxed tap
- Additional issues: counter doesn't wrap at 64 in 64-mode, mj uses wrong
  counter, twiddle select/number/address formulas wrong for 64-mode,
  bf2_start registration differs from upstream, stage-3 multiply enable
  wrong, extra multiplier output register in 64-mode stage 3
- STATUS: **FIXED** — the corrected candidate passes the immutable 64- and
  128-point single-frame and continuous-frame regression. These mismatch
  counts describe the superseded candidate, not the current RTL.

### 2. Historical Gemini repair loop stall ✗ → CONTROLLER FIXED
- gemini-3.1-pro-preview ran for 1.5+ hours without completing iteration 1
- Root cause: initial regression ALREADY PASSES on the VM (candidate is
  functionally correct with iverilog), so the model has nothing to fix
  but keeps exploring/reading in a loop
- `max_tool_iterations = 80` is too high
- The old controller had no useful transition from "initial regression
  passes" to physical-objective optimization.
- STATUS: **FIXED IN CONTROLLER** — the bounded controller now evaluates the
  passing candidate physically, gives Gemini measured area/power objective
  feedback, limits tool/model iterations and output, enforces the SDK timeout,
  rejects duplicate candidates, records interrupts, and fails closed on
  evaluator errors. The first two Sep 1 paid attempts produced no accepted
  edit. The third low-thinking attempt produced a candidate that the immutable
  judge rejected; the accepted Luna candidate was restored, and no rejected
  candidate contributed to the frozen result. The successful compacted RTL
  came from Luna and passed the same outer judges.

### 3. Gemini modified test harness (judge tampering) ✗
- Iteration 1 of the first Gemini run modified `shared_activity_tb.sv`
- The loop correctly detected this and blocked the run
- STATUS: **FIXED** — prompt hardened, protected files enforced

### 4. Shared activity TB doesn't drive input frames ✗
- The original shared_activity_tb.sv never asserted di_en
- It only checked idle output (which is trivially zero)
- STATUS: **FIXED** — replaced with real TB that drives frames

### 5. Historical shared physical-flow functional-gate failure ✗ → FIXED
- The fail-closed flow correctly rejected the superseded candidate.
- The corrected candidate now passes RTL regression, mapped-netlist GLS,
  OpenROAD place-and-route, propagated setup/hold timing, DRC, normalized-VCD
  activity checks, and OpenSTA power in two complete no-model runs.
- STATUS: **FIXED** — frozen result is `shared_baseline_sky130.json`.

### 6. VCD silent-prefix dilution ✗ → FIXED
- Original VCDs started at t=3415000 ps (fft64) / 7915000 ps (fft128)
- OpenSTA inferred 23-25 ns clock period instead of 10 ns
- Fixed with vcd_normalize.py (shifts to #0, validates period)
- STATUS: **FIXED**

### 7. Icarus GLS stale cache ✗ → FIXED
- The executable-exists check reused old binaries even after TB changes
- Led to wrong activity data
- Fixed: always-rebuild policy
- STATUS: **FIXED**

### 8. Verilator GLS incompatible with sky130 models ✗
- Verilator mishandles sequential UDP flops (dfrtp cells stuck)
- The FUNCTIONAL define + UNIT_DELAY workaround doesn't fix all cases
- Fixed: use Icarus Verilog for all gate-level simulation
- STATUS: **FIXED** (documented, iverilog used instead)

### 9. Stage-1 compile missing core RTL files ✗ → FIXED
- The stage-2 compile only included the wrapper, not the core RTL files
- CORE_RTL was defined but never passed to the Verilator command
- Fixed: ACTIVITY_SOURCES array with complete per-design file list
- STATUS: **FIXED**

### 10. fft64 record polluted by fft128 run ✗ → FIXED
- Pre-RPT_TAG fft128 backend overwrote untagged fft64 report files
- Fixed: RPT_TAG design-scoped report names, design-scoped ODB/VCDs
- STATUS: **FIXED**

---

## MATCHED BASELINE SUMMARY (corrected)

| Metric | FFT64 | FFT128 |
|---|---|---|
| Placed cell area | 164,408 µm² | 260,477 µm² |
| Streaming power | 23.314 mW | 41.040 mW |
| E/FFT (finite 3-frame burst) | 20.40 nJ | 71.20 nJ |
| Setup WNS (propagated) | +0.867 ns | +0.122 ns |
| Min WNS | +0.099 ns | +0.201 ns |
| DRC | 0 | 0 |
| GLS golden | Pass | Pass |
| STA-1452 | absent | absent |
| VCD normalized | yes | yes |
| Reproducibility | 2 runs identical | 1 run (2nd interrupted) |

Combined separate-core placed cell area: **424,885 µm²**

Current compacted bit-exact shared candidate: **271,078.736 µm² synthesized**
(24.73% reduction vs the standalone synthesis sum) and **315,359 µm² placed**
(25.78% reduction vs the standalone placed sum). The first correct but
uncompacted candidate was 356,628 µm² synthesized / 414,157 µm² placed. The
earlier 237,431 µm² / 44% estimate came from broken RTL and is retired.

---

## SHARED CANDIDATE: RESOLVED ARCHITECTURE FINDING

The r2²SDF delay-buffer depth is part of the algorithm structure. The
64-point and 128-point transforms have different feedback distances,
butterfly pairing timing, -j rotation timing, and twiddle addressing. The
failed first candidate did not preserve all of those mode-specific semantics:

1. The butterfly x0 input must read from the mode-muxed tap (not the
   fixed long-tap position) — this was the primary implementation bug
2. The counter must wrap at the frame length (64 vs 128) — without this,
   continuous multi-frame streaming misaligns all subsequent frames
3. The mj rotation timing depends on the counter AND the buffer depth
4. The twiddle addressing differs per mode (different bit selections,
   different tw_num widths, different table sizes)

The experiment now resolves the earlier uncertainty: r2²SDF state can be
shared across these transform sizes while remaining bit-exact, but correct
sharing requires consistent mode-dependent taps, wrap, control, and twiddle
semantics. The current candidate demonstrates functional sharing. Its physical
result also shows that correctness alone does not guarantee the original area
or power hypothesis. Compaction of duplicated mode-specific delay storage
raised the placed-area saving from 2.52% to 25.78% and materially reduced
power, while energy per transform remains above the dedicated baselines.

---

## SHARED CANDIDATE: REMAINING WORK

1. Repeat the full compacted shared run independently for reproducibility
   parity and compare canonical netlist/DEF plus headline metrics.
2. Physically evaluate only functionally passing candidates; retain timing,
   zero DRC, activity coverage, and exact candidate/input hashes as hard gates.
3. Investigate safe clock-enable/data-hold behavior for inactive storage and
   the unused 64-mode stage-3 twiddle path. Do not synthesize gated clocks in
   RTL.
4. Use the now-bounded low-thinking Gemini path only for focused follow-up
   changes; preserve the Luna candidate as the current accepted implementation.

---

## FILE INVENTORY

### Created this session
- `fft128_oracle.py` — FFT128 independent arithmetic oracle
- `fft128_regression.py` — FFT128 directed regression runner
- `test_fft128_oracle.py` — 20 tests
- `test_fft128_regression.py` — 10 tests
- `benchmarks/halo_fft128_reference/` — fixture (wrapper, TB, manifest, vectors)
- `third_party/r22sdf/FFT128.v` — curated upstream (byte-identical)
- `third_party/r22sdf/Twiddle128.v` — curated upstream (byte-identical)
- `fft64_oracle.py` — FFT64 independent arithmetic oracle (1,038 lines)
- `test_fft64_oracle.py` — 27 tests
- `physical/rtl/peweaver_shared_fft.v` — bit-exact compacted shared 64/128
  candidate; one complete optimized physical run frozen
- `physical/rtl/peweaver_ppa_fft64.v` — FFT64 PPA wrapper
- `physical/rtl/peweaver_ppa_fft128.v` — FFT128 PPA wrapper
- `physical/rtl/peweaver_ppa_shared_fft.v` — shared PPA wrapper
- `physical/vcd_normalize.py` — VCD timestamp normalizer/validator
- `physical/synth/filter_liberty.py` — liberty cell filter
- `physical/leakage_check/` — reproducible SPICE leakage sanity check
- `physical/assemble_results.py` — result record assembler
- `physical/tool-lock.json` — pinned tools + PDK + hashes
- `physical/pdk/sky130hd/` — ORFS platform files (pinned)

### Modified this session
- `benchmarks/halo_fft64_reference/README.md` — Phase 1 oracle documentation
- `benchmarks/halo_fft128_reference/README.md` — Phase 2 documentation
- `benchmarks/halo_fft128_reference/manifest.json` — independent_oracle field
- `third_party/r22sdf/README.md` — provenance for new files
- `examples/peweaver/README.md` — Phase 1 + physical flow documentation
- `physical/README.md` — frozen decisions + v2 results + FFT128
- `physical/run-physical.sh` — full parameterization + fixes
- `physical/assemble_results.py` — v2 (per-design, corrected energy)
- `physical/tool-lock.json` — ORFS provenance added
- `physical/openroad/fft64_frontend.tcl` — TOP_MODULE + repair_timing
- `physical/openroad/fft64_backend.tcl` — ODB_PATH + RPT_TAG + propagated clocks
- `physical/constraints/fft64_baseline.sdc` — clock uncertainty added
- `physical/synth/fft64_synth.ys` — filtered liberty + shared template
- `test_fft64_regression.py` — discovery set updated

---

## 2026-09-04: ChiaMerge clean-room run `merge-clean-1` — new accepted shared candidate

A clean-room ChiaMerge run (one `ChiaMerge` call: one architecture
`ChiaAdvise` + one transactional `ChiaIterate{ChiaAdvise -> ChiaImplement ->
ChiaCheckCondition}`) produced a **new shared 64/128 candidate from nothing
but the pinned reference designs and the behavioral contract**, and it passed
the full deterministic gate ladder (lint -> bit-exact functional both modes ->
full physical flow -> portfolio) on turn 32, then reproduced **identically**
in a model-free independent physical re-run.

### Result (both the in-loop run and the independent re-run agree exactly)

| Metric | New candidate (mergerun1) | Prior accepted | Two-core sum |
|---|---:|---:|---:|
| Placed cell area | **286,970 um^2** | 315,359 um^2 | 424,885 um^2 |
| Instances | 39,886 | 43,797 | — |
| Timing | met, +0.1087/+0.1304 ns | met | — |
| DRC | 0 | 0 | — |
| Streaming power 64 | **39.819 mW** | 40.013 mW | 23.314 mW |
| Streaming power 128 | **40.444 mW** | 42.162 mW | 41.040 mW |
| RTL size | 26,860 B, 8 modules | 62,123 B, 1 module | — |

- Area reduction vs two-core standalone sum: **32.459%** (prior: 25.78%).
- The new design also dominates the prior accepted candidate on every
  measured axis (area -9.0%, both mode powers lower, fewer instances).
- Strict per-mode power caveat unchanged: mode-64 power is still above the
  standalone FFT64 core; the shared-vs-two-core-chip power claim still
  requires the combined dual-core baseline measurement under a matched
  schedule.

### Provenance and hashes

- Candidate SHA-256:
  `ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e`
  (hierarchical: `peweaver_shared_fft`, `SharedSdfUnit`, `SharedDelayBuffer`,
  `SdfUnit2`, `DelayBuffer`, `Butterfly`, `Multiply`, `Twiddle`).
- Reproducibility result SHA-256:
  `2867fd7440c5fa0dd90c4cd0283c03f4a2477102b9858399ccf42b7445c000a8`
  (`orchestration/runs/merge_clean_1/shared_mergerun1_sky130.json`).
- Candidate archived:
  `orchestration/runs/merge_clean_1/peweaver_shared_fft.mergerun1.v`.
- Run state, turn history, architecture advice, gate detail:
  `orchestration/runs/merge_clean_1/` (state.json, advice_turn1.md,
  check_turn32.json, input_hashes.json).
- VM evidence: `/work/peweaver/runs/merge-clean-1/` (preserved on /work);
  turn-32 in-loop physical evidence in `.../physical/results.turn32/`;
  model-free repro log `~/runs/merge_repro_physical.log`.
- Leakage sanity record regenerated fresh 2026-09-04 via
  `leakage_check/run_leakage_check.sh` (design-independent nand2 spot-check;
  values identical to the prior record).

### How it ran (composition, as designed)

1. Turn 1: Sol (`openrouter/openai/gpt-5.6-sol`) derived the sharing
   architecture from the reference inputs only (mode-locked r2^2SDF, three
   shared stages + conditional radix-2 tail, per-stage mode table).
2. Turns 2-31: transactional iterate. Each turn: fresh sandbox from best,
   per-turn Sol advice, one reply-mode generation burst (model returns the
   complete file; controller writes it), deterministic gates; promote only on
   milestone advance (level 1 = lint-clean skeleton, turn 22).
3. Turn 32: gemini-3.8-flash burst produced the design that passed all four
   gates; ACCEPT.

Implementer model changes during the run (all openrouter): glm-5.3-flash ->
glm-4.7-flash (turn ~21) -> gemini-3.8-flash (turn ~30). glm-5.3-flash
consistently drops long generations (empty response, fast-fail, no structured
error); Sol's assessment: model-route-specific gateway/streaming limit,
confirmed by siblings succeeding on the identical pipeline (glm-4.7-flash 37KB
output, gemini-3.8-flash pass).

### Honesty notes / next hardening

- The functional judge is the public directed regression (bit-exact both
  modes, single + continuous frames + GLS). Hidden randomized holdout vectors
  have NOT been run against this candidate yet; do that before any external
  claim.
- The adviser (Sol) had read access to the run root, which contains a copy of
  the prior accepted RTL. Structural comparison (5.7% text similarity,
  disjoint module set, 26.9KB vs 62.1KB) shows the produced design is
  independent of it. Future runs should scope adviser reads to `inputs/` only.
- The in-loop physical run reused the (design-independent) leakage record
  from the copied tree; the repro run regenerated it fresh and fail-closed
  until it was re-created, then matched exactly.
- Prior accepted candidate (`6a56b832...`, 315,359 um^2) remains the frozen
  fallback; supersede it in the headline only after hidden-holdout vectors
  pass.

## 2026-09-04 (later): hidden randomized holdout — `reproducible-pass-and-sensitive`

The mergerun1 candidate was then subjected to a controller-only randomized
holdout suite (`orchestration/hidden_holdout.py` +
`physical/activity/hidden_holdout_tb.sv`), generated from the INDEPENDENT
oracles (which reproduce the fixture goldens exactly and never consult them):

- **36/36 cases bit-exact**, including: 6 corner frames x both modes (zeros,
  +full-scale, -full-scale, alternating +/-full, impulse, ramp), 6 random
  frames x both modes (arbitrary 16-bit data), 3-frame continuous bursts with
  three DISTINCT random frames per mode, mid-frame reset then fresh frame,
  aborted partial frame then reset then fresh frame, and 64<->128 mode
  switches with per-mode outputs.
- **Exact first-valid latency 71/137 asserted and met on every single-frame
  case** (the directed judge never checked this), plus exact N-wide output
  pulses with no gaps.
- **Mutation sensitivity proven**: deliberately corrupted candidates all fail
  the suite — one-LSB twiddle errors (reachable addresses re/im), a
  multiplier scale shift (>>>15 -> >>>14), and an input-counter off-by-one.
  Two initially chosen mutation targets proved semantically neutral (an
  unreachable twiddle address; a schedule signal whose early fire is
  absorbed) and were replaced; the suite fails closed if a mutation cannot
  be applied.
- **Documented deviation**: after an aborted partial frame the candidate
  emits one garbage output pulse (64/128 cycles) before reset. This is
  IDENTICAL to the pinned reference behavior (r2^2SDF has no frame-validity
  tracking); the spec section-6 abort clause has never been met by any
  design here, including the prior accepted candidate. Post-reset recovery
  is bit-exact in all cases.

Verdict: the mergerun1 candidate is a genuine, general FFT datapath — not
specialized to the directed vectors. Combined with the model-free physical
reproducibility run, the result is reproducibility-qualified per the AGENTS.md
ladder. The corrupted-RTL sensitivity checks also validate the judge itself
(test-the-tests).

## 2026-09-04 (evening): generalization campaign started

- chia_merge.py is now domain-neutral (zero benchmark vocabulary; a permanent
  unit test enforces it). Prompt templates are generic; per-domain knowledge
  lives only in the driver (inputs, contract, gates).
- Preregistration manifest frozen before the reproduction campaign
  (orchestration/runs/merge_repro_preregistration.json): prompts, inputs,
  contract, models, budgets (turns=32), acceptance criteria. Three
  sequential clean-start runs (merge-repro-1/2/3, no resume, fresh dirs)
  launched; every outcome will be reported.
- Second-domain demo built and gate-validated: two-MAC merge
  (orchestration/mac_merge_driver.py + merge_benchmarks/mac_reference/).
  Selftest: shared one-multiplier candidate passes all four gates
  (bit-exact vs pure-python oracle over 1200 randomized cycles with resets,
  en gaps, mode switches; exactly one multiplier; gate count 44% below the
  two-reference sum); the reference-mux control is rejected (3 multipliers).
  The MAC ChiaMerge run itself executes after the reproduction campaign.

## 2026-09-04 (night): clean-start reproduction campaign — run 1 ACCEPTED

merge-repro-1 (preregistered composition, clean dir, no resume): **accepted at
turn 10** with all four gates — a DIFFERENT architecture than the discovery
run's candidate (21,181 bytes vs 26,860; distinct sha
`589585de33d164a1b5ee56c0fa19452caa0ce856789cfa0f0e1fd4b8bbaa2ee3`):

| Metric | repro-1 candidate | discovery candidate |
|---|---:|---:|
| Placed area | 283,464 um^2 | 286,970 um^2 |
| vs two-core sum | 33.3% below | 32.46% below |
| Instances | 38,962 | 39,886 |
| Timing / DRC | met / 0 | met / 0 |
| Power 64 / 128 | 40.29 / 40.84 mW | 39.82 / 40.44 mW |

Hidden randomized holdout on the new candidate: 36/36 bit-exact vs the
independent oracles; mutation sensitivity: scale_shift and literal_lsb
applied and caught; the three structure-specific mutation targets do not
match this design's text and are recorded as not-applied (architecture-
adaptive mutation targets remain future work). Two independent clean starts
have now produced two different, both fully valid, sub-baseline shared FFTs.
merge-repro-2/-3 continue in the preregistered chain.

## 2026-09-04 (final): preregistered reproduction campaign COMPLETE — 3/3 accepted

All three clean-start runs (fresh dirs, no resume, frozen composition,
preregistered budgets/models/hashes in
`orchestration/runs/merge_repro_preregistration.json`) accepted:

| Run | Accepted at | Area (um^2) | vs two-core sum | Inst | Power 64/128 (mW) | Candidate SHA-256 (prefix) | Holdout |
|---|---:|---:|---:|---:|---|---|---|
| merge-repro-1 | turn 10 | 283,464 | 33.3% below | 38,962 | 40.29 / 40.84 | `589585de...` | 36/36 + sensitivity |
| merge-repro-2 | turn 2 | 286,736 | 32.5% below | 39,826 | 40.02 / 40.63 | `e5f104b8...` | 36/36 + 4/5 mutations caught |
| merge-repro-3 | turn 13 | 288,658 | 32.1% below | 39,928 | 40.45 / 41.08 | `150d5b25...` | 36/36 + sensitivity |

Every run produced a DIFFERENT valid architecture (three distinct SHAs, three
distinct designs) that is bit-exact in both modes, meets the exact 71/137
latency, passes timing with DRC 0, and lands 32-33% below the combined
two-core baseline. Acceptance rate: **3/3**; turns-to-accept: 10 / 2 / 13
(the discovery run's 32 included all framework debugging). Failure
transparency: repro-3 spent turns 4-12 rejected/stalled before converging;
all histories are in each run's artifacts.

Claims now supported: the frozen preregistered composition (prompts, models,
gates, budgets — hashes recorded BEFORE the runs) achieves **k/n = 3/3
clean-run acceptance** with per-run architectural diversity, per Sol's freeze
requirements ("prompt/version X achieved k/n"). Second-domain MAC demo assets
and gate ladder are validated and waiting; the MAC merge run and ablations
are the next experiments. Per-mode power vs the standalone FFT64 core and the
shared-vs-two-core-chip comparison caveats remain as previously documented.

## 2026-09-04 (late): Gemini Developer API wired in; MAC second-domain merge ACCEPTED turn 1

- Operator-directed provider switch: the implementer backend now supports
  `gemini/<model>` model strings, wired to the native
  `chia.models.vertex.DirectGeminiLLM` (Gemini Developer API, credit-funded
  key held at the documented secret path, env-only, never logged; max_tokens
  65536). The architecture-advice prompt now inlines the complete input
  sources, so a pure-text adviser needs no filesystem access (this also
  closes the adviser-wandering leak channel for gemini-backed runs). The
  adviser role remains gpt-5.6-sol via openrouter. 96 tests green; live
  probes passed (short + long generation).
- **MAC second-domain merge (`mac-merge-1`): ACCEPTED ON TURN 1.** One
  ChiaMerge call over the same domain-neutral primitives: Sol architecture
  advice -> gemini-3.8-flash generation -> all four gates passed
  (lint clean; bit-exact vs pure-python oracle over 1200 randomized cycles
  with resets/en-gaps/mode-switches; exactly one 8x8 multiplier; gate count
  531 = 44.0% below the two-reference sum 949). Candidate: 755 bytes, sha
  `1b6df687...`. Second domain proven empirically; two domains, both
  accepted, same framework, only the driver (inputs/contract/gates) differed.

## 2026-09-05: final-campaign batch (preregistered; Sol-reviewed code; operator asleep)

### Frozen inputs and tooling

- Campaign preregistration frozen at
  `orchestration/campaigns/final_campaign/preregistration.json`
  (sha `29d6f60e...` manifest `input_manifest.json`, 19 frozen inputs) BEFORE
  any new outcome was viewed. MAC gate ladder upgraded 4 -> 6 gates
  (lint, randomized-oracle functional, directed signed corners, structure,
  area, formal). mac-merge-1 is labeled PILOT 4-gate evidence; clean 6-gate
  k/n is computed only from preregistered starts 2/3.
- Sol (gpt-5.6-sol) integration review of the new code found 6 CRITICAL +
  13 HIGH/MEDIUM defects; all fixed before any start ran, including:
  multiplier-instance counting (row->count sum), per-candidate area-cache
  keying, archive-wide Pareto dominance + pruning, recovery hash-identity
  unification, crash-safe physical-budget reservation, finite-objective
  validation, fail-closed verify_final, worker-kill ancestry protection,
  legal mode transitions in both stimulus generators, formal-harness
  $past/reset/mode-legality bugs, dual TOP_MODULE + provenance + mode SDC.
- MAC gates now dispatch through CHIA `@ChiaFunction` nodes
  (`evaluator_nodes.py`): Ray-scheduled with local fallback; infrastructure
  failures become RETRY, not semantic rejection. Unit tests: 103 passing.

### MAC second-domain results (all on VM, frozen composition)

- mac-merge-1 candidate `1b6df687...` re-evaluated under the frozen 6-gate
  ladder: **PASS 6/6** (separate six-gate re-evaluation evidence, not a
  retrospective clean start).
- mac-merge-2 (preregistered clean start): **ACCEPTED turn 1, 6/6 gates**.
  Candidate `3340103b...` (857 bytes).
- mac-merge-3 (preregistered clean start): **ACCEPTED turn 1, 6/6 gates**.
  Candidate `7a9a2fb7...` (679 bytes).
- All three candidates: distinct code, identical structure result
  (exactly one 8x8 multiplier) and identical generic cell count 531 =
  44.0% below the two-reference sum 949 (unweighted generic Yosys cell
  count, not mapped area). 6/6 = lint clean; bit-exact vs the pure-python
  oracle over 1200 randomized cycles with contract-legal mode transitions;
  bit-exact on 157 directed signed-corner cycles (corners, wrap, overflow,
  mode-1 interruption, reset); exactly one multiplier post-opt; area;
  SymbiYosys BMC depth-12 (BOUNDED) sequential-contract proof with symbolic
  operands under declared protocol assumptions (initial reset; mode changes
  only while en=0).
- Negative controls: naive two-multiplier mux REJECTED (structure);
  double-product TDM candidate REJECTED (functional/corners); mutation
  suite `mac_mutants.py` valid: signedness/acc-hold/reset/enable/truncation
  each caught by >=1 gate, and legal operand commutation correctly NOT
  over-rejected (structure gate proves sharing; naive control covers real
  duplication). Report: `runs/mac-mutants-1/mutation_report.json`.
- Formal evidence class: bounded (BMC depth 12, z3). Arithmetic beyond the
  bound is covered by the independent pure-python oracle judge. Mirror hold
  properties are mirror-internal by construction (documented limitation).

### Dual-core ungated FFT reference (variant A, model-free)

- Wrapper `physical/rtl/peweaver_ppa_dual_fft.v`: both frozen cores
  instantiated, inactive core held with di_en=0, both clocks running,
  output mux by mode; I/O contract identical to the shared wrapper.
- Module-name collisions (FFT, Twiddle, and SdfUnit->Twiddle binding)
  resolved by pure-rename derivations under `physical/rtl/dual/`
  (FFT128_core / SdfUnit128 / Twiddle128_core + wrapper derivation),
  logic identical, hash-pinned in the flow inputs.
- Matched activity schedule: `dual_activity_tb.sv` is an exact mirror of
  the shared TB (same tasks, timing, vectors). Frozen constraint set
  duplicated to `dual_baseline.sdc` with `mode` constrained.
- Status: synthesis passed; RTL + mapped GLS passed (64- and 128-mode
  streaming); OpenROAD frontend passed; backend detailed routing in
  progress at last check. Result JSON pending; no dual numbers recorded yet.

### Evidence archive

- VM evidence pulled to `orchestration/runs/` (merge-repro-1/2/3,
  mac-merge-1/2/3, mac-merge-1-reeval6, mac-mutants-1): state/check/advice/
  implement/manifest JSONs, best candidates, holdout and mutation reports.
- 13 pulled artifacts hash-pinned in
  `orchestration/campaigns/final_campaign/vm_artifacts_manifest.json`;
  audit clean.

## 2026-09-05 (later): dual-core DRT debugging, direction and open questions

### Dual-core backend debugging (all model-free)

- The first dual backend run ground 4h+ with zero log output (DRT block-
  buffered through pipes). Sol ops consult (saved at
  `/tmp/opencode/sol_ops_consult.md` on the operator machine): kill —
  >40x runtime on 1.17x cells is pathology; relaunch with visibility
  (OpenROAD -log/-metrics + stdbuf -oL + detailed_route -verbose 1,
  logging-only); ranked pathologies: stale guides after post-GR repair,
  pin-access explosion, local congestion hotspot, clock/PDN interaction,
  tool bug.
- Instrumented rerun (frontend ODB checkpoint reused; frozen backend tcl
  copied with only -verbose 0 -> 1, verified otherwise identical) showed
  DRT genuinely iterating: 6 iterations in 45 min, violations flat at
  ~3.6k -> real convergence grind, not a hang.
- Cross-checks: the shared design's GP also stops at overflow ~0.0994
  (normal stopping criterion), and its whole backend takes ~6 min. Dual
  violations are met1-dominated (131k met1 markers vs 10k met2; 424k um
  met1 wire). Diagnosis: met1 local congestion under the placement
  density target 0.60 (two cores' worth of cell pins/followpins + 6,939
  clock sinks + output-mux interface).
- Fix applied (DUAL-ONLY, DECLARED): `global_placement -density 0.50`
  (from 0.60). Die area/utilization 40 unchanged (no area bias); the
  deviation favors the control, so any shared-vs-dual claim that survives
  it is conservative. Frontend rerun passed; backend rerun is converging
  (violations 3638 -> 942 -> 819 -> 653 -> 385 over iterations at last
  check, still running).

### Direction after the dual lands (for operator consultation)

1. Dual result + independent model-free repeat (preregistered budget 2
   full physical runs). Then the combined-chip comparison becomes valid:
   report dual placed area/power vs shared under the matched schedule,
   with the density deviation disclosed.
2. ChiaPowerSave FFT campaign on the shared incumbent (hypothesis order in
   FINAL_CAMPAIGN_PLAN.md section 12; lexicographic gates; Pareto archive;
   budgets 16 candidates / 5 full physical runs / 1 independent repeat).
3. Variant B dual-core gating (model-free dlclkp wrapper) with the same
   physical-run budget — the dual side's "equal-budget intervention".
4. Attribution: hierarchical attribution-only synthesis on shared + dual
   (Sol-endorsed scope) BEFORE broad RTL power edits; attribution output
   drives hypothesis reordering.
5. GDS stream-out + independent DRC/LVS on the final shared + dual points
   (operator approved tool install; pin versions in a SEPARATE
   finalization tool-lock; frozen physical/tool-lock.json untouched).
6. FIR second PowerSave domain (P1) and thermal sensitivity (P1) per the
   plan's priority ladder; drop order if time runs short: P2 -> FIR GDS ->
   advanced thermal.
7. Paper freeze Sep 17-18; submission Sep 20 AoE.

### Open questions for the consultation

- Q1 equal-budget: is variant-B-as-model-free-intervention the right
  reading of plan section 12, or does the operator want a model-driven
  dual campaign too (cost: higher risk, more VM/model budget)?
- Q2 sequencing: dual repeat first (2-3h VM) or start the ChiaPowerSave
  FFT campaign while the dual repeat runs? (Physical runs are serial on
  the 8-vCPU VM; model candidate generation could overlap the repeat.)
- Q3 GDS scope: stream out only the final points (plan section 14), or
  also the frozen shared baseline early to de-risk the flow?
- Q4 MAC holdout hardening: add the second controller-only seed now
  (cheap) — yes/no?

## 2026-09-05 (evening): external review response — framework hardening, controls, ablation

An external model review (gpt-6-astra) of the campaign plan, guide, and code
was triaged. Findings accepted and fixed the same day, before any new model
campaign:

1. Candidate/feedback association (CRITICAL): rejected candidates were
   deleted while their feedback text persisted, so a later turn could be
   told to repair a design it was not shown. `ChiaIterate` now preserves
   the rejected sandbox, binds feedback to the rejected workspace hash,
   and requires the next turn to explicitly repair-or-branch.
2. Evaluation retry: infrastructure failures consumed a generation turn
   and discarded a sound candidate. Evaluation of the SAME sandbox is now
   retried up to 3 times with no model call; the turn is consumed only if
   the evaluator stays down, and the candidate is preserved.
3. Reply-mode permission regression: the ChiaImplement opencode backend
   had edit/bash ALLOW (a regression from the backend refactor); restored
   to deny-all REPLY_PERMISSIONS (gemini backend unaffected; no live run
   used the permissive config).
4. ChiaPowerSave: config fingerprint is now mandatory (construction fails
   without it); the FFT PowerSave driver inlines the full incumbent source
   into the implement prompt (previously the implementer could not see
   the design it was rewriting).
5. ChiaMerge gained an injectable adviser/implementer factory seam (unit
   tests run with no Ray/models) and the preregisterable
   `ablate_no_feedback` mode: turn-1 architecture advice only, no gate
   feedback — the controlled "is feedback helping?" comparison.
6. Headline reconciliation: the accepted candidate's row now carries its
   own measured numbers (286,970 um^2, 39.819/40.444 mW, 39.02/74.42 nJ);
   the prior fallback's row is separate. Guide wording: density change
   described as a routing intervention with direction-of-bias argued from
   measurements; holdout framed as agreement-on-tested-cases.
7. Synthesis-only sharing control (model-free): the naive two-reference
   MAC composition keeps >=2 $mul cells through elaboration and
   synthesizes to 967 generic cells — ABOVE the 949 two-reference sum and
   45% above the accepted candidate's 531; `share -aggressive` does not
   change this. Sharing required architectural restructuring that plain
   synthesis does not perform. Report:
   `/work/peweaver/runs/mac-synth-control/synthesis_control_report.json`.
8. Second-seed MAC hidden judge (controller-only seed 0x7EEDBEEF, 1502
   randomized cycles + directed corners): all three accepted candidates
   bit-exact. Reports under runs/mac-merge-*/hidden_judge/.

Test totals: 107 passing locally, 66 on the VM subset.

## 2026-09-05 (night): UNGATED DUAL-CORE FFT REFERENCE PHYSICALLY MEASURED

The no-sharing control (plan workstream 4, variant A) completed the frozen
flow on the VM after the declared placement-density fix:

- Convergence: the density 0.50 rerun drove DRT violations 19,829 -> 0 over
  ~17 iterations (attempt 2 had stalled at ~3.6k under density 0.60). The
  dual-only deviation is now validated as a routability fix, not a
  concession: the design closed with timing MET (setup +0.468 ns, hold
  +0.093 ns), DRC 0, 127,304 annotated pins in both power windows.
- Machine-readable result: results/dual_baseline_sky130.json (VM).

| Metric | FFT64 | FFT128 | Standalone sum | Ungated dual-core | Shared `ce64c715...` |
|---|---:|---:|---:|---:|---:|
| Placed cell area | 164,408 | 260,477 | 424,885 (sum) | **429,130** (+1.0% vs sum) | **286,970** (32.46% below sum) |
| Streaming p64 (mW) | 23.314 | — | — | **61.523** | **39.819** |
| Streaming p128 (mW) | — | 41.040 | — | **61.446** | **40.444** |
| E/FFT 64 (nJ) | 20.40 | — | — | **60.29** | **39.02** |
| E/FFT 128 (nJ) | — | 71.20 | — | **113.06** | **74.42** |

Reading (strict, matched schedule, same frozen corner):
- The ungated dual-core chip is 1% LARGER than the two standalone dies sum
  (wrapper/mux overhead) and its streaming power is 61.5/61.4 mW in modes
  64/128 — the inactive core's clock tree and internal activity keep
  burning (both core clocks run; only di_en is gated).
- The shared candidate is 33.1% smaller in placed area than the ungated
  dual-core chip and 35.3% / 34.2% lower streaming power in modes
  64/128, with finite energy 35.3% / 34.2% lower.
- Honest caveats: this control keeps the inactive core's clock running
  (ungated by construction). The power-managed dual-core (variant B,
  model-free dlclkp wrapper) is the fair next control; the placement
  density 0.50 deviation is disclosed in the result record.
- The dual result is a single physical run; the preregistered
  independent model-free repeat is the next VM action.

Process notes: assemble_results required (a) the backend log at its
canonical name (instrumented log copied over), and (b) the design-
independent leakage sanity record (same PDK/corner, generated in the
local environment) copied into results/leakage_check/.

## 2026-09-05 (night, cont.): FIR THIRD-DOMAIN MERGE ACCEPTED TURN 1

The stateful two-context FIR merge (astra-suggested shape: two 8-tap
constant-coefficient filters, different pinned coefficients, mutually
exclusive activation, independent histories) ran as the third ChiaMerge
domain:

- fir-merge-1: **ACCEPTED TURN 1, 6/6 gates** — lint clean; bit-exact vs
  the pure-python oracle over 1502 randomized cycles (contract-legal ctx
  switches only while en=0, resets); bit-exact on 35 directed corners
  (per-context impulse responses = exact coefficient sequences, context
  alternation with preserved histories, wrap stress); **8 multiplier
  cells** (the references have 8 each — the agent beat the <=16 combined
  bound); **4484 generic cells = 11.6% below** the two-reference sum
  5071; second in-ladder stimulus (different seed) bit-exact over 1202
  cycles. Candidate `009851fd...` (5138 bytes).
- Context: my hand-written positive control (constant products + shared
  ctx-muxed adder tree) FAILED the area floor (5328 > 4564 floor); the
  naive 16-multiplier mux passes functionally but is only 4.6% below the
  sum (rejected by the 10% floor). The model-driven loop found an
  8-multiplier shared architecture meeting the floor on the first turn —
  qualitatively harder than the MAC (independent histories + constant-
  coefficient arithmetic where naive multiplier sharing destroys yosys's
  constant optimization).
- Benchmarks validated by selftest BEFORE the model ran: positive control
  passes all gates; 16-mult mux rejected (area); shared-delay-line
  cheater rejected (functional — histories corrupt). Ladder: lint,
  randomized oracle, directed corners, structure (<=16 muls), area (>=10%
  below sum), second-seed randomized re-check.
- Two-domain-plus status: FFT (32-33% area, physical), MAC (44% generic
  cell count, formal), FIR (11.6% cell count, stateful histories) — all
  accepted with distinct drivers over the same primitives.
- Assets: merge_benchmarks/fir_reference/{fir_a.v,fir_b.v,
  fir_holdout_tb.sv}; orchestration/fir_merge_driver.py. The FIR domain
  also exercises the repaired ChiaIterate semantics (rejected-candidate
  preservation, feedback binding, eval retry) which shipped this session.

## 2026-09-05 (night, final): DUAL REPEAT — exact deterministic match

The preregistered independent model-free repeat of the ungated dual-core
reference (full flow from synthesis, fresh results directory, same
declared density-0.50 frontend) reproduced the first run EXACTLY:

- Placed area: 429,130 um^2 (identical), 48% utilization.
- Streaming power mode 64: 61.5231 mW (bit-identical to the reported
  digit: internal 4.569015e-02 W, switching 1.583277e-02 W).
- Streaming power mode 128: 61.4464 mW (bit-identical).
- DRC report: empty (0 violations). 127,304 annotated pins in both
  windows.

The dual-core control is reproducibility-qualified. The combined-chip
comparison is now fully supported under the standing claim rules:
shared `ce64c715...` vs ungated dual-core (both physically measured,
matched schedule): area 286,970 vs 429,130 (33.1% below), streaming
power 39.819 vs 61.523 mW (mode 64, 35.3% below) and 40.444 vs
61.446 mW (mode 128, 34.2% below). Variant B (power-managed dual,
model-free dlclkp wrapper) was subsequently measured as a separate control;
its result is recorded in the submission-edge package and is not an area win.

FIR: fir-merge-1 also recorded tonight (accepted turn 1, 6/6; details
above). VM work batch closed; Ray and the VM stopped after the repeat.

## 2026-09-06: attribution complete; ChiaPowerSave FFT campaign running

### Attribution (workstream 3, shared incumbent, mode-64 streaming window)

The attribution-only flow (name-preserving synthesis -> P&R -> per-region
report_power -instances via generated region maps) completed. The attr
netlist P&R'd to exactly the frozen placed area (315,359 um^2, 47%), so
the attribution physical run matches the frozen flow's geometry.

- Region reports: stage1/stage2/stage3/clock_root/io/control_glue
  (6 buckets; stage assignments by driven-RTL-net prefixes s1_/s2_/s3_,
  clock tree by cell class clkbuf/clkgate — the clock bucket is COMPLETE).
- **Headline: fallback F attribution assigns 19.66 mW (49.1%) to
  sequential cells and 16.02 mW (40.0%) to the clock network** — 4,606
  clock-buffer instances, internal-power dominated. Stage logic is tiny by comparison (mapped cells:
  stage1 0.50 mW, stage2 0.22 mW, stage3 0.23 mW; control_glue 2.23 mW
  of mapped cells).
- Caveat: region sums cover 57.2% of the grand total (the rest are cells
  whose driven nets lost public names through opt); sequential and clock
  categories are evidence from fallback F, not an exhaustive S0 partition.
  Evidence-backed hypothesis order for PowerSave:
  (1) dlclkp-gate the mode-128 tail stage and 128-only delay-bank
  segments (cuts clock-tree load AND internal power together);
  (2) gate other provably holding banks in mode 64; (3) operand
  isolation (stage logic is small).
- Attribution is evidence, not signoff power; never compared against
  frozen PPA. Files: results_attr/reports/attr_power_*.rpt + summary.

### ChiaPowerSave FFT campaign (ps-fft-6 running)

- Runs ps-fft-1..5 were debugging iterations of the campaign driver, each
  failing fail-closed BEFORE any candidate acceptance: (1) incumbent
  path bug, (2) missing os import, (3) stale snapshot results tripping
  fail-closed checks, (4) leakage record missing after source cleanup,
  (5) area_proxy regex on a truncated note (proxy synth output exceeds
  the 20k note window; the cell-count line fell outside), (6) proxy
  trigger could never fire (no numeric proxies in cheap-gate details).
  All fixed; the trigger is disabled (0.0) — every all-gates-passing
  candidate earns a physical run, capped by the 5-run budget.
- ps-fft-6 (live): incumbent seeded and measured exactly (286,970 um^2,
  39.819/40.444 mW, 39.02/74.42 nJ); turn 1's candidate passed all cheap
  gates (lint, bit-exact functional, synth proxy 27,604 cells vs
  incumbent 32,745) and is in physical evaluation (run 1/5).
- Budgets: 16 candidates / 5 physical runs / verify_final independent
  repeat. Objectives: area, p64, p128, e64, e128 (all minimized);
  hard constraint: placed area >=20% below the 424,885 um^2 standalone
  sum. Attribution summary is injected into the adviser prompt.

## 2026-09-06 (complete): first ChiaPowerSave FFT campaign — VERIFIED PARETO RESULT, power targets NOT met

ps-fft-6 exhausted its preregistered budget (6 candidates generated / 5
full physical runs) and closed with verify_final PASSING ALL CHECKS
(candidate hash, cheap-gate ACCEPT, physical pass, finite objectives,
hard constraints, metrics agreement).

- Promoted Pareto point `f4d5ae2f...` (26,869 bytes): placed area
  **282,963 um^2** (−4,007 um^2 vs the incumbent's 286,970; now **33.4%
  below** the 424,885 standalone sum), p64 39.931 mW (+0.112 vs 39.819),
  p128 40.445 mW (~unchanged), e64 39.13 nJ, e128 74.42 nJ (~unchanged).
- Pareto frontier (archive): incumbent `ce64c715...` (best p64) and
  `f4d5ae2f...` (best area) — incomparable points, correctly kept.
- **Power targets NOT met**: p64 39.93 vs the 23.314 mW target; p128
  40.44 vs 41.040 (mode-128 streaming power is now BELOW its standalone
  reference, consistent with the earlier finding). The mode-64 gap is
  dominated by synchronous power on fallback F (49.1% sequential cells,
  40.0% clock network);
  three of five physical runs failed on timing (timing_met=False, drc=0)
  — the model's clock-gating attempts broke timing and were correctly
  rejected; one flow rc=1; one invalid; one implement infra failure.
- Honest verdict: a small VERIFIED area improvement with small raw
  single-run power deltas; no statistical unchanged claim is made. Per the plan this is a scientific success
  (matched baseline, equal budget, Pareto frontier, negative result
  reported), and it sharpens the paper's message: the remaining mode-64
  excess lives in clocking, which naive model-driven gating does not fix
  — motivating careful, characterized-cell clock gating (variant B on
  the dual side; a timing-aware gating hypothesis on the shared side)
  as the next lever.
- Evidence: runs/ps_fft_campaign/ (state, checks, advice, implement,
  physical results per turn, pareto.json, final_repeat.json, promoted
  candidate). Local archive synced.

## 2026-09-07: Variant B power-managed dual-core control — first valid physical pass

Variant B is the approved model-free wrapper using characterized
`sky130_fd_sc_hd__dlclkp_4` cells. It is a power control, not a model-generated
area optimization, and equal physical-run budget does not imply equal design
effort.

- Attempt 1 completed the full flow but was rejected fail-closed for hold:
  hold −0.316 ns on five input-port paths, setup +0.436 ns, DRC 0.
- An infrastructure run that omitted `PEWEAVER_DESIGN=dual_b` accidentally
  routed fft64 under the B template; it is recorded as a driver failure and
  is not counted as a B evaluation.
- Attempt 2 used the disclosed B-only hold-repair frontend, then the unchanged
  backend. It passed mapped GLS, propagated-clock STA, TNS 0, DRC 0, and
  scenario/streaming activity annotation.
- Measured result: 429,655 um^2 placed cell area, setup/hold +0.445/+0.178 ns,
  mode-64/mode-128 streaming power 23.387/41.712 mW, and finite energy
  22.919/76.750 nJ per transform. Compared with Dual A, power and finite
  energy are 61.99%/32.12% lower in modes 64/128, while area is 0.12% larger.
- No idle-only B VCD was measured, so B is not extrapolated into the sparse-duty
  workload matrix. Primary result and all JSON-referenced physical artifacts
  are archived under `orchestration/runs/submission_edge_20260906/dual_b/`.
