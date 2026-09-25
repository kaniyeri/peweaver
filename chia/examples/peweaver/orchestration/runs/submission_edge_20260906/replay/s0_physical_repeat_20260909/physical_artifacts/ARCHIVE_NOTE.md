# S0 Repeat Physical Artifact Archive

The `results/` directory is a local archive of the detailed artifacts for the
post-audit, non-preregistered S0 physical repeat.

- Source sandbox: `/work/peweaver/runs/s0-independent-repeat-20260909`
- Source result record: `../s0_physical_repeat_sky130.json`
- Source audit record: `../s0_physical_repeat_audit.json`
- Archived files: 78 files, approximately 251 MB
- Validation: all 24 artifact entries in the source result record matched the
  archived file size and SHA-256 hash after path rebasing.
- Flow provenance: the repeat used `cf833c5866b326cccaf71362c0c534b6c5d1d4ff19951e084ef1cc506c6f7f83`; the historical primary S0 record used `3d8e08b0463e4787bc98c5d1d93d156860dc6466628dc52f897a87f6a6b5e47d`. This difference is disclosed in the audit record.
- The result record remains authoritative for the declared artifact hashes,
  tool pins, metrics, and claim boundary.

This archive is reproducibility evidence for the physical repeat. It is not
independent streamed-layout DRC/LVS signoff.
