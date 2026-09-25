# Discrepancy Log and Reconciliation

**Date:** 2026-09-07  
**Phase:** Submission Edge Execution (`submission_edge_20260906`)  
**Scope:** Pre-execution audit and reconciliation of primary artifacts vs narrative prose.

---

### Item 1: Status of Ungated Dual Baseline (Design A)
* **Finding:** Narrative text in some earlier sections of `AGENTS.md` listed Design A as "in progress", while chronology in `physical/update.md` recorded completion and exact repeat.
* **Primary Evidence:** `physical/results/dual_baseline_sky130.json` (and `results_repeat/`) records 429,130 um^2 placed cell area, 48% utilization, 0 DRC violations, setup slack +0.468 ns, hold slack +0.093 ns, mode-64 streaming power 61.523 mW, mode-128 streaming power 61.446 mW. Exact deterministic match across both runs.
* **Reconciliation:** Design A is formally verified and completed with an exact deterministic repeat. Status updated to COMPLETED.

---

### Item 2: ChiaPowerSave `ps-fft-6` Candidate Generation & Physical Run Counts
* **Finding:** Narrative summary referred to "16 candidates generated" as if 16 candidate RTLs were created, whereas `state.json` records 7 turns and 5 physical runs.
* **Primary Evidence:** `state.json` from `ps_fft_campaign/artifacts/`:
  - Total turns: 7
  - Turn 1: candidate generated -> cheap gates pass -> physical evaluation (timing fail)
  - Turn 2: candidate generated -> cheap gate INVALID (syntax/lint) -> no physical run
  - Turn 3: `implement_infra_failed` -> no candidate generated -> turn retried
  - Turn 4: candidate generated (`f4d5ae2f...`) -> cheap gates pass -> physical evaluation -> PARETO promoted
  - Turn 5: candidate generated -> cheap gates pass -> physical evaluation (timing fail)
  - Turn 6: candidate generated -> cheap gates pass -> physical evaluation (flow rc=1)
  - Turn 7: candidate generated -> cheap gates pass -> physical evaluation (timing fail)
* **Reconciliation:** 16 was the configured maximum candidate generation cap (`budget_candidates: 16`), not the realized count. Exactly 6 candidates were generated across 7 turns. Exactly 5 physical evaluations were executed, exhausting the physical evaluation budget (`budget_physical: 5`).

---

### Item 3: S0 to S1 Area Reduction Arithmetic
* **Finding:** `update.md` prose stated: "placed area 282,963 um^2 (−1,401 um^2 vs the incumbent's 286,970)".
* **Primary Evidence:**
  - S0 placed area: 286,970.0 um^2 (`pareto.json`, `best_metrics`)
  - S1 placed area: 282,963.0 um^2 (`pareto.json`, `final_repeat.json`)
  - Difference: $286,970.0 - 282,963.0 = 4,007.0\ \mu\text{m}^2$ ($1.3963\% \approx 1.40\%$).
* **Reconciliation:** The figure "1,401 um^2" was an arithmetic transcription error. The verified reduction is 4,007 um^2 (1.40% below S0, 33.40% below the standalone sum of 424,885 um^2).

---

### Item 4: Attribution Design Identity & Category Provenance (Design F vs S0)
* **Finding:** Narrative text referred to a "49.1% clock tree" fraction characterizing S0.
* **Primary Evidence:**
  - `audit/attribution_f_reports/reports/power_streaming_shared.rpt`:
    - Sequential cells: 19.657 mW (49.1%)
    - Clock network: 16.021 mW (40.0%)
    - Combinational logic: 4.336 mW (10.8%)
    - Leakage: 0.00016 mW (<0.01%)
    - Total power: 40.013 mW (100.0%)
  - Placed cell area in attribution run: 315,359 um^2 (exact match for Design F).
  - Mode-64 streaming power: 40.013 mW (exact match for Design F).
  - Design S0 sha256 is `ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e` (placed area 286,970 um^2, mode-64 power 39.819 mW).
* **Reconciliation:** 
  1. The attribution run characterized fallback **Design F**, NOT accepted Design S0.
  2. The 49.1% fraction represents **Sequential cell internal/switching power** (flip-flop state elements), while the **Clock distribution network** accounts for 40.0%. Together, clocking and sequential state account for 89.1% of power, whereas combinational logic accounts for only 10.8%.
  3. We discard the claim that "S0 clock tree is 49%". The finding is that in the shared SDF architecture (analyzed on F), synchronous sequential elements (49.1%) and the clock tree (40.0%) dominate dissipation, explaining why combinational RTL optimizations cannot recover power without addressing clocking and register holding.

---

### Item 5: Attribution Region Map Completeness
* **Finding:** Initial summary implied region maps completely decomposed chip power.
* **Primary Evidence:**
  - `attr_power_clock_root.rpt`: 19.657 mW
  - `attr_power_control_glue.rpt`: 2.232 mW
  - `attr_power_stage1.rpt`: 0.503 mW
  - `attr_power_stage2.rpt`: 0.218 mW
  - `attr_power_stage3.rpt`: 0.227 mW
  - `attr_power_io.rpt`: 0.044 mW
  - Sum of categorized instances: 22.881 mW
  - Total chip power reported: 40.013 mW
  - Coverage: $22.881 / 40.013 = 57.18\%$.
* **Reconciliation:** The region decomposition is partial (57.18% instance-attributed). The remaining 42.82% consists of gate-level cells whose driver nets lost original RTL hierarchy names during logic optimization. Combinational/sequential sub-block assignments represent lower bounds, not exhaustive partitions.

---

### Item 6: Characterization of Power Differences
* **Finding:** Statements that power was "statistically unchanged" between S0 and S1.
* **Primary Evidence:** Single physical P&R runs were executed for each candidate in the PowerSave campaign. No distribution or variance estimation was performed.
* **Reconciliation:** We discard the phrase "statistically unchanged". Instead, report raw measured deltas:
   - $\Delta P_{64} = +0.11251\ \text{mW}$ ($+0.28\%$)
   - $\Delta P_{128} = +0.00108\ \text{mW}$ ($+0.003\%$)
   - $\Delta E_{64} = +0.11026\ \text{nJ}$ ($+0.28\%$)
   - $\Delta E_{128} = +0.00199\ \text{nJ}$ ($+0.003\%$)
  - $\Delta \text{Area} = -4,007\ \mu\text{m}^2$ ($-1.40\%$).
  These represent small, deterministic OpenROAD/OpenSTA differences on single runs.

---

### Item 7: FIR Campaign Scope
* **Finding:** Narrative references to "FIR merge" could be conflated with physical PPA campaigns.
* **Primary Evidence:** `fir-merge-1` accepted candidate `009851fd...` (5,138 bytes) passed 6-gate RTL ladder (lint, randomized oracle, directed corners, structure $\le 16$ mults, generic cell area $\ge 10\%$ reduction, second-seed recheck). Generic cell count: 4,484 cells (11.6% below reference sum 5,071).
* **Reconciliation:** FIR is an RTL-level structural merge proof-of-concept for stateful arithmetic. No physical synthesis, P&R, or PowerSave campaign was preregistered or conducted for FIR.

---

## Addendum 2026-09-07 (post-audit): Variant B physical attempt ledger

Per the first-valid-B rule (plan §4), the full ledger of B physical
attempts is recorded here rather than only successful outcomes.

* **Attempt 1** (frontend `dual_d050_frontend.tcl`, no hold repair):
  completed end-to-end; **REJECTED fail-closed** — timing_met=False
  (hold −0.316 ns on 5 input-port data paths; setup +0.436 ns; DRC 0).
  Scientific context only, not claims: p64 23.241 mW, p128 41.581 mW
  (vs A 61.523/61.446 mW); e64 22.78 nJ. Recorded in
  `dual_b/results/physical_attempt1.json`. Budget: 1/5.
* **Infra event (not a B attempt):** a driver run omitted
  `PEWEAVER_DESIGN=dual_b`, synthesized/routed the fft64 design by
  mistake, and destroyed the attempt-1 ODB. No B candidate was
  evaluated; no power/area numbers from it are valid; the dual_b
  netlist was regenerated identically (same size, same source).
  Logged as a driver defect with fix (PEWEAVER_DESIGN export).
* **Attempt 2** (completed, first valid pass): frontend
  `dual_b_d050_frontend_holdfix.tcl` — a B-only flow deviation adding
  `repair_timing -hold` after both post-CTS and post-global-route
  setup-repair stages (direction: repair the specified failure; disclosed
  per plan). Backend unchanged. Mapped GLS, propagated-clock STA, TNS 0,
  DRC 0, and all three activity runs completed. Result is archived at
  `dual_b/results/physical_attempt2/dual_b_sky130.json` (sha256
  `a8b5cc2bc36775efe675f72f52e0207e9f8dcbebc04748eb6b8e6966270b84ed`).
  Placed cell area is 429,655 um²; setup/hold slack is +0.445/+0.178 ns;
  p64/p128 is 23.387/41.712 mW; finite e64/e128 is 22.919/76.750 nJ.
  Against ungated Dual A, streaming power and finite energy are lower by
  61.99% (mode 64) and 32.12% (mode 128), while placed cell area is
  525 um² (+0.12%) larger. Budget: 2/5.

**B acceptance boundary:** B is a valid power-managed dual-core control and
not an area-improvement candidate. Its continuous mode results are measured;
no idle-only B VCD exists, so B is excluded from the sparse-duty workload
model. No B GDS was streamed in this phase; the S0/A GDS artifacts remain
round-trip audited but independently streamed-layout DRC/LVS is pending.

---

## Addendum 2026-09-08: controller-only MAC holdout

Accepted MAC M2 and M3 were re-evaluated after acceptance with controller-only
seed `0x7EEDBEEF`. Both candidates were bit-exact over 1,502 randomized cycles
and 157 directed cycles. Reports are archived under
`mac_hidden_judge/m2_fixed/` and `mac_hidden_judge/m3_fixed/`.

The first local invocation exposed a harness path bug: relative candidate paths
were resolved from each Verilator temporary work directory. The judge now
resolves the candidate and work paths before compilation; the documented
relative-path invocation passes for both candidates.

---

## Addendum 2026-09-08: fresh S0 hidden holdout

The controller-owned FFT hidden holdout was rerun against the frozen S0 RTL
using the local OSS CAD Suite Verilator. An initial invocation supplied a
relative candidate path while the judge compiled from the physical directory;
it failed before compilation and is not a candidate verdict. The corrected
absolute-path invocation passed all 36 cases: both modes, six directed
corners, six random cases per mode, bursts, aborts, mid-reset, mode switches,
bit-exact outputs. The runner's declared contract included exact 71/137-cycle
first-valid latency, but the archived report and log preserve pass/fail and
case results rather than a numeric latency trace. The report and complete log are archived under
`replay/final_s0_hidden_holdout/`; this is a functional controller replay,
not a new physical run or optimization campaign.

---

## Addendum 2026-09-09: independent S0 physical repeat

An isolated sandbox on the existing physical VM performed a post-audit,
non-preregistered rerun of the frozen shared FFT
flow with S0 RTL hash
`ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e`.
The first sandbox attempt failed before a candidate verdict because the copied
fixture set omitted the 128-point vector directory. A fresh second attempt
passed RTL activity, mapped Icarus GLS, VCD normalization, synthesis, OpenROAD
placement/CTS/routing, OpenRCX extraction, propagated-clock STA, activity-based
power, and standard result assembly.

The repeat exactly matched the primary S0 record: 286,970 um2 placed area,
timing met, TNS 0, router DRC 0, 39.81859/40.44372 mW streaming power, and
39.0222182/74.4164448 nJ finite energy in modes 64/128. The result and audit
are archived under `replay/s0_physical_repeat_20260909/`. This is a model-free
physical repeat in an isolated sandbox, not independent streamed-layout
DRC/LVS signoff.
