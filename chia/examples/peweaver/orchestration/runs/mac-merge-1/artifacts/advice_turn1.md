## 1. Architecture

### Datapath

Use one top-level module, `shared_mac`, containing one genuinely shared datapath:

- `a_s`, `b_s`: signed 8-bit interpretations of `a` and `b`.
- `product[15:0]`: exact signed 8×8 combinational product.
- `acc[15:0]`: the sole accumulator state.
- `sum[15:0]`: low 16 bits of `acc + product`.
- `y[15:0]`: the shared output register.
- Mode-dependent next-state selection around the shared multiplier and output register.

Conceptually:

- One signed 8×8 multiplier computes `product = signed(a) * signed(b)` in both modes.
- One 16-bit wrapping adder computes `sum = acc + product`.
- `mode` selects whether an enabled edge commits `sum` or `product` to `y`.
- Only mode 0 writes `acc`.

No instance of `mac_a` or `mac_b` is retained, and there is no duplicated multiplier lane.

### Sequential behavior

Use one rising-edge sequential process with this priority:

1. `reset`
2. `en`
3. hold

State transitions:

| Condition | `acc_next` | `y_next` |
|---|---:|---:|
| `reset=1` | `16'h0000` | `16'h0000` |
| `reset=0, en=0` | `acc` | `y` |
| `reset=0, en=1, mode=0` | `sum` | `sum` |
| `reset=0, en=1, mode=1` | `acc` | `product` |

All arithmetic wraps naturally to 16 bits. There is no saturation, rounding, or extra product truncation because a signed 8×8 product fits exactly in 16 bits.

### Sharing and area rationale

Compared with the two separate input designs:

- Multipliers: reduced from two to exactly one.
- State:
  - Separate designs: `mac_a.acc`, `mac_a.y`, and `mac_b.y` = 48 state bits.
  - Shared design: `acc` and `y` = 32 state bits.
- Added logic is only mode/enable steering and the accumulator write qualification.
- The mode-0 adder already corresponds to the adder required by `mac_a`; no second adder is needed.

Thus the merged structure removes one multiplier and one 16-bit output register. The small mode-selection logic should leave synthesized area strictly below the sum of separately synthesized inputs under the same synthesis flow and constraints.

### State ownership across modes

`acc` belongs exclusively to the accumulating workload:

- It is cleared by reset.
- It is updated only on `en=1 && mode=0`.
- It is unchanged during every mode-1 transaction.
- It is also unchanged whenever `en=0`.

Consequently, mode-1 products cannot enter the running sum. A transition between modes occurs only while `en=0` by contract, so that transition causes no state update. `y` is intentionally shared because it represents the result of whichever workload most recently completed an enabled transaction.

No separate mode history register is required. Correctness depends only on the value of `mode` sampled on an enabled rising edge. The environmental restriction that mode changes occur while `en=0` prevents ambiguous lane selection around active transactions.

---

## 2. Resource and schedule table

There is no pipeline, microcoded schedule, counter, or lookup table. Every enabled operation completes at one rising edge using the combinational result formed during the preceding cycle.

| Resource / element | Width or depth | Mode 0 schedule | Mode 1 schedule | Hold/reset behavior |
|---|---:|---|---|---|
| Signed input interpretation | 2 × 8 bits | Continuously interpret `a[7:0]`, `b[7:0]` as two’s complement | Same shared interpretation | Stateless |
| Shared multiplier | One signed 8×8 → 16-bit product | Continuously computes `product`; consumed when `en=1` | Same multiplier; consumed when `en=1` | Stateless; no clock enable needed |
| Wrapping accumulator adder | 16+16 → low 16 bits | Computes `sum = (acc + product) mod 2^16`; committed on enabled edge | Result is unused; may remain combinationally active | Stateless |
| Accumulator register `acc` | One entry × 16 bits | Write `sum` on each edge with `en=1` | No write | Clear to zero on reset; otherwise hold |
| Output-result selection | 2:1, 16 bits | Select `sum` | Select `product` | Selection matters only when `en=1` |
| Output register `y` | One entry × 16 bits | Write selected `sum` on enabled edge | Write selected `product` on enabled edge | Clear to zero on reset; hold when disabled |
| Pipeline stages | 0 internal stages | Single-cycle registered result | Single-cycle registered result | N/A |
| Counters | None | Period: N/A | Period: N/A | N/A |
| ROM/RAM tables | None | Addressing: N/A | Addressing: N/A | N/A |
| Mode state/history | None | Current sampled `mode` controls transaction | Same | Mode changes while `en=0` create no write |

### Cycle schedule

For cycle `N`, inputs and controls must be stable for the setup/hold window around rising edge `N`:

- If reset is asserted, `acc` and `y` become zero immediately after that edge.
- Otherwise, if enabled:
  - Mode 0 commits `acc_old + signed(a)*signed(b)` to both `acc` and `y`.
  - Mode 1 commits `signed(a)*signed(b)` to `y`, while retaining `acc_old`.
- Otherwise both registers retain their prior values.

The product and sum are not stored in intermediate registers, so there is no transaction latency beyond the destination register update at the sampling edge.

---

## 3. Exact interface and timing contract

Top module name: `shared_mac`.

Ports, and no others:

| Direction | Name | Width | Meaning |
|---|---|---:|---|
| Input | `clock` | 1 | Rising-edge clock |
| Input | `reset` | 1 | Synchronous active-high reset |
| Input | `mode` | 1 | `0`: accumulating lane; `1`: product lane |
| Input | `en` | 1 | Transaction/register enable |
| Input | `a` | 8 | Signed two’s-complement operand |
| Input | `b` | 8 | Signed two’s-complement operand |
| Output | `y` | 16 | Registered signed two’s-complement result, exposed as raw bits |

Timing and priority:

- State changes only on `posedge clock`.
- `reset` has priority over `en` and `mode`.
- With `reset=1`, both `acc` and `y` clear regardless of other inputs.
- With `reset=0 && en=0`, both states hold.
- With `reset=0 && en=1 && mode=0`:
  - `product = signed(a[7:0]) × signed(b[7:0])`
  - `acc_next = (acc_old + product) mod 2^16`
  - `y_next = acc_next`
- With `reset=0 && en=1 && mode=1`:
  - `y_next = product mod 2^16`
  - `acc_next = acc_old`
- `mode` may change only while `en=0`.
- There is one result per enabled edge and no bubbles or pipeline flush requirements.

---

## 4. Ranked risks and implementation/verification order

1. **Signed multiplication semantics**
   - Highest risk: accidentally treating unsigned ports as unsigned, or allowing expression sizing/sign extension to vary by language rules.
   - First implement explicit signed 8-bit operand interpretations and a 16-bit signed product.
   - Verify exhaustive or formal equality for all 65,536 `(a,b)` combinations, emphasizing `8'h80`, `8'hFF`, `8'h00`, and `8'h7F`.

2. **Accumulator wrapping and expression width**
   - Ensure addition is exactly modulo \(2^{16}\), with no unintended 17-bit state or incorrect signed extension.
   - Verify overflow cases such as `16'h7FFF + 1`, `16'h8000 + 16'hFFFF`, and repeated `(-128)×(-128)` products.

3. **Mode-1 accumulator isolation**
   - Verify formally that `!reset && en && mode` implies `acc_next == acc_old`.
   - Run sequences containing many mode-1 operations between mode-0 operations and compare the resumed sum against a reference model containing only mode-0 products.

4. **Reset/enable priority and hold behavior**
   - Verify reset clears both registers even when `en=1`.
   - Assert that `!reset && !en` implies stable `acc` and `y`.
   - Check reset during both modes and immediately before/after legal mode transitions.

5. **Output timing equivalence**
   - In mode 0, `y` must receive the newly calculated sum, not the old accumulator.
   - In mode 1, `y` must receive the current edge’s product.
   - Use cycle-accurate assertions based on pre-edge state.

6. **Structural sharing and synthesis result**
   - After functional verification, inspect elaborated/synthesized netlists to confirm exactly one multiplier structure/operator and one accumulator adder.
   - Synthesize `mac_a`, `mac_b`, and `shared_mac` independently with identical settings; confirm `area(shared_mac) < area(mac_a) + area(mac_b)`.
   - Check that synthesis has not inferred duplicated multipliers due to signedness conversions or alternate expressions.

7. **Legal mode-transition sequences**
   - Verify `mode` changes on disabled cycles preserve both states.
   - Add an environment assumption/assertion that mode is stable across enabled operation boundaries; do not add extra hardware that changes the specified behavior.