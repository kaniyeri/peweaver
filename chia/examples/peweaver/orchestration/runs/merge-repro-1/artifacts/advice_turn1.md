## 1. Architecture

Use one mode-configurable radix-\(2^2\) SDF pipeline containing three shared `SdfUnit`-equivalent stages followed by one radix-2 finishing stage:

```text
input
  -> CSDF0
  -> CSDF1
  -> CSDF2
  -> R2_FINAL (128 mode only)
  -> output
```

### Per-mode configuration

| Mode | CSDF0 | CSDF1 | CSDF2 | Final path |
|---|---:|---:|---:|---|
| 64-point | N=64, M=64 | N=64, M=16 | N=64, M=4 | bypass `R2_FINAL` |
| 128-point | N=128, M=128 | N=128, M=32 | N=128, M=8 | use `R2_FINAL` |

This is the same factorization as the references, but each corresponding 64/128 stage is one physical configurable stage. It is not two cores behind a mux.

### Shared resources

Each `CSDFk` physically contains:

- Two complex butterflies:
  - BF1: four signed 17-bit add/sub operations, `RH=0`.
  - BF2: four signed 17-bit add/sub operations, `RH=1`.
- Two programmable complex delay rings.
- One complex multiplier, except that CSDF2 bypasses it in 64 mode because `M=4`.
- One registered twiddle lookup port.
- Shared 7-bit sequencing counters and valid state.

`R2_FINAL` contains one complex butterfly with `RH=0` and a depth-1 complex delay. It is clocked/selected only for 128-point operation.

Thus the merged maximum hardware is seven complex butterflies, three complex multipliers, and 127 complex delay words. The separate cores require 63+127=190 complex delay words and duplicate all common datapath/control logic.

### Delay implementation

Replace shifting arrays with fixed-capacity circular delay storage, advancing every clock exactly as `DelayBuffer.v` does—not only on valid cycles. Each ring uses the selected logical depth shown below and read-before-write behavior equivalent to a depth-\(D\) shift register.

The storage is shared between modes; 64 mode uses only the smaller logical window. Delay data need not be reset because no output is marked valid until every active delay has been overwritten. Ring pointers, counters, and all validity state are asynchronously reset.

### Twiddle sharing

Use the 128-point literal table as the canonical coefficient bank. The 64-point literals are exactly its even-index entries:

```text
rom_addr = mode_q ? tw_addr_128 : {tw_addr_64, 1'b0}
```

Only addresses reachable as \(n\times\{0,1,2,3\}\) need implementation:

```text
R = {0..31} union {2*k | 0<=k<=31} union {3*k | 0<=k<=31}
```

Every reachable entry must use the exact 16-bit literals from `Twiddle128.v`; unreachable entries may return deterministic zero rather than `x`. Address zero bypasses the multiplier. Each CSDF stage needs an independent lookup port because all three stages can require coefficients concurrently; the coefficient constants/decoder definition is common across modes.

The complex multiplier preserves the reference ordering:

```text
arbr = signed(a_re) * signed(b_re)   // 32 bits
arbi = signed(a_re) * signed(b_im)
aibr = signed(a_im) * signed(b_re)
aibi = signed(a_im) * signed(b_im)

m_re = (arbr >>> 15) - (aibi >>> 15) // low 16 bits
m_im = (arbi >>> 15) + (aibr >>> 15) // low 16 bits
```

Do not replace this with a three-real-multiplier identity: independently truncated products make that transformation non-equivalent.

### Mode and state ownership

- `mode_q` is the sole owner of configuration.
- While idle, the first accepted sample uses `mode` directly and captures it into `mode_q` on that edge, avoiding a one-cycle error if `di_en` follows reset immediately.
- Once work is in flight, `mode_q` is held.
- A 9-bit `outstanding` counter tracks accepted samples minus emitted samples. `idle` is true only when `outstanding==0` and no partial input-frame/control-valid state exists.
- The environment must reset and drain before changing mode, as required. Asynchronous reset clears `mode_q`, `outstanding`, all counters, enables, valid pipelines, and delay pointers. Consequently stale delay contents can never assert `do_en`.
- There is no per-mode computational state and no inactive core whose state can leak through a selector.

## 2. Resource and schedule table

Offsets below are measured from the edge accepting sample 0 of a frame.

| Resource | 64-point configuration | 128-point configuration |
|---|---|---|
| Global/local counter width | 7 bits; wrap at 64, bit 6 forced/cleared | 7 bits; wrap at 128 |
| CSDF0 | M=64; DB1=32, DB2=16; output offset 51 | M=128; DB1=64, DB2=32; output offset 99 |
| CSDF1 | M=16; DB1=8, DB2=4; input 51, output 66 | M=32; DB1=16, DB2=8; input 99, output 126 |
| CSDF2 | M=4; DB1=2, DB2=1; multiplier bypass; input 66, output 71 | M=8; DB1=4, DB2=2; input 126, output 135 |
| `R2_FINAL` | bypass with no added register/latency | DB=1, RH=0; input 135, output 137 |
| Total complex delay state | 63 words used | 127 words used |
| Output valid span | offsets 71 through 134: 64 clocks | offsets 137 through 264: 128 clocks |

For each configurable CSDF stage with selected \(M\):

- `di_count`, `bf1_count`, and `bf2_count` have period \(N\).
- BF1 delay depth is \(M/2\).
- BF2 delay depth is \(M/4\).
- `bf1_bf = di_count[log2(M)-1]`.
- `bf1_start` occurs at `di_count == M/2-1`.
- The `-j` path is selected when
  `bf1_count[log2(M)-1 : log2(M)-2] == 2'b11`.
- Registered BF2 control is the selected `bf1_count[log2(M)-2]`.
- `bf2_start` corresponds to `bf1_count == M/4-1`.
- `tw_sel = {bf2_count[log2(M)-2], bf2_count[log2(M)-1]}`.
- `tw_num = (bf2_count << log2(N/M))`, truncated to `log2(N)-2` bits.
- `tw_addr = tw_num * tw_sel`.
- Nonfinal CSDF latency is \(3M/4+3\).
- The `M=4` multiplier-bypassed stage latency is \(3M/4+2=5\).
- `R2_FINAL` latency is 2.

Concrete thresholds:

| Stage | 64 BF1/BF2 start thresholds | 128 BF1/BF2 start thresholds |
|---|---:|---:|
| CSDF0 | 31 / 15 | 63 / 31 |
| CSDF1 | 7 / 3 | 15 / 7 |
| CSDF2 | 1 / 0 | 3 / 1 |

Once a stage starts emitting, its stage-valid remains asserted for exactly \(N\) clocks. The following frame may enter every \(N\) input clocks, so stages simultaneously process different frames without resource conflicts.

## 3. Exact interface and timing contract

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

There are no other ports.

- `reset` has active-high asynchronous assertion.
- `mode=0`: exactly 64 consecutive enabled natural-order inputs form a frame.
- `mode=1`: exactly 128 consecutive enabled natural-order inputs form a frame.
- No backpressure; every `di_en=1` edge accepts one sample.
- If the sample-0 acceptance edge is cycle 0:
  - 64 mode first asserts `do_en` at cycle 71.
  - 128 mode first asserts `do_en` at cycle 137.
- `do_en` remains high for exactly 64 or 128 consecutive clocks.
- Continuous same-mode frames may begin every \(N\) clocks.
- Output order is bit-reversed and total scaling is exactly \(1/N\).
- All arithmetic wraps modulo \(2^{16}\); there is no saturation.
- After reset, `do_en` remains low until a newly accepted frame reaches its specified latency.

## 4. Ranked implementation and verification risks

1. **Cycle alignment and nonblocking-register boundaries**  
   First reproduce one configurable CSDF stage and prove latencies 51/99, 15/27, and 5/9 against the corresponding reference stages. Verify every internal valid edge, twiddle address, and bypass cycle before integration.

2. **Twiddle address/register alignment**  
   The table output, `mu_en`, BF2 data, and multiplier-result register must remain aligned exactly as in `SdfUnit.v`. Exhaustively compare all reachable addresses in both modes and prove `Twiddle64[a] == Twiddle128[2*a]`.

3. **Signed truncation and rounding**  
   Unit-test butterfly extrema and odd negative values for arithmetic-floor shifts. Exhaustively/randomly compare the complex multiplier’s four separately shifted products, overflow, and address-zero bypass.

4. **Programmable circular-delay equivalence**  
   Compare each logical depth—64, 32, 16, 8, 4, 2, and 1—against the always-shifting reference buffer, including invalid gaps and reset without clearing data memory.

5. **Mode capture and reset flushing**  
   Test immediate mode-1 input after reset deassertion, reset during fill/output, reset between continuous frames, idle drains, and mode changes. Assert that `do_en` cannot survive reset or expose stale storage.

6. **Continuous-frame overlap**  
   Compare long uninterrupted bursts in both modes. Check frame boundaries while input, intermediate-stage output, and final output belong to different frames concurrently.

7. **Physical implementation**  
   After bit-exact RTL equivalence, synthesize early. Preserve multiplier pipeline boundaries, use balanced coefficient muxes, constrain high-fanout mode/control nets, and floorplan delay banks near their butterflies. Iterate mapping until 10 ns timing has TNS 0, then verify mapped simulation, DRC 0, and placed area below 424,885 µm².