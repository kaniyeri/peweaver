### Highest-value instruction: fix and verify the configurable delay-store primitive

The undefined `DEPTH` at line 405 is the immediate blocker, but do not patch it with an arbitrary constant. Make the storage bound a compile-time parameter such as `MAX_DEPTH`, while keeping the selected delay a runtime/configuration input such as `depth_i`.

Expected structure and behavior:

- Declare:
  - `buf_re[0:MAX_DEPTH-1]`
  - `buf_im[0:MAX_DEPTH-1]`
  - `wr_ptr`
- On **every** rising edge, regardless of `di_en`:
  1. Present `buf_*[wr_ptr]` as the delayed output.
  2. Write the current input into `buf_*[wr_ptr]`.
  3. Advance `wr_ptr`, wrapping when `wr_ptr == depth_i-1`.
- Use nonblocking assignments so reading and writing the same location gives read-before-write behavior.
- Asynchronously reset `wr_ptr` and any output-valid/control state. The memory contents need not be reset.
- Do not qualify memory movement with valid.
- Keep `depth_i` unchanged while data is active or draining.

Instantiate each store with its physical maximum and select the mode-specific depth:

- `64 → 32`
- `32 → 16`
- `16 → 8`
- `8 → 4`
- `4 → 2`
- `2 → 1`
- Final store: fixed depth `1`

Do not proceed to arithmetic changes until this primitive passes:

1. **Elaboration/lint:** Verilator compiles `peweaver_shared_fft.v` with no undefined parameters or out-of-range array accesses.
2. **Cycle-tag test:** Drive unique `di_re/di_im` values every clock. For every selectable depth `D`, after warm-up the output at edge `k` must equal the input from edge `k-D`.
3. **Invalid-clock test:** Toggle `di_en` randomly while continuing to change input data; the delay must still advance every clock.
4. **Depth-1 test:** Confirm output is the previous clock’s input, not the value being written on the current edge.
5. **Reset test:** Reset must restart the pointer/control state and prevent stale data from becoming valid; memory contents themselves may remain unknown.

This resolves the current functional-gate blocker while directly addressing the architecture’s second-highest cycle-accuracy risk.