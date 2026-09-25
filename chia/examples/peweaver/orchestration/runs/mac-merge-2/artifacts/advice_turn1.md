## 1. Architecture

### Shared datapath

The top-level design is a single module, `shared_mac`, containing:

- One signed 8×8 combinational multiplier.
  - Inputs: `a_signed[7:0]`, `b_signed[7:0]`
  - Output: `product[15:0]`
  - `product = a_signed * b_signed`
- One 16-bit wrapping adder.
  - Inputs: `acc[15:0]`, `product[15:0]`
  - Output: `sum[15:0] = acc + product`
  - Carry-out is discarded, implementing modulo \(2^{16}\).
- One 16-bit accumulator register, `acc`.
- One 16-bit output register, `y`.
- A small result-selection mux:
  - `mode=0`: selected result is `sum`
  - `mode=1`: selected result is `product`

There is no second multiplier, duplicated lane, pipeline, memory, lookup table, or instantiated copy of either input design.

### State update policy

At each rising edge of `clock`, priority is:

1. If `reset=1`:
   - `acc <= 16'h0000`
   - `y <= 16'h0000`
2. Else if `en=0`:
   - `acc` holds
   - `y` holds
3. Else if `en=1 && mode=0`:
   - `acc <= sum`
   - `y <= sum`
4. Else (`en=1 && mode=1`):
   - `acc` holds
   - `y <= product`

The accumulator is therefore owned exclusively by mode 0. Mode 1 can read neither an alternative accumulator nor modify `acc`; it only writes the shared output register. Consequently, any number of mode-1 operations can occur between mode-0 operations without disturbing the mode-0 running sum.

Because the contract permits `mode` to change only while `en=0`, a mode transition itself causes no state update. The state held before the transition remains intact until the first enabled edge in the new mode.

### Signed arithmetic

Treat both multiplier operands as signed 8-bit two’s-complement values. The sole multiplication expression must have signed operands and a signed 16-bit result:

- Input range: −128 through +127
- Exact product range: −16384 through +16129
- All products fit exactly in signed 16 bits.
- Accumulation uses the raw 16-bit product bit pattern.
- The adder discards overflow, producing modulo-\(2^{16}\) wrapping.

The output is a raw 16-bit two’s-complement word. Declaring it signed is appropriate but does not change its stored bits.

### Sharing and area rationale

Compared with the sum of the two references, the merged design removes:

- One complete 8×8 multiplier
- One of the two independent `y` registers
- Duplicated product-lane control

It retains:

- One multiplier
- The accumulator and adder required by mode 0
- One shared output register
- A result mux and minimal mode-qualified enables

The mux/control overhead should be substantially smaller than the removed multiplier and output register. Final compliance with “strictly below” must still be checked using the required synthesis tool, library, constraints, and identical area-reporting flow. The synthesis netlist should also be inspected to confirm exactly one multiplier structure and no accidental duplication caused by separate multiplication expressions.

## 2. Resource and schedule table

| Resource / signal | Width | State depth | Period / addressing | Mode 0 schedule | Mode 1 schedule |
|---|---:|---:|---|---|---|
| Signed multiplier | 8×8 → 16 | 0, combinational | Available every cycle; no table/address | Computes `product=a*b`; captured only when `en=1` | Same shared computation; captured only when `en=1` |
| `product` net | 16 | 0 | No storage or pipeline stage | Feeds wrapping adder | Feeds output-result mux directly |
| Wrapping adder | 16+16 → 16 | 0, combinational | Available every cycle; carry discarded | Computes `sum=acc+product` | Result unused; must not update state |
| `acc` register | 16 | 1 word | No counter; indefinite retention | Clear on reset; write `sum` on `en=1`; otherwise hold | Clear on reset; always hold when not reset |
| Result mux | 16, 2:1 | 0 | Selected by `mode` | Selects `sum` | Selects `product` |
| `y` register | 16 | 1 word | No counter; indefinite retention | Clear on reset; write `sum` on enabled edge | Clear on reset; write `product` on enabled edge |
| Register controls | Reset plus enables | 0 | No sequencer | `acc_we=en && !mode`; `y_we=en` | `acc_we=0`; `y_we=en` |
| Pipeline stages | — | 0 | Single-cycle, non-pipelined | Multiply and add before the same capture edge | Multiply before the same capture edge |
| Counters | — | 0 | Not present | N/A | N/A |
| Memories/tables | — | 0 | Not present; no addressing | N/A | N/A |

Reset overrides all write enables. No valid/ready signals or latency counters are needed.

## 3. Exact interface and timing contract

The only top module is named `shared_mac`, with exactly:

- `input clock`
- `input reset`
- `input mode`
- `input en`
- `input [7:0] a`
- `input [7:0] b`
- `output [15:0] y`

Signed declarations may be used for `a`, `b`, and `y`, but their physical widths and port list remain exactly as above. There are no other external signals.

Timing is rising-edge synchronous:

- `reset` is synchronous and active high.
- Reset has priority over `en` and `mode`.
- With reset asserted at a rising edge, `acc` and `y` become zero after that edge.
- With reset deasserted and `en=0`, both registers hold.
- With `en=1, mode=0`, the product and old accumulator are combined during that cycle; after the edge, both `acc` and `y` contain the wrapped sum.
- With `en=1, mode=1`, after the edge `y` contains the exact signed product while `acc` remains unchanged.
- There is no added pipeline latency: each enabled edge commits the operation represented by `a`, `b`, and `mode` sampled for that edge.
- `mode` transitions occur only while `en=0`; those transition edges preserve both states.

## 4. Ranked risks and implementation/verification order

1. **Signed multiplier inference**
   - Highest risk: unsigned extension or mixed signed/unsigned expression rules can corrupt negative products.
   - Implement first.
   - Verify all operand corner combinations, especially `8'h80`, `8'hFF`, `8'h00`, and `8'h7F`.

2. **Accumulator ownership across mode changes**
   - Ensure only `en && !mode` can write `acc`.
   - Verify mode-0 accumulation, several mode-1 products, then resumed mode-0 accumulation from the preserved sum.

3. **Sequential priority and hold behavior**
   - Implement explicit priority: reset, enabled operation, implicit hold.
   - Verify reset while enabled, long disabled intervals, and mode changes during disabled cycles.

4. **Modulo-\(2^{16}\) accumulation**
   - Ensure no saturation and no unintended wider retained result.
   - Verify positive overflow, negative overflow, repeated `−128×−128`, and repeated negative products.

5. **Output-register semantics**
   - `y` must hold when disabled and must not automatically expose a combinational product or accumulator.
   - Verify that changing `a`, `b`, or `mode` with `en=0` does not change registered `y`.

6. **Single-multiplier synthesis**
   - Use exactly one multiplication expression feeding both paths.
   - Synthesize and inspect arithmetic/resource reports and the structural netlist for one 8×8 multiplier implementation.

7. **Strict area target**
   - Synthesize `mac_a`, `mac_b`, and `shared_mac` separately under identical settings.
   - Confirm `area(shared_mac) < area(mac_a) + area(mac_b)` and ensure optimization did not invalidate the one-multiplier structural check.