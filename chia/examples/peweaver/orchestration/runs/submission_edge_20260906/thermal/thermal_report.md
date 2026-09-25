# Thermal Sensitivity Analysis: Shared (S0) vs Ungated Dual (A)

## Scientific Question & Findings
**Question 2:** *Does reducing total power also reduce modeled peak on-die temperature, or does spatial concentration change the result?*

### Methodology & Disclosures
- **Model Type:** HotSpot 32×32 grid model; temperatures extracted strictly from **Layer 0 (silicon die)**, excluding package and sink nodes.
- **Package Parameters:** Pinned standard quad flat package (60 mm heatsink, 30 mm spreader, silicon conductivity 130 W/m-K).
- **Power Density Comparison:**
  - **Shared Design S0:** Total power = **39.82 mW** (mode 64) / **40.44 mW** (mode 128) on a **0.627 mm²** die.
    - Dissipation density: **0.0635 W/mm²** (mode 64) / **0.0645 W/mm²** (mode 128).
  - **Dual Baseline A:** Total power = **61.52 mW** (mode 64) / **61.45 mW** (mode 128) on a **0.925 mm²** die.
    - Dissipation density: **0.0665 W/mm²** (mode 64) / **0.0665 W/mm²** (mode 128).
  - **Power Ratio (S0 / A):** **64.7%** (Shared saves **35.3%** in total power).
  - **Density Ratio (S0 / A):** **95.5%** (Power density is **4.5% lower** in S0 because the 35.3% power reduction exceeds the 32.2% die area reduction).

## Geometry Comparison 1: Actual Die Footprints (Uniform Block Model)
Both designs modeled across their full routed silicon area under identical package boundary conditions.

| Ambient | Convection R_th (K/W) | S0 Mode-64 Rise (mK) | A Mode-64 Rise (mK) | Mode-64 Delta (mK) | S0 Mode-128 Rise (mK) | A Mode-128 Rise (mK) | Lower Temp Design |
|---|---|---|---|---|---|---|---|
| amb_300K | 0.1 | 440.0 | 480.0 | -40.0 | 440.0 | 470.0 | **S0 (Shared)** |
| amb_300K | 0.5 | 450.0 | 500.0 | -50.0 | 460.0 | 500.0 | **S0 (Shared)** |
| amb_300K | 1.0 | 470.0 | 530.0 | -60.0 | 480.0 | 530.0 | **S0 (Shared)** |
| amb_300K | 2.0 | 510.0 | 590.0 | -80.0 | 520.0 | 590.0 | **S0 (Shared)** |
| amb_300K | 5.0 | 630.0 | 780.0 | -150.0 | 640.0 | 780.0 | **S0 (Shared)** |
| amb_300K | 10.0 | 830.0 | 1090.0 | -260.0 | 850.0 | 1090.0 | **S0 (Shared)** |
| amb_310K | 0.1 | 440.0 | 480.0 | -40.0 | 440.0 | 470.0 | **S0 (Shared)** |
| amb_310K | 0.5 | 450.0 | 500.0 | -50.0 | 460.0 | 500.0 | **S0 (Shared)** |
| amb_310K | 1.0 | 470.0 | 530.0 | -60.0 | 480.0 | 530.0 | **S0 (Shared)** |
| amb_310K | 2.0 | 510.0 | 590.0 | -80.0 | 520.0 | 590.0 | **S0 (Shared)** |
| amb_310K | 5.0 | 630.0 | 780.0 | -150.0 | 640.0 | 780.0 | **S0 (Shared)** |
| amb_310K | 10.0 | 830.0 | 1090.0 | -260.0 | 850.0 | 1090.0 | **S0 (Shared)** |

## Geometry Comparison 2: Common Outer Footprint Sensitivity
Both designs evaluated within a common 0.9616 mm × 0.9616 mm silicon outline, with S0's compact core placed at the center and inactive perimeter silicon modeled explicitly.

| Ambient | Convection R_th (K/W) | S0 Core Rise (mK) | A Die Rise (mK) | Delta (mK) | Thermal Winner |
|---|---|---|---|---|---|
| amb_300K | 0.1 | 340.0 | 480.0 | -140.0 | **S0 (Shared)** |
| amb_300K | 0.5 | 350.0 | 500.0 | -150.0 | **S0 (Shared)** |
| amb_300K | 1.0 | 370.0 | 530.0 | -160.0 | **S0 (Shared)** |
| amb_300K | 2.0 | 410.0 | 590.0 | -180.0 | **S0 (Shared)** |
| amb_300K | 5.0 | 540.0 | 780.0 | -240.0 | **S0 (Shared)** |
| amb_300K | 10.0 | 740.0 | 1090.0 | -350.0 | **S0 (Shared)** |
| amb_310K | 0.1 | 340.0 | 480.0 | -140.0 | **S0 (Shared)** |
| amb_310K | 0.5 | 350.0 | 500.0 | -150.0 | **S0 (Shared)** |
| amb_310K | 1.0 | 370.0 | 530.0 | -160.0 | **S0 (Shared)** |
| amb_310K | 2.0 | 410.0 | 590.0 | -180.0 | **S0 (Shared)** |
| amb_310K | 5.0 | 540.0 | 780.0 | -240.0 | **S0 (Shared)** |
| amb_310K | 10.0 | 740.0 | 1090.0 | -350.0 | **S0 (Shared)** |

## Grounded Conclusions
1. **Lower Total Power Yields Lower Modeled Peak Rise Across Tested Ranges:** In both geometry comparisons and across all evaluated convection resistances, the shared design produces lower peak temperature rise above ambient than Dual Baseline A.
2. **Areal Density Mechanics:** S0's 35.3% power reduction outpaces its 32.2% area reduction, resulting in slightly lower areal power density (0.0635 vs 0.0665 W/mm²). Consequently, spatial concentration does not invert the thermal ranking.
3. **Claim Boundary:** This is an uncalibrated HotSpot RC-lumped grid sensitivity model comparing uniform-block dissipation. It does NOT constitute a clinical implant safety assessment or biological tissue compliance claim.
