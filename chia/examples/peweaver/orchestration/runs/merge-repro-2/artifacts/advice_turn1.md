## 1. Shared architecture

Use the 128-point radix-\(2^2\) SDF pipeline as the physical superset and configure its first three stages for either transform size:

```text
input
  -> configurable SDF stage S0
  -> configurable SDF stage S1
  -> configurable SDF stage S2
  -> optional radix-2 stage S3
  -> output
```

| Mode | S0 M | S1 M | S2 M | S3 |
|---|---:|---:|---:|---|
| `mode_q=0` | 64 | 16 | 4 | bypassed |
| `mode_q=1` | 128 | 32 | 8 | enabled, M=2 |

This is one datapath, not two cores: S0–S2 each contain one physical pair of butterflies, one physical feedback-memory pair, and one physical complex multiplier. Mode only selects counter bits, feedback taps, twiddle addressing, and the S3 bypass. The resulting arithmetic inventory is exactly the 128-point superset:

- 7 complex butterflies: two in each of S0–S2 and one in S3.
- 3 complex multipliers: one in each of S0–S2.
- 127 complex feedback words total.
- One logical 128-point coefficient set, exposed through the three simultaneous stage lookup ports needed by the streaming pipeline.

### Configurable SDF stage

Each of S0–S2 follows `SdfUnit.v` exactly:

- First butterfly: RH=0.
- Second butterfly: RH=1.
- First feedback depth `D1=M/2`.
- Second feedback depth `D2=M/4`.
- `-j` operation exactly `{re,im}={old_im,-old_re mod 2^16}`.
- Registered twiddle lookup, registered multiplier-bypass decision, and registered result, preserving the reference pipeline.
- For `M=4`, multiplier output is bypassed exactly as in the 64-point final `SdfUnit`.

Implement each feedback memory at its maximum required depth and select one of two fixed taps. Memories shift every clock, including invalid clocks, matching `DelayBuffer.v`; they must not be valid-gated.

Maximum physical memories:

- S0: 64-word DB1 and 32-word DB2.
- S1: 16-word DB1 and 8-word DB2.
- S2: 4-word DB1 and 2-word DB2.
- S3: 1 word.

In 64-point mode, S0–S2 select the shallower taps 32/16, 8/4, and 2/1 respectively. Selecting a shallow tap while retaining the longer shift array does not affect feedback semantics.

### Mode and state ownership

Use:

- `mode_q`: latched transform mode.
- `mode_locked`: indicates that mode has been captured.
- `pipeline_idle`: all input/frame and interstage valid state clear.

Asynchronous reset clears `mode_locked`, all counters, frame/valid state, and `do_en`. On the first accepted sample satisfying `di_en && !mode_locked && pipeline_idle`, capture `mode` into `mode_q` and set `mode_locked`. The first sample can enter S0 on that same edge because the edge’s S0 action is independent of M: it writes the first feedback word and starts the common count sequence. `mode_q` then remains immutable until reset.

Feedback/data registers need not be reset. After reset, all valid ownership is cleared, and each selected feedback delay is overwritten before it is consumed. Therefore stale data cannot become externally valid. S3 receives no valid samples in 64-point mode, and its output is physically bypassed.

A mode change is consequently accepted only after reset and while idle. No unlocked mode sampling occurs during processing or drain.

---

## 2. Resource and schedule table

All counters are physically 7 bits. In 64-point mode, the low six bits form the modulo-64 count and bit 6 remains zero; in 128-point mode all seven bits are used.

For every configurable stage:

- `di_count`: increments on each consecutive input-valid cycle; clears on a valid gap.
- `bf1_count`, `bf2_count`: modulo N while their associated stream-valid is active.
- `bf1_bf = di_count[log2(M)-1]`.
- Registered `bf2_bf = bf1_count[log2(M)-2]`.
- `bf1_mj` when `bf1_count[log2(M)-1:log2(M)-2] == 2'b11`.
- Valid burst length is N and supports immediately adjacent same-mode frames.

| Resource | 64-point configuration | 128-point configuration | Enable/schedule |
|---|---|---|---|
| S0 DB1 | depth/tap 32 | depth/tap 64 | shifts every clock |
| S0 DB2 | depth/tap 16 | depth/tap 32 | shifts every clock |
| S0 counters | period 64; M=64 | period 128; M=128 | starts from top `di_en` |
| S0 multiplier | enabled iff twiddle address !=0 | same | one result/cycle |
| S1 DB1 | depth/tap 8 | depth/tap 16 | shifts every clock |
| S1 DB2 | depth/tap 4 | depth/tap 8 | shifts every clock |
| S1 counters | period 64; M=16 | period 128; M=32 | driven by S0 valid |
| S1 multiplier | enabled iff address !=0 | same | one result/cycle |
| S2 DB1 | depth/tap 2 | depth/tap 4 | shifts every clock |
| S2 DB2 | depth/tap 1 | depth/tap 2 | shifts every clock |
| S2 counters | period 64; M=4 | period 128; M=8 | driven by S1 valid |
| S2 multiplier | always bypassed | address-zero bypass only | physical multiplier shared across modes |
| S3 DB | bypassed | depth 1 | shifts every clock; valid only in mode 1 |
| S3 butterfly | bypassed | RH=0, alternating store/butterfly cycles | driven by S2 valid |
| Output mux | S2 result | S3 result | selected only by locked `mode_q` |

### Twiddle schedule

Retain the reference address equation per stage:

```text
sel[1] = bf2_count[log2(M)-2]
sel[0] = bf2_count[log2(M)-1]
n      = truncated(bf2_count << (log2(N)-log2(M)))
addr   = n * sel
```

Use one 7-bit canonical address into the literal 128-point table:

- In 128-point mode: `rom_addr = addr128`.
- In 64-point mode: `rom_addr = {addr64,1'b0}`.

Every 64-point literal equals the corresponding even-index 128-point literal, so this removes the separate 64-entry table without changing coefficients. Address zero still bypasses multiplication; its stored coefficient may remain `16'h0000 + j16'h0000` as in the references.

Equivalent stage forms are:

| Mode/stage | `n` before `* sel` | `sel` |
|---|---|---|
| 64 S0, M=64 | `count[3:0]` | `{count[4],count[5]}` |
| 64 S1, M=16 | `count[1:0] << 2` | `{count[2],count[3]}` |
| 64 S2, M=4 | irrelevant; multiplier bypassed | — |
| 128 S0, M=128 | `count[4:0]` | `{count[5],count[6]}` |
| 128 S1, M=32 | `count[2:0] << 2` | `{count[3],count[4]}` |
| 128 S2, M=8 | `count[0] << 4` | `{count[1],count[2]}` |

The lookup has one registered cycle exactly like `Twiddle*.v`. Since all three stages can require coefficients in the same cycle, provide three combinational/read ports over the same literal coefficient definition; do not time-multiplex a single-port table.

### Latency schedule

Reference stage latency contributions, measured inclusively in the same convention as the source comments:

| Path | Stage contribution |
|---|---:|
| 64 S0, M=64 | 50 clocks |
| 64 S1, M=16 | 14 clocks |
| 64 S2, M=4 | 4 clocks |
| 128 S0, M=128 | 98 clocks |
| 128 S1, M=32 | 26 clocks |
| 128 S2, M=8 | 8 clocks |
| 128 S3 | 1 clock |

There is one receiving edge between cascaded stages. Thus, with the sample-0 acceptance edge called cycle 1:

- 64 mode: S0 first valid cycle 51, S1 cycle 66, final S2/output cycle 71.
- 128 mode: S0 first valid cycle 99, S1 cycle 126, S2 cycle 135, S3/output cycle 137.

The implementation should derive output validity from the same interstage-valid pipeline, not from an independent top-level delay counter.

---

## 3. Exact interface and timing contract

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

No other ports.

- `reset` has active-high asynchronous assertion.
- `mode=0`: 64-point FFT.
- `mode=1`: 128-point FFT.
- Exactly N consecutive `di_en` cycles constitute one natural-order frame.
- No backpressure; one input sample is accepted per asserted cycle.
- First `do_en` is cycle 71 for N=64 or cycle 137 for N=128, counted from the sample-0 acceptance edge using the reference latency convention.
- `do_en` remains asserted for exactly N consecutive cycles.
- Adjacent same-mode frames are accepted every N cycles and produce one result per cycle during output bursts.
- Output is bit-reversed and scaled by 1/N.
- Reset immediately invalidates all pending output; no pre-reset frame may reappear.
- Mode is captured only while idle and remains locked through all processing. Changing mode requires reset and a drained/idle restart.

Arithmetic is signed Q1.15 with modulo-\(2^{16}\) result storage, no saturation.

---

## 4. Implementation and verification order, ranked by risk

1. **Cycle-exact valid/control pipeline.**  
   First reproduce each reference stage’s `di_count`, start/end, registered enables, and interstage edge alignment. Verify impulse tags and frame numbers before checking arithmetic. Continuous back-to-back frames are the critical case.

2. **Configurable feedback depths and counter-bit selection.**  
   Validate every selected tap and M-dependent bit index independently for `{64,16,4}` and `{128,32,8}`. An off-by-one delay changes both ordering and latency.

3. **Signed butterfly semantics.**  
   Use explicit signed 17-bit add/sub, add RH at 17-bit width, then arithmetic `>>>1`. Exhaustively compare corner values for RH=0 and RH=1, especially negative odd sums and overflow boundaries.

4. **Complex multiply truncation.**  
   Preserve four exact signed 16×16 products and independently arithmetic-shift each product by 15 before the final 16-bit add/sub. Do not algebraically rearrange products across truncation points.

5. **Unified twiddle addressing.**  
   Prove that every reachable 64-point address maps to `2*addr64` in the 128 table and compare all reachable coefficients against both source tables. Explicitly verify address/data register alignment and address-zero bypass.

6. **S3 mode bypass and mode locking.**  
   Test asynchronous reset at every pipeline phase, then restart in either mode. Assert that `do_en=0` immediately and remains clear until the new frame’s specified latency.

7. **Physical timing and area.**  
   Synthesize early after functional equivalence. The likely 10 ns critical paths are coefficient decode through multiplier/addition and large feedback-tap mux routing. Keep twiddle and multiplier result registers at the reference boundaries; avoid adding latency. Confirm the shared design remains near the single 128-core resource count and therefore comfortably below the combined-core area baseline.