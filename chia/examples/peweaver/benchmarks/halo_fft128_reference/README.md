# halo_fft128_reference — Phase A2 stateful FFT reference fixture

Reference-only fixture for the second stateful integration milestone. It wraps
the curated third-party `r22sdf` 128-point R2^2SDF streaming FFT (see
`../../third_party/r22sdf/README.md`) in a PEWeaver-owned top module and
verifies its interface/control contract with a directed Verilator regression.

This is a **HALO-inspired stateful FFT proxy**. It is not HALO RTL and nothing
here claims to reproduce HALO results, clinical performance, or any PPA number.

## Contents

| File | Role |
| --- | --- |
| `peweaver_halo_fft128_reference.v` | PEWeaver-owned wrapper; gives the upstream `FFT` top a PEWeaver-prefixed module name. Pure name-isolation pass-through, `WIDTH=16`. |
| `fft128_directed_tb.sv` | Directed Verilator testbench (see checks below). |
| `manifest.json` | Versioned workload contract (`schema_version: 1`). Reference tier, no miter, no `expected_equivalent`. |
| `vectors/input4.txt`, `vectors/input5.txt` | Upstream 128-sample stimulus frames (hex re/im per line). |
| `vectors/output4.txt`, `vectors/output5.txt` | Upstream ModelSim golden outputs, natural bin order. |

The designated independent arithmetic cross-check for this fixture is
`examples/peweaver/fft128_oracle.py` (Phase 2 of
`examples/peweaver/PHYSICAL_PPA_PLAN.md`), which follows the same approach as
the FFT64 oracle (`examples/peweaver/fft64_oracle.py`): a dependency-free,
cycle-accurate fixed-point model that computes the golden output sets from the
input frames alone.

## How to run

From the repository root:

```text
python3 examples/peweaver/fft128_regression.py examples/peweaver/benchmarks/halo_fft128_reference
```

The runner resolves Verilator exactly like `run-local.sh` (`PEWEAVER_VERILATOR`,
then the workspace OSS CAD Suite, then `PATH`), compiles into a temporary
directory with `--binary --timing --x-assign 0 --x-initial 0`, runs the binary
from this fixture directory, and passes only if the binary exits 0 and prints
`PEWEAVER_SIM_PASS halo_fft128_reference`. Missing tools, compile errors,
timeouts, malformed vectors, or unknown results fail closed. Optional flags:
`--json <path>` (same result schema as the other runners) and `--timeout`.

The fixture is deliberately excluded from the three corpus gates
(`equivalence_runner.py`, `synthesis_runner.py`, `simulation_runner.py`): its
manifest defines no `miter`/`top`, so manifest discovery skips it, and
`fft128_regression.py` rejects any reference manifest that grows a miter or
`expected_equivalent` field. It has **no sharing miter and no
expected-equivalence contract** and must not be counted as a sharing-positive
case.

## What the directed regression verifies

1. **Asynchronous active-high reset**: `reset` is asserted and deasserted
   between clock edges (not aligned to them) at power-on, between
   transactions, and mid-frame.
2. **Exactly 128 consecutive valid input samples** per transaction (`di_en`
   high for exactly 128 cycles, natural order), verified by construction and
   re-checked in the testbench.
3. **No output valid before the documented pipeline latency**: the first
   `do_en` is observed at cycle 137 under the documented convention (sample 0
   driven at a negedge, consumed at the first following posedge = cycle 1;
   `do_en` sampled at the negedge of cycle 137). This matches the upstream
   `FFT128.v` header comment ("The output latency is 137 clock cycles").
4. **Exactly 128 consecutive output-valid samples**: `do_en` high for exactly
   128 consecutive cycles, then low (gaps and extra pulses are failures).
5. **Reset between transactions clears/drains state**: after a reset and a
   256-cycle idle drain (longer than the deepest 64-deep `DelayBuffer` in
   `SdfUnit` with M=128), the bus stays quiet — no stale `do_en`.
6. **No stale output on the second transaction**: the post-reset frame
   reproduces the upstream golden output bit-exactly.
7. **Back-to-back streaming** without reset (upstream usage pattern) also
   reproduces the golden output.
8. **Mid-frame asynchronous abort**: an aborted frame never asserts `do_en`,
   and the following post-reset transaction still matches golden.

## Vector provenance and claim boundary

`vectors/` files are byte-copies of upstream `r22sdf` `sim/fft_128` vectors at
pinned revision `f7dca6e548e1370b69a09382d30609ee14ba4a57`
(`input4.txt` SHA-256 `b8d2d555c07608b054acb238141a7d6ac851bfda91d443a1a3e0f59a5b2cd36b`,
`input5.txt` SHA-256 `f0d2837424dc4d7e9e19e550ebcfec7852d85b096dc5e3cff9d26203223cb0e1`,
`output4.txt` SHA-256 `e7e0e7029d0d63be9f4abac4123e3ee7cd9a8be0b6547f1f2e9e7f753a82c5da`,
`output5.txt` SHA-256 `aa5eabb5a1e76ead7f34c05aacd12c90709972c45a3392be231a46c2b9d79f61`).
The upstream `TB128.v` captures outputs in bit-reversed order and writes the
natural-order bins, so the testbench compares captured sample `bitrev7(n)`
against golden line `n`.

These goldens validate interface/control behavior and reproduce upstream
behavior under Verilator. The Phase 2 independent oracle
(`../../fft128_oracle.py`) cross-checks both goldens from the input
frames alone (`natural_order(emission)[n] == golden[n]`); the golden
files are never read during the oracle's computation. The goldens are
therefore a cross-check of the independent oracle. There is still no formal
proof and no HALO, clinical, or PPA claim.

## Simulation policy notes

- Two-state simulation: upstream `Twiddle64.v`/`Twiddle128.v`/`SdfUnit*.v`
  contain deliberate `1'bx` assignments for never-selected paths; Verilator
  resolves them to 0 (`--x-assign 0 --x-initial 0`), and the testbench drives
  defined zero on idle inputs so delay-line contents are deterministic.
- No upstream file was edited. Module-name isolation is done by the wrapper;
  the only build-compatibility measures are compile flags.

## Formal-proof boundary

**Full 128-point fixed-point arithmetic is not formally proved.** There is no
miter, no `expected_equivalent` flag, and no Yosys equivalence or SAT proof for
this fixture. Verification is the directed Verilator regression above,
cross-checked by the Phase 2 independent oracle (a simulation model, not a
proof). Later phases must prove wrapper/control properties formally (reduced
instances if necessary) and keep differential simulation for the full-size
core, reporting that decomposition precisely.
