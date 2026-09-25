# Workload Energy Break-Even Analysis (Measured Parameterized)

## Scientific Question & Methodology
**Question 1:** *Does shared hardware retain an energy advantage against an unshared dual-core implementation, and under which workloads?*

### Grounded Energy Formulation
- **Active Energy per Transform ($E_{active}$):** Directly anchored to authoritative physical measurements of finite 3-frame transform energy (including pipeline fill and drain):
  - S0: $E_{64} = 39.0222182$ nJ, $E_{128} = 74.41644480000001$ nJ
  - A:  $E_{64} = 60.292618399999995$ nJ, $E_{128} = 113.06141280000001$ nJ
- **Measured Transform Durations:** $T_{64} = 0.98$ us and $T_{128} = 1.84$ us per completed transform, including fill and drain; average power uses the same finite window as the measured energy.
- **Mixed-Schedule Active Energy:** Weighted sum $E_{active} = \beta E_{64} + (1 - \beta) E_{128}$ with the matching weighted transform duration (eliminating dimensional averaging errors).
- **Idle Dissipation Model:** Modeled as $E_{idle} = P_{idle} \cdot T_{active} \frac{1 - \alpha}{\alpha}$. Evaluated with nominal idle dissipation ($P_{idle,S0} = 28.5$ mW, $P_{idle,A} = 48.2$ mW) and bounded across clock-only lower bounds (16.0 / 28.0 mW) and scenario ceilings (38.5 / 59.3 mW).

## Workload Comparison Table (All Idle Models)

| Idle Model | Schedule | Active Duty Cycle | S0 Energy/FFT (nJ) | A Energy/FFT (nJ) | S0 Avg Power (mW) | A Avg Power (mW) | Energy Advantage (%) | Winning Design |
|---|---|---|---|---|---|---|---|---|
| lower_bound | Mode 128 (100%) | 5% | 633.78 | 1091.94 | 17.22 | 29.67 | **+42.0%** | **S0 (Shared)** |
| lower_bound | Mode 128 (100%) | 10% | 339.38 | 576.74 | 18.44 | 31.34 | **+41.2%** | **S0 (Shared)** |
| lower_bound | Mode 128 (100%) | 25% | 162.74 | 267.62 | 22.11 | 36.36 | **+39.2%** | **S0 (Shared)** |
| lower_bound | Mode 128 (100%) | 50% | 103.86 | 164.58 | 28.22 | 44.72 | **+36.9%** | **S0 (Shared)** |
| lower_bound | Mode 128 (100%) | 75% | 84.23 | 130.24 | 34.33 | 53.09 | **+35.3%** | **S0 (Shared)** |
| lower_bound | Mode 128 (100%) | 100% | 74.42 | 113.06 | 40.44 | 61.45 | **+34.2%** | **S0 (Shared)** |
| lower_bound | Mixed 50/50 | 5% | 485.36 | 836.80 | 17.21 | 29.67 | **+42.0%** | **S0 (Shared)** |
| lower_bound | Mixed 50/50 | 10% | 259.76 | 442.00 | 18.42 | 31.35 | **+41.2%** | **S0 (Shared)** |
| lower_bound | Mixed 50/50 | 25% | 124.40 | 205.12 | 22.06 | 36.37 | **+39.4%** | **S0 (Shared)** |
| lower_bound | Mixed 50/50 | 50% | 79.28 | 126.16 | 28.11 | 44.74 | **+37.2%** | **S0 (Shared)** |
| lower_bound | Mixed 50/50 | 75% | 64.24 | 99.84 | 34.17 | 53.10 | **+35.7%** | **S0 (Shared)** |
| lower_bound | Mixed 50/50 | 100% | 56.72 | 86.68 | 40.23 | 61.47 | **+34.6%** | **S0 (Shared)** |
| lower_bound | Mode 64 (100%) | 5% | 336.94 | 581.65 | 17.19 | 29.68 | **+42.1%** | **S0 (Shared)** |
| lower_bound | Mode 64 (100%) | 10% | 180.14 | 307.25 | 18.38 | 31.35 | **+41.4%** | **S0 (Shared)** |
| lower_bound | Mode 64 (100%) | 25% | 86.06 | 142.61 | 21.95 | 36.38 | **+39.6%** | **S0 (Shared)** |
| lower_bound | Mode 64 (100%) | 50% | 54.70 | 87.73 | 27.91 | 44.76 | **+37.6%** | **S0 (Shared)** |
| lower_bound | Mode 64 (100%) | 75% | 44.25 | 69.44 | 33.86 | 53.14 | **+36.3%** | **S0 (Shared)** |
| lower_bound | Mode 64 (100%) | 100% | 39.02 | 60.29 | 39.82 | 61.52 | **+35.3%** | **S0 (Shared)** |
| nominal | Mode 128 (100%) | 5% | 1070.78 | 1798.13 | 29.10 | 48.86 | **+40.5%** | **S0 (Shared)** |
| nominal | Mode 128 (100%) | 10% | 546.38 | 911.25 | 29.69 | 49.52 | **+40.0%** | **S0 (Shared)** |
| nominal | Mode 128 (100%) | 25% | 231.74 | 379.12 | 31.49 | 51.51 | **+38.9%** | **S0 (Shared)** |
| nominal | Mode 128 (100%) | 50% | 126.86 | 201.75 | 34.47 | 54.82 | **+37.1%** | **S0 (Shared)** |
| nominal | Mode 128 (100%) | 75% | 91.90 | 142.62 | 37.46 | 58.13 | **+35.6%** | **S0 (Shared)** |
| nominal | Mode 128 (100%) | 100% | 74.42 | 113.06 | 40.44 | 61.45 | **+34.2%** | **S0 (Shared)** |
| nominal | Mixed 50/50 | 5% | 820.23 | 1377.95 | 29.09 | 48.86 | **+40.5%** | **S0 (Shared)** |
| nominal | Mixed 50/50 | 10% | 418.38 | 698.34 | 29.67 | 49.53 | **+40.1%** | **S0 (Shared)** |
| nominal | Mixed 50/50 | 25% | 177.27 | 290.56 | 31.43 | 51.52 | **+39.0%** | **S0 (Shared)** |
| nominal | Mixed 50/50 | 50% | 96.90 | 154.64 | 34.36 | 54.84 | **+37.3%** | **S0 (Shared)** |
| nominal | Mixed 50/50 | 75% | 70.11 | 109.33 | 37.30 | 58.16 | **+35.9%** | **S0 (Shared)** |
| nominal | Mixed 50/50 | 100% | 56.72 | 86.68 | 40.23 | 61.47 | **+34.6%** | **S0 (Shared)** |
| nominal | Mode 64 (100%) | 5% | 569.69 | 957.78 | 29.07 | 48.87 | **+40.5%** | **S0 (Shared)** |
| nominal | Mode 64 (100%) | 10% | 290.39 | 485.42 | 29.63 | 49.53 | **+40.2%** | **S0 (Shared)** |
| nominal | Mode 64 (100%) | 25% | 122.81 | 202.00 | 31.33 | 51.53 | **+39.2%** | **S0 (Shared)** |
| nominal | Mode 64 (100%) | 50% | 66.95 | 107.53 | 34.16 | 54.86 | **+37.7%** | **S0 (Shared)** |
| nominal | Mode 64 (100%) | 75% | 48.33 | 76.04 | 36.99 | 58.19 | **+36.4%** | **S0 (Shared)** |
| nominal | Mode 64 (100%) | 100% | 39.02 | 60.29 | 39.82 | 61.52 | **+35.3%** | **S0 (Shared)** |
| upper_bound | Mode 128 (100%) | 5% | 1420.38 | 2186.19 | 38.60 | 59.41 | **+35.0%** | **S0 (Shared)** |
| upper_bound | Mode 128 (100%) | 10% | 711.98 | 1095.07 | 38.69 | 59.52 | **+35.0%** | **S0 (Shared)** |
| upper_bound | Mode 128 (100%) | 25% | 286.94 | 440.40 | 38.99 | 59.84 | **+34.9%** | **S0 (Shared)** |
| upper_bound | Mode 128 (100%) | 50% | 145.26 | 222.17 | 39.47 | 60.37 | **+34.6%** | **S0 (Shared)** |
| upper_bound | Mode 128 (100%) | 75% | 98.03 | 149.43 | 39.96 | 60.91 | **+34.4%** | **S0 (Shared)** |
| upper_bound | Mode 128 (100%) | 100% | 74.42 | 113.06 | 40.44 | 61.45 | **+34.2%** | **S0 (Shared)** |
| upper_bound | Mixed 50/50 | 5% | 1088.13 | 1675.32 | 38.59 | 59.41 | **+35.0%** | **S0 (Shared)** |
| upper_bound | Mixed 50/50 | 10% | 545.28 | 839.19 | 38.67 | 59.52 | **+35.0%** | **S0 (Shared)** |
| upper_bound | Mixed 50/50 | 25% | 219.57 | 337.52 | 38.93 | 59.84 | **+34.9%** | **S0 (Shared)** |
| upper_bound | Mixed 50/50 | 50% | 111.00 | 170.29 | 39.36 | 60.39 | **+34.8%** | **S0 (Shared)** |
| upper_bound | Mixed 50/50 | 75% | 74.81 | 114.55 | 39.80 | 60.93 | **+34.7%** | **S0 (Shared)** |
| upper_bound | Mixed 50/50 | 100% | 56.72 | 86.68 | 40.23 | 61.47 | **+34.6%** | **S0 (Shared)** |
| upper_bound | Mode 64 (100%) | 5% | 755.89 | 1164.46 | 38.57 | 59.41 | **+35.1%** | **S0 (Shared)** |
| upper_bound | Mode 64 (100%) | 10% | 378.59 | 583.32 | 38.63 | 59.52 | **+35.1%** | **S0 (Shared)** |
| upper_bound | Mode 64 (100%) | 25% | 152.21 | 234.63 | 38.83 | 59.86 | **+35.1%** | **S0 (Shared)** |
| upper_bound | Mode 64 (100%) | 50% | 76.75 | 118.41 | 39.16 | 60.41 | **+35.2%** | **S0 (Shared)** |
| upper_bound | Mode 64 (100%) | 75% | 51.60 | 79.66 | 39.49 | 60.97 | **+35.2%** | **S0 (Shared)** |
| upper_bound | Mode 64 (100%) | 100% | 39.02 | 60.29 | 39.82 | 61.52 | **+35.3%** | **S0 (Shared)** |

## Grounded Findings
1. **100% Active Window Duty (finite three-frame window):** S0 consumes **35.28% less energy** per transform in mode 64 (39.022 vs 60.293 nJ). These finite three-frame energies are directly measured from physical VCD back-annotation; the model adds no idle interval between windows at alpha=1.
2. **Mode-128 Continuous Streaming:** S0 consumes **34.18% less energy** per transform (74.416 vs 113.061 nJ).
3. **Sparse Telemetry (10% Duty Cycle, Mode 64):** Under the nominal idle-power model (not a direct idle-only VCD measurement), S0 consumes **40.18% less energy** per transform (290.392 vs 485.417 nJ). The model assigns lower idle dissipation to S0 than to un-gated Dual A.
4. **Absence of Crossover Against Ungated Dual A:** Across all evaluated duty cycles (5%, 10%, 25%, 50%, 75%, 100%) and occupancy ratios, S0 is lower than un-gated Dual A in this declared sensitivity model because it has lower active transform energy and lower modeled idle power. This does not claim dominance over power-managed B.
5. **Sensitivity coverage:** The emitted matrix contains 54 points (18 schedules per idle model) across lower-bound, nominal, and scenario-ceiling idle assumptions. Direct idle-only VCD measurement with zero data toggles remains future characterization.

## Measured Continuous-Streaming Controls

Variant B is the first valid power-managed dual-core control after two physical attempts. Its source result is `../dual_b/results/physical_attempt2/dual_b_sky130.json`.

| Design | Role | Mode | Energy/FFT (nJ) | Streaming Power (mW) | Placed Cell Area (um²) | Timing | DRC |
|---|---|---:|---:|---:|---:|---|---:|
| S0 | shared | 64 | 39.022 | 39.819 | 286970 | PASS | 0 |
| S0 | shared | 128 | 74.416 | 40.444 | 286970 | PASS | 0 |
| A | ungated dual control | 64 | 60.293 | 61.523 | 429130 | PASS | 0 |
| A | ungated dual control | 128 | 113.061 | 61.446 | 429130 | PASS | 0 |
| B | power-managed dual control | 64 | 22.919 | 23.387 | 429655 | PASS | 0 |
| B | power-managed dual control | 128 | 76.750 | 41.712 | 429655 | PASS | 0 |

Against A, B reduces measured streaming power and finite energy by 61.99% in mode 64 and 32.12% in mode 128, while placed cell area is 0.12% larger. B has no idle-only VCD, so it is intentionally excluded from the sparse-duty sensitivity table.
