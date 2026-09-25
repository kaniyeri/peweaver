### Highest-value instruction: repair and validate the twiddle ROM syntax first

The functional gate is currently blocked at compilation, so do not change pipeline control or arithmetic yet.

- Correct `wn_re[90]` from the malformed `16'DAD8` to the exact reference literal `16'hDAD8`.
- Confirm against `third_party/r22sdf/Twiddle128.v`:
  - `wn_re[90] == 16'hDAD8`
  - `wn_im[90] == 16'h7A7D`
- Scan the entire ROM for any other malformed numeric literals before testing.

Then run the official regression. Before moving on, require:

1. Verilator compilation/elaboration succeeds with no illegal-literal errors.
2. When registered ROM address `addr == 7'd90`, the corresponding registered outputs are `tw_re == 16'hDAD8` and `tw_im == 16'h7A7D`.
3. The regression reaches simulation and reports all four functional cases rather than stopping at compile.
4. For any passing case, `do_en` begins at cycle 71 in mode 0 or cycle 137 in mode 1 and remains high for exactly 64 or 128 consecutive cycles.

Only after this blocker is removed should the next burst investigate cycle or data mismatches.