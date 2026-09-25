# dwt-merge-1: fourth-domain ChiaMerge run (accepted)

- **Result**: accepted turn 2, all six gates (best_level 6).
- **Candidate**: `best/dwt_shared.v`, sha256 `27ce1aab1fc04c4608b2787a2dfa9006ba90a121500544ba517b677fec0cf91e`.
- **Area proxy**: 6,533 unweighted generic Yosys cells = 64.82% below the
  independently synthesized two-reference sum 18,570 (never mapped area).
- **Structure**: 8 normalized multiplication operators.
- **Correctness**: 1,504-cycle public oracle and 73-cycle directed corners
  bit-exact at RTL; 1,204-cycle controller-only synthesized-netlist holdout
  bit-exact (Icarus + Yosys simcells).
- **Independent repeat**: `repeat_result.json` (fresh root, frozen evaluator
  `d7c089bb...`) passes all six gates.
- **Controls**: model-free folded control passed 6/6 (6,521 cells); the naive
  two-reference wrapper failed structure (24 muls) and area (16,968 cells);
  the shared-history cheater failed functional gates; all 10 mutations were
  caught by their intended gates (see `../campaigns/dwt_campaign/`).
- **Honest failure record**: turn-1 candidate `865744924b0545fa` was not evaluated in-run
  because the first launch was SIGTERM'd by the shared Ray cluster's teardown;
  post-hoc it passes all six gates (6,519 cells). Relaunched with
  `RAY_ADDRESS=local` in tmux and resumed; the turn-2 candidate was accepted.
- **Scope**: synthesis-level only; no physical, power, timing, or mapped-area
  claim; references are an explicitly unfolded spatial baseline.
