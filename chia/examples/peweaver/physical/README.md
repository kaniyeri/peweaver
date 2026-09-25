# FFT physical flow

`run-physical.sh` synthesizes, places, routes, and measures one selected design with the pinned SkyWater 130 tools. Results are single-corner estimates.

```sh
PEWEAVER_DESIGN=shared ./run-physical.sh
```

Run from this directory. Other design values are `fft64`, `fft128`, and `dual`. Use the tool versions and PDK recorded in [tool-lock.json](tool-lock.json). The slim release omits large generated VCD, SPEF, DEF, ODB, and GDS files.

The [project README](../../../../README.md) has the measured comparison. The [canonical result JSON](../orchestration/runs/submission_edge_20260906/manifest/canonical_comparison.json) has the full values.
