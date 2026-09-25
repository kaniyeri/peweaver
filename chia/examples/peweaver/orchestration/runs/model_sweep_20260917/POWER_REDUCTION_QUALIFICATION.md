# Preliminary Power Fixture Qualification

Status: **functional qualification passed; physical power claim remains preliminary**.

The controller-owned `power_reduction_independent_judge.py` was run against
the frozen mapped netlists in `/work/peweaver/runs/chia_power_reduction`.
The judge owns fresh stimuli, fresh reference models, and fresh Icarus
testbenches. It does not import `test_power_reduction_domains.py` or the
merge-driver oracle modules.

| Domain | Random scenario | Directed scenario | Baseline | Optimized |
|---|---:|---:|---:|---:|
| MAC | 1502 cycles | 33 cycles | PASS | PASS |
| FIR | 1502 cycles | 34 cycles | PASS | PASS |
| DWT | 1502 cycles | 25 cycles | PASS | PASS |

Random seeds: MAC `0xA64C0DE1`, FIR `0xF1A5EED1`, DWT `0xD07C0DE1`.

The result bundle is `power_reduction_independent_judge.json`.

## Frozen Inputs

- MAC baseline: `2d986aa9e179902931453334543f085c5c820309c586b950b8f25205f69ba7d8`
- MAC optimized: `a136f702ab8d27cd21edfd3e9bc0da2bde6a62a9262c1bece8db2c7fbb756a41`
- FIR baseline: `6df293c92476e935e7ffd807fa91a9990ff32f0316a22e7799a66c7865f540a3`
- FIR optimized: `05472cc5154cf683cd887dbfecf3c137f5373da1bd121b50e6f7798949d5e606`
- DWT baseline: `6ace91bc6944c44b1ccb76f5f8ed9573b31ac027bb28c1125520a5b14e27ec11`
- DWT optimized: `d7c58d661026b28504fbfc79d5eafbe820a7451521f2fcd97c8e3431e833fc94`

Judge hash: `e96880240cd3e8d1ac4d124f47147f466a4ea7cf87f1279e42464c511f900206`.

## ChiaPowerSave Adapter Smoke Test

The real MAC baseline and optimized mapped artifacts were placed in an
isolated fixture campaign and evaluated through `make_power_activity_gate` and
`ChiaPowerSave`. The optimized fixture reached `TARGET` at `0.3151784 mW`;
the controller-only `verify_final` repeat passed all checks, including
candidate hash, finite objectives, physical gate, and metric agreement.
The archived result is `power_save_adapter_smoke.json`.

This is an integration smoke test over frozen artifacts, not a new physical
campaign or an accepted PEWeaver candidate.

## Claim Boundary

This establishes independent cycle-level agreement for the generated RTL
pairs at RTL-equivalent mapped-netlist level under the listed scenarios. It
does not establish accepted-merge provenance, exhaustive correctness, or a
new physical power result. The previously measured power deltas remain
generated-pair preliminary measurements. FIR switching-power increase remains
material and must be reported alongside its total-power reduction.
