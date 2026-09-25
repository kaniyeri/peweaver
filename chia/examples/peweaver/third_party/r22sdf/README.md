# Curated third-party source: r22sdf FFT (64-point and 128-point)

This directory is a curated import of the upstream `r22sdf` Verilog FFT. It is
used by PEWeaver as a **HALO-inspired stateful FFT proxy**. It is NOT HALO RTL,
and nothing in PEWeaver claims to reproduce HALO's implementation or published
process-node results.

## Provenance

| Field | Value |
| --- | --- |
| Upstream URL | `https://github.com/nanamake/r22sdf` |
| Pinned upstream revision | `f7dca6e548e1370b69a09382d30609ee14ba4a57` |
| License | MIT, Copyright (c) 2017 Nanamaru Namake (see `LICENSE`) |
| Selected configuration | 64-point and 128-point R2^2SDF streaming FFT, `WIDTH=16` |
| Role in PEWeaver | Stateful reference integration (Phase A: 64-point; Phase A2: 128-point) |

Upstream working tree at the pinned revision was clean (no local modifications)
when the files below were copied. Files are byte-identical to upstream; no
logic, port, or formatting edits were made. Module-name isolation for PEWeaver
is done by a PEWeaver-owned wrapper (`benchmarks/halo_fft64_reference/
peweaver_halo_fft64_reference.v` and
`benchmarks/halo_fft128_reference/peweaver_halo_fft128_reference.v`) that
instantiates upstream module `FFT`, not by editing upstream source.

## Copied files and SHA-256

| File | SHA-256 |
| --- | --- |
| `FFT64.v` | `e56b335628fcb1bc588a26878dcb0e758df90a484a64f74b047ecada80c78dd0` |
| `FFT128.v` | `ae36712af9ab76902ff6af07011f891fc8db879833150f6134e3741d187d9097` |
| `SdfUnit.v` | `2e66d792173d339e4f1998d19f093a1febd0ad38b732f4d7e16716e3d7656276` |
| `SdfUnit2.v` | `a52f23fc8b2c80309529e48dff235b1ae449988efbb2b0fe92c903b5d8fa570c` |
| `Butterfly.v` | `82c7b18da61d728fd64df3eee9150b120716916ec41756e9bec5df6ddc9ed3d3` |
| `DelayBuffer.v` | `9bb52fc0fed7c0d37901bd783d9c3c2b91c840c6a6409a177b592dac3fff7104` |
| `Multiply.v` | `d5fda5b3f7e3762a62e7ba0fbdfabf5acab53e9fba0010a76f07baa5948c1a7b` |
| `Twiddle64.v` | `bd93b4e6c6e109eb48d1add52cbcadf13987afa9faf01195b4929fef0c2225ca` |
| `Twiddle128.v` | `9553ed80bf180a56ca419077710e009e9fd76bec58d4e7d5d9581374362bba32` |
| `LICENSE` | `84f826632172fb1201ae86fbea41b331505e21d09ba81a5c03c94bde46e0f952` |

## File usage notes

- `FFT64.v` (module `FFT`) is the top module and instantiates `SdfUnit` three
  times (M=64, M=16, M=4) plus `Butterfly`, `DelayBuffer`, `Multiply`, and
  `Twiddle` (provided by `Twiddle64.v`).
- `FFT128.v` (module `FFT`) instantiates `SdfUnit` three times (N=128 with
  M=128, M=32, M=8) plus `SdfUnit2`, with `Butterfly`, `DelayBuffer`,
  `Multiply`, and `Twiddle` (provided by `Twiddle128.v`) underneath. Its
  header comment documents a 137-cycle output latency.
- `SdfUnit2.v` (the final radix-2 stage, M=2) IS instantiated by `FFT128.v` as
  the last stage of the 128-point transform; it is NOT instantiated by
  `FFT64.v` (upstream reserves it for transform sizes that are not powers of
  four).
- `Twiddle64.v` and `Twiddle128.v` contain deliberate `16'hxxxx` ROM literals
  for table entries that the R2^2SDF addressing never selects. Under
  Verilator's two-state simulation these resolve to zero; the directed
  regressions document this two-state policy.

## Deliberately not copied

`.git/`, `quartus/`, `sim/` testbenches and ModelSim project files, `img/`,
`tool/` generator scripts, and the 1024-point variants (`FFT1024_32B.v`,
`Twiddle1024_32B.v`, `TwiddleConvert4.v`, `TwiddleConvert8.v`, `SdfUnit_TC.v`).
Upstream `sim/fft_64` and `sim/fft_128` input/output vectors are handled
separately under `benchmarks/halo_fft64_reference/vectors/` and
`benchmarks/halo_fft128_reference/vectors/` with their own provenance records.
