# PEWeaver

Code for *PEWeaver: CHIA-Governed RTL Sharing for BCI-Inspired Signal Processing*.

PEWeaver uses CHIA to propose shared RTL. A separate evaluator checks behavior and hardware cost before accepting a design.

## Results

FFT results are single-run SkyWater 130 estimates at one corner. Power is measured from switching activity.

| FFT design | Placed area (µm²) | Streaming power, 64 / 128 (mW) |
|---|---:|---:|
| Dual A, two cores | 429,130 | 61.523 / 61.446 |
| S0, shared core | 286,970 | 39.819 / 40.444 |
| S1, PowerSave | 282,963 | 39.931 / 40.445 |
| Dual B, clock gated | 429,655 | 23.387 / 41.712 |

| Design | Shared / two references (generic Yosys cells) | Reduction |
|---|---:|---:|
| MAC | 531 / 949 | 44.0% |
| FIR | 4,484 / 5,071 | 11.6% |
| DWT | 6,533 / 18,570 | 64.8% |

## Model cost

| Campaign | Runs | Estimated USD per run |
|---|---:|---:|
| FFT discovery | 1 | $5.03 |
| FFT merge reproduction | 3 | $3.42 average ($0.85–$5.66) |
| FFT PowerSave | 1 | $2.68 |
| MAC six-gate clean start | 2 | $0.103 average |
| FIR merge | 1 | $0.044 |
| DWT merge | 1 | $0.393 |

Source: [cost CSV](chia/examples/peweaver/paper_data/model_usage/ccusage_per_task_and_experiment_20260925.csv) and [method](chia/examples/peweaver/paper_data/model_usage/ccusage_probe_20260925.md). These are OpenCode `ccusage` estimates, not billed costs. The $106.23 total covers 958 sessions including sweeps; sum only `row_type=run`. The earlier $24.89 export overlaps. Native Gemini, VM, and physical-tool costs are excluded.

## Code

- [ChiaMerge](chia/examples/peweaver/orchestration/chia_merge.py) and [ChiaPowerSave](chia/examples/peweaver/orchestration/chia_power_save.py) are PEWeaver code under the vendored CHIA workspace.
- The [FFT driver](chia/examples/peweaver/orchestration/peweaver_chia_graph.py) sets the checks. The accepted [S0 RTL](chia/examples/peweaver/orchestration/runs/merge_clean_1/peweaver_shared_fft.mergerun1.v) is the main design.
- Accepted [MAC RTL](chia/examples/peweaver/orchestration/runs/mac-merge-2/best/shared_mac.v) and [DWT RTL](chia/examples/peweaver/orchestration/runs/dwt-merge-1/best/dwt_shared.v) are also included.

## Quick start

With Python dependencies from `chia/pyproject.toml`, Yosys, and Verilator installed:

```sh
cd chia
./examples/peweaver/run-local.sh
```

This runs local checks without a model call or physical design run. See [measurement data](chia/examples/peweaver/orchestration/runs/submission_edge_20260906/manifest/canonical_comparison.json) and [evidence pointers](chia/examples/peweaver/REVIEWER_GUIDE.md).
