## 1. Shared architecture

### Top-level organization

`peweaver_shared_fft` contains one configurable, seven-butterfly SDF pipeline:

1. `stage0`: configurable radix-\(2^2\) SDF unit  
2. `stage1`: configurable radix-\(2^2\) SDF unit  
3. `stage2`: configurable radix-\(2^2\) SDF unit  
4. `stage3_r2`: configurable radix-2 SDF unit, enabled only for 128-point mode

This is the 128-point topology, with delay lengths and control periods shortened in 64-point mode and the final radix-2 stage bypassed. No complete mode-specific FFT cores are instantiated.

### Shared resources

Both modes use the same physical:

- Six radix-2 butterflies in the three radix-\(2^2\) stages
- Three complex multipliers, one per radix-\(2^2\) stage
- Six complex delay stores, with maximum depths:
  - 64, 32, 16, 8, 4, 2 samples
- One depth-1 complex delay for the final radix-2 stage
- Three registered twiddle-table read paths
- One 128-entry logical twiddle coefficient definition
- Stage counters, valid controls, and output registers

The arithmetic cannot be time-multiplexed between stages because all three stages process one sample concurrently during sustained streaming. It is nevertheless shared between FFT sizes: the same three multipliers and six/seven butterflies execute either workload.

Maximum data-delay storage is 127 complex words, versus 63 words for the original 64-point core plus 127 for the original 128-point core. Arithmetic is reduced from 13 to 7 butterflies and from 6 to 3 complex multipliers relative to two side-by-side cores.

### Per-mode configuration

Only small configuration/control state is mode-dependent:

- `mode_q`: one latched mode bit
- Effective FFT length: 64 or 128
- Counter width/terminal comparison: 6/63 or 7/127
- Six selected delay depths
- Stage twiddle-resolution exponents
- Final radix-2 enable/bypass
- Expected latency and frame length

There are no duplicated arithmetic pipelines or duplicated frame data stores.

### Delay-store implementation

Each delay store implements an exact clock-delay, not a valid-qualified FIFO. It writes every clock, matching `DelayBuffer.v`. A circular store may replace a physical shift register provided its output is the value from exactly `DEPTH` preceding clock edges and read-before-write behavior is preserved.

The selected depth is fixed for the entire active/draining interval. Therefore changing a circular modulus cannot corrupt an active frame.

### Twiddle sharing

Use the literal 128-point Q1.15 table as the canonical coefficient set. Every 64-point coefficient equals the corresponding even-indexed 128-point coefficient:

- 128 mode: `rom_addr = tw_addr`
- 64 mode: `rom_addr = {tw_addr[5:0],1'b0}`

Each radix-\(2^2\) stage requires an independent registered read in the same cycle. This is one logical coefficient definition with three read paths, not separate 64- and 128-point tables. Address zero remains literal zero because multiplication is bypassed there. Unreachable `x` entries need not be represented as functional coefficients; every reachable address must contain the exact reference literal.

### Mode and state ownership

`mode_q` is captured only when no accepted sample remains in flight. The first post-reset sample may atomically capture `mode` and use that same value for all mode-sensitive decisions on its acceptance edge. Once any sample is outstanding, all controls use `mode_q`; changes on the external `mode` input are ignored until the design is idle again.

Maintain an 8-bit `outstanding` count:

- Increment for `di_en && !do_en`
- Decrement for `do_en && !di_en`
- Hold when both or neither are asserted
- Idle means `outstanding == 0`

The maximum steady-state occupancy is bounded by the 137-cycle pipeline latency, so 8 bits are sufficient.

Asynchronous reset clears:

- All stage enable/valid state
- All counters and butterfly scheduling state
- `outstanding`
- `do_en`
- Any output-valid pipeline state

Delay memories and arithmetic data registers need not be reset because no post-reset output is declared valid until newly accepted data has filled all required delays. Thus stale data cannot become externally observable. A legal mode transition occurs only after drain and reset; the new mode is then captured before or with its first accepted sample.

---

## 2. Resource and schedule table

Let:

- `L = 6` in 64 mode, `7` in 128 mode
- `N = 2^L`
- For each radix-\(2^2\) stage, `m = log2(M)`
- Stage sample counters are physically 7 bits; 64 mode compares/wraps at 63 and ignores bit 6

| Resource | Physical maximum | 64-point configuration | 128-point configuration |
|---|---:|---:|---:|
| FFT length | 7-bit control | `N=64`, `L=6` | `N=128`, `L=7` |
| `stage0` resolution | `m<=7` | `M=64`, `m=6` | `M=128`, `m=7` |
| `stage0.db1` | 64 complex | depth 32 | depth 64 |
| `stage0.db2` | 32 complex | depth 16 | depth 32 |
| `stage1` resolution | `m<=5` | `M=16`, `m=4` | `M=32`, `m=5` |
| `stage1.db1` | 16 complex | depth 8 | depth 16 |
| `stage1.db2` | 8 complex | depth 4 | depth 8 |
| `stage2` resolution | `m<=3` | `M=4`, `m=2` | `M=8`, `m=3` |
| `stage2.db1` | 4 complex | depth 2 | depth 4 |
| `stage2.db2` | 2 complex | depth 1 | depth 2 |
| `stage3_r2.db` | 1 complex | bypassed | depth 1, enabled |
| Butterflies | 7 total | first 6 active | all 7 active |
| Complex multipliers | 3 total | one per active R22 stage | same three |
| Output latency | — | 71 clocks | 137 clocks |
| Output run | — | 64 consecutive clocks | 128 consecutive clocks |

### Common radix-\(2^2\) scheduling

For each stage with local exponent `m`:

- Input counter `di_count`:
  - Increments on consecutive `di_en`
  - Returns to zero when `di_en=0`
  - Period is `N`
- First butterfly select:
  - `bf1_bf = di_count[m-1]`
- First delay:
  - `D1 = 2^(m-1)`
- First-output start:
  - Trigger when `di_count == D1-1`
- First single-path active interval:
  - Exactly `N` samples
- `-j` selection:
  - `bf1_count[m-1:m-2] == 2'b11`
  - Mapping is `(re,im) -> (im,-re mod 2^16)`
- Second butterfly select:
  - Registered copy of `bf1_count[m-2]`
- Second delay:
  - `D2 = 2^(m-2)`
- Second-output start:
  - Registered trigger when `bf1_count == D2-1` while first-path valid
- Second single-path active interval:
  - Exactly `N` samples
- Multiplier output valid:
  - Delayed exactly as in the reference unit
- For `m=2`, multiplier output is bypassed and the second-butterfly registered result is used directly

### Twiddle schedule

For each radix-\(2^2\) stage:

- `tw_sel = {bf2_count[m-2], bf2_count[m-1]}`
- `tw_num` reproduces the reference-width truncation of  
  `bf2_count << (L-m)` into `L-2` bits
- Local address: `tw_addr = tw_num * tw_sel`
- Canonical table address:
  - 64 mode: `table_addr = 2 * tw_addr`
  - 128 mode: `table_addr = tw_addr`
- Coefficient lookup has one registered-clock latency
- `mu_en` is the correspondingly registered test `tw_addr != 0`
- Address zero selects the unmultiplied butterfly data

The resulting stage address patterns include:

| Stage | 64-point local address basis | 128-point address basis |
|---|---|---|
| `stage0` | low 4 count bits × selector, then table index doubled | low 5 bits × selector |
| `stage1` | low 2 bits shifted by 2 × selector, then doubled | low 3 bits shifted by 2 × selector |
| `stage2` | multiplier bypass (`m=2`) | low 1 bit shifted by 4 × selector |

### Arithmetic rules

- First butterfly in each radix-\(2^2\) stage: `RH=0`
- Second butterfly: `RH=1`
- Final radix-2 butterfly: `RH=0`
- Butterfly intermediates are signed 17-bit add/subtract results
- Stored result is `(value + RH) >>> 1`
- Each complex multiply uses four independent signed 16×16 products
- Each product is arithmetically shifted right by 15 before add/subtract
- Final complex add/subtract wraps modulo \(2^{16}\), with no saturation
- Do not replace the four-product multiply with a three-multiplier identity; independent truncation would change results

---

## 3. Exact interface and timing contract

The sole external module is:

```text
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

- `reset` has active-high asynchronous assertion.
- `mode=0` selects 64-point operation.
- `mode=1` selects 128-point operation.
- A frame is exactly `N` consecutive clocks with `di_en=1`.
- Samples are accepted at one per clock with no backpressure.
- Input order is natural order.
- From the edge accepting sample 0:
  - 64 mode: first `do_en` exactly 71 clocks later
  - 128 mode: first `do_en` exactly 137 clocks later
- `do_en` remains asserted for exactly `N` consecutive clocks.
- Output is bit-reversed and scaled by exactly `1/N` according to the reference fixed-point operations.
- Same-mode frames may be accepted back-to-back every `N` clocks.
- Output runs for back-to-back frames are consequently contiguous.
- Mode is fixed from first acceptance through complete output drain.
- A mode change requires idle drain and reset.
- Reset immediately invalidates all pending output; no sample belonging to an earlier frame or mode may subsequently assert `do_en`.

---

## 4. Ranked implementation and verification risks

1. **Cycle-exact control and latency**  
   Implement first. Reproduce all registered start conditions, enable delays, bypass points, and nonblocking-assignment timing. Verify valid-only models for isolated frames, gaps, and back-to-back frames before adding arithmetic.

2. **Configurable delay semantics**  
   Verify each selectable circular delay against `DelayBuffer.v`, including read-before-write behavior and writes during invalid clocks. An off-by-one delay changes both data and butterfly pairing.

3. **Twiddle addressing and table unification**  
   Implement the exact expression widths and truncation rules, then prove that every reachable 64-point address maps to the doubled 128-table address. Compare all reachable coefficients literally.

4. **Signed arithmetic fidelity**  
   Unit-test butterfly overflow, negative odd values, `RH=0/1`, `-32768` negation, multiplication shifts, and modulo-16-bit complex recombination. Avoid implicit unsigned expressions and unsized constants.

5. **64-point final-stage bypass**  
   Confirm that bypassing `stage3_r2` removes both its data delay and its valid delay; the 64-point path must remain exactly 71 clocks.

6. **Reset, drain, and mode capture**  
   Test reset during input, between input and output, and during output. Ensure asynchronous control clearing prevents any stale `do_en`, and ensure `mode_q` cannot change with `outstanding != 0`.

7. **Continuous multi-frame state rollover**  
   Compare several back-to-back frames per mode, especially counter wrap boundaries and the transition between adjacent output frames.

8. **Synthesis/P&R closure**  
   Preserve pipeline registers around twiddle lookup and multiplication. Check that variable-depth delay implementation does not create a long combinational read mux. If inferred memories are unsuitable in sky130, use fixed maximum arrays with registered/timed taps while retaining exact delay semantics. Arithmetic sharing should provide the main area margin below 424,885 µm².