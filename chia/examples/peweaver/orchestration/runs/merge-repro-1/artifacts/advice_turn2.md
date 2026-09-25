## Highest-value next burst: establish the required top-level RTL contract

The evaluator found no recognizable DUT, so implementing deeper FFT logic has zero value until the design can be discovered and compiled. Create a synthesizable top-level module named **exactly**:

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

Use active-high asynchronous reset (`posedge reset`). Do not rename ports, add parameters, or substitute `reset_n`.

For this burst, implement the interface plus reset-safe state ownership:

- `mode_q` captures `mode` on the first accepted idle sample (`di_en==1`) and remains unchanged while work is outstanding.
- A 9-bit `outstanding` counter increments on accepted inputs and decrements on `do_en`; handle simultaneous input/output without changing the count.
- Reset asynchronously clears:
  - `mode_q`
  - `outstanding`
  - all valid/control pipelines
  - stage counters and delay pointers
  - `do_en`
- `do_en` must never be unknown and must be `0` during and immediately after reset.
- `do_re` and `do_im` may be deterministic zero until the datapath is integrated.

Avoid inventing a placeholder output-valid latency pulse: a false `do_en` would violate the contract and complicate later verification. Keep it low until it is driven by a real stage-valid chain.

### Verify before moving on

1. **Discovery/lint:** Confirm the evaluator can find `peweaver_shared_fft` and all nine exact ports, with no width or direction mismatch.
2. **Reset test:** Assert `reset` between clock edges and verify `do_en` drops immediately; after deassertion, it remains low without accepted data.
3. **Immediate-input mode capture:** Deassert reset and present `mode=1`, `di_en=1` at the next edge. Verify that edge accepts the sample and sets `mode_q=1`—it must not use reset’s old mode value.
4. **Mode stability:** Change external `mode` while `outstanding!=0`; verify `mode_q` does not change.
5. **Known-state checks:** Assert that `do_en`, counters, valid bits, and pointers are never `X` after reset.

Only after this shell passes lint and reset/interface tests should the next burst implement and compare one configurable `CSDF` stage.