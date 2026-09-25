# halo_fft64_reference — Phase A stateful FFT reference fixture

Reference-only fixture for the first stateful integration milestone. It wraps
the curated third-party `r22sdf` 64-point R2^2SDF streaming FFT (see
`../../third_party/r22sdf/README.md`) in a PEWeaver-owned top module and
verifies its interface/control contract with a directed Verilator regression.

This is a **HALO-inspired stateful FFT proxy**. It is not HALO RTL and nothing
here claims to reproduce HALO results, clinical performance, or any PPA number.

## Contents

| File | Role |
| --- | --- |
| `peweaver_halo_fft64_reference.v` | PEWeaver-owned wrapper; gives the upstream `FFT` top a PEWeaver-prefixed module name. Pure name-isolation pass-through, `WIDTH=16`. |
| `fft64_directed_tb.sv` | Directed Verilator testbench (see checks below). |
| `manifest.json` | Versioned workload contract (`schema_version: 1`). Reference tier, no miter, no `expected_equivalent`. |
| `vectors/input4.txt`, `vectors/input5.txt` | Upstream 64-sample stimulus frames (hex re/im per line). |
| `vectors/output4.txt`, `vectors/output5.txt` | Upstream ModelSim golden outputs, natural bin order. |

The independent arithmetic oracle for this fixture is
`examples/peweaver/fft64_oracle.py` (Phase 1 of
`examples/peweaver/PHYSICAL_PPA_PLAN.md`): a dependency-free, cycle-accurate
fixed-point model whose derived semantics are documented in its module
docstring. It computes both golden output sets bit-exactly from the input
frames alone and performs no file I/O; `test_fft64_oracle.py` is the only
place where the golden vectors are loaded. During development the oracle was
additionally compared cycle-for-cycle against Verilator traces of the
unmodified `SdfUnit` (internal counters, delay lines, mux selections, twiddle
addressing, and pipeline registers) as a manual debugging aid; that trace
comparison is not retained as an automated test - the automated acceptance
test is the bit-exact golden-vector match. Implementation: OpenCode Go Luna.

## How to run

From the repository root:

```text
python3 examples/peweaver/fft64_regression.py examples/peweaver/benchmarks/halo_fft64_reference
```

The runner resolves Verilator exactly like `run-local.sh` (`PEWEAVER_VERILATOR`,
then the workspace OSS CAD Suite, then `PATH`), compiles into a temporary
directory with `--binary --timing --x-assign 0 --x-initial 0`, runs the binary
from this fixture directory, and passes only if the binary exits 0 and prints
`PEWEAVER_SIM_PASS halo_fft64_reference`. Missing tools, compile errors,
timeouts, malformed vectors, or unknown results fail closed. Optional flags:
`--json <path>` (same result schema as the other runners) and `--timeout`.

The fixture is deliberately excluded from the three corpus gates
(`equivalence_runner.py`, `synthesis_runner.py`, `simulation_runner.py`): its
manifest defines no `miter`/`top`, so manifest discovery skips it, and
`fft64_regression.py` rejects any reference manifest that grows a miter or
`expected_equivalent` field. It has **no sharing miter and no
expected-equivalence contract** and must not be counted as a sharing-positive
case.

## What the directed regression verifies

1. **Asynchronous active-high reset**: `reset` is asserted and deasserted
   between clock edges (not aligned to them) at power-on, between
   transactions, and mid-frame.
2. **Exactly 64 consecutive valid input samples** per transaction (`di_en`
   high for exactly 64 cycles, natural order), verified by construction and
   re-checked in the testbench.
3. **No output valid before the documented pipeline latency**: the first
   `do_en` is observed at cycle 71 under the documented convention (sample 0
   driven at a negedge, consumed at the first following posedge = cycle 1;
   `do_en` sampled at the negedge of cycle 71). This matches the upstream
   `FFT64.v` header comment ("The output latency is 71 clock cycles").
4. **Exactly 64 consecutive output-valid samples**: `do_en` high for exactly
   64 consecutive cycles, then low (gaps and extra pulses are failures).
5. **Reset between transactions clears/drains state**: after a reset and a
   96-cycle idle drain (longer than the deepest 32-deep `DelayBuffer`), the
   bus stays quiet — no stale `do_en`.
6. **No stale output on the second transaction**: the post-reset frame
   reproduces the upstream golden output bit-exactly.
7. **Back-to-back streaming** without reset (upstream usage pattern) also
   reproduces the golden output.
8. **Mid-frame asynchronous abort**: an aborted frame never asserts `do_en`,
   and the following post-reset transaction still matches golden.

## Vector provenance and claim boundary

`vectors/` files are byte-copies of upstream `r22sdf` `sim/fft_64` vectors at
pinned revision `f7dca6e548e1370b69a09382d30609ee14ba4a57`
(`input4.txt` SHA-256 `fbb38b67aea7457007aafa92aef1dc9b2be713163cc0b19cf5736539933f574c`,
`input5.txt` SHA-256 `bdb77eba9f17ceae499006df0413012c59b450de73da431adbc7d22b03d0fae1`,
`output4.txt` SHA-256 `d9d3e5bd20e4680e12025beae7beaeeb27f8d7c2a779803f1596de70b20f2058`,
`output5.txt` SHA-256 `a32132fbc5dbe01e16f52df6155e081941a838fde27a0e0b550e2afa9e62b94b`).
The upstream `TB64.v` captures outputs in bit-reversed order and writes the
natural-order bins, so the testbench compares captured sample `bitrev6(n)`
against golden line `n`.

These goldens validate interface/control behavior and reproduce upstream
behavior under Verilator. The Phase 1 independent oracle
(`../../fft64_oracle.py`) reproduces both goldens bit-exactly
(`natural_order(emission)[n] == golden[n]`) from the input frames alone; the
golden files are never read during the oracle's computation. The goldens are
therefore a cross-check of the independent oracle. There is still no formal
proof and no HALO, clinical, or PPA claim.

## Simulation policy notes

- Two-state simulation: upstream `Twiddle64.v`/`SdfUnit*.v` contain deliberate
  `1'bx` assignments for never-selected paths; Verilator resolves them to 0
  (`--x-assign 0 --x-initial 0`), and the testbench drives defined zero on
  idle inputs so delay-line contents are deterministic.
- No upstream file was edited. Module-name isolation is done by the wrapper;
  the only build-compatibility measures are compile flags.

## Formal-proof boundary

**Full 64-point fixed-point arithmetic is not formally proved.** There is no
miter, no `expected_equivalent` flag, and no Yosys equivalence or SAT proof for
this fixture. Verification is the directed Verilator regression above, now
cross-checked by the Phase 1 independent oracle (a simulation model, not a
proof). Later phases must prove wrapper/control properties formally (reduced
instances if necessary) and keep differential simulation for the full-size
core, reporting that decomposition precisely.
