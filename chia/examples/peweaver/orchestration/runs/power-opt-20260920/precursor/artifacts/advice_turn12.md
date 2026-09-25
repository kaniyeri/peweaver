## Highest-value burst: fix and exhaustively verify the configurable delay store

The immediate blocker is compilation: `buf_im[0:DEPTH-1]` references undefined `DEPTH`. Fix the delay module interface so storage uses a **compile-time maximum depth** (for example, parameter `MAX_DEPTH`) while a mode-selected input controls the **runtime effective depth**.

Concretely:

- Declare both arrays identically:
  - `buf_re[0:MAX_DEPTH-1]`
  - `buf_im[0:MAX_DEPTH-1]`
- Keep an appropriately sized circular pointer `wr_ptr`.
- On **every** rising edge, regardless of `di_en`:
  1. Capture `buf_re[wr_ptr]` / `buf_im[wr_ptr]` as the delayed output.
  2. Write current `di_re` / `di_im` into that same location.
  3. Wrap `wr_ptr` at `effective_depth - 1`.
- Ensure explicit read-before-write semantics; do not rely on ambiguous inferred-RAM collision behavior.
- Keep `effective_depth` constant while samples are outstanding, deriving it from `mode_q`, not live `mode`.

Instantiate/configure the seven stores for these depth pairs:

- `stage0.db1`: 32 / 64
- `stage0.db2`: 16 / 32
- `stage1.db1`: 8 / 16
- `stage1.db2`: 4 / 8
- `stage2.db1`: 2 / 4
- `stage2.db2`: 1 / 2
- `stage3_r2.db`: bypass / 1

For the 64-point final-stage bypass, bypass both data and valid timing entirely; do not pass through a depth-1 store.

## Verification required before proceeding

First rerun Verilator lint/compile and require **zero errors**, specifically confirming no remaining `DEPTH` references or invalid zero-width pointer declarations.

Then unit-test each effective depth independently with a unique value every clock, including clocks where `di_en=0`. For every cycle `t >= depth`, require:

```text
do_re(t) == di_re(t-depth)
do_im(t) == di_im(t-depth)
```

Exercise:

- Every supported depth: `1, 2, 4, 8, 16, 32, 64`
- Pointer wrap for at least three full revolutions
- A write/read collision at every wrap boundary
- Random `di_en` gaps, proving delay advancement is clock-based rather than valid-qualified
- Signed-looking and boundary bit patterns, although the store must preserve all 16 bits opaquely
- Asynchronous reset of control followed by refill, proving stale memory is never marked valid
- Mode/depth changes only after `outstanding == 0` and reset

Finally, run a valid-only pipeline test and confirm the externally visible first-output timing remains:

- Mode 0: `do_en` begins exactly 71 clocks after acceptance of sample 0 and lasts 64 clocks
- Mode 1: `do_en` begins exactly 137 clocks after acceptance of sample 0 and lasts 128 clocks

Do not debug twiddles or arithmetic until this compile blocker and exact-delay semantics pass; every butterfly pairing depends on them.