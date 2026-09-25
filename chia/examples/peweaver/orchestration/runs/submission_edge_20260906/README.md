# PEWeaver Submission-Edge Execution & Evidence Release (Audited)
**Release Date:** 2026-09-07  
**Submission Target:** 2026-09-20 AoE  
**Authoritative Guidance:** `ASTRA_RELEASE_REPAIR_PLAN.md`  
**Execution Phase ID:** `submission_edge_20260906`  

---

## 1. Executive Status Ledger

| Work Package | Task / Experiment | Status | Key Deliverable / Primary Evidence |
|---|---|---|---|
| **WP0** | Audit, Reconcile & Synchronize | **COMPLETE** | `manifest/discrepancy_log.md`, `manifest/canonical_comparison.json`, `audit/artifact_index.json` |
| **WP0** | Fail-closed Release Artifact Verification | **COMPLETE; REFRESH AFTER REGENERATION** | `audit/verify_artifact_index.py`; final inventory is regenerated from the workspace root |
| **WP0** | Phase Manifest Scope/Identity Snapshot | **COMPLETE; POST-OUTCOME DISCLOSED** | `manifest/phase_manifest.json`, `manifest/inventory.json` |
| **WP1** | Variant B (dlclkp ICG Dual) Cheap Checks | **COMPLETE** | `rtl/peweaver_ppa_dual_fft_icg.v`, mapped GLS pass |
| **WP1** | Variant B Full Physical P&R (Attempt 2/5; first valid pass) | **COMPLETE** | `dual_b/results/physical_attempt2/dual_b_sky130.json`; timing/DRC/activity pass |
| **WP1** | Workload Energy Parameterized Model | **COMPLETE** | `workloads/workload_metrics.csv`, `breakeven_analysis.md` |
| **WP2** | HotSpot Thermal Tool Bring-up & Lock | **COMPLETE** | `thermal/thermal_lock.json`, HotSpot git `f18831e` |
| **WP2** | Thermal Sensitivity Analysis (S0 vs A) | **COMPLETE** | `thermal/thermal_report.md`, `thermal_results.json` |
| **WP3** | Replay Corpus Freeze (31 candidates, 5 strata) | **COMPLETE** | `replay/corpus_manifest.json` |
| **WP3** | Candidate-by-Gate Evidence Matrix | **EVIDENCE-SCOPED** | `replay/candidate_by_gate_matrix.md`, `replay/candidate_by_gate_matrix.json` |
| **WP3** | Evaluator Detection Summary & Traceability | **EVIDENCE-SCOPED** | `replay/detection_summary.json`, `contract_to_evidence_index.json` |
| **WP4** | Finalization Tool Installation (KLayout) | **COMPLETE** | KLayout 0.26.2 (CLI) & 0.30.12 (Python `klayout.db`) |
| **WP4** | S0 & A Full-Stack GDS Stream-out + Round-trip Audit | **ROUND-TRIP AUDITED; INDEPENDENT DRC/LVS PENDING** | `shared_s0_clean.gds` (29 MB), `dual_a_clean.gds` (42 MB) |
| **WP4** | Layout Verification & Status Ledger | **STACK AUDITED; DRC/LVS PENDING** | `finalization/finalization_tool_lock.json`, streamout scripts |

---

## 2. Pinned Design Identities & Primary Comparison Table

All measurements recorded at the frozen open-PDK corner: **SkyWater 130 (sky130A), standard cell library `sky130_fd_sc_hd`, typical-typical corner `tt_025C_1v80`**. Clock period = **10.0 ns** (100 MHz). Timing uses propagated clocks post-CTS with 0.10 ns setup / 0.05 ns hold uncertainty.

| Design ID | Role / Description | Primary RTL / Source Hash (SHA-256) | Placed Cell Area | Total Power (mW) [Stream 64 / Stream 128] | Finite Energy (nJ) [E_64 / E_128] | DRC Violations | Setup / Hold Slack (ns) | GDS Status |
|---|---|---|---:|---:|---:|---:|---:|---|
| **S0** | Primary accepted shared candidate (discovery) | `ce64c71552f0aa1750ae62c15a081d16d52e92396d9d67243088aeec4723e92e` | **286,970 um²** (−32.5% vs standalone sum; −33.1% vs Dual A) | 39.819 / 40.444 | 39.022 / 74.416 | 0 | **+0.108688 / +0.130449** | **STREAMOUT + ROUND-TRIP AUDITED** (`shared_s0_clean.gds`, 29 MB, 250k instances) |
| **S1** | PowerSave area Pareto point (single-run power tradeoff) | `f4d5ae2fadc63ab075f97344ec0ed4ccae6f6e66c8219a072c4c316a17b9e700` | **282,963 um²** (−33.4% vs standalone sum; −4,007 um² vs S0) | 39.931 / 40.445 | 39.132 / 74.418 | **NOT LOCALLY REPORTED** | **NOT LOCALLY REPORTED** | Archived in `ps_fft_campaign/best/`; final repeat archives PPA metrics but not timing/DRC detail |
| **A** | Ungated dual-core reference control | `27a4fe51709ede28365ac10a966394f550b6a339e6676b9957f2cb1ec3e55099` | **429,130 um²** (placed dual baseline) | 61.523 / 61.446 | 60.293 / 113.061 | 0 | **+0.467856 / +0.093027** | **STREAMOUT + ROUND-TRIP AUDITED** (`dual_a_clean.gds`, 42 MB, 366k instances) |
| **B** | Power-managed dual-core (`dlclkp_4` ICG), first valid pass | `6f79acd5337a98a84be744197a533d73760e7ac95db5f793a92f343ac3055afb` | **429,655 um²** (+0.12% vs Dual A; +1.12% vs standalone sum) | **23.387 / 41.712** | **22.919 / 76.750** | 0 | **+0.445 / +0.178** | **Measured; full stack not streamed** |
| **F** | Historical shared fallback (pre-loop baseline) | `6a56b8326993d091cd989fc45a68ac341e5a25a33aaace47e81fa42a1ab78499` | **315,359 um²** (−25.8% vs standalone sum) | 40.013 / 42.162 | 39.21 / 77.58 | 0 | +0.13 / +0.16 | Historical fallback; characterized in attribution run |

The machine-generated canonical comparison is `manifest/canonical_comparison.json`
and `manifest/canonical_comparison.csv`. It is the numerical source for this
table; B is a non-merged power control and is not part of the shared-candidate
area claim.

---

## 3. Scientific Question 1: Workload Break-Even (S0 vs A)

**Research Question:** *Does shared hardware retain an energy advantage against an unshared dual-core implementation, and under which workloads?*

### Grounded Findings (`workloads/breakeven_analysis.md`, `workloads/measured_control_comparison.csv`)
1. **Measured Finite-Window Energy Advantage (100% Active Window Duty):**
   - In the finite three-frame window, S0 consumes **35.28% less energy** per transform in mode 64 (39.02 vs 60.29 nJ) and **34.18% less energy** in mode 128 (74.42 vs 113.06 nJ), directly measured from physical VCD back-annotation. The 100% active-window model adds no idle interval but retains fill/drain overhead.
2. **Parametric Sensitivity Across Duty Cycles (5% to 100%):**
   - Active energy is modeled as the weighted sum $E_{active} = \beta E_{64} + (1 - \beta) E_{128}$ using measured finite transform energies (including pipeline fill and drain).
     - Across the full declared sensitivity envelope and all 54 evaluated points, S0's modeled energy advantage ranges from **34.18% to 42.07%**. The nominal idle model spans **34.18% to 40.52%**; these are modeled finite-window results, not idle-only VCD measurements.
    - No crossover point exists against **un-gated Dual A**; this does not claim dominance over power-managed B.
3. **Disclosures:**
   - Standalone idle power is evaluated across an explicit sensitivity envelope [clock network lower bound, nominal, scenario ceiling]; dedicated idle-only VCD back-annotation is planned as future characterization.

### Measured Power-Managed Control (Variant B)
- Variant B is the first valid power-managed dual-core control after two physical attempts. Attempt 1 was rejected for hold timing; attempt 2 added disclosed hold repair and passed mapped GLS, propagated-clock STA, TNS 0, DRC 0, and activity annotation.
- Against ungated Dual A, measured streaming power is **61.99% lower** in mode 64 (23.387 vs 61.523 mW) and **32.12% lower** in mode 128 (41.712 vs 61.446 mW). Finite three-frame energy is **61.99% lower** in mode 64 and **32.12% lower** in mode 128.
- Variant B placed cell area is **429,655 um²**, 525 um² (**+0.12%**) above Dual A. It is therefore a power-managed control, not an area-improvement result. Sparse-duty B comparisons are not reported because idle-only B activity was not directly measured.

---

## 4. Scientific Question 2: Spatial & Transient Thermal Sensitivity

**Research Question:** *Does reducing total power also reduce modeled peak on-die temperature, or does spatial concentration change the result?*

### Grounded Findings (`thermal/thermal_report.md`)
1. **Model Rigor:**
   - Evaluated using HotSpot 32×32 grid simulations, with peak and average temperatures extracted strictly from **Layer 0 (silicon die)**, excluding package and sink nodes.
   - Pinned standard quad flat package (60 mm heatsink, 30 mm spreader, silicon conductivity 130 W/m-K).
2. **Geometry 1 (Actual Die Footprints, Uniform Block Model):**
   - Across the entire convection resistance parameter sweep ($R_{th,conv} \in [0.1, 10.0]\ \text{K/W}$) and both ambient temperatures (300 K and 310.15 K), **Shared Design S0 exhibits lower modeled peak temperature rise than Dual Baseline A in 100% of cases**.
3. **Why Spatial Concentration Does Not Invert the Ordering:**
   - S0 reduces die footprint by **32.2%** ($0.6269\ \text{mm}^2$ vs $0.9246\ \text{mm}^2$).
   - However, S0 reduces total power by **35.3%** ($39.82\ \text{mW}$ vs $61.52\ \text{mW}$).
   - Consequently, areal power dissipation density is **4.5% lower** in S0 ($0.0635\ \text{W/mm}^2$) than in A ($0.0665\ \text{W/mm}^2$).
4. **Disclosures & Gate Decision:**
   - OpenSTA does not report per-instance power across 53k gates. Per Section 5 of the plan, a uniform-block thermal sensitivity model is delivered without heuristic internal splits, and fine-grained spatial sub-block hotspot conclusions are marked **UNAVAILABLE**.

---

## 5. Scientific Question 3: Evaluator Layer Efficacy & Fault Replay

**Research Question:** *Which incorrect or misleading candidate results are prevented by each deterministic evaluator layer?*

### Audited Replay Ledger (`replay/candidate_by_gate_matrix.md`, `replay/detection_summary.json`)
A frozen corpus of **31 distinct candidate records** across 5 explicit strata is represented in the ledger. The regenerated matrix applies strict fail-closed semantics: missing, invalid, unknown, or partial evidence is reported as **NOT_EVALUATED**, not treated as a passing or failing nested execution.

| Candidate Stratum | Total Cases | Defects | Evaluated Defects | Unevaluated Defects | Config 1 | Config 2 | Config 3 | Evaluated Legal | False Rejections |
|---|---|---|---|---|---|---|---|---|---|
| **Natural LLM Failures (Live Campaign)** | 5 | 5 | 0 | 5 | N/A | N/A | N/A | 0 | N/A |
| **Accepted Legal Candidates** | 9 | 0 | 0 | 0 | N/A | N/A | N/A | 3 | 0 / 3 |
| **Architectural / Negative Controls** | 4 | 4 | 0 | 4 | N/A | N/A | N/A | 0 | N/A |
| **Injected RTL Mutations** | 9 | 9 | 0 | 9 | N/A | N/A | N/A | 0 | N/A |
| **Infrastructure / Provenance Faults** | 4 | 4 | 0 | 4 | N/A | N/A | N/A | 0 | N/A |
| **Overall Total** | **31** | **22** | **0** | **22** | **N/A** | **N/A** | **N/A** | **3** | **0 / 3** |

### Key Takeaways:
- The corpus contains **22 recorded defect entries**, but none has complete local evidence for a fresh nested replay execution; therefore detection percentages are intentionally **not reported**.
- Three legal rows have complete local evidence: accepted S0, MAC M2, and MAC M3. They produce **0/3 false rejections** under the represented gate checks.
- Natural failures, architectural controls, mutations, and infrastructure faults remain observed records and evidence references, but are not converted into synthetic Config 1/2/3 detection results.
- The companion figure reports evidence coverage rather than implying a 100% detection result.
- **Controller-only MAC holdout:** accepted M2 and M3 both pass seed `0x7EEDBEEF` over 1,502 randomized cycles plus 157 directed cycles; reports are archived under `mac_hidden_judge/m2_fixed/` and `mac_hidden_judge/m3_fixed/`.
- **Fresh controller-only S0 FFT holdout:** the frozen S0 RTL passes all 36 archived bit-exact cases across both modes, including corners, random frames, bursts, aborts, mid-reset, and mode switches; report and complete run log are archived under `replay/final_s0_hidden_holdout/`. The archive records pass/fail rather than a latency trace, so exact 71/137-cycle latency remains a separately declared contract, not a newly reconstructed mapped-GLS measurement here.
- **Post-audit model-free S0 physical repeat:** an isolated sandbox reran the pinned current physical flow with the exact S0 RTL hash. The result matches the primary S0 record exactly for area, timing, TNS, router DRC, both streaming powers, and both finite energies; the result, audit, detailed 78-file physical archive, and hash-validation note are under `replay/s0_physical_repeat_20260909/`. The repeat flow-script hash differs from the historical primary record and is disclosed in the audit, so this is not an identical-flow rerun. It was not preregistered and independent streamed-layout DRC/LVS remains outside the repeat.

---

## 6. Layout Finalization Status (WP4)

- **Full-Stack GDS Stream-out + Round-trip Audit:**
  - Using KLayout with technology LEF (`sky130_fd_sc_hd__nom.tlef`) and cell LEF attached to resolve all via definitions (`M1M2_PR`, `L1M1_PR_MR`, `M2M3_PR`, etc.):
    - `shared_s0_clean.gds`: Top cell `peweaver_ppa_shared_fft`, BBox $791.79\ \mu\text{m} \times 791.79\ \mu\text{m}$, 250,549 resolved instances, SHA-256 `acdd02e0c82df4d5ae4dc32d2423471da9108ac26a4936377b1d917e0dbfbeda` (29.9 MB, round-trip audited).
    - `dual_a_clean.gds`: Top cell `peweaver_ppa_dual_fft`, BBox $961.55\ \mu\text{m} \times 961.55\ \mu\text{m}$, 366,961 resolved instances, SHA-256 `d7daecfbf5dc6dc07ca41ad42742ce71ed915ae11ca129593c6a67cf6827391f` (43.2 MB, round-trip audited).
- **Layout DRC / LVS Disclosure:**
  - OpenROAD detailed router DRC reported **0 violations** for both designs.
  - Independent streamed-layout DRC decks from Volare PDK (`sky130A_mr.drc` and `sky130A.lydrc`) are pinned in `finalization_tool_lock.json`; automated independent KLayout DRC/LVS execution remains pending. The GDS status is full-stack stream-out plus round-trip audit, not independent signoff.
  - Two independent KLayout batch attempts were recorded; pinned KLayout 0.26.2 segfaulted in Salt/Ruby startup before producing a report, including a clean-home/offscreen retry. This is an infrastructure failure, not a DRC pass or fail (`finalization/layout_verification_status.json`).

---

## 7. Claim Boundary & Disclosures
1. **No Silicon Tapeout Claim:** This is a provisional physical design and PPA estimate at the frozen `sky130A` / `tt_025C_1v80` corner using an open-source EDA flow. No multi-corner signoff, IR-drop/EM, or silicon measurement is claimed.
2. **No Clinical / Implant Claim:** While untethered BCI hardware motivates the surrogate, no biological tissue compliance, thermal safety margin, or clinical feasibility is claimed.
3. **Attribution Provenance:** Hierarchical power attribution was executed on fallback Design F (315k um²), showing 49.1% sequential register dissipation and 40.0% clock network power (89.1% total synchronous dissipation). This evidence informs why combinational RTL optimization alone did not recover power in ChiaPowerSave.
