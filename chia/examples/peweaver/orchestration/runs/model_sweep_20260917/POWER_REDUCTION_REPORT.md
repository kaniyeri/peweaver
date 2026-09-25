# Preliminary Generated-Pair Power Measurements

Activity-based power measurements on **SkyWater 130nm standard cells** (`sky130_fd_sc_hd__tt_025C_1v80.lib`) using OpenSTA and cycle-accurate mapped-netlist VCD simulation. These are generated benchmark RTL pairs, not accepted PEWeaver merge candidates.

| Benchmark Domain | Baseline Power | Power-Optimized | Total Change | Switching Change | Sequential Change | Key Mechanisms |
|---|---:|---:|---:|---:|---:|---|
| **MAC** (8x8 Acc/Prod) | 0.4690 mW | 0.3152 mW | **32.79% lower** | **30.47% lower** | **45.86% lower** | Multiplier operand isolation & adder input gating |
| **FIR** (Dual 8-Tap Q15) | 2.6170 mW | 2.3161 mW | **11.50% lower** | **55.80% higher** | **68.23% lower** | Split-context ICG clock gating & multiplier freeze |
| **DWT** (Dual-Context db2) | 5.5654 mW | 4.0533 mW | **27.17% lower** | **6.08% lower** | **67.58% lower** | Active-cycle decimation operand isolation & split ICG |

### Qualification Boundary:
- The original 1200-cycle captures matched within each generated baseline/optimized pair.
- Independent controller-owned mapped-netlist qualification is archived separately in `power_reduction_independent_judge.json`.
- These measurements have no accepted-merge provenance and are not exhaustive correctness or silicon evidence.
- Optimized clock gating uses the characterized `sky130_fd_sc_hd__dlclkp_4` integrated clock latch cell; no combinational clock gating is claimed.
