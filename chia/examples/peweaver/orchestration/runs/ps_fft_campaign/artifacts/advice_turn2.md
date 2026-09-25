## Atomic hypothesis

**Clock-gate only the mode-128-only upper halves of the six `SharedDelayBuffer` banks with characterized `sky130_fd_sc_hd__dlclkp` cells.**

Make no other optimization in this candidate—specifically, no operand isolation, tail-stage gating, arithmetic changes, counter changes, or reset changes.

### Why retry this hypothesis

The previous physical failure did not test this hypothesis correctly:

- It used `if (mode)` clock enables, which synthesized approximately 2,016 bits into enabled flops rather than removing their clock-tree activity.
- It also added multiplier operand-isolation muxes, violating the one-hypothesis rule.
- Those muxes touched the already-critical multiply datapath and plausibly caused the reported timing failure.
- The result reduced `p64` by only about 0.021 mW while increasing area from 286,970 to 311,415 and `p128` from 40.44 to 42.07 mW.

Thus the failure is evidence against enable-flop substitution and bundled operand isolation, not against real integrated clock gating.

## Exact scope

In `SharedDelayBuffer`:

1. Keep the first `DEPTH0` complex words on the original `clock`.
2. Put the remaining `DEPTH1-DEPTH0` words on one local `dlclkp` gated clock.
3. Drive the gate enable from the existing `mode` input, which is already `active_mode` at all six instances.
4. On each enabled edge, upper word zero must capture the **pre-edge** lower terminal word.
5. Preserve the existing output selection:
   - Mode 64: lower terminal word.
   - Mode 128: upper terminal word.
6. Preserve unreset delay storage.

Use separate nonblocking lower-bank and upper-bank sequential processes. Do not add a boundary register, since that would alter mode-128 latency.

This creates exactly six local clock gates and suppresses mode-64 clocks to:

| Bank extension | Clocked bits removed in mode 64 |
|---|---:|
| 32 complex words | 1,024 |
| 16 complex words | 512 |
| 8 complex words | 256 |
| 4 complex words | 128 |
| 2 complex words | 64 |
| 1 complex word | 32 |
| **Total** | **2,016** |

## Evidence basis

Clock-root power is 19.66 mW, or 49.1% of total mode-64 streaming power, with 19.23 mW attributed to internal power. By contrast, all three named FFT stages together account for under 1 mW. Removing clock edges from 2,016 storage bits therefore targets the dominant measured mechanism directly; operand isolation does not.

## Correctness argument

- **Mode 64:** The upper halves are neither selected nor able to feed the lower halves, so freezing them cannot affect values, valid timing, frame continuity, or the 71-cycle latency.
- **Mode 128:** `active_mode` is stable high before useful traffic under the reset-separated protocol. The characterized latch-based gates pass every functional edge, reproducing the original full-depth shifts and 137-cycle latency.
- **Transitions:** Stale upper data is harmless because mode changes are reset-separated and the incumbent already relies on valid-state flushing for its unreset delay arrays.

## Implementation and physical cautions

- Instantiate the actual characterized primitive with its `CLK`, `GATE`, and `GCLK` pins; never synthesize a behavioral `clock & mode`.
- Any RTL-only functional model must be excluded from synthesis without causing a duplicate definition during GLS.
- Confirm the mapped netlist contains exactly six `sky130_fd_sc_hd__dlclkp_*` instances and no enable-flop replacement for the upper banks.
- Check clock-gating setup/hold and the lower-terminal-to-upper-word-zero crossing after CTS.
- The data-critical multiplier paths must remain structurally identical to the incumbent.

Acceptance remains bit-exact RTL and mapped GLS, exact 71/137-cycle latency, TNS 0, DRC 0, qualifying area, and separate 64/128 power measurements.