## Atomic hypothesis

**Clock-gate only the mode-128-only upper extensions of the six `SharedDelayBuffer` banks using six characterized `sky130_fd_sc_hd__dlclkp_1` cells.**

Do not combine this with tail-stage gating, operand isolation, reset changes, arithmetic changes, or valid-based gating.

### Exact scope

The six shared buffers have depths:

| Buffer | 64-mode depth | 128-mode depth | Mode-128-only state |
|---|---:|---:|---:|
| `SU0.DB1` | 32 | 64 | 1,024 bits |
| `SU0.DB2` | 16 | 32 | 512 bits |
| `SU1.DB1` | 8 | 16 | 256 bits |
| `SU1.DB2` | 4 | 8 | 128 bits |
| `SU2.DB1` | 2 | 4 | 64 bits |
| `SU2.DB2` | 1 | 2 | 32 bits |
| **Total** | | | **2,016 bits** |

In `SharedDelayBuffer` at `best/peweaver_shared_fft.v:406-436`:

- Keep indices `0 .. DEPTH0-1` on the original clock.
- Put indices `DEPTH0 .. DEPTH1-1` on one local gated clock.
- Drive each gate’s `GATE` from the existing buffer `mode` input.
- Preserve the two taps exactly:
  - mode 64: lower-bank terminal
  - mode 128: upper-bank terminal
- Preserve unreset delay storage.
- Do not add a boundary register.

The upper bank must capture the **pre-edge** lower terminal value using nonblocking semantics. Otherwise, mode-128 data shifts by a cycle and violates the 137-cycle latency.

## Correctness basis

All six buffer `mode` inputs originate from top-level `active_mode` (`best/peweaver_shared_fft.v:37,57,81,105`). Once the first input is accepted, `active_mode` remains locked until reset.

- **Mode 64:** the upper extensions are neither selected nor connected back into the active lower portions. Holding them cannot affect arithmetic, feedback, valid timing, or the 71-cycle latency.
- **Mode 128:** the gates remain continuously enabled through input, pipeline fill, output drain, and same-mode back-to-back frames. The split bank is cycle-equivalent to the incumbent full-depth shift register.
- **Mode transitions:** reset-separated mode changes allow the integrated latch gate to acquire the new static enable before useful traffic.

Do not gate these banks from `di_en` or local valid signals. SDF state must continue shifting during fill and drain.

## Why the previous functional failure is unrelated

The rejected staging file contains a concrete tail arithmetic typo:

```verilog
assign bf_sp_im = bf_en ? y0_im : db_do_re;
```

at `source/physical/rtl/peweaver_shared_fft.v:512`. The accepted incumbent correctly selects `db_do_im` at `best/peweaver_shared_fft.v:508`.

Because this tail is selected only in mode 128, that typo explains a completed 384-output burst with three value errors. The rejected file also changed reset process sensitivities. A replacement must retain the accepted file’s arithmetic and reset code verbatim outside the buffer split.

## Expected power effect

This directly targets the dominant measured component: clock-root power is approximately 49.1% of total. During mode 64, clock edges are removed from 2,016 storage bits and their local clock subtrees. Unlike an RTL `if (mode)` enable, a real `dlclkp` can reduce clock-pin and clock-tree internal power.

Mode-128 power may rise slightly from six gate cells and CTS overhead, so acceptance depends on the measured aggregate objective rather than only `p64`.

## Implementation-flow caution

The Verilator regression compiles only the wrapper, candidate, and testbench, while synthesis performs hierarchy checking before reading Liberty. Therefore the complete candidate needs:

- a synthesis-visible black-box declaration for the exact characterized primitive;
- real `dlclkp` instances in the synthesized branch;
- a Verilator-only clock-enable model for the upper-bank updates, not a generated `clock & mode` expression.

The mapped netlist must contain exactly six characterized clock gates and no combinationally generated clocks.

## Required checks

1. Bit-exact single and three-frame bursts in both modes.
2. Exact 71/137-cycle first-valid latency and contiguous 192/384-output bursts.
3. Reset-separated `64→128`, `128→64`, and `128→64→128`.
4. Structural confirmation of six `sky130_fd_sc_hd__dlclkp_1` instances.
5. Mapped GLS with the PDK gate model.
6. Setup, hold, and clock-gating checks, especially each lower-to-upper boundary.
7. TNS 0, DRC 0, and area below 339,908 µm².

No files were edited.