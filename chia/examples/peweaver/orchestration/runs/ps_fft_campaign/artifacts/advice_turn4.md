## Failure diagnosis

The reported line:

`shared_activity_tb.sv:247: Verilog $finish`

is only the testbench termination point. `burst_len=384` confirms the final three-frame mode-128 burst produced the expected number of valid outputs, so the failure was primarily numerical rather than latency or valid-window corruption.

The rejected staging RTL contains a likely mode-128 data bug:

```verilog
assign bf_sp_im = bf_en ? y0_im : db_do_re;
```

The accepted incumbent correctly uses:

```verilog
assign bf_sp_im = bf_en ? y0_im : db_do_im;
```

Because this is in the 128-point tail, it explains correct burst length with mode-128 value mismatches. The exact three error events cannot be reconstructed from the aggregate log, and that rejected file also contains unrelated reset and twiddle changes. Therefore, any future candidate must be based only on:

`/work/peweaver/runs/ps-fft-6/best/peweaver_shared_fft.v`

—not the failed physical staging copy.

## One atomic hypothesis

> **Clock-gate only the mode-128-only upper extensions of the six shared delay buffers in mode 64, using one characterized `sky130_fd_sc_hd__dlclkp` cell per buffer.**

Do not combine this with tail gating, operand isolation, arithmetic changes, counter changes, or reset cleanup.

### Targeted state

Each shared delay has `DEPTH1 = 2 × DEPTH0`. Mode 64 reads only the lower half; the upper half cannot feed backward into it.

| Buffer | 128-only words | Clocked bits |
|---|---:|---:|
| `SU0.DB1` | 32 complex | 1,024 |
| `SU0.DB2` | 16 complex | 512 |
| `SU1.DB1` | 8 complex | 256 |
| `SU1.DB2` | 4 complex | 128 |
| `SU2.DB1` | 2 complex | 64 |
| `SU2.DB2` | 1 complex | 32 |
| **Total** | **63 complex** | **2,016** |

This directly attacks the dominant measured component: clock-root power is approximately 49.1% of total, while named stage arithmetic is comparatively small.

## Required semantics

For each delay buffer:

- Keep indices `0 .. DEPTH0-1` on the original clock.
- Clock indices `DEPTH0 .. DEPTH1-1` from a characterized latch-based clock gate.
- Enable the gate with the already transaction-stable active mode.
- Preserve the existing output taps exactly.
- In mode 128, the first upper element must capture the **pre-edge** value of the last lower element.
- Leave delay-array reset behavior unchanged.

Separate nonblocking lower- and upper-bank processes preserve the required pre-edge boundary transfer. Adding a boundary register would create an off-by-one delay and violate the 137-cycle contract.

The gate must not depend on `di_en`, pipeline valid, busy, or `do_en`: SDF storage must continue moving during fill and drain.

## Why this should be safe

- **Mode 64:** The frozen upper state is neither selected nor fed back into the active lower half.
- **Mode 128:** The gate remains enabled continuously, reproducing the original full-depth shift.
- **Mode changes:** They are reset-separated, and the characterized latch-based gate handles a static mode enable without combinationally generating a clock.
- **Arithmetic and latency:** Neither is modified.

A Verilator-compatible behavioral path may be needed because the RTL judge likely lacks the PDK cell model, but the synthesis path must instantiate the real characterized cell. Post-synthesis inspection must prove that the 2,016 bits are genuinely behind six ICGs—not converted into D-input-enabled flops.

## Main risks to check

1. Exactly six `sky130_fd_sc_hd__dlclkp` instances survive synthesis.
2. No AND, mux, or ternary logic drives a clock.
3. The lower-to-upper boundary remains cycle-exact.
4. Generated-clock CTS/STA recognizes the gated domains.
5. Clock-gating setup/hold and ordinary setup/hold both pass.
6. Mode-128 power overhead from six gates does not outweigh the mode-64 improvement.
7. Mapped GLS includes the correct PDK gate model.

This hypothesis is preferable to the prior DFFE/operand-isolation attempt: that candidate barely improved mode-64 power, increased mode-128 power and area, and failed timing. Genuine ICG insertion targets clock-pin and local clock-tree activity rather than merely suppressing D transitions.

No files were edited.