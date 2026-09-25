# Evidence pointers

The [project README](../../../README.md) gives the results and local command. The main source files are:

- FFT: [S0 RTL](orchestration/runs/merge_clean_1/peweaver_shared_fft.mergerun1.v), [independent functional check](orchestration/shared_fft_regression.py), and [canonical measurements](orchestration/runs/submission_edge_20260906/manifest/canonical_comparison.json).
- PowerSave: [S1 RTL](orchestration/runs/ps_fft_campaign/best/peweaver_shared_fft.v) and [campaign state](orchestration/runs/ps_fft_campaign/artifacts/state.json). S1 improves area, not measured power.
- MAC: [accepted RTL](orchestration/runs/mac-merge-2/best/shared_mac.v) and [driver](orchestration/mac_merge_driver.py). The formal check is bounded BMC at depth 12.
- FIR: [driver](orchestration/fir_merge_driver.py) and [reference filters](merge_benchmarks/fir_reference/).
- DWT: [accepted RTL](orchestration/runs/dwt-merge-1/best/dwt_shared.v), [driver](orchestration/dwt_merge_driver.py), and [repeat result](orchestration/runs/dwt-merge-1/repeat_result.json).

FFT figures are placed-area and activity-power estimates at one SkyWater 130 corner. MAC, FIR, and DWT reductions are generic synthesis cell counts. This slim checkout omits the large physical files, so it is not a full physical reproduction archive.
