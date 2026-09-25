# PEWeaver: Paper Narrative and Structural Strategy
**Target:** 4-Page Submission (Submission Deadline: 2026-09-20 AoE)  
**Artifact Baseline:** `submission_edge_20260906`  
**Theme:** Autonomous Hardware Sharing under Strict Physical Evaluator Governance  

---

## Executive Pitch & The Scientific Story

Most AI-for-hardware work stops at generating Verilog that compiles or passes a superficial testbench ("paper RTL"). In reality, modern silicon design rules, timing closure, physical routing congestion, and activity-based power represent an unforgiving, non-negotiable reality that generative models cannot simulate internally.

**PEWeaver demonstrates that autonomous agents can discover novel, non-trivial hardware sharing across complex sequential DSP pipelines—delivering a verified 32–33% placed cell area reduction in SkyWater 130 nm—provided the agent is governed by an unyielding, model-independent, fail-closed physical evaluator ladder.**

The paper is structured around three interlocking pillars:
1. **The Architectural Triumph:** In the tested negative control, standard synthesis (Yosys `abc`) fails to share the sequential hardware (0 multipliers shared). PEWeaver's agent loop discovers valid unified SDF sharing in the physically evaluated FFT and closes its timing and router-DRC gates, with 3/3 clean-room FFT reproductions. MAC passes a six-gate RTL/formal ladder, and FIR passes a six-gate RTL ladder; neither has a physical PPA result in this package.
2. **The Honest Power & Thermal Reality:** We reject "AI hype" and present an honest scientific accounting. A subsequent PowerSave campaign reduced area by 1.40% but changed measured power only slightly on a single run (raw deltas, not a statistical claim). Attribution on fallback F found **49.1% sequential-cell power and 40.0% clock-network power**, so synchronous components together account for 89.1%; naive RTL edits alone cannot remove that bottleneck. Against **un-gated Dual A**, the shared design's modeled finite-window energy advantage spans **34.18%–42.07% across the full declared sensitivity envelope** and **34.18%–40.52% under the nominal model**. These workload values use declared idle assumptions, not direct idle-only VCD measurements. The separate power-managed control B reduces measured dual-core streaming power by 61.99%/32.12% in modes 64/128, but is 0.12% larger than A and has no idle-only measurement.
3. **The MAGE Governance Audit:** We maintain a 31-record replay corpus across 5 explicit strata with evidence-aware, fail-closed classification. The current release does **not** claim corpus-wide detection rates: 22 defect records lack complete local nested-gate evidence, while 3 legal records have complete evidence and 0/3 are falsely rejected. This is an artifact audit/replay ledger, not a fresh execution of every candidate.

---

## 4-Page Section-by-Section Blueprint

### Page 1: Introduction & The Problem of Autonomous Hardware Sharing
* **The Promise & Pitfall of LLMs in Silicon:** LLMs excel at syntax and localized logic, but hardware design suffers from a severe *semantic gap* (MAGE theory): code that appears functional at the RTL level routinely fails physical synthesis, introduces timing loops, or violates physical DRC rules.
* **Why Traditional EDA Fails at Sequential Sharing:** In this tested flow, standard logic synthesis performs combinational sharing but does not infer the required stateful resource reuse across mutually exclusive modes in the pipelined DSP block.
* **Our Contributions:**
  1. *CHIA-Native Governance Framework:* Domain-neutral `ChiaMerge` and `ChiaPowerSave` transactional primitives with fail-closed gate ladders, config-fingerprinted resumption, and worker-kill isolation.
   2. *Verified Multi-Domain Hardware Sharing:* 32.5% to 33.4% placed-cell area reduction in the physically evaluated 130 nm FFT flow, 44% generic-cell reduction with bounded formal evidence in MAC, and stateful filter sharing in FIR at the RTL/structural level.
   3. *Full-Chip Control & Workload Matrix:* Physical comparison against an explicitly placed and routed dual-core baseline (Dual A), plus a first-valid ICG power-managed control (Variant B) that closes timing and DRC and provides continuous-streaming power measurements. Sparse-duty B extrapolation is intentionally excluded.
   4. *Thermal & Evaluator Replay Grounding:* Pinned HotSpot thermal sensitivity analysis and a 31-candidate evaluator replay matrix confirming the necessity of physical gate ladders.

---

### Page 2: Architecture, Governance, and The Gate Ladder
* **System Architecture:**
  - Decoupled **Adviser** (reasoning over architecture advice, power attribution, and gate feedback) and bounded **Implementer** operating in an isolated transactional sandbox (`ChiaIterate`).
  - Strict clean-room contract: candidate sees only interface obligations, baseline RTL, and deterministic validator error logs.
* **The Fail-Closed Evaluator Ladder (Figure: Gate Progression):**
  - *Gate 1 (Syntax/Lint):* Icarus Verilog strict linting, module port binding.
  - *Gate 2 (Functional Random Oracle):* 1,200–1,500 cycle randomized vector comparison against independent pure-Python mathematical oracles (no golden files consulted).
  - *Gate 3 (Directed Corners & Holdout):* Full dynamic range corners (zeros, alternating signs, impulses) and controller-owned hidden randomized holdouts. The archived holdout report records pass/fail and bit-exact cases, but does not preserve a latency trace; exact 71/137-cycle latency remains a separately declared contract rather than a newly reconstructed mapped-GLS result in this package.
  - *Gate 4 (Mapped GLS):* Unit-delay gate-level simulation of the synthesized netlist using Sky130 functional models, catching logic-opt and don't-care synthesis corruption.
  - *Gate 5 (Physical P&R & STA):* OpenROAD automated placement, CTS, detailed routing, OpenRCX parasitic extraction, and propagated-clock OpenSTA timing (+0.10 ns setup / +0.05 ns hold uncertainty at `tt_025C_1v80`).
  - *Gate 6 (DRC & Provenance):* Zero DRC violations, nonzero activity back-annotation, and SHA-256 manifest verification.
* **Domain Breadth:**
  - *FFT (Primary Physical Flow):* 64-point / 128-point reconfigurable SDF pipeline.
  - *MAC (Formal Second Domain):* 6-gate ladder incorporating SymbiYosys BMC depth-12 bounded formal verification with symbolic operands.
  - *FIR (Third Domain):* 8-tap constant-coefficient filter with independent state histories.

---

### Page 3: Physical Results, Attribution, and Workload Break-Even
* **Headline Comparison Table:**
  - Columns: Design ID (S0, S1, A, B), Role, Cell Area (um²), Streaming Power (mW), Energy/FFT (nJ), Routing DRC, Setup Slack, Layout Status.
  - Callout: S0 achieves **286,970 um²** (32.5% below the standalone sum, 33.1% below placed Dual A).
   - Power: S0 streaming power is **39.82 mW** (mode 64) and **40.44 mW** (mode 128) vs Dual A's **61.52 mW** / **61.45 mW**, or **35.3% / 34.2% lower**, respectively.
* **The Clock-Tree Attribution Finding (Honest Science):**
  - Describe the hierarchical power attribution analysis.
   - Key finding: fallback F attribution assigns **49.1% to sequential cells and 40.0% to the clock network** (89.1% synchronous total), not 49% to the clock tree alone.
    - The subsequent model-driven PowerSave campaign produced a verified area win (S1: 282,963 um², -1.40% vs S0), with canonical single-run deltas of +0.11251 mW/+0.00108 mW and +0.11026 nJ/+0.00199 nJ in modes 64/128; report these as raw deltas only. Naive RTL clock-gating broke timing closure in 3/5 physical candidates, while the gate ladder correctly rejected them.
   - Variant B is a disclosed model-free ICG control: attempt 1 failed hold timing; attempt 2 passed with 429,655 um², 23.387/41.712 mW streaming power, and +0.445/+0.178 ns setup/hold slack. It is a power control, not an area win.
* **Workload Energy Break-Even Analysis (Figure: Fig 1 Energy vs Duty Cycle):**
    - Evaluate the 54-point S0-vs-A workload matrix (5% to 100% duty cycle, 0%/50%/100% mode-64 occupancy, and lower-bound/nominal/ceiling idle models).
    - Under the declared nominal idle-power model, S0 consumes **35.28% less energy** at 100% active-window duty and **40.18% less energy** at 10% duty in mode 64 against **un-gated Dual A**. These are finite three-frame window calculations with no added idle interval at alpha=1, not indefinitely sustained-stream measurements.
   - Conclusion: No crossover exists against un-gated Dual A in this model. B is excluded from sparse-duty extrapolation and prevents a claim of universal power dominance.
* **Silicon Footprint & Thermal Distribution (Figures: Fig 4 Paired Heatmap & Fig 5 Layout):**
  - Silicon die footprint: S0 ($0.627\ \text{mm}^2$) vs Dual A ($0.925\ \text{mm}^2$) represents a **32.2% die footprint reduction**.
   - Thermal analysis in HotSpot across $R_{th,conv} \in [0.1, 10.0]\ \text{K/W}$: Figure 3 uses actual die footprints and at 300 K / 1 K/W gives approximately +470 mK (S0) versus +530 mK (A). Figure 4 uses a common outer footprint and gives +370 mK versus +530 mK; it is a geometry-control result, not the actual-die shrink result.
  - Why? Power reduction (35.3%) outpaces area reduction (32.2%), reducing areal dissipation density from $0.0665\ \text{W}/\text{mm}^2$ (A) to $0.0635\ \text{W}/\text{mm}^2$ (S0).

---

### Page 4: Evaluator Replay, MAGE Governance, and Conclusion
* **Evidence Ledger on 31-Candidate Corpus (Figure: Fig 2 Replay Evidence Coverage):**
   - Present the 5-strata evidence matrix:
     - *Natural LLM failures (5):* timing regressions and implementation failures from the live campaign.
     - *Accepted legal candidates (9):* FFT S0/S1/Repro1-3, MAC M2/M3, FIR F1, legal commutation.
     - *Architectural / negative controls (4):* functionally plausible but structurally unsafe or below-floor designs.
     - *RTL mutations (9):* Arithmetic shifts, twiddle corruptions, accumulator hold violations, counter wraps.
     - *Infrastructure/provenance faults (4):* stale, incomplete, or provenance-invalid evidence.
      - Quantitative Result: **0/22 defect records are evidence-complete for a fresh nested replay statistic**; detection rates are withheld. Three legal records are evidence-complete and the represented checks falsely reject **0/3**.
* **Implications for AI-Driven System Design (MAGE Connection):**
    - In this study, externalized contracts and fail-closed gate ladders are what convert commodity LLM proposals into durable, physically checked hardware artifacts.
    - The current replay package demonstrates evidence discipline and fail-closed handling; it does not claim a fresh, corpus-wide detection rate until the missing nested executions are archived.
* **Layout Finalization & Reproducibility Package:**
   - Both S0 and Dual A streamed out to full-stack layout GDS (`shared_s0_clean.gds`, `dual_a_clean.gds`) and passed round-trip layer audits.
   - Independent KLayout DRC/LVS decks are pinned, but execution remains pending; router DRC 0 is not independent streamed-layout signoff.
  - Complete reproducibility package: all logs, seeds, manifests, vectors, and netlists.
* **Limitations & Claim Boundary:**
  - Surrogate experimental vehicle (64/128-point FFT), not clinical BCI hardware.
  - Single frozen corner (`sky130A`, `tt_025C_1v80`, 10 ns clock); no multi-corner signoff, IR-drop, or biological tissue claims.

---

## Strategic Framing Guidelines for Writing

1. **Lead with Rigor, Not Agent Hype:**  
   Emphasize that the evaluator—not the model—is the ultimate authority. The agent proposes; the deterministic physical design ladder disposes.
2. **Turn the Negative Power Result into a Major Asset:**  
   Reviewers distrust papers where every AI metric is unrealistically favorable. The fact that ChiaPowerSave honestly encountered a synchronous-power bottleneck (49.1% sequential cells plus 40.0% clock network on fallback F), and that 3/5 physical candidates were rejected for timing regressions, proves that our evaluator ladder is genuinely enforced, not rubber-stamped.
   3. **Contrast with Standard Synthesis:**
      In the tested negative control, Yosys `abc` shared 0 multipliers. The agent found valid architectural sharing that the tested deterministic synthesis flow did not infer.
4. **Tight Coordination Between Visuals and Text:**  
    - Figure 1: Workload Break-Even curve (nominal mode-64 modeled 35.28%–40.52% energy win against un-gated Dual A).
    - Figure 2: Replay evidence-coverage chart (shows which defect rows have complete local evidence; detection rates are withheld).
    - Figure 3: Actual-die thermal resistance curve (at 1 K/W, +470 mK S0 vs +530 mK A).
    - Figure 4: Common-outer-footprint paired HotSpot heatmap (+370 mK S0 vs +530 mK A); this geometry is distinct from Figure 3.
   - Figure 5: Scaled Layout Footprint (visually displays -32.2% die area reduction).
