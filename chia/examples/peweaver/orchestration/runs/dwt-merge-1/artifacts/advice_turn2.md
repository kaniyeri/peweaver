### Highest-value next burst: lock down the cycle-accurate shared scheduler before optimizing state

Implement or audit the controller around one shared eight-multiplier low/high filter bank. Use these explicit operation predicates from **old state**:

- `A_L1 = en && !ctx && a_ph`
- `B_L1 = en &&  ctx && b_ph`
- `B_L2 = en &&  ctx && !b_ph && b_pending`

Required behavior:

- Toggle `a_ph` or `b_ph` only when that context accepts a sample.
- `A_L1` and `B_L1` use `[x, w0, w1, w2]`.
- On `B_L1`, capture `b_l1_*`, push the freshly computed signed `lo_sum[30:15]` into `b_q0..b_q3`, and toggle pair parity.
- Set `b_pending` only on B pair indices `1,3,5,…`; consume it on the next enabled B edge with old `b_ph=0`.
- `B_L2` must use the already-updated q-window, then pulse `b_l2_valid` and clear `b_pending`.
- Clear all three valid signals every non-reset edge; output data must otherwise hold.
- `en=0` and inactive contexts must preserve histories, phases, q-window, pending work, and output data.
- Synchronous reset must clear every state and output field.

Before any packing or cell-count optimization, verify directed traces showing:

1. A/B L1 valids only at accepted indices `1,3,5,…`.
2. B L2’s first valid at accepted B index `4`, computed from `[q1,q0,0,0]`.
3. A pending B-L2 job survives `en=0` and Context-A suspension.
4. Data holds while valids deassert.
5. Arithmetic uses eight signed 16×16 products, explicit 40-bit sign extension, modulo-\(2^{40}\) sums, and exact `[30:15]` extraction.

Then run the frozen gate ladder and do not proceed until lint plus randomized and directed RTL comparison pass cycle-for-cycle. Afterward, confirm normalized multiplier count is `<= 8` and synthesized generic cells are `< 11142`. If the current RTL already satisfies the traces, preserve it and diagnose the apparent evaluator interruption rather than redesigning the datapath.