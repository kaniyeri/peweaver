## 1. Architecture

### Shared combinational datapath

Use one unpipelined db2 analysis bank shared by:

- Context A level 1
- Context B level 1
- Context B level 2

The bank has four signed 16-bit operands `s0..s3` and produces two signed 40-bit results:

- `lo_sum = H0*s0 + H1*s1 + H2*s2 + H3*s3`
- `hi_sum = G0*s0 + G1*s1 + G2*s2 + G3*s3`

Pinned signed 16-bit literals:

| Lane | Low coefficient | High coefficient |
|---|---:|---:|
| 0 | `15826` | `-4240` |
| 1 | `27411` | `-7345` |
| 2 | `7345` | `27411` |
| 3 | `-4240` | `-15826` |

This uses exactly eight normalized signed multiplication operators. Each product is signed 32-bit, explicitly sign-extended to 40 bits before a fixed three-adder tree. Every addition is 40-bit, so overflow wraps modulo \(2^{40}\).

No arithmetic pipeline is needed: the selected operation is calculated from state existing immediately before the active edge and captured on that edge.

### Operand selection

Use a small operation selector, conceptually:

- `OP_A_L1`: `{x, a_w0, a_w1, a_w2}`
- `OP_B_L1`: `{x, b_w0, b_w1, b_w2}`
- `OP_B_L2`: `{b_q0, b_q1, b_q2, b_q3}`
- `OP_IDLE`: result ignored

For both level-1 operations, the operand vector is the fresh sample followed by the three most recent accepted samples. A fourth level-1 history register is unnecessary because neither reference reads `w3`.

For B level 1, `b_q_new` is exactly `lo_sum[30:15]`, interpreted as signed 16-bit.

### Packed state ownership

Keep logically separate A and B fields, preferably inside one packed next-state register to reduce unweighted generic Yosys cell count. All updates are derived from the old packed state, and the register is assigned as one next-state object.

Required logical state:

**Context A — 130 bits**

- `a_w0..a_w2`: 3 × 16 = 48 bits
- `a_ph`: 1 bit
- `a_l1_lo`, `a_l1_hi`: 80 bits
- `a_l1_valid`: 1 bit

**Context B — 277 bits**

- `b_w0..b_w2`: 48 bits
- `b_ph`: 1 bit
- `b_q0..b_q3`: 64 bits
- `b_mpar`: 1 bit
- `b_pending`: 1 bit
- B level-1 data and valid: 81 bits
- B level-2 data and valid: 81 bits

Total logical state: **407 bits**.

Packing is a synthesis-oriented representation, not shared ownership: each field still belongs exclusively to one context. On an enabled edge, only fields belonging to `ctx` may change, except that all valid bits are cleared by default because they are strobes. Inactive context histories, phases, pending work, and data registers remain unchanged.

Synchronous reset clears the entire packed state independently of `ctx` and `en`.

### Valid handling

On every non-reset edge:

- Clear `a_l1_valid`, `b_l1_valid`, and `b_l2_valid`.
- Assert only the strobe produced by the selected active context.
- Data outputs hold unless their corresponding result is produced.

Thus a strobe never remains asserted through `en=0` or context suspension, while stored data continues to hold.

### Why one bank is sufficient

The B schedule guarantees no arithmetic collision:

- B level 1 occurs only when old `b_ph=1`.
- A pending B level-2 job is consumed when old `b_ph=0`.
- Therefore B level 1 and B level 2 never need the bank on the same edge.
- Only one context can accept a sample on any edge.

This is genuine time-sharing; there are not separate A, B-L1, and B-L2 arithmetic banks.

---

## 2. Resource and Schedule Table

### Major resources and state

| Resource | Width/depth | Address or phase | Enable/update schedule |
|---|---:|---|---|
| Shared low/high bank | 8 signed 16×16 multipliers; 6 signed 40-bit adders | Four fixed coefficient lanes | Captured only for A-L1, B-L1, or B-L2 events |
| Operand mux | 4 × signed 16-bit | `OP_A_L1`, `OP_B_L1`, `OP_B_L2` | Combinational from active context and old phase/pending |
| A level-1 history | Depth 3 × 16 | `a_w0` newest through `a_w2` oldest | Shift on `en && !ctx` |
| B level-1 history | Depth 3 × 16 | `b_w0` newest through `b_w2` oldest | Shift on `en && ctx` |
| B level-2 history | Depth 4 × 16 | `b_q0` newest through `b_q3` oldest | Shift only on B level-1 production |
| `a_ph` | Modulo-2 accepted-sample phase | Initial 0; old value 1 means output | Toggle on each accepted A sample |
| `b_ph` | Modulo-2 accepted-sample phase | Initial 0; old value 1 means output | Toggle on each accepted B sample |
| `b_mpar` | Modulo-2 B-pair phase | Initial 0; old value 1 creates job | Toggle on every B level-1 pair |
| `b_pending` | One-entry job flag | 0/1 | Set on odd B pair index; clear on consumption |
| Output data registers | A: 80 bits; B: 160 bits | Direct output slices | Update only on corresponding production event |
| Valid registers | 3 bits | One per output pair | Cleared each non-reset edge, selectively asserted |

There is no coefficient ROM or run-time coefficient address. Lane number 0–3 is the fixed coefficient-table address.

### Edge schedule

| Active condition before edge | Datapath operation | State action after edge |
|---|---|---|
| `reset=1` | None | Clear all A and B state and outputs |
| `en=0` | Idle | Histories/phases/pending/data hold; all valids become 0 |
| `en=1, ctx=0, a_ph=0` | Idle | Shift A sample history; toggle `a_ph` to 1 |
| `en=1, ctx=0, a_ph=1` | `OP_A_L1` | Shift A history; capture A low/high; pulse `a_l1_valid`; toggle phase |
| `en=1, ctx=1, b_ph=1` | `OP_B_L1` | Shift B history; capture B L1; pulse `b_l1_valid`; push signed `lo_sum[30:15]` into q-window; conditionally create job; toggle `b_mpar` and `b_ph` |
| `en=1, ctx=1, b_ph=0, b_pending=1` | `OP_B_L2` | Shift B level-1 history; capture B L2 from current q-window; pulse `b_l2_valid`; clear pending; toggle `b_ph` |
| `en=1, ctx=1, b_ph=0, b_pending=0` | Idle | Shift B level-1 history; toggle `b_ph` |

When B creates a job, the q-window is pushed on that edge. Because the state update is edge-triggered, the following enabled `b_ph=0` edge sees the updated q-window and computes the required level-2 result. If execution is suspended, `b_pending`, `b_ph`, and the q-window remain intact.

---

## 3. Exact Interface and Timing Contract

Top module name: **`dwt_shared`**

Ports:

- Inputs:
  - `clock`
  - `reset`: synchronous active-high
  - `ctx`: `0` selects A; `1` selects B
  - `en`
  - signed `[15:0] x`
- Outputs:
  - signed `[39:0] a_l1_lo`
  - signed `[39:0] a_l1_hi`
  - `a_l1_valid`
  - signed `[39:0] b_l1_lo`
  - signed `[39:0] b_l1_hi`
  - `b_l1_valid`
  - signed `[39:0] b_l2_lo`
  - signed `[39:0] b_l2_hi`
  - `b_l2_valid`

Timing:

1. `reset=1` at a rising edge clears every history element, phase bit, pending flag, output datum, and valid bit.
2. An input sample is accepted only on a rising edge with `reset=0 && en=1`.
3. Only the context selected by `ctx` accepts that sample.
4. A and B accepted-sample indices advance independently.
5. Level-1 output is captured on indices 1, 3, 5, …, identified by the old context phase being 1.
6. B level-2 input is the signed 16-bit slice `[30:15]` of the freshly calculated B level-1 low result.
7. B pair indices 1, 3, 5, … create a pending level-2 job.
8. The job is consumed on the next enabled B edge with old `b_ph=0`; B level-2 data updates and `b_l2_valid` pulses on that edge.
9. `en=0` does not advance either context or consume pending work.
10. `ctx` changes are contractually restricted to reset edges or edges with `en=0`.
11. Valid outputs are one-cycle strobes. Data outputs hold between updates.
12. All sums wrap at 40 bits, with no saturation or rounding.

---

## 4. Ranked Risks and Implementation/Verification Order

1. **B level-2 scheduling and q-window age**
   - Highest risk: using the pre-push q-window on the creation edge or consuming pending work too early.
   - Implement B phases, `b_mpar`, q shift, and pending sequencing first.
   - Verify directed traces around pair indices 1 and 3, including multi-cycle `en=0` suspension after job creation.

2. **Signed arithmetic and Verilog expression sizing**
   - Declare every operand, coefficient, and product signed.
   - Form explicit signed 32-bit products, sign-extend each to 40 bits, and use only 40-bit additions.
   - Verify minimum/maximum samples, negative coefficients, overflow wrapping, and signed extraction of `[30:15]`.

3. **Old-state versus next-state use**
   - All datapath operands must come from old state plus current `x`.
   - B-L2 must read the q-window present before its consumption edge.
   - Compare edge-by-edge against the two references under randomized `en`.

4. **Context isolation and valid strobes**
   - Confirm inactive histories, phases, pending state, and output data never change.
   - Confirm all valids deassert on idle and suspension edges.
   - Test legal context switches with long suspensions and resume each context mid-phase.

5. **Synthesis structure and generic-cell threshold**
   - Use one eight-multiplier bank and one packed next-state register.
   - Avoid helper expressions that duplicate multipliers after normalization.
   - Run the frozen normalization/stat flow early; inspect normalized `$mul` count and generic-cell count before extensive cleanup.

6. **Reset and output-hold behavior**
   - Verify synchronous reset priority over `en` and `ctx`.
   - Check every output is zero immediately after a reset edge and data remains stable whenever its valid strobe is not being produced.