## 1. Architecture

### Top-level organization

Use one configurable radix-\(2^2\) SDF pipeline sized for the 128-point case:

```text
input
  -> shared configurable R2² stage P0
  -> shared configurable R2² stage P1
  -> shared configurable R2² stage P2
  -> 128-only radix-2 stage P3
  -> mode-selected output
```

- **64-point mode:** `P0/P1/P2` use \(M=64/16/4\); output bypasses `P3`.
- **128-point mode:** the same physical `P0/P1/P2` use \(M=128/32/8\), followed by `P3` with \(M=2\).
- This is not two cores behind a mux: both modes use the same three butterfly pipelines, feedback stores, multipliers, coefficient logic, and valid pipeline.
- No output-reordering RAM is needed. The SDF schedule naturally consumes natural order and emits bit-reversed order.

### Shared arithmetic

Each shared R2² stage contains:

- Two complex butterflies:
  - `BF1`: four signed 17-bit add/sub operations, `(value + 0) >>> 1`.
  - `BF2`: four signed 17-bit add/sub operations, `(value + 1) >>> 1`.
- Two complex feedback delays, implemented as programmable-depth circular buffers rather than maximum-depth shift chains.
- The `-j` path after `BF1`: `{re,im} = {db1_im, -db1_re}` with 16-bit modular negation.
- One complex multiplier after `BF2`, with four exact signed 16×16 products. Each product is independently arithmetically shifted by 15 before the final 16-bit modular add/sub.
- Registered coefficient lookup and the same bypass alignment as the references: address zero bypasses multiplication.

Three complex multipliers are retained because all three SDF stages process a sample concurrently during sustained one-sample-per-cycle operation. Time-sharing them would violate throughput.

`P2`’s multiplier is clock/data-disabled in 64-point mode because \(M=4\) requires no multiplication, but the same multiplier is active for \(M=8\) in 128-point mode.

### Twiddle storage

Use the literal 128-point Q1.15 table as the canonical coefficient set. Every required 64-point coefficient is the corresponding even entry:

```text
W64[a] == W128[2*a]
```

Thus:

```text
rom_addr = mode_q ? addr128 : {addr64, 1'b0}
```

Each active R2² stage needs a coefficient read every cycle, so provide three registered read ports/decoders into one canonical literal table definition. Do not calculate coefficients from trigonometric approximations. Unreachable `xxxx` reference entries need not be selected; all reachable entries must use the exact literals.

### Mode and state ownership

Control registers include:

- `mode_q`: latched only with the first accepted sample while idle.
- `busy_q`: set on that acceptance and held until the final output-valid sample drains.
- Uniform 7-bit sample/count state; bit 6 is masked/forced clear in 64-point mode.
- Per-stage valid flags, counters, circular-buffer pointers, ROM alignment registers, and multiplier-bypass flags.

While `busy_q=1`, `mode_q` cannot change. Consecutive same-mode frames may overlap normally; their valid windows abut. A mode transition is legal only after drain and reset, as required.

Active-high asynchronous reset must immediately:

- Clear `busy_q`, `do_en`, all stage valid flags, counters, pointers, butterfly phase state, coefficient-valid/bypass state, and the `P3` valid state.
- Prevent any pre-reset transaction from reasserting output valid.
- Permit `mode_q` to be selected again by the first post-reset accepted sample.

The data arrays and arithmetic pipeline data registers need not be reset. In every stage, the initial store phase overwrites each selected feedback location before that location is consumed by a valid butterfly. Resetting validity and pointers therefore prevents stale mode/frame data from becoming observable while avoiding a large reset network.

---

## 2. Resource and schedule table

### Physical resources

| Resource | Physical capacity | 64-point configuration | 128-point configuration |
|---|---:|---:|---:|
| `P0.DB1` | 64 complex words | depth 32 | depth 64 |
| `P0.DB2` | 32 complex words | depth 16 | depth 32 |
| `P1.DB1` | 16 complex words | depth 8 | depth 16 |
| `P1.DB2` | 8 complex words | depth 4 | depth 8 |
| `P2.DB1` | 4 complex words | depth 2 | depth 4 |
| `P2.DB2` | 2 complex words | depth 1 | depth 2 |
| `P3.DB` | 1 complex word | bypassed/inactive | depth 1 |
| R2² butterflies | 3 × (`BF1`,`BF2`) | all shared | all shared |
| Radix-2 butterfly | 1 | inactive | active, RH=0 |
| Complex multipliers | 3 | P0/P1 active as scheduled; P2 bypass | P0/P1/P2 active as scheduled |
| Twiddle literals | 128 complex constants | even-address subset | native addresses |

A “complex word” is 32 bits: 16-bit real plus 16-bit imaginary.

### Per-stage parameters and latency

Latency is measured from a stage’s accepted sample 0 to its first valid output.

| Mode | Stage | \(N\) | \(M\) | `DB1` | `DB2` | Stage latency | Twiddle |
|---|---|---:|---:|---:|---:|---:|---|
| 64 | P0 | 64 | 64 | 32 | 16 | 51 = 3M/4+3 | W64 |
| 64 | P1 | 64 | 16 | 8 | 4 | 15 = 3M/4+3 | W64 |
| 64 | P2 | 64 | 4 | 2 | 1 | 5 = 3M/4+2 | bypass |
| 64 | Total | | | | | **71** | |
| 128 | P0 | 128 | 128 | 64 | 32 | 99 = 3M/4+3 | W128 |
| 128 | P1 | 128 | 32 | 16 | 8 | 27 = 3M/4+3 | W128 |
| 128 | P2 | 128 | 8 | 4 | 2 | 9 = 3M/4+3 | W128 |
| 128 | P3 | 128 | 2 | 1 | — | 2 | none |
| 128 | Total | | | | | **137** | |

These boundaries preserve the reference register placement: feedback output, butterfly output, registered twiddle, multiplier/bypass output, and final radix-2 output.

### R2² stage schedule

For a stage with `LM=log2(M)` and a 7-bit local accepted-stream counter:

- Input counter period: `N` accepted samples.
- `BF1` feedback/add-sub phase:

```text
bf1_bf = di_count[LM-1]
```

It stores during the first `M/2` samples and butterflies during the second `M/2`, repeating over the frame.

- `BF1` output-valid sequence starts when:

```text
di_count == M/2 - 1
```

and lasts exactly `N` stage cycles.

- `-j` is selected when:

```text
bf1_count[LM-1:LM-2] == 2'b11
```

- `BF2` phase is the registered value of:

```text
bf1_count[LM-2]
```

- `BF2` output sequence starts from the registered comparison:

```text
bf1_sp_en && (bf1_count == M/4 - 1)
```

and lasts `N` cycles.

- Both valid counters wrap at `N-1`; a broken/nonconsecutive input sequence resets the input count, matching the reference assumptions.

### Twiddle addressing

For each R2² stage:

```text
tw_sel = {bf2_count[LM-2], bf2_count[LM-1]}
tw_addr = tw_num * tw_sel       // modulo N
```

Mode/stage-specific `tw_num` values are:

| Mode/stage | `tw_num` before multiplication |
|---|---|
| 64/P0, M=64 | `bf2_count[3:0]` |
| 64/P1, M=16 | `{bf2_count[1:0],2'b00}` |
| 64/P2, M=4 | `0`; multiplier always bypassed |
| 128/P0, M=128 | `bf2_count[4:0]` |
| 128/P1, M=32 | `{bf2_count[2:0],2'b00}` |
| 128/P2, M=8 | `{bf2_count[0],4'b0000}` |

For 64-point operation, zero-extend the 6-bit modular result and double it to address the 128-entry literal table. Register `tw_addr!=0` alongside the registered coefficient; use that delayed flag to select multiplication versus the correspondingly delayed unmodified sample.

### `P3` schedule

In 128-point mode:

- `bf_en` toggles on every valid input to `P3`.
- Even phase writes the one-word feedback register.
- Odd phase performs the RH=0 butterfly.
- `do_en` is the input valid delayed by two registers.

In 64-point mode, `P3` is disabled and output comes directly from `P2`.

---

## 3. Exact interface and timing

```verilog
module peweaver_shared_fft (
    input         clock,
    input         reset,
    input         mode,
    input         di_en,
    input  [15:0] di_re,
    input  [15:0] di_im,
    output        do_en,
    output [15:0] do_re,
    output [15:0] do_im
);
```

There are no other external ports.

- `reset` has active-high asynchronous assertion.
- `mode=0`: exactly 64 consecutive enabled samples form a frame.
- `mode=1`: exactly 128 consecutive enabled samples form a frame.
- One sample is accepted on every rising edge with `di_en=1`; there is no backpressure.
- If the sample-0 acceptance edge is cycle 0:
  - 64-point `do_en` first asserts at cycle 71.
  - 128-point `do_en` first asserts at cycle 137.
- A standalone frame produces exactly `N` consecutive valid outputs and then deasserts.
- In continuous same-mode traffic, adjacent frame-valid windows may directly abut, maintaining one output per cycle.
- Output words are Q1.15, scaled by \(1/N\), and emitted in bit-reversed index order.
- `mode_q` is captured with the first sample of an idle transaction and remains fixed through drain. A different mode requires idle drain followed by reset.

---

## 4. Ranked implementation and verification risks

1. **Cycle alignment and exact latency**  
   Implement control/valid logic first, initially with tagged dummy samples. Verify every stage latency and the totals 71/137, including consecutive frames, reset on every possible pipeline cycle, and back-to-back valid windows.

2. **Signed arithmetic and truncation points**  
   Implement butterflies and multiplication next. Explicitly use signed 17-bit butterfly intermediates and signed 32-bit products. Verify negative odd values, `-32768`, overflow wrap, arithmetic shifts, RH=0/1, and independent per-product truncation before complex add/sub.

3. **Twiddle address and ROM-register alignment**  
   Compare `tw_sel`, `tw_num`, address, bypass flag, and selected literals cycle-by-cycle against each reference stage. Exhaustively enumerate reachable addresses in every `(N,M)` configuration and prove the 64-point/even-128-table equivalence.

4. **Programmable feedback-buffer semantics**  
   Verify read-before-write behavior and exact delays 1,2,4,8,16,32,64. Compare each buffer output and butterfly input against the reference shift buffers over multiple continuous frames.

5. **Reset and mode ownership**  
   Assert reset asynchronously during fill, butterfly, multiply, and output phases. Confirm immediate `do_en=0`, no later stale valid, pointer restart, overwrite-before-read, and immutable `mode_q` while busy.

6. **Continuous-frame boundary behavior**  
   Test at least three frames without gaps in each mode. Pay special attention to counter wrap, simultaneous end/start conditions, and feedback locations reused at frame boundaries.

7. **Physical implementation**  
   After bit-exact RTL equivalence, synthesize early. Preserve pipeline boundaries around coefficient lookup and multipliers, use circular memories instead of deep shift muxes, disable unused `P3/P2-multiply` logic by mode, and constrain the 10 ns path. The shared design removes three duplicate R2² stages and all 64-core feedback storage versus the combined baseline, providing the main area margin below 424,885 µm².