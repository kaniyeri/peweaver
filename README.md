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

| Campaign | Turns | OpenCode sessions | Advisor | Implementer | OpenCode Advisor cost estimate |
|---|---:|---:|---|---|---:|
| FFT discovery | 32 | 75 | GPT-5.6 Sol | Gemini 3.8 Flash | $5.03 |
| MAC clean starts (2) | 1 | 6 | GPT-5.6 Sol | Gemini 3.8 Flash | $0.103 |
| FFT PowerSave | 7 | 11 | GPT-5.6 Sol | Gemini 3.8 Flash | $2.68 |
| FIR merge | 1 | 1 | GPT-5.6 Sol | Gemini 3.8 Flash | $0.044 |
| DWT merge | 2 | 3 | GPT-5.6 Sol | Gemini 3.8 Flash | $0.393 |

Turns include failed attempts. Costs are ccusage estimates from OpenCode session records.

## Code

- [ChiaMerge](chia/examples/peweaver/orchestration/chia_merge.py) and [ChiaPowerSave](chia/examples/peweaver/orchestration/chia_power_save.py) are PEWeaver code under the vendored CHIA workspace.
- The [FFT driver](chia/examples/peweaver/orchestration/peweaver_chia_graph.py) sets the checks. The accepted [S0 RTL](chia/examples/peweaver/orchestration/runs/merge_clean_1/peweaver_shared_fft.mergerun1.v) is the main design.
- Accepted [MAC RTL](chia/examples/peweaver/orchestration/runs/mac-merge-2/best/shared_mac.v) and [DWT RTL](chia/examples/peweaver/orchestration/runs/dwt-merge-1/best/dwt_shared.v) are also included.


## Run the FFT merge loop

From `chia/examples/peweaver/`, with the physical toolchain (Yosys/Verilator/Icarus, OpenROAD, volare sky130A) installed and `opencode auth login` done:

```sh
./run-fft-chiamerge.sh --dry-run   # preflight only; no model calls
./run-fft-chiamerge.sh             # full ChiaMerge loop; about 1 h of physical flow per turn
```

`PLANNER_MODEL`, `WORKER_MODEL`, and `TURNS` configure the loop. 
