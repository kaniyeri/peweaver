# Candidate stateful reference: r22sdf FFT

Status: imported (Phase A) as a curated third-party reference under
`../third_party/r22sdf/` with the directed regression in
`../benchmarks/halo_fft64_reference/`. 64-point configuration only; the shared
short/long FFT is future work.

| Field | Value |
| --- | --- |
| Upstream | `https://github.com/nanamake/r22sdf` |
| Pinned revision | `f7dca6e548e1370b69a09382d30609ee14ba4a57` |
| License | MIT, Copyright (c) 2017 Nanamaru Namake |
| Selected configuration | `verilog/FFT64.v`, 64-point R2^2SDF, `WIDTH=16` |
| Supporting RTL | `SdfUnit.v`, `SdfUnit2.v`, `Butterfly.v`, `DelayBuffer.v`, `Multiply.v`, `Twiddle64.v` |

The upstream `FFT64.v` declares a streaming interface: active-high asynchronous
`reset`, `di_en`, 16-bit real/imaginary inputs, and `do_en` plus 16-bit
real/imaginary outputs. Its source comments specify 64 consecutive natural-order
input samples, output scaled by `1/N` in bit-reversed order, and a 71-cycle
latency. These facts must be independently rechecked by the local directed
simulation before becoming a PEWeaver contract.

## Intended use

This is a labelled **HALO-inspired proxy**, not a reproduction of HALO RTL or
published process-node results. The initial experiment will compare separate
short and long streaming wrappers against a mode-selected shared wrapper. The
wrapper, not upstream RTL, owns mode-transition rules: no input acceptance
during an illegal change, drain all in-flight samples, and never expose a stale
result across modes.

Before copying any upstream source, retain the MIT license text with the copied
files, record source hashes in the manifest, and add independent golden vectors
and reset/back-to-back/mode-transition tests. Do not claim full-size formal
equivalence; formally prove the reduced control instance and use differential
Verilator regression for the 64-point core.
