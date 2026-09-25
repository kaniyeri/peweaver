## 1. Architecture

Use one mode-locked radix-\(2^2\) SDF pipeline with three shared stages and one conditional radix-2 tail:

```text
input
  -> R22_STAGE0
  -> R22_STAGE1
  -> R22_STAGE2
  -> [R2_TAIL only in 128 mode]
  -> output
```

| Block | 64-point configuration | 128-point configuration |
|---|---:|---:|
| `R22_STAGE0` | N=64, M=64 | N=128, M=128 |
| `R22_STAGE1` | N=64, M=16 | N=128, M=32 |
| `R22_STAGE2` | N=64, M=4, multiplier bypassed | N=128, M=8 |
| `R2_TAIL` | bypassed and invalid | M=2, RH=0 |

This is genuinely shared: both modes use the same three pairs of butterflies, feedback storage, control structure, and interstage registers. Only delay taps, counter terminal values, control-bit selection, twiddle addressing, and the final-tail mux depend on mode.

### Shared resources

- Six 16-bit complex butterflies in the three radix-\(2^2\) stages:
  - first butterfly: `RH=0`
  - second butterfly: `RH=1`
- Three complex multipliers:
  - stages 0 and 1 use them in both modes
  - stage 2 uses its multiplier only in 128 mode
- One 128-point twiddle constant table, shared by all stages and modes.
- One radix-2 tail butterfly, needed only by 128 mode.
- Maximum feedback storage:
  - stage 0: 64 and 32 complex words
  - stage 1: 16 and 8 complex words
  - stage 2: 4 and 2 complex words
  - tail: 1 complex word
  - total: 127 complex words

The selectable delays should be implemented as maximum-depth shift storage with mode-selected taps. Storage shifts every clock, matching `DelayBuffer.v`; it is not gated by valid.

### Twiddle sharing

The 128-point table subsumes the 64-point table exactly:

```text
W64[k] = W128[2*k]
```

For every address used by the 64-point core, both 16-bit literals match. Thus no separate 64-point ROM is needed.

Use a 7-bit physical address:

```text
phase_sel = {bf2_count[m-2], bf2_count[m-1]}   // phases 0,2,1,3
base      = bf2_count[m-3:0] << (7-m)
tw_addr   = phase_sel * base
```

where `m=log2(M)`. This directly gives 128-table addresses in both modes. `tw_addr==0` bypasses the multiplier; table entry zero may remain `16'h0000,j16'h0000`. Only reachable addresses need literal cases; unreachable reference `xxxx` entries must never be selected.

### Mode and state ownership

Use:

- `mode_q`: latched operating mode
- `mode_valid`: indicates that `mode_q` belongs to the current reset epoch
- `busy`: input frame or pipeline output is outstanding
- 7-bit frame/sample and stage counters
- reset-cleared valid/enable state at every stage

Rules:

1. Asynchronous reset immediately clears `mode_valid`, `busy`, all counters, stage valid state, and `do_en`.
2. While idle, `mode_q` may track/capture `mode`; the first accepted sample locks it.
3. While `busy=1`, changes on external `mode` are ignored.
4. Continuous frames inherit the locked mode; there is no relatching at frame boundaries while earlier data remains in flight.
5. A mode transition therefore requires reset, as required by the contract.
6. Feedback data arrays need not be reset. All valid state is reset, and each selected delay is overwritten before its first legal butterfly read. Consequently stale words from a previous mode can never become valid output.
7. In 64 mode the tail receives no valid state, and top-level output selects stage 2. In 128 mode output selects the tail.

---

## 2. Per-stage schedule

Let local cycle 0 be the edge accepting that stage's first input. Each stage receives and emits exactly N consecutive valid samples.

For a radix-\(2^2\) stage:

- `di_count`: modulo N while input valid; zero on a pre-frame gap
- BF1 select: `di_count[m-1]`, period M, blocks of M/2
- BF1 delay: \(D_1=M/2\)
- `bf1_start`: `di_count == D1-1`
- BF1 `-j`: `bf1_count[m-1:m-2] == 2'b11`
- BF2 select: registered `bf1_count[m-2]`, period M/2, blocks of M/4
- BF2 delay: \(D_2=M/4\)
- `bf2_start`: registered detection of  
  `bf1_sp_en && bf1_count == D2-1`
- `bf1_count` and `bf2_count`: modulo N during their N-cycle valid windows
- Twiddle phase over each M-sample period: `0,2,1,3`
- Normal radix-\(2^2\) latency: \(D_1+D_2+3\)
- M=4 final-stage latency: \(D_1+D_2+2\), because multiplier/ROM output is bypassed

### Configuration table

| Stage | Mode | M | BF1 delay | BF2 delay | Counter width/period | Twiddle base and address | Stage latency | First output, top-relative |
|---|---:|---:|---:|---:|---|---|---:|---:|
| `R22_STAGE0` | 64 | 64 | 32 | 16 | 7-bit, modulo 64; control period 64 | `base=count[3:0]<<1`; `addr=sel*base` | 51 | 51 |
| `R22_STAGE0` | 128 | 128 | 64 | 32 | 7-bit, modulo 128; control period 128 | `base=count[4:0]`; `addr=sel*base` | 99 | 99 |
| `R22_STAGE1` | 64 | 16 | 8 | 4 | 7-bit, modulo 64; control period 16 | `base=count[1:0]<<3`; `addr=sel*base` | 15 | 66 |
| `R22_STAGE1` | 128 | 32 | 16 | 8 | 7-bit, modulo 128; control period 32 | `base=count[2:0]<<2`; `addr=sel*base` | 27 | 126 |
| `R22_STAGE2` | 64 | 4 | 2 | 1 | 7-bit, modulo 64; control period 4 | no multiplier; unconditional twiddle bypass | 5 | 71 |
| `R22_STAGE2` | 128 | 8 | 4 | 2 | 7-bit, modulo 128; control period 8 | `base=count[0]<<4`; `addr=sel*base` | 9 | 135 |
| `R2_TAIL` | 64 | — | — | — | disabled; valid forced low | bypass stage 2 | 0 | 71 |
| `R2_TAIL` | 128 | 2 | 1 | — | `bf_en` toggles on each valid sample; period 2 | none | 2 | 137 |

For all radix-\(2^2\) rows, `count` in the twiddle expression is `bf2_count`, and:

```text
sel = {bf2_count[m-2], bf2_count[m-1]}
```

Each listed first-output point begins an uninterrupted N-cycle valid interval. Consecutive same-mode input frames produce consecutive stage-valid and final-output windows with one sample per clock.

### Arithmetic

Every shared butterfly must explicitly sign-extend operands to 17 bits:

```text
sum/difference = signed 17-bit operation
result = (sum_or_difference + RH) >>> 1
```

and retain the low 16 result bits.

Each complex multiplier retains four independent signed 16×16 products:

- `arbr`, `arbi`, `aibr`, `aibi`: signed 32-bit
- each product independently arithmetic-shifted by 15 and truncated to 16 bits
- `m_re = sc_arbr - sc_aibi`
- `m_im = sc_arbi + sc_aibr`
- 16-bit modulo arithmetic, no saturation

Do not replace this with a three-multiply identity: independent product truncations make that non-bit-exact.

The BF1 `-j` operation is exactly:

```text
re_out = im_in
im_out = 16'b0 - re_in
```

---

## 3. Exact interface and latency

The top level has no parameters and exactly these ports:

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

`reset` has active-high asynchronous assertion.

If the edge accepting input sample 0 is cycle 0:

| Locked mode | Frame size | First `do_en` | Valid duration |
|---|---:|---:|---:|
| `mode_q=0` | 64 | cycle 71 | cycles 71–134, exactly 64 cycles |
| `mode_q=1` | 128 | cycle 137 | cycles 137–264, exactly 128 cycles |

Outputs are scaled by one bit at each radix-2 butterfly, giving total scaling `1/64` or `1/128`, and are emitted in bit-reversed order.

---

## 4. Risks and implementation/verification order

1. **Cycle and valid alignment**
   - Highest risk because the ROM register, `mu_en`, butterfly data registers, and enable registers have deliberate offsets.
   - First reproduce each reference stage's latency independently: 51/15/5 and 99/27/9/2.
   - Then verify cumulative first-valid cycles 71 and 137, including back-to-back frames.

2. **Signed arithmetic and truncation**
   - Implement and exhaustively/unit-test butterfly boundary values first.
   - Verify negative odd sums use arithmetic-floor shifting.
   - Verify each 32-bit multiplier product is shifted independently before the final 16-bit add/sub.
   - Test `16'h8000`, `16'h7fff`, negative-one, overflow, and `-j` negation of `16'h8000`.

3. **Twiddle address phase ordering**
   - Preserve the non-obvious selector order `{count[m-2],count[m-1]}`, which produces `0,2,1,3`, not `0,1,2,3`.
   - Compare every reachable address and literal against each reference.
   - Explicitly prove the 64-mode mapping `addr128=2*addr64`.

4. **Variable-depth feedback taps**
   - Check off-by-one behavior for all selected depths: 64/32, 32/16, 16/8, 8/4, 4/2, 2/1, and tail 1.
   - Verify storage shifts even when valid is low, as in `DelayBuffer.v`.
   - Confirm stale post-reset data cannot be consumed before overwrite.

5. **Mode/reset ownership**
   - Verify external `mode` changes are ignored while busy.
   - Assert reset during input, pipeline drain, and output; `do_en` must drop asynchronously and never reappear from old state.
   - Test 128→reset→64 and 64→reset→128 with adversarial old feedback contents.

6. **64-mode tail bypass**
   - Ensure bypass changes neither latency nor data and tail valid remains cleared.
   - Ensure stage 2 multiplier is bypassed only for M=4, while 128-mode M=8 uses it.

7. **Area and 10 ns timing**
   - Preserve register boundaries around twiddle lookup and multiplication.
   - Use sparse reachable-address constant decoding rather than two complete tables.
   - Synthesize early after arithmetic equivalence. The merged design has 7 versus 13 total reference butterflies, 3 versus 5 complex multipliers, and 127 versus 190 complex delay words, providing the primary area margin without risky arithmetic restructuring.