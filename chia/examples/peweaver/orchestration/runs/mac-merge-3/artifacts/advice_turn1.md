## 1. Architecture

Use a single-cycle, genuinely shared datapath:

- `a_s`: signed 8-bit interpretation of `a`
- `b_s`: signed 8-bit interpretation of `b`
- `product[15:0] = a_s * b_s`
- `acc[15:0]`: the only accumulator state
- `sum[15:0] = acc + product`, with natural modulo-\(2^{16}\) truncation
- `next_value[15:0] = mode ? product : sum`
- `y[15:0]`: registered externally visible result

Only one signed 8×8 multiplication operation is present. Both modes consume the same `product`; there are no duplicated mode-specific datapaths or instances of `mac_a`/`mac_b`.

### State updates

On each rising edge of `clock`, in priority order:

1. If `reset=1`:
   - `acc <= 16'h0000`
   - `y <= 16'h0000`
2. Else if `en=1`:
   - If `mode=0`:
     - `acc <= sum`
     - `y <= sum`
   - If `mode=1`:
     - `acc` holds
     - `y <= product`
3. Else:
   - `acc` holds
   - `y` holds

### Sharing and state ownership

- The multiplier is shared unconditionally because multiplication is identical in both source designs.
- The 16-bit adder is needed only by accumulating transactions, but only one physical adder exists.
- `acc` belongs exclusively to mode 0:
  - mode-0 accepted transactions update it;
  - mode-1 transactions cannot modify it;
  - disabled cycles and mode changes cannot modify it.
- `y` is shared output state. Each enabled transaction writes the result selected by the sampled `mode`.
- No mode-history register is required. The contract guarantees that `mode` changes only while `en=0`, and those cycles hold all state. Thus an accumulated partial sum survives any number of product-mode transactions and mode changes.
- Each accepted transaction is completed on one edge; there is no pipeline state that could contain work from the previous mode.

The implementation should contain exactly one multiplication expression, with both operands explicitly converted to signed 8-bit values before multiplication. Addition and assignment are 16-bit, intentionally wrapping on overflow.

## 2. Resource and schedule table

| Resource / signal | Width and depth | Period / addressing | `mode=0`, `en=1` | `mode=1`, `en=1` | `en=0` |
|---|---:|---|---|---|---|
| Signed multiplier | 8×8 → 16 bits, combinational, depth 0 | No counter; no table | Compute `product=a_s*b_s` | Same shared computation | May compute combinationally, but result is not captured |
| Accumulation adder | 16+16 → 16 bits, combinational, depth 0 | No counter; modulo \(2^{16}\) | Compute `sum=acc+product` | Result unused | Result unused |
| Result selector | 2:1, 16 bits, combinational | Select address is `mode` | Select `sum` | Select `product` | Selection irrelevant |
| `acc` register | 16 bits, one state element / one-cycle storage depth | No counter or addressing | Load `sum` | Hold | Hold |
| `y` register | 16 bits, one state element / one-cycle storage depth | No counter or addressing | Load `sum` | Load `product` | Hold |
| Reset control | Synchronous, active high | Evaluated every rising edge | Clear both registers when asserted | Same | Same |
| Pipeline registers | None beyond `acc` and `y` | No valid/phase counter | N/A | N/A | N/A |
| Memories/tables | None | No table depth or address | N/A | N/A | N/A |

### Per-edge schedule

| Edge condition | Multiplier result used by | Adder used | `acc` action | `y` action |
|---|---|---|---|---|
| `reset=1` | Neither | No | Clear | Clear |
| `reset=0, en=1, mode=0` | Adder | Yes | Load `acc + product` | Load identical value |
| `reset=0, en=1, mode=1` | `y` input | No | Hold | Load `product` |
| `reset=0, en=0` | Neither | No | Hold | Hold |

There are no counters, iterative multiplication cycles, lookup tables, or pipeline bubbles. Throughput is one accepted operation per clock, and architectural latency is one rising edge.

### Resource comparison

The merged design has:

- one 8×8 signed multiplier rather than two;
- one 16-bit accumulator adder rather than duplicating mode datapaths;
- two 16-bit registers (`acc` and `y`);
- one small result-selection/control network.

It removes the second multiplier and the separate product-lane output register from the combined source implementations. This should synthesize strictly below the sum of separately synthesized `mac_a` and `mac_b`, assuming identical synthesis constraints and no artificial preservation of unused logic. Post-synthesis checks must confirm exactly one multiplier structure and the required strict area inequality.

## 3. Exact interface and timing contract

Top module name:

`shared_mac`

Ports, and no others:

| Name | Direction | Width | Meaning |
|---|---|---:|---|
| `clock` | input | 1 | Rising-edge clock |
| `reset` | input | 1 | Synchronous active-high reset |
| `mode` | input | 1 | `0`: accumulating lane; `1`: product lane |
| `en` | input | 1 | Transaction/state-update enable |
| `a` | input | 8 | Signed two’s-complement multiplicand |
| `b` | input | 8 | Signed two’s-complement multiplier |
| `y` | output | 16 | Registered signed two’s-complement result |

At every rising edge:

- `reset` has priority over `en` and `mode`.
- With reset asserted, `acc` and `y` become zero immediately after the edge.
- With reset deasserted and `en=1`, operands and `mode` sampled for that edge determine the new state:
  - `mode=0`: `y` and `acc` receive `(acc + signed(a)*signed(b)) mod 65536`.
  - `mode=1`: `y` receives `signed(a)*signed(b)` represented in 16 bits; `acc` holds.
- With `en=0`, both registers hold regardless of operand or mode changes.
- `y` remains stable between active edges.
- There is no saturation, rounding, extra output latency, or hidden transaction state.
- The environment changes `mode` only while `en=0`.

## 4. Ranked risks and implementation/verification order

1. **Signed multiplication correctness**
   - Highest risk is accidental unsigned multiplication or an incorrectly sized intermediate.
   - First implement explicit signed 8-bit operand interpretations and a signed 16-bit product.
   - Verify corner cases: `-128×-128=16384`, `-128×127=-16256`, `-1×-1=1`, and mixed signs.

2. **Accumulator isolation in product mode**
   - Ensure `acc` has no assignment on enabled `mode=1` cycles.
   - Verify: accumulate, switch during a disabled cycle, execute several product operations, switch back during a disabled cycle, and continue from the preserved sum.

3. **Nonblocking-update semantics for mode 0**
   - Both `acc` and `y` must receive the same newly computed sum based on the old `acc`.
   - Avoid making `y` lag `acc` by one transaction.
   - Verify after every mode-0 edge that `y == acc`.

4. **Reset and enable priority**
   - Reset must clear state even when `en=1`.
   - Verify reset with both mode values, reset concurrent with enable, and the first operation after reset.

5. **Modulo-\(2^{16}\) accumulation**
   - Ensure carry-out is discarded without saturation or unintended width extension.
   - Verify positive overflow, negative overflow, and long randomized accumulation sequences against a 16-bit reference model.

6. **Hold behavior and mode transitions**
   - Confirm `en=0` prevents changes to both `acc` and `y`, even while `a`, `b`, and `mode` toggle.
   - Check that changing modes alone never exposes a combinational value at `y`.

7. **Structural sharing and area**
   - Inspect elaborated/synthesized netlists for one multiplier only.
   - Check that coding style did not cause duplicated signed/unsigned multiplier variants.
   - Synthesize `mac_a`, `mac_b`, and `shared_mac` with identical constraints, then require `area(shared_mac) < area(mac_a) + area(mac_b)`.

8. **Final contract verification**
   - Run directed corner cases followed by randomized cycle-by-cycle comparison against a reference model.
   - Add structural checks for top-module name, exact port set, absence of forbidden constructs, one multiplier, and no instantiated source modules.