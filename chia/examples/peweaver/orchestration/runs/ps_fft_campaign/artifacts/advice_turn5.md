## Recommended atomic hypothesis

**Clock-gate only the mode-128-only upper extensions of the six `SharedDelayBuffer` instances in mode 64, using one characterized `sky130_fd_sc_hd__dlclkp_1` per buffer.**

Do not combine this candidate with tail gating, operand isolation, counter enables, reset changes, or arithmetic restructuring.

## Evidence basis

The incumbent shifts every delay buffer to its mode-128 depth regardless of mode. In mode 64, the upper extensions are unused:

| Buffer | 128-only complex words | Clocked bits |
|---|---:|---:|
| `SU0.DB1` | 32 | 1,024 |
| `SU0.DB2` | 16 | 512 |
| `SU1.DB1` | 8 | 256 |
| `SU1.DB2` | 4 | 128 |
| `SU2.DB1` | 2 | 64 |
| `SU2.DB2` | 1 | 32 |
| **Total** | **63** | **2,016** |

This directly targets the dominant measured mechanism: `clock_root` accounts for 19.6566 mW, approximately 49.1% of total streaming power, with 19.2296 mW being internal power. The named arithmetic stages together consume less than 1 mW, making operand isolation a lower-priority hypothesis.

## Required structural behavior

Within `SharedDelayBuffer`:

- Keep indices `0 .. DEPTH0-1` on the original `clock`.
- Put indices `DEPTH0 .. DEPTH1-1` behind one local `sky130_fd_sc_hd__dlclkp_1`.
- Drive `GATE` from the buffer’s existing `mode`, which receives transaction-stable `active_mode`.
- Preserve the existing output taps:
  - mode 64: `DEPTH0-1`
  - mode 128: `DEPTH1-1`
- Keep delay storage unreset, exactly as in the incumbent.
- Use separate nonblocking lower- and upper-bank processes so the first upper word captures the **pre-edge** value of the lower terminal word.
- Do not introduce a boundary register; it would add one cycle to mode-128 behavior.
- Do not gate from `di_en`, local valid signals, or `do_en`, because SDF storage must continue shifting through fill and drain.

## Correctness argument

- **Mode 64:** Upper storage is neither selected nor fed back into the lower bank. Freezing it cannot alter FFT values, valid generation, frame continuity, or the 71-cycle latency.
- **Mode 128:** The gate remains enabled continuously, so the split storage is cycle-equivalent to the original full-depth shift and preserves the 137-cycle latency.
- **Mode transitions:** Changes are reset-separated, allowing the latch-based clock gates to acquire the static mode before useful traffic. Stale upper-bank contents are flushed before becoming valid, as with the incumbent’s unreset delay arrays.
- **Arithmetic:** No arithmetic or twiddle path changes.

## Implementation-flow constraint

RTL simulation may require a clock-enable behavioral branch for the upper-bank updates because the Verilator judge may not include the PDK primitive model. That branch must not synthesize. The synthesis branch must instantiate the actual characterized cell—never `clock & mode`, a ternary clock, or generic combinational logic driving a clock.

## Acceptance checks

1. Exactly six `sky130_fd_sc_hd__dlclkp_1` instances survive synthesis.
2. The 2,016 upper-extension bits are physically clocked by those gates, not transformed into D-input-enabled flops.
3. No generic logic drives clock pins.
4. Bit-exact 64/128 operation, including continuous three-frame bursts.
5. Exact first-valid latencies of 71 and 137 cycles.
6. Reset-separated `64→128`, `128→64`, and return-to-128 cases.
7. Mapped GLS passes with the PDK gate model.
8. Clock-gating checks, ordinary setup/hold, TNS 0, and DRC 0.
9. Area remains below 339,908 µm².
10. Measure both modes: expect a meaningful `p64/e64` reduction and a small possible `p128/e128` overhead from six gates.

No files were edited.