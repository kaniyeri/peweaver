# PEWeaver orchestration

[ChiaMerge](chia_merge.py) runs a candidate through ordered checks and records the verdict. [ChiaPowerSave](chia_power_save.py) uses the same checks while tracking area, power, and energy trade-offs.

The [FFT driver](peweaver_chia_graph.py) supplies the FFT contract and evaluator. The [MAC](mac_merge_driver.py), [FIR](fir_merge_driver.py), and [DWT](dwt_merge_driver.py) drivers supply their own contracts and checks.

Accepted and failed attempts remain under `runs/`. See the [project README](../../../../README.md) for results and the local command.
